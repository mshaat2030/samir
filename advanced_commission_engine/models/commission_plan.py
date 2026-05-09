# -*- coding: utf-8 -*-
"""Commission Plan — master configuration for a commission scheme."""

import logging
from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)

COMMISSION_TYPES = [
    ('sales', 'Sales Commission'),
    ('collection', 'Collection Commission'),
    ('recurring', 'Recurring Commission'),
    ('subscription_renewal', 'Subscription Renewal'),
    ('project_milestone', 'Project Milestone'),
    ('referral', 'Referral Commission'),
    ('manager_override', 'Manager Override'),
    ('team', 'Team Commission'),
    ('recruitment', 'Recruitment Commission'),
    ('profit_sharing', 'Profit Sharing'),
    ('territory', 'Territory Commission'),
    ('kpi_incentive', 'KPI Incentive'),
]

CALC_METHODS = [
    ('fixed_percent', 'Fixed Percentage'),
    ('fixed_amount', 'Fixed Amount'),
    ('progressive_slabs', 'Progressive Slabs'),
    ('tiered', 'Tiered'),
    ('margin_based', 'Margin Based'),
    ('revenue_based', 'Revenue Based'),
    ('profit_based', 'Profit Based'),
    ('weighted_kpi', 'Weighted KPI Score'),
    ('hybrid', 'Hybrid'),
    ('dynamic_formula', 'Dynamic Formula'),
]

BASE_ON = [
    ('invoice', 'Customer Invoice'),
    ('payment', 'Customer Payment'),
    ('sale_order', 'Sale Order'),
    ('subscription', 'Subscription'),
    ('project_task', 'Project Task'),
    ('crm_lead', 'CRM Lead'),
    ('kpi', 'KPI Score'),
    ('custom', 'Custom / Formula'),
]


