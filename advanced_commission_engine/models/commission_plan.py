# -*- coding: utf-8 -*-
"""Commission Plan – the master configuration for all commission types."""

from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError


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

CALCULATION_METHODS = [
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

PERIOD_TYPES = [
    ('weekly', 'Weekly'),
    ('monthly', 'Monthly'),
    ('quarterly', 'Quarterly'),
    ('yearly', 'Yearly'),
    ('custom', 'Custom'),
]


class CommissionPlan(models.Model):
    """Commission Plan defines all configuration for a commission programme.

    A plan holds rules, eligibility criteria, approval workflow settings,
    accounting configuration and integrations with payroll and sales.
    """

    _name = 'commission.plan'
    _description = 'Commission Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'
    _rec_name = 'name'
    _check_company_auto = True

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Plan Name',
        required=True,
        tracking=True,
        index=True,
    )
    code = fields.Char(
        string='Plan Code',
        required=True,
        copy=False,
        index=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('commission.plan'),
        tracking=True,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, tracking=True)
    description = fields.Text(string='Description')
    color = fields.Integer(string='Color', default=0)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )

    # ── Commission Type & Method ──────────────────────────────────────────────
    commission_type = fields.Selection(
        COMMISSION_TYPES,
        string='Commission Type',
        required=True,
        default='sales',
        tracking=True,
        index=True,
    )
    calculation_method = fields.Selection(
        CALCULATION_METHODS,
        string='Calculation Method',
        required=True,
        default='fixed_percent',
        tracking=True,
    )

    # ── Period Configuration ──────────────────────────────────────────────────
    period_type = fields.Selection(
        PERIOD_TYPES,
        string='Period Type',
        required=True,
        default='monthly',
        tracking=True,
    )
    date_start = fields.Date(
        string='Effective From',
        tracking=True,
        index=True,
    )
    date_end = fields.Date(
        string='Effective Until',
        tracking=True,
        index=True,
    )

    # ── Rules ─────────────────────────────────────────────────────────────────
    rule_ids = fields.One2many(
        'commission.rule',
        'plan_id',
        string='Commission Rules',
        copy=True,
    )
    rule_count = fields.Integer(
        string='Rules',
        compute='_compute_rule_count',
    )

    # ── Eligibility ───────────────────────────────────────────────────────────
    employee_ids = fields.Many2many(
        'hr.employee',
        'commission_plan_employee_rel',
        'plan_id',
        'employee_id',
        string='Eligible Employees',
    )
    team_ids = fields.Many2many(
        'crm.team',
        'commission_plan_team_rel',
        'plan_id',
        'team_id',
        string='Eligible Sales Teams',
    )
    job_ids = fields.Many2many(
        'hr.job',
        'commission_plan_job_rel',
        'plan_id',
        'job_id',
        string='Eligible Job Positions',
    )
    department_ids = fields.Many2many(
        'hr.department',
        'commission_plan_dept_rel',
        'plan_id',
        'department_id',
        string='Eligible Departments',
    )

    # ── Product/Category Scope ────────────────────────────────────────────────
    product_ids = fields.Many2many(
        'product.product',
        'commission_plan_product_rel',
        'plan_id',
        'product_id',
        string='Applicable Products',
    )
    product_category_ids = fields.Many2many(
        'product.category',
        'commission_plan_product_cat_rel',
        'plan_id',
        'category_id',
        string='Applicable Product Categories',
    )

    # ── Customer/Region Scope ─────────────────────────────────────────────────
    partner_ids = fields.Many2many(
        'res.partner',
        'commission_plan_partner_rel',
        'plan_id',
        'partner_id',
        string='Specific Customers',
    )
    country_ids = fields.Many2many(
        'res.country',
        'commission_plan_country_rel',
        'plan_id',
        'country_id',
        string='Countries',
    )
    country_group_ids = fields.Many2many(
        'res.country.group',
        'commission_plan_country_group_rel',
        'plan_id',
        'group_id',
        string='Country Groups / Regions',
    )

    # ── Source Document Configuration ─────────────────────────────────────────
    source_document = fields.Selection(
        [
            ('sale_order', 'Sales Order'),
            ('invoice', 'Customer Invoice'),
            ('payment', 'Customer Payment'),
            ('pos_order', 'POS Order'),
            ('project_task', 'Project Task'),
            ('subscription', 'Subscription'),
            ('crm_lead', 'CRM Opportunity'),
        ],
        string='Source Document',
        default='invoice',
        tracking=True,
        help='Which document triggers commission calculation.',
    )
    invoice_state_trigger = fields.Selection(
        [
            ('posted', 'Invoice Posted'),
            ('paid', 'Invoice Fully Paid'),
            ('partial', 'Invoice Partially Paid'),
        ],
        string='Invoice Trigger',
        default='paid',
    )
    include_tax = fields.Boolean(
        string='Include Taxes in Base',
        default=False,
    )
    collection_delay_days = fields.Integer(
        string='Collection Delay Penalty After (Days)',
        default=0,
        help='Apply a penalty for invoices paid after this many days. 0 = no penalty.',
    )
    collection_delay_penalty_pct = fields.Float(
        string='Collection Delay Penalty %',
        default=0.0,
    )

    # ── Approval Workflow ─────────────────────────────────────────────────────
    approval_required = fields.Boolean(
        string='Manager Approval Required',
        default=True,
        tracking=True,
    )
    finance_approval_required = fields.Boolean(
        string='Finance Approval Required',
        default=True,
        tracking=True,
    )
    auto_approve_below = fields.Monetary(
        string='Auto-Approve Below Amount',
        currency_field='currency_id',
        default=0,
        help='Automatically approve settlements below this amount. 0 = never auto-approve.',
    )

    # ── Accounting ────────────────────────────────────────────────────────────
    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Analytic Account',
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Accounting Journal',
        domain=[('type', 'in', ['general', 'purchase'])],
    )
    expense_account_id = fields.Many2one(
        'account.account',
        string='Commission Expense Account',
        domain=[('deprecated', '=', False)],
    )
    payable_account_id = fields.Many2one(
        'account.account',
        string='Commission Payable Account',
        domain=[('deprecated', '=', False)],
    )
    create_accrual = fields.Boolean(
        string='Create Accrual Entries',
        default=False,
    )

    # ── Payroll Integration ───────────────────────────────────────────────────
    payroll_input_type_id = fields.Many2one(
        'hr.payslip.input.type',
        string='Payroll Input Type',
        help='Commission amount will be injected into payslips using this input type.',
    )
    is_taxable = fields.Boolean(
        string='Taxable Commission',
        default=True,
    )

    # ── KPI Configuration ─────────────────────────────────────────────────────
    kpi_ids = fields.Many2many(
        'commission.kpi',
        'commission_plan_kpi_rel',
        'plan_id',
        'kpi_id',
        string='KPIs',
    )
    formula_id = fields.Many2one(
        'commission.formula',
        string='Dynamic Formula',
    )

    # ── Gamification ──────────────────────────────────────────────────────────
    enable_leaderboard = fields.Boolean(
        string='Enable Leaderboard',
        default=True,
    )
    enable_badges = fields.Boolean(
        string='Enable Badges',
        default=True,
    )

    # ── Stats (computed) ─────────────────────────────────────────────────────
    settlement_count = fields.Integer(
        compute='_compute_settlement_count',
        string='Settlements',
    )
    total_paid = fields.Monetary(
        compute='_compute_total_paid',
        string='Total Paid',
        currency_field='currency_id',
    )

    # ── State ─────────────────────────────────────────────────────────────────
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('archived', 'Archived'),
        ],
        default='draft',
        tracking=True,
        index=True,
    )


    # ── Computes ──────────────────────────────────────────────────────────────
    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        'Plan code must be unique per company.',
    )


    @api.depends('rule_ids')
    def _compute_rule_count(self):
        for plan in self:
            plan.rule_count = len(plan.rule_ids)

    def _compute_settlement_count(self):
        data = self.env['commission.settlement'].read_group(
            [('plan_id', 'in', self.ids)],
            ['plan_id'],
            ['plan_id'],
        )
        mapping = {d['plan_id'][0]: d['plan_id_count'] for d in data}
        for plan in self:
            plan.settlement_count = mapping.get(plan.id, 0)

    def _compute_total_paid(self):
        data = self.env['commission.settlement'].read_group(
            [('plan_id', 'in', self.ids), ('state', '=', 'paid')],
            ['plan_id', 'final_amount:sum'],
            ['plan_id'],
        )
        mapping = {d['plan_id'][0]: d['final_amount'] for d in data}
        for plan in self:
            plan.total_paid = mapping.get(plan.id, 0.0)

    # ── Constraints ───────────────────────────────────────────────────────────
    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for plan in self:
            if plan.date_start and plan.date_end and plan.date_start > plan.date_end:
                raise ValidationError('Plan start date must be before end date.')

    @api.constrains('collection_delay_penalty_pct')
    def _check_penalty_pct(self):
        for plan in self:
            if not (0 <= plan.collection_delay_penalty_pct <= 100):
                raise ValidationError('Collection delay penalty must be between 0 and 100%.')

    # ── Onchange ──────────────────────────────────────────────────────────────
    @api.onchange('calculation_method')
    def _onchange_calculation_method(self):
        if self.calculation_method != 'dynamic_formula':
            self.formula_id = False
        if self.calculation_method != 'weighted_kpi':
            self.kpi_ids = [(5,)]

    @api.onchange('commission_type')
    def _onchange_commission_type(self):
        """Set sensible defaults based on commission type."""
        mapping = {
            'sales': 'invoice',
            'collection': 'payment',
            'recurring': 'subscription',
            'subscription_renewal': 'subscription',
            'project_milestone': 'project_task',
            'referral': 'invoice',
            'manager_override': 'invoice',
            'team': 'invoice',
            'recruitment': 'invoice',
            'profit_sharing': 'invoice',
            'territory': 'invoice',
            'kpi_incentive': 'invoice',
        }
        self.source_document = mapping.get(self.commission_type, 'invoice')

    # ── Actions ───────────────────────────────────────────────────────────────
    def action_activate(self):
        for plan in self:
            if not plan.rule_ids:
                raise UserError('Cannot activate a plan with no rules.')
            plan.state = 'active'

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_archive_plan(self):
        self.write({'state': 'archived', 'active': False})

    def action_view_settlements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Settlements – {self.name}',
            'res_model': 'commission.settlement',
            'view_mode': 'list,form',
            'domain': [('plan_id', '=', self.id)],
            'context': {'default_plan_id': self.id},
        }

    def action_view_rules(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Rules – {self.name}',
            'res_model': 'commission.rule',
            'view_mode': 'list,form',
            'domain': [('plan_id', '=', self.id)],
            'context': {'default_plan_id': self.id},
        }

    def action_simulate(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Simulate – {self.name}',
            'res_model': 'wizard.commission.simulator',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_plan_id': self.id},
        }

    def action_new_version(self):
        """Create a new version of this plan."""
        self.ensure_one()
        sequence_val = self.env['ir.sequence'].next_by_code('commission.plan') or '/'
        new_plan = self.copy({
            'name': f'{self.name} (v2)',
            'code': sequence_val,
            'state': 'draft',
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'commission.plan',
            'view_mode': 'form',
            'res_id': new_plan.id,
        }

    # ── ORM Overrides ─────────────────────────────────────────────────────────
    def unlink(self):
        for plan in self:
            if plan.state == 'active':
                raise UserError(f"Cannot delete active plan '{plan.name}'. Archive it first.")
        return super().unlink()
