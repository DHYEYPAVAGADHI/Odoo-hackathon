# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import date


PRIORITY = [('0', 'Normal'), ('1', 'Low'), ('2', 'High'), ('3', 'Critical')]


class AssetflowMaintenance(models.Model):
    _name = 'assetflow.maintenance'
    _description = 'Asset Maintenance Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, create_date desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('assetflow.maintenance'),
    )
    asset_id = fields.Many2one(
        'assetflow.asset',
        string='Asset',
        required=True,
        tracking=True,
        ondelete='restrict',
    )
    issue_description = fields.Text(string='Issue Description', required=True)
    priority = fields.Selection(PRIORITY, string='Priority', default='0', tracking=True)
    technician_id = fields.Many2one(
        'res.users',
        string='Assigned Technician',
        tracking=True,
        domain="[('share', '=', False)]",
    )
    reported_by_id = fields.Many2one(
        'res.users',
        string='Reported By',
        default=lambda self: self.env.user,
        tracking=True,
    )
    scheduled_date = fields.Date(string='Scheduled Date', tracking=True)
    resolution_date = fields.Date(string='Resolution Date', tracking=True)
    resolution_notes = fields.Text(string='Resolution Notes')
    estimated_cost = fields.Float(string='Estimated Cost', digits=(16, 2))
    actual_cost = fields.Float(string='Actual Cost', digits=(16, 2), tracking=True)
    state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('approved', 'Approved'),
            ('in_progress', 'In Progress'),
            ('resolved', 'Resolved'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='pending',
        required=True,
        tracking=True,
    )

    # ── State Machine ────────────────────────────────────────────────────────

    def action_approve(self):
        for rec in self:
            if rec.state != 'pending':
                raise ValidationError("Only pending requests can be approved.")
            rec.write({'state': 'approved'})
            # Lock asset into Under Maintenance
            rec.asset_id.write({'state': 'maintenance'})
            rec.asset_id.message_post(
                body=f"Asset set to <b>Under Maintenance</b> — Maintenance Request: {rec.name}."
            )

    def action_start_work(self):
        for rec in self:
            if rec.state != 'approved':
                raise ValidationError("Please approve the maintenance request before starting work.")
            rec.write({'state': 'in_progress'})

    def action_resolve(self):
        for rec in self:
            if rec.state not in ('approved', 'in_progress'):
                raise ValidationError("Only approved or in-progress maintenance requests can be resolved.")
            if not rec.resolution_notes:
                raise ValidationError(
                    "Please provide Resolution Notes before marking this maintenance request as resolved."
                )
            rec.write({'state': 'resolved', 'resolution_date': date.today()})
            # Return asset to Available only if no other open maintenance request exists
            other_open = self.search([
                ('asset_id', '=', rec.asset_id.id),
                ('state', 'in', ('approved', 'in_progress')),
                ('id', '!=', rec.id),
            ])
            if not other_open:
                rec.asset_id.write({'state': 'available'})
                rec.asset_id.message_post(
                    body=f"Asset returned to <b>Available</b> — Maintenance Request {rec.name} resolved."
                )

    def action_cancel(self):
        for rec in self:
            if rec.state == 'resolved':
                raise ValidationError("Resolved maintenance requests cannot be cancelled.")
            if rec.state in ('approved', 'in_progress'):
                other_open = self.search([
                    ('asset_id', '=', rec.asset_id.id),
                    ('state', 'in', ('approved', 'in_progress')),
                    ('id', '!=', rec.id),
                ])
                if not other_open and rec.asset_id.state == 'maintenance':
                    rec.asset_id.write({'state': 'available'})
            rec.write({'state': 'cancelled'})


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT CYCLE
# ─────────────────────────────────────────────────────────────────────────────

AUDIT_LINE_STATUS = [
    ('pending', 'Pending Verification'),
    ('verified', 'Verified'),
    ('missing', 'Missing'),
    ('damaged', 'Damaged'),
]


