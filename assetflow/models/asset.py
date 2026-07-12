# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import date
from dateutil.relativedelta import relativedelta


LIFECYCLE_STATES = [
    ('available', 'Available'),
    ('allocated', 'Allocated'),
    ('reserved', 'Reserved'),
    ('maintenance', 'Under Maintenance'),
    ('lost', 'Lost'),
    ('retired', 'Retired'),
    ('disposed', 'Disposed'),
]

CONDITION_LEVELS = [
    ('new', 'New'),
    ('good', 'Good'),
    ('fair', 'Fair'),
    ('poor', 'Poor'),
    ('damaged', 'Damaged'),
]


class AssetflowAsset(models.Model):
    _name = 'assetflow.asset'
    _description = 'AssetFlow Asset'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'asset_tag asc'

    # ── Identity ─────────────────────────────────────────────────────────────
    name = fields.Char(string='Asset Name', required=True, tracking=True)
    asset_tag = fields.Char(
        string='Asset Tag', copy=False, readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('assetflow.asset'),
    )
    serial_number = fields.Char(string='Serial Number', copy=False, tracking=True)
    image = fields.Image(string='Asset Image', max_width=1024, max_height=1024)

    # ── Classification ────────────────────────────────────────────────────────
    category_id = fields.Many2one(
        'assetflow.category', string='Category', required=True,
        tracking=True, ondelete='restrict',
    )
    department_id = fields.Many2one(
        'assetflow.department', string='Department',
        tracking=True, ondelete='restrict',
    )
    location = fields.Char(string='Location / Room', tracking=True)
    condition = fields.Selection(
        CONDITION_LEVELS, string='Condition', default='new', tracking=True,
    )

    # ── Financial ─────────────────────────────────────────────────────────────
    acquisition_date = fields.Date(
        string='Acquisition Date', default=fields.Date.today, tracking=True,
    )
    cost = fields.Float(string='Acquisition Cost', digits=(16, 2), tracking=True)
    warranty_expiry = fields.Date(
        string='Warranty Expiry', compute='_compute_warranty_expiry', store=True,
    )
    is_under_warranty = fields.Boolean(
        string='Under Warranty', compute='_compute_warranty_expiry', store=True,
    )

    # ── Lifecycle ──────────────────────────────────────────────────────────────
    state = fields.Selection(
        LIFECYCLE_STATES, string='Status', default='available',
        required=True, tracking=True, group_expand='_expand_states',
    )
    is_bookable_resource = fields.Boolean(
        string='Bookable Resource', default=False, tracking=True,
        help='Expose this asset as a shared bookable resource (room, vehicle, equipment).',
    )
    responsible_user_id = fields.Many2one(
        'res.users', string='Responsible Person', tracking=True,
        domain="[('share', '=', False)]",
    )
    notes = fields.Html(string='Internal Notes')
    active = fields.Boolean(default=True)

    # ── Documents ─────────────────────────────────────────────────────────────
    document_ids = fields.Many2many(
        'ir.attachment', string='Documents',
        help='Attach purchase invoice, warranty certificate, manual, etc.',
    )

    # ── Risk Intelligence ──────────────────────────────────────────────────────
    maintenance_count = fields.Integer(
        string='Resolved Maintenance Count',
        compute='_compute_maintenance_stats', store=True,
    )
    open_maintenance_count = fields.Integer(
        string='Open Maintenance', compute='_compute_maintenance_stats', store=True,
    )
    maintenance_risk = fields.Selection(
        selection=[('low', 'Low Risk'), ('medium', 'Medium Risk'), ('high', 'High Risk')],
        string='Maintenance Risk',
        compute='_compute_maintenance_risk', store=True, tracking=True,
    )

    # ── Computed KPIs ──────────────────────────────────────────────────────────
    current_holder_id = fields.Many2one(
        'hr.employee', string='Currently With',
        compute='_compute_current_holder', store=True,
    )
    total_allocation_count = fields.Integer(
        string='Total Allocations', compute='_compute_allocation_stats',
    )
    active_booking_count = fields.Integer(
        string='Active Bookings', compute='_compute_booking_stats',
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    allocation_ids = fields.One2many('assetflow.allocation', 'asset_id', string='Allocations')
    booking_ids = fields.One2many('assetflow.booking', 'resource_id', string='Bookings')
    maintenance_ids = fields.One2many('assetflow.maintenance', 'asset_id', string='Maintenance Records')
    audit_line_ids = fields.One2many('assetflow.audit.line', 'asset_id', string='Audit History')

    # ── Computed ───────────────────────────────────────────────────────────────

    @api.depends('acquisition_date', 'category_id.warranty_period')
    def _compute_warranty_expiry(self):
        today = date.today()
        for asset in self:
            if asset.acquisition_date and asset.category_id.warranty_period:
                expiry = asset.acquisition_date + relativedelta(
                    months=asset.category_id.warranty_period
                )
                asset.warranty_expiry = expiry
                asset.is_under_warranty = expiry >= today
            else:
                asset.warranty_expiry = False
                asset.is_under_warranty = False

    @api.depends('maintenance_ids', 'maintenance_ids.state')
    def _compute_maintenance_stats(self):
        Maintenance = self.env['assetflow.maintenance']
        for asset in self:
            asset.maintenance_count = Maintenance.search_count([
                ('asset_id', '=', asset.id), ('state', '=', 'resolved'),
            ])
            asset.open_maintenance_count = Maintenance.search_count([
                ('asset_id', '=', asset.id),
                ('state', 'in', ('pending', 'approved', 'in_progress')),
            ])

    @api.depends('maintenance_count')
    def _compute_maintenance_risk(self):
        for asset in self:
            count = asset.maintenance_count
            if count >= 5:
                asset.maintenance_risk = 'high'
            elif count >= 3:
                asset.maintenance_risk = 'medium'
            else:
                asset.maintenance_risk = 'low'

    @api.depends('allocation_ids', 'allocation_ids.state', 'allocation_ids.employee_id')
    def _compute_current_holder(self):
        for asset in self:
            active_alloc = self.env['assetflow.allocation'].search([
                ('asset_id', '=', asset.id), ('state', '=', 'active'),
            ], limit=1)
            asset.current_holder_id = active_alloc.employee_id if active_alloc else False

    def _compute_allocation_stats(self):
        for asset in self:
            asset.total_allocation_count = len(asset.allocation_ids)

    def _compute_booking_stats(self):
        for asset in self:
            asset.active_booking_count = self.env['assetflow.booking'].search_count([
                ('resource_id', '=', asset.id),
                ('state', 'in', ('confirmed', 'in_use')),
            ])

    # ── Constraints ────────────────────────────────────────────────────────────

    @api.constrains('serial_number')
    def _check_unique_serial(self):
        for asset in self:
            if asset.serial_number:
                duplicate = self.search([
                    ('serial_number', '=', asset.serial_number),
                    ('id', '!=', asset.id),
                ])
                if duplicate:
                    raise ValidationError(
                        f"Serial number '{asset.serial_number}' is already assigned to "
                        f"'{duplicate[0].name}' (Tag: {duplicate[0].asset_tag}). "
                        "Each asset must have a unique serial number."
                    )

    # ── State Transitions ──────────────────────────────────────────────────────

    def action_set_available(self):
        for rec in self:
            if rec.state in ('maintenance', 'reserved', 'retired', 'lost'):
                rec.state = 'available'
                rec.message_post(body="Asset status manually set to <b>Available</b>.")

    def action_set_retired(self):
        for rec in self:
            active_allocations = self.env['assetflow.allocation'].search_count([
                ('asset_id', '=', rec.id), ('state', '=', 'active'),
            ])
            if active_allocations:
                raise ValidationError(
                    f"Asset '{rec.name}' has an active allocation. "
                    "Return the asset before retiring it."
                )
            rec.state = 'retired'

    def action_mark_lost(self):
        for rec in self:
            rec.state = 'lost'
            rec.message_post(body="Asset marked as <b>Lost</b>.")

    def action_set_disposed(self):
        for rec in self:
            rec.state = 'disposed'

    # ── Smart Buttons ──────────────────────────────────────────────────────────

    def action_view_allocations(self):
        return {
            'type': 'ir.actions.act_window', 'name': 'Allocation History',
            'res_model': 'assetflow.allocation', 'view_mode': 'list,form',
            'domain': [('asset_id', '=', self.id)],
            'context': {'default_asset_id': self.id},
        }

    def action_view_bookings(self):
        return {
            'type': 'ir.actions.act_window', 'name': 'Bookings',
            'res_model': 'assetflow.booking', 'view_mode': 'calendar,list,form',
            'domain': [('resource_id', '=', self.id)],
            'context': {'default_resource_id': self.id},
        }

    def action_view_maintenance(self):
        return {
            'type': 'ir.actions.act_window', 'name': 'Maintenance Records',
            'res_model': 'assetflow.maintenance', 'view_mode': 'list,form',
            'domain': [('asset_id', '=', self.id)],
            'context': {'default_asset_id': self.id},
        }

    def action_quick_allocate(self):
        return {
            'type': 'ir.actions.act_window', 'name': 'Allocate Asset',
            'res_model': 'assetflow.allocation', 'view_mode': 'form',
            'target': 'new',
            'context': {'default_asset_id': self.id},
        }

    def action_raise_maintenance(self):
        return {
            'type': 'ir.actions.act_window', 'name': 'Raise Maintenance Request',
            'res_model': 'assetflow.maintenance', 'view_mode': 'form',
            'target': 'new',
            'context': {'default_asset_id': self.id},
        }

    # ── Kanban group expand ────────────────────────────────────────────────────

    @api.model
    def _expand_states(self, states, domain, order):
        return [key for key, _val in LIFECYCLE_STATES]