class CommissionPlan(models.Model):
    """Master commission plan definition."""

    _name = 'commission.plan'
    _description = 'Commission Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _rec_name = 'name'

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(string='Plan Name', required=True, tracking=True)
    code = fields.Char(
        string='Code', required=True, copy=False,
        default=lambda self: self.env['ir.sequence'].next_by_code('commission.plan'),
    )
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Company',
        required=True, default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        related='company_id.currency_id', store=True, readonly=True,
    )

    # ── Type & Method ─────────────────────────────────────────────────────────
    commission_type = fields.Selection(
        COMMISSION_TYPES, string='Commission Type',
        required=True, tracking=True, index=True,
    )
    calculation_method = fields.Selection(
        CALC_METHODS, string='Calculation Method',
        required=True, tracking=True,
    )
    base_on = fields.Selection(
        BASE_ON, string='Base On',
        required=True, default='invoice', tracking=True,
        help='What source document drives commission calculation.',
    )

    # ── Rules ─────────────────────────────────────────────────────────────────
    rule_ids = fields.One2many(
        'commission.rule', 'plan_id', string='Commission Rules',
    )
    rule_count = fields.Integer(compute='_compute_rule_count')

    # ── Employees & Teams ─────────────────────────────────────────────────────
    employee_ids = fields.Many2many(
        'hr.employee', 'commission_plan_employee_rel',
        'plan_id', 'employee_id',
        string='Assigned Employees',
    )
    team_ids = fields.Many2many(
        'crm.team', 'commission_plan_team_rel',
        'plan_id', 'team_id',
        string='Assigned Sales Teams',
    )

    # ── Formula ───────────────────────────────────────────────────────────────
    formula_id = fields.Many2one(
        'commission.formula', string='Dynamic Formula',
        domain=[('active', '=', True)],
        help='Used when calculation_method = dynamic_formula.',
    )

    # ── Thresholds & Limits ───────────────────────────────────────────────────
    min_commission = fields.Monetary(string='Minimum Commission', currency_field='currency_id')
    max_commission = fields.Monetary(string='Maximum Commission (Cap)', currency_field='currency_id')
    min_base_amount = fields.Monetary(
        string='Minimum Base Amount',
        currency_field='currency_id',
        help='Transactions below this amount are excluded.',
    )
    max_base_amount = fields.Monetary(
        string='Maximum Base Amount',
        currency_field='currency_id',
        help='Transactions above this amount use this as the cap.',
    )

    # ── Collection Settings ───────────────────────────────────────────────────
    collection_delay_penalty = fields.Float(
        string='Collection Delay Penalty (%/month)',
        help='Penalty applied for each month of collection delay.',
    )
    max_invoice_age_days = fields.Integer(
        string='Max Invoice Age (Days)',
        default=0,
        help='0 = no limit. Invoices older than this are excluded.',
    )

    # ── Payroll Integration ───────────────────────────────────────────────────
    payroll_salary_rule_id = fields.Many2one(
        'hr.salary.rule', string='Salary Rule',
        help='Salary rule used when processing commission in payroll.',
    )
    is_taxable = fields.Boolean(string='Taxable', default=True, tracking=True)

    # ── Accounting ────────────────────────────────────────────────────────────
    account_id = fields.Many2one(
        'account.account', string='Commission Account',
        domain=[('deprecated', '=', False)],
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Analytic Account',
    )
    journal_id = fields.Many2one(
        'account.journal', string='Commission Journal',
    )

    # ── Approval Workflow ─────────────────────────────────────────────────────
    require_manager_approval = fields.Boolean(
        string='Require Manager Approval', default=True, tracking=True,
    )
    require_finance_approval = fields.Boolean(
        string='Require Finance Approval', default=True, tracking=True,
    )
    require_hr_approval = fields.Boolean(
        string='Require HR Approval', default=False, tracking=True,
    )
    auto_approve_threshold = fields.Monetary(
        string='Auto-Approve Threshold',
        currency_field='currency_id',
        help='Settlements below this amount are auto-approved.',
    )

    # ── Gamification ──────────────────────────────────────────────────────────
    enable_gamification = fields.Boolean(string='Enable Gamification', default=True)
    enable_leaderboard = fields.Boolean(string='Enable Leaderboard', default=True)
    enable_badges = fields.Boolean(string='Enable Badges', default=True)

    # ── Clawback Settings ─────────────────────────────────────────────────────
    enable_clawback = fields.Boolean(string='Enable Clawback', tracking=True)
    clawback_period_months = fields.Integer(
        string='Clawback Period (Months)', default=3,
        help='Number of months after payment within which clawback can occur.',
    )

    # ── Split Payout ──────────────────────────────────────────────────────────
    enable_split_payout = fields.Boolean(string='Enable Split Payout')
    split_payout_count = fields.Integer(string='Split Payout Installments', default=1)

    # ── Notes ─────────────────────────────────────────────────────────────────
    description = fields.Html(string='Description')
    notes = fields.Text(string='Internal Notes')

    # ── Computed Stats ────────────────────────────────────────────────────────
    settlement_count = fields.Integer(compute='_compute_settlement_count', string='Settlements')
    employee_count = fields.Integer(compute='_compute_employee_count', string='Employees')
    total_paid = fields.Monetary(
        compute='_compute_total_paid', currency_field='currency_id',
        string='Total Paid (YTD)',
    )

    _sql_constraints = [
        ('code_company_uniq', 'UNIQUE(code, company_id)', 'Plan code must be unique per company.'),
        ('min_commission_gte_zero', 'CHECK(min_commission >= 0)', 'Minimum commission cannot be negative.'),
        ('max_commission_gte_zero', 'CHECK(max_commission >= 0)', 'Maximum commission cannot be negative.'),
        ('split_payout_count_gte_one', 'CHECK(split_payout_count >= 1)', 'Split payout installments must be at least 1.'),
    ]

    # ── Compute ───────────────────────────────────────────────────────────────

    @api.depends('rule_ids')
    def _compute_rule_count(self):
        for rec in self:
            rec.rule_count = len(rec.rule_ids)

    def _compute_settlement_count(self):
        Settlement = self.env['commission.settlement']
        for rec in self:
            rec.settlement_count = Settlement.search_count([('plan_id', '=', rec.id)])

    def _compute_employee_count(self):
        for rec in self:
            rec.employee_count = len(rec.employee_ids)

    def _compute_total_paid(self):
        Settlement = self.env['commission.settlement']
        for rec in self:
            domain = [('plan_id', '=', rec.id), ('state', '=', 'paid')]
            settlements = Settlement.search(domain)
            rec.total_paid = sum(settlements.mapped('total_commission'))

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('min_commission', 'max_commission')
    def _check_commission_limits(self):
        for rec in self:
            if rec.max_commission and rec.min_commission > rec.max_commission:
                raise ValidationError('Minimum commission cannot exceed maximum commission.')

    @api.constrains('min_base_amount', 'max_base_amount')
    def _check_base_limits(self):
        for rec in self:
            if rec.max_base_amount and rec.min_base_amount > rec.max_base_amount:
                raise ValidationError('Minimum base amount cannot exceed maximum base amount.')

    @api.constrains('calculation_method', 'formula_id')
    def _check_formula_required(self):
        for rec in self:
            if rec.calculation_method == 'dynamic_formula' and not rec.formula_id:
                raise ValidationError('A formula must be selected when using Dynamic Formula method.')

    # ── Onchange ──────────────────────────────────────────────────────────────

    @api.onchange('commission_type')
    def _onchange_commission_type(self):
        type_base_map = {
            'sales': 'invoice',
            'collection': 'payment',
            'recurring': 'subscription',
            'subscription_renewal': 'subscription',
            'project_milestone': 'project_task',
            'referral': 'crm_lead',
            'manager_override': 'invoice',
            'team': 'invoice',
            'recruitment': 'custom',
            'profit_sharing': 'custom',
            'territory': 'invoice',
            'kpi_incentive': 'kpi',
        }
        if self.commission_type:
            self.base_on = type_base_map.get(self.commission_type, 'invoice')

    @api.onchange('calculation_method')
    def _onchange_calculation_method(self):
        if self.calculation_method != 'dynamic_formula':
            self.formula_id = False

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_view_rules(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Rules — {self.name}',
            'res_model': 'commission.rule',
            'view_mode': 'list,form',
            'domain': [('plan_id', '=', self.id)],
            'context': {'default_plan_id': self.id},
        }

    def action_view_settlements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Settlements — {self.name}',
            'res_model': 'commission.settlement',
            'view_mode': 'list,kanban,form',
            'domain': [('plan_id', '=', self.id)],
        }

    def action_duplicate_plan(self):
        """Duplicate this plan with a new code."""
        self.ensure_one()
        new_plan = self.copy({'code': self.code + '-COPY', 'name': self.name + ' (Copy)'})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'commission.plan',
            'view_mode': 'form',
            'res_id': new_plan.id,
        }

    def action_archive(self):
        self.write({'active': False})

    # ── Helpers ───────────────────────────────────────────────────────────────

    def get_applicable_rules(self, employee=None, invoice=None, sale_order=None):
        """Return rules matching the given context, ordered by priority."""
        self.ensure_one()
        rules = self.rule_ids.filtered('active').sorted('sequence')
        result = []
        for rule in rules:
            if rule.matches_context(employee=employee, invoice=invoice, sale_order=sale_order):
                result.append(rule)
                if rule.stop_further_rules:
                    break
        return result

    def apply_commission_cap(self, amount):
        """Clamp commission to plan limits."""
        self.ensure_one()
        if self.min_commission and amount < self.min_commission:
            amount = self.min_commission
        if self.max_commission and amount > self.max_commission:
            amount = self.max_commission
        return amount
