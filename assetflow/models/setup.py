# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta


class AssetflowDepartment(models.Model):
    _name = 'assetflow.department'
    _description = 'AssetFlow Department'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _parent_name = 'parent_id'
    _parent_store = True
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(string='Department Name', required=True, tracking=True)
    department_head_id = fields.Many2one(
        'res.users', string='Department Head', tracking=True,
        domain="[('share', '=', False)]",
    )
    parent_id = fields.Many2one(
        'assetflow.department', string='Parent Department',
        index=True, ondelete='restrict',
    )
    child_ids = fields.One2many('assetflow.department', 'parent_id', string='Sub-Departments')
    parent_path = fields.Char(index=True)
    active = fields.Boolean(default=True, tracking=True)
    asset_count = fields.Integer(string='Assets', compute='_compute_asset_count')
    employee_count = fields.Integer(string='Employees', compute='_compute_employee_count')
    description = fields.Text(string='Description')

    def _compute_asset_count(self):
        for dept in self:
            dept.asset_count = self.env['assetflow.asset'].search_count(
                [('department_id', '=', dept.id)]
            )

    def _compute_employee_count(self):
        for dept in self:
            dept.employee_count = self.env['hr.employee'].search_count(
                [('assetflow_department_id', '=', dept.id)]
            )

    def action_open_assets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Assets — {self.name}',
            'res_model': 'assetflow.asset',
            'view_mode': 'list,kanban,form',
            'domain': [('department_id', '=', self.id)],
            'context': {'default_department_id': self.id},
        }


class AssetflowCategory(models.Model):
    _name = 'assetflow.category'
    _description = 'Asset Category'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Category Name', required=True, tracking=True)
    warranty_period = fields.Integer(
        string='Warranty Period (Months)', default=12,
        help='Standard warranty duration in months for assets in this category.',
    )
    description = fields.Text(string='Description')
    color = fields.Integer(string='Color Index')
    asset_count = fields.Integer(string='Assets', compute='_compute_asset_count')
    active = fields.Boolean(default=True)

    def _compute_asset_count(self):
        for cat in self:
            cat.asset_count = self.env['assetflow.asset'].search_count(
                [('category_id', '=', cat.id)]
            )


class HrEmployeeAssetflow(models.Model):
    """
    Extends hr.employee with AssetFlow-specific role and department linkage.
    Role assignment is restricted to Admin-group members at ORM level.
    """
    _inherit = 'hr.employee'

    assetflow_role = fields.Selection(
        selection=[
            ('admin', 'AssetFlow Admin'),
            ('manager', 'Asset Manager'),
            ('dept_head', 'Department Head'),
            ('employee', 'Employee'),
        ],
        string='AssetFlow Role',
        default='employee',
        tracking=True,
    )
    assetflow_department_id = fields.Many2one(
        'assetflow.department',
        string='AssetFlow Department',
        tracking=True,
    )
    employee_asset_count = fields.Integer(
        string='Assets Held', compute='_compute_employee_asset_count',
    )

    def _compute_employee_asset_count(self):
        Allocation = self.env['assetflow.allocation']
        for emp in self:
            emp.employee_asset_count = Allocation.search_count(
                [('employee_id', '=', emp.id), ('state', '=', 'active')]
            )

    def _is_assetflow_admin(self):
        admin_group = self.env.ref('assetflow.group_assetflow_admin', raise_if_not_found=False)
        return admin_group and self.env.user in admin_group.users

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'assetflow_role' in vals and vals.get('assetflow_role') != 'employee':
                if not self._is_assetflow_admin():
                    from odoo.exceptions import AccessError
                    raise AccessError(
                        "Only an AssetFlow Admin can assign roles other than 'Employee'. "
                        "Please contact your system administrator."
                    )
        return super().create(vals_list)

    def write(self, vals):
        if 'assetflow_role' in vals and not self._is_assetflow_admin():
            from odoo.exceptions import AccessError
            raise AccessError(
                "Only an AssetFlow Admin can reassign AssetFlow Roles. "
                "Please contact your system administrator."
            )
        return super().write(vals)

    def action_promote_to_manager(self):
        self.ensure_one()
        if not self._is_assetflow_admin():
            from odoo.exceptions import AccessError
            raise AccessError("Only Admins can promote employees.")
        self.write({'assetflow_role': 'manager'})
        manager_group = self.env.ref('assetflow.group_assetflow_manager', raise_if_not_found=False)
        if manager_group and self.user_id:
            manager_group.write({'users': [(4, self.user_id.id)]})

    def action_promote_to_dept_head(self):
        self.ensure_one()
        if not self._is_assetflow_admin():
            from odoo.exceptions import AccessError
            raise AccessError("Only Admins can promote employees.")
        self.write({'assetflow_role': 'dept_head'})
        dept_head_group = self.env.ref('assetflow.group_assetflow_dept_head', raise_if_not_found=False)
        if dept_head_group and self.user_id:
            dept_head_group.write({'users': [(4, self.user_id.id)]})
