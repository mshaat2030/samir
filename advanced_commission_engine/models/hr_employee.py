# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # Commission fields
    sale_team_id = fields.Many2one(
        'crm.team', string='Sales Team',
        groups='advanced_commission_engine.group_commission_manager',
    )
    commission_plan_ids = fields.Many2many(
        'commission.plan',
        'commission_plan_employee_rel',
        'employee_id', 'plan_id',
        string='Commission Plans',
        groups='advanced_commission_engine.group_commission_manager',
    )
    commission_active = fields.Boolean(
        string='Commission Eligible',
        default=True,
        groups='advanced_commission_engine.group_commission_manager',
    )
    commission_currency_id = fields.Many2one(
        'res.currency',
        string='Commission Currency',
        related='company_id.currency_id',
        readonly=True,
    )

    # Statistics (computed)
    total_commission_ytd = fields.Monetary(
        string='Commission YTD',
        currency_field='commission_currency_id',
        compute='_compute_commission_stats',
        groups='advanced_commission_engine.group_commission_manager',
    )
    total_commission_mtd = fields.Monetary(
        string='Commission MTD',
        currency_field='commission_currency_id',
        compute='_compute_commission_stats',
        groups='advanced_commission_engine.group_commission_manager',
    )
    open_disputes_count = fields.Integer(
        string='Open Disputes',
        compute='_compute_commission_stats',
        groups='advanced_commission_engine.group_commission_manager',
    )
    settlement_count = fields.Integer(
        string='Settlements',
        compute='_compute_commission_stats',
        groups='advanced_commission_engine.group_commission_manager',
    )

    def _compute_commission_stats(self):
        today = fields.Date.today()
        for emp in self:
            # YTD
            ytd_lines = self.env['commission.line'].search([
                ('employee_id', '=', emp.id),
                ('state', '=', 'paid'),
                ('date', '>=', today.replace(month=1, day=1)),
                ('line_type', '=', 'commission'),
            ])
            emp.total_commission_ytd = sum(ytd_lines.mapped('commission_amount'))
            # MTD
            mtd_lines = self.env['commission.line'].search([
                ('employee_id', '=', emp.id),
                ('state', '=', 'paid'),
                ('date', '>=', today.replace(day=1)),
                ('line_type', '=', 'commission'),
            ])
            emp.total_commission_mtd = sum(mtd_lines.mapped('commission_amount'))
            # Disputes
            emp.open_disputes_count = self.env['commission.dispute'].search_count([
                ('employee_id', '=', emp.id),
                ('state', 'in', ('open', 'under_review')),
            ])
            # Settlements
            emp.settlement_count = self.env['commission.settlement'].search_count([
                ('employee_id', '=', emp.id),
            ])

    def action_view_commission_settlements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Settlements for %s') % self.name,
            'res_model': 'commission.settlement',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    def action_view_commission_disputes(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Disputes for %s') % self.name,
            'res_model': 'commission.dispute',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
        }
