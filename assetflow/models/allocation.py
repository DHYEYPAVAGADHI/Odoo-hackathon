# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import date


class AssetflowAllocation(models.Model):
    _name = 'assetflow.allocation'
    _description = 'Asset Allocation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('assetflow.allocation'),
    )
    asset_id = fields.Many2one(
        'assetflow.asset', string='Asset', required=True,
        tracking=True, ondelete='restrict',
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Allocated To', required=True,
        tracking=True, ondelete='restrict',
    )
    department_id = fields.Many2one(
        'assetflow.department', string='Department',
        related='asset_id.department_id', store=True,
    )
    allocation_date = fields.Date(
        string='Allocation Date', default=fields.Date.today,
        required=True, tracking=True,
    )
    expected_return_date = fields.Date(string='Expected Return Date', tracking=True)
    actual_return_date = fields.Date(string='Actual Return Date', tracking=True)
    return_condition = fields.Selection(
        [('new', 'New'), ('good', 'Good'), ('fair', 'Fair'),
         ('poor', 'Poor'), ('damaged', 'Damaged')],
        string='Return Condition',
    )
    return_notes = fields.Text(string='Return / Condition Notes')
    state = fields.Selection(
        selection=[
            ('active', 'Active'),
            ('returned', 'Returned'),
            ('overdue', 'Overdue'),
            ('transfer_requested', 'Transfer Requested'),
        ],
        string='Status', default='active', required=True, tracking=True,
    )
    approved_by_id = fields.Many2one(
        'res.users', string='Approved By', tracking=True,
        default=lambda self: self.env.user,
    )
    purpose = fields.Text(string='Purpose / Notes')

    # Transfer workflow fields
    transfer_to_employee_id = fields.Many2one(
        'hr.employee', string='Transfer To', tracking=True,
    )
    transfer_reason = fields.Text(string='Transfer Reason')
    transfer_approved_by_id = fields.Many2one(
        'res.users', string='Transfer Approved By', tracking=True,
    )

    # ── Asset state sync ──────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec.asset_id.write({'state': 'allocated'})
            rec.asset_id.message_post(
                body=f"Asset allocated to <b>{rec.employee_id.name}</b> — Ref: {rec.name}"
            )
        return records

    def write(self, vals):
        result = super().write(vals)
        for rec in self:
            if rec.state == 'returned' and rec.asset_id.state == 'allocated':
                rec.asset_id.write({'state': 'available'})
                if rec.return_condition:
                    rec.asset_id.write({'condition': rec.return_condition})
        return result

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('asset_id', 'state')
    def _check_no_double_allocation(self):
        for rec in self:
            if rec.state not in ('active', 'transfer_requested'):
                continue
            conflicting = self.env['assetflow.allocation'].search([
                ('asset_id', '=', rec.asset_id.id),
                ('state', 'in', ('active', 'transfer_requested')),
                ('id', '!=', rec.id),
            ])
            if conflicting:
                raise ValidationError(
                    f"Asset '{rec.asset_id.name}' (Tag: {rec.asset_id.asset_tag}) is "
                    f"currently held by '{conflicting[0].employee_id.name}' "
                    f"(Ref: {conflicting[0].name}).\n\n"
                    "To reassign this asset, use the 'Request Transfer' button on the "
                    "existing allocation instead of creating a new one."
                )

    @api.constrains('expected_return_date', 'allocation_date')
    def _check_return_date(self):
        for rec in self:
            if rec.expected_return_date and rec.allocation_date:
                if rec.expected_return_date < rec.allocation_date:
                    raise ValidationError(
                        "Expected Return Date cannot be earlier than the Allocation Date."
                    )

    # ── State Machine ─────────────────────────────────────────────────────────

    def action_mark_returned(self):
        for rec in self:
            if rec.state not in ('active', 'overdue'):
                raise ValidationError("Only Active or Overdue allocations can be returned.")
            rec.write({'state': 'returned', 'actual_return_date': date.today()})

    def action_request_transfer(self):
        """Initiates a transfer request — sets state to transfer_requested."""
        self.ensure_one()
        if rec := self:
            if rec.state != 'active':
                raise ValidationError("Only active allocations can be transferred.")
            return {
                'type': 'ir.actions.act_window',
                'name': 'Request Asset Transfer',
                'res_model': 'assetflow.transfer.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_allocation_id': rec.id, 'default_asset_id': rec.asset_id.id},
            }

    def action_approve_transfer(self):
        """Manager/Dept Head approves the transfer, closing old and opening new allocation."""
        for rec in self:
            if rec.state != 'transfer_requested':
                raise ValidationError("Only transfer-requested allocations can be approved.")
            if not rec.transfer_to_employee_id:
                raise ValidationError("Please specify the employee to transfer to.")
            # Close current allocation
            rec.write({
                'state': 'returned',
                'actual_return_date': date.today(),
                'transfer_approved_by_id': self.env.user.id,
            })
            # Create new allocation
            new_alloc = self.env['assetflow.allocation'].create({
                'asset_id': rec.asset_id.id,
                'employee_id': rec.transfer_to_employee_id.id,
                'allocation_date': date.today(),
                'expected_return_date': rec.expected_return_date,
                'approved_by_id': self.env.user.id,
                'purpose': f"Transfer from {rec.employee_id.name} (Ref: {rec.name}). Reason: {rec.transfer_reason or 'N/A'}",
            })
            rec.asset_id.message_post(
                body=f"Asset transferred from <b>{rec.employee_id.name}</b> to "
                     f"<b>{rec.transfer_to_employee_id.name}</b> — New Ref: {new_alloc.name}"
            )

    # ── Cron: Overdue Detection ───────────────────────────────────────────────

    def action_mark_overdue(self):
        """Called daily by ir.cron to flag past-due allocations."""
        today = date.today()
        overdue = self.search([
            ('state', '=', 'active'),
            ('expected_return_date', '<', today),
            ('expected_return_date', '!=', False),
        ])
        for rec in overdue:
            rec.write({'state': 'overdue'})
            rec.activity_schedule(
                'mail.mail_activity_data_warning',
                date_deadline=today,
                summary='Asset Return Overdue',
                note=(
                    f"The allocation of <b>{rec.asset_id.name}</b> "
                    f"(Tag: {rec.asset_id.asset_tag}) to <b>{rec.employee_id.name}</b> "
                    f"was due on {rec.expected_return_date.strftime('%d %b %Y')}. "
                    "Please follow up immediately."
                ),
                user_id=rec.approved_by_id.id or self.env.user.id,
            )
        return True
