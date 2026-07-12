# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class AssetflowTransferWizard(models.TransientModel):
    _name = 'assetflow.transfer.wizard'
    _description = 'Asset Transfer Request Wizard'

    allocation_id = fields.Many2one('assetflow.allocation', string='Current Allocation', required=True)
    asset_id = fields.Many2one('assetflow.asset', string='Asset', related='allocation_id.asset_id', readonly=True)
    current_holder_id = fields.Many2one('hr.employee', string='Currently With', related='allocation_id.employee_id', readonly=True)
    transfer_to_employee_id = fields.Many2one('hr.employee', string='Transfer To', required=True)
    transfer_reason = fields.Text(string='Reason for Transfer', required=True)
    expected_return_date = fields.Date(string='Expected Return Date (for new holder)')

    def action_submit_transfer(self):
        self.ensure_one()
        alloc = self.allocation_id
        if alloc.state != 'active':
            raise ValidationError("Only active allocations can have a transfer requested.")
        alloc.write({
            'state': 'transfer_requested',
            'transfer_to_employee_id': self.transfer_to_employee_id.id,
            'transfer_reason': self.transfer_reason,
        })
        alloc.message_post(
            body=f"Transfer requested to <b>{self.transfer_to_employee_id.name}</b>. "
                 f"Reason: {self.transfer_reason}"
        )
        alloc.activity_schedule(
            'mail.mail_activity_data_todo',
            summary='Asset Transfer Approval Required',
            note=f"Please approve or reject the transfer of {alloc.asset_id.name} "
                 f"from {alloc.employee_id.name} to {self.transfer_to_employee_id.name}.",
            user_id=alloc.approved_by_id.id or self.env.user.id,
        )
        return {'type': 'ir.actions.act_window_close'}
