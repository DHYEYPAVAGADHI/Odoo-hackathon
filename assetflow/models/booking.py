# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime


class AssetflowBooking(models.Model):
    _name = 'assetflow.booking'
    _description = 'Resource Booking'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_time asc'

    name = fields.Char(
        string='Booking Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('assetflow.booking'),
    )
    resource_id = fields.Many2one(
        'assetflow.asset',
        string='Resource',
        required=True,
        tracking=True,
        ondelete='restrict',
        domain="[('is_bookable_resource', '=', True), ('state', 'in', ['available', 'reserved'])]",
    )
    booked_by_id = fields.Many2one(
        'res.users',
        string='Booked By',
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='On Behalf Of',
        tracking=True,
    )
    start_time = fields.Datetime(string='Start Time', required=True, tracking=True)
    end_time = fields.Datetime(string='End Time', required=True, tracking=True)
    duration_hours = fields.Float(
        string='Duration (Hrs)', compute='_compute_duration', store=True,
    )
    purpose = fields.Text(string='Purpose / Description')
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('in_use', 'In Use'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
    )
    color = fields.Integer(string='Color Index', compute='_compute_color')

    # ── Computed ─────────────────────────────────────────────────────────────

    @api.depends('start_time', 'end_time')
    def _compute_duration(self):
        for rec in self:
            if rec.start_time and rec.end_time:
                delta = rec.end_time - rec.start_time
                rec.duration_hours = delta.total_seconds() / 3600.0
            else:
                rec.duration_hours = 0.0

    @api.depends('state')
    def _compute_color(self):
        color_map = {
            'draft': 0,
            'confirmed': 10,
            'in_use': 2,
            'completed': 5,
            'cancelled': 1,
        }
        for rec in self:
            rec.color = color_map.get(rec.state, 0)

    # ── Overlap Constraint ───────────────────────────────────────────────────
    # The query mirrors standard interval-overlap logic:
    #   existing.start < new.end  AND  existing.end > new.start
    # Any record satisfying both conditions overlaps the requested window.

    @api.constrains('resource_id', 'start_time', 'end_time', 'state')
    def _check_no_booking_overlap(self):
        for rec in self:
            if rec.state == 'cancelled':
                continue
            if rec.start_time and rec.end_time and rec.start_time >= rec.end_time:
                raise ValidationError(
                    "Booking End Time must be strictly after the Start Time."
                )
            overlapping = self.env['assetflow.booking'].search([
                ('resource_id', '=', rec.resource_id.id),
                ('state', 'not in', ['cancelled', 'completed']),
                ('id', '!=', rec.id),
                ('start_time', '<', rec.end_time),
                ('end_time', '>', rec.start_time),
            ])
            if overlapping:
                conflict = overlapping[0]
                raise ValidationError(
                    f"Booking conflict detected for resource '{rec.resource_id.name}'.\n"
                    f"The time window {rec.start_time.strftime('%d %b %Y %H:%M')} — "
                    f"{rec.end_time.strftime('%d %b %Y %H:%M')} overlaps with an existing "
                    f"booking by {conflict.booked_by_id.name} "
                    f"({conflict.start_time.strftime('%H:%M')} — {conflict.end_time.strftime('%H:%M')}, "
                    f"Ref: {conflict.name}).\n"
                    "Please select a different time slot or resource."
                )

    # ── State Transitions ────────────────────────────────────────────────────

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError("Only Draft bookings can be confirmed.")
            rec.write({'state': 'confirmed'})
            rec.resource_id.write({'state': 'reserved'})

    def action_start(self):
        for rec in self:
            if rec.state != 'confirmed':
                raise ValidationError("Please confirm the booking before starting use.")
            rec.write({'state': 'in_use'})

    def action_complete(self):
        for rec in self:
            rec.write({'state': 'completed'})
            # Release resource back to available only when no other confirmed booking overlaps now
            other_active = self.env['assetflow.booking'].search([
                ('resource_id', '=', rec.resource_id.id),
                ('state', 'in', ['confirmed', 'in_use']),
                ('id', '!=', rec.id),
            ])
            if not other_active:
                rec.resource_id.write({'state': 'available'})

    def action_cancel(self):
        for rec in self:
            if rec.state in ('completed',):
                raise ValidationError("Completed bookings cannot be cancelled.")
            rec.write({'state': 'cancelled'})
            other_active = self.env['assetflow.booking'].search([
                ('resource_id', '=', rec.resource_id.id),
                ('state', 'in', ['confirmed', 'in_use']),
                ('id', '!=', rec.id),
            ])
            if not other_active and rec.resource_id.state == 'reserved':
                rec.resource_id.write({'state': 'available'})