class AssetflowAudit(models.Model):
    _name = 'assetflow.audit'
    _description = 'Asset Audit Cycle'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc'

    name = fields.Char(string='Audit Cycle Name', required=True, tracking=True)
    date_start = fields.Date(string='Start Date', required=True, tracking=True)
    date_end = fields.Date(string='End Date', required=True, tracking=True)
    auditor_id = fields.Many2one(
        'res.users',
        string='Lead Auditor',
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
    )
    department_id = fields.Many2one(
        'assetflow.department', string='Scope: Department', tracking=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('in_progress', 'In Progress'),
            ('closed', 'Closed'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
    )
    audit_line_ids = fields.One2many('assetflow.audit.line', 'audit_id', string='Audit Lines')
    discrepancy_summary = fields.Html(string='Discrepancy Summary', readonly=True)
    notes = fields.Text(string='Audit Notes')

    # Aggregates
    total_assets = fields.Integer(compute='_compute_line_stats', store=True)
    verified_count = fields.Integer(compute='_compute_line_stats', store=True)
    missing_count = fields.Integer(compute='_compute_line_stats', store=True)
    damaged_count = fields.Integer(compute='_compute_line_stats', store=True)

    @api.depends('audit_line_ids', 'audit_line_ids.status')
    def _compute_line_stats(self):
        for audit in self:
            lines = audit.audit_line_ids
            audit.total_assets = len(lines)
            audit.verified_count = len(lines.filtered(lambda l: l.status == 'verified'))
            audit.missing_count = len(lines.filtered(lambda l: l.status == 'missing'))
            audit.damaged_count = len(lines.filtered(lambda l: l.status == 'damaged'))

    @api.constrains('date_start', 'date_end')
    def _check_date_range(self):
        for rec in self:
            if rec.date_end < rec.date_start:
                raise ValidationError("Audit End Date cannot be before the Start Date.")

    def action_start_audit(self):
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError("Only Draft audits can be started.")
            if not rec.audit_line_ids:
                raise ValidationError(
                    "Please add at least one asset to the audit line before starting the audit cycle."
                )
            rec.write({'state': 'in_progress'})

    def action_close_audit(self):
        """
        Reconcile audit findings with the asset master:
        - Missing → asset.state = 'lost'
        - Damaged  → asset.condition = 'damaged'
        - Verified → no state change (confirms current state is accurate)
        Then generate an HTML discrepancy summary and close the cycle.
        """
        for audit in self:
            if audit.state != 'in_progress':
                raise ValidationError("Only in-progress audits can be closed.")

            pending_lines = audit.audit_line_ids.filtered(lambda l: l.status == 'pending')
            if pending_lines:
                raise ValidationError(
                    f"{len(pending_lines)} audit line(s) are still marked as 'Pending Verification'. "
                    "Please complete all verifications before closing the audit."
                )

            missing_assets = []
            damaged_assets = []

            for line in audit.audit_line_ids:
                if line.status == 'missing':
                    line.asset_id.write({'state': 'lost'})
                    missing_assets.append(line.asset_id.name)
                elif line.status == 'damaged':
                    line.asset_id.write({'condition': 'damaged'})
                    damaged_assets.append(line.asset_id.name)

            # Build discrepancy summary
            summary_lines = [f"<h3>Audit Discrepancy Report — {audit.name}</h3>"]
            summary_lines.append(f"<p><b>Period:</b> {audit.date_start} to {audit.date_end}</p>")
            summary_lines.append(f"<p><b>Lead Auditor:</b> {audit.auditor_id.name}</p>")
            summary_lines.append(
                f"<p><b>Total Assets Audited:</b> {audit.total_assets} | "
                f"<b>Verified:</b> {audit.verified_count} | "
                f"<b>Missing:</b> {len(missing_assets)} | "
                f"<b>Damaged:</b> {len(damaged_assets)}</p>"
            )

            if missing_assets:
                summary_lines.append("<p><b style='color:red;'>Missing Assets (marked Lost):</b></p><ul>")
                for a in missing_assets:
                    summary_lines.append(f"<li>{a}</li>")
                summary_lines.append("</ul>")

            if damaged_assets:
                summary_lines.append("<p><b style='color:orange;'>Damaged Assets (condition updated):</b></p><ul>")
                for a in damaged_assets:
                    summary_lines.append(f"<li>{a}</li>")
                summary_lines.append("</ul>")

            if not missing_assets and not damaged_assets:
                summary_lines.append("<p style='color:green;'><b>✓ No discrepancies found. All assets verified.</b></p>")

            audit.write({
                'state': 'closed',
                'discrepancy_summary': "\n".join(summary_lines),
            })

    def action_populate_from_department(self):
        """Convenience: auto-populate audit lines from department asset registry."""
        self.ensure_one()
        domain = [('state', 'not in', ['disposed', 'retired'])]
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))
        assets = self.env['assetflow.asset'].search(domain)
        existing_asset_ids = self.audit_line_ids.mapped('asset_id').ids
        new_lines = []
        for asset in assets:
            if asset.id not in existing_asset_ids:
                new_lines.append({
                    'audit_id': self.id,
                    'asset_id': asset.id,
                    'status': 'pending',
                })
        if new_lines:
            self.env['assetflow.audit.line'].create(new_lines)
        return True


class AssetflowAuditLine(models.Model):
    _name = 'assetflow.audit.line'
    _description = 'Audit Line Item'
    _order = 'asset_id asc'

    audit_id = fields.Many2one(
        'assetflow.audit', string='Audit Cycle', required=True, ondelete='cascade',
    )
    asset_id = fields.Many2one(
        'assetflow.asset', string='Asset', required=True, ondelete='restrict',
    )
    asset_tag = fields.Char(related='asset_id.asset_tag', store=True, string='Asset Tag')
    category_id = fields.Many2one(related='asset_id.category_id', store=True, string='Category')
    location = fields.Char(related='asset_id.location', store=True, string='Location')
    status = fields.Selection(
        AUDIT_LINE_STATUS,
        string='Verification Status',
        default='pending',
        required=True,
    )
    remarks = fields.Char(string='Auditor Remarks')
    verified_by_id = fields.Many2one(
        'res.users', string='Verified By', default=lambda self: self.env.user,
    )

    @api.constrains('audit_id', 'asset_id')
    def _check_unique_asset_per_audit(self):
        for line in self:
            duplicate = self.search([
                ('audit_id', '=', line.audit_id.id),
                ('asset_id', '=', line.asset_id.id),
                ('id', '!=', line.id),
            ])
            if duplicate:
                raise ValidationError(
                    f"Asset '{line.asset_id.name}' (Tag: {line.asset_id.asset_tag}) "
                    "has already been added to this audit cycle. Each asset can appear only once per audit."
                )
