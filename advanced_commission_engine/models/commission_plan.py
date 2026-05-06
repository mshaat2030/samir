# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class CommissionPlan(models.Model):
    _name = 'commission.plan'
    _description = 'Commission Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'commission.mixin']
    _order = 'sequence, name'
    _rec_name = 'name'

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(string='Plan Name', required=True, tracking=True)
    code = fields.Char(string='Plan Code', copy=False, index=True)
    sequence = fields.Integer(default=10)
    description = fields.Html(string='Description', sanitize=True)
    color = fields.Integer(string='Color Index', default=0)
    tag_ids = fields.Many2many('commission.tag', string='Tags')

    # ── Plan Type ─────────────────────────────────────────────────────────────
    plan_type = fields.Selection([
        ('fixed_percent', 'Fixed Percentage'),
        ('tiered', 'Tiered'),
        ('slab', 'Slab/Bracket'),
        ('formula', 'Formula-Based'),
        ('kpi', 'KPI-Based'),
        ('margin', 'Margin-Based'),
        ('profit', 'Profit-Based'),
        ('revenue', 'Revenue-Based'),
        ('hybrid', 'Hybrid'),
    ], string='Plan Type', required=True, default='fixed_percent', tracking=True)

    base_metric = fields.Selection([
        ('sale_amount', 'Sale Amount'),
        ('invoiced_amount', 'Invoiced Amount'),
        ('collected_amount', 'Collected Amount'),
        ('margin_amount', 'Margin Amount'),
        ('profit_amount', 'Profit Amount'),
        ('gross_profit', 'Gross Profit'),
        ('net_revenue', 'Net Revenue'),
    ], string='Base Metric', default='invoiced_amount', required=True)

    commission_base = fields.Selection([
        ('pre_tax', 'Pre-Tax Amount'),
        ('post_tax', 'Post-Tax Amount'),
        ('net', 'Net Amount'),
    ], string='Commission Base', default='pre_tax', required=True)

    # ── Fixed Percentage ──────────────────────────────────────────────────────
    fixed_rate = fields.Float(
        string='Fixed Rate (%)',
        digits=(5, 4),
        help='Commission rate as percentage (e.g. 5.0 = 5%)',
    )

    # ── Caps & Floors ─────────────────────────────────────────────────────────
    has_cap = fields.Boolean(string='Apply Cap')
    cap_amount = fields.Monetary(string='Maximum Commission', currency_field='currency_id')
    has_floor = fields.Boolean(string='Apply Floor')
    floor_amount = fields.Monetary(string='Minimum Commission', currency_field='currency_id')
    cap_type = fields.Selection([
        ('amount', 'Fixed Amount'),
        ('percent_of_base', 'Percent of Base'),
        ('percent_of_salary', 'Percent of Salary'),
    ], string='Cap Type', default='amount')

    # ── Validity ──────────────────────────────────────────────────────────────
    date_from = fields.Date(string='Valid From', required=True, tracking=True)
    date_to = fields.Date(string='Valid To', tracking=True)
    is_active_now = fields.Boolean(
        string='Currently Active',
        compute='_compute_is_active_now',
        store=True,
        search='_search_is_active_now',
    )

    # ── Versioning ────────────────────────────────────────────────────────────
    version = fields.Integer(string='Version', default=1, readonly=True, copy=False)
    parent_plan_id = fields.Many2one(
        'commission.plan', string='Previous Version', readonly=True, copy=False
    )
    child_plan_ids = fields.One2many(
        'commission.plan', 'parent_plan_id', string='Newer Versions', readonly=True
    )

    # ── Assignment ────────────────────────────────────────────────────────────
    assignment_type = fields.Selection([
        ('employee', 'Specific Employees'),
        ('team', 'Sales Teams'),
        ('department', 'Departments'),
        ('job_position', 'Job Positions'),
        ('all', 'All Employees'),
    ], string='Assignment Type', default='employee', required=True)

    employee_ids = fields.Many2many(
        'hr.employee', 'commission_plan_employee_rel',
        'plan_id', 'employee_id',
        string='Employees',
    )
    team_ids = fields.Many2many(
        'crm.team', 'commission_plan_team_rel',
        'plan_id', 'team_id',
        string='Sales Teams',
    )
    department_ids = fields.Many2many(
        'hr.department', 'commission_plan_dept_rel',
        'plan_id', 'department_id',
        string='Departments',
    )
    job_ids = fields.Many2many(
        'hr.job', 'commission_plan_job_rel',
        'plan_id', 'job_id',
        string='Job Positions',
    )

    # ── Rules ─────────────────────────────────────────────────────────────────
    rule_ids = fields.One2many(
        'commission.rule', 'plan_id',
        string='Commission Rules',
        copy=True,
    )
    rule_count = fields.Integer(compute='_compute_rule_count', store=True)

    # ── Trigger ───────────────────────────────────────────────────────────────
    trigger_type = fields.Selection([
        ('sale_confirm', 'Sale Order Confirmed'),
        ('invoice_validate', 'Invoice Validated'),
        ('payment_collect', 'Payment Collected'),
        ('subscription_renew', 'Subscription Renewed'),
        ('project_milestone', 'Project Milestone'),
        ('pos_order', 'POS Order'),
        ('manual', 'Manual'),
    ], string='Trigger', default='invoice_validate', required=True, tracking=True)

    payment_delay_days = fields.Integer(
        string='Payment Delay (Days)',
        default=0,
        help='Days after trigger before commission becomes payable',
    )

    # ── Clawback ──────────────────────────────────────────────────────────────
    has_clawback = fields.Boolean(string='Enable Clawback')
    clawback_days = fields.Integer(
        string='Clawback Period (Days)',
        default=90,
        help='Period during which commission can be clawed back on refund/cancellation',
    )
    clawback_rate = fields.Float(
        string='Clawback Rate (%)',
        default=100.0,
        digits=(5, 2),
    )

    # ── Split Commissions ─────────────────────────────────────────────────────
    allow_split = fields.Boolean(string='Allow Split Commissions')
    split_method = fields.Selection([
        ('equal', 'Equal Split'),
        ('manual', 'Manual Split'),
        ('contribution', 'By Contribution'),
    ], string='Split Method', default='equal')

    # ── Retroactive ───────────────────────────────────────────────────────────
    allow_retroactive = fields.Boolean(string='Allow Retroactive Adjustments')
    retroactive_months = fields.Integer(
        string='Retroactive Period (Months)', default=3
    )

    # ── Formula ───────────────────────────────────────────────────────────────
    formula = fields.Text(
        string='Commission Formula',
        help='Python-safe formula. Available variables: amount, rate, margin, quantity, target, achieved, employee',
    )
    formula_test_amount = fields.Float(string='Test Amount', default=10000.0)
    formula_test_result = fields.Float(string='Test Result', readonly=True)

    # ── KPI Settings ─────────────────────────────────────────────────────────
    kpi_ids = fields.One2many('commission.kpi', 'plan_id', string='KPIs')
    kpi_aggregation = fields.Selection([
        ('all', 'All KPIs Must Be Met'),
        ('weighted', 'Weighted Average'),
        ('best', 'Best KPI'),
    ], string='KPI Aggregation', default='weighted')

    # ── Accounting ────────────────────────────────────────────────────────────
    debit_account_id = fields.Many2one(
        'account.account', string='Commission Expense Account'
    )
    credit_account_id = fields.Many2one(
        'account.account', string='Commission Payable Account'
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Analytic Account'
    )
    journal_id = fields.Many2one(
        'account.journal', string='Accounting Journal',
        domain="[('type', 'in', ['general', 'purchase'])]",
    )

    # ── Payroll ───────────────────────────────────────────────────────────────
    payroll_input_type_id = fields.Many2one(
        'hr.payslip.input.type',
        string='Payroll Input Type',
        help='Payroll input type used when creating payslip entries',
    )
    settlement_method = fields.Selection([
        ('payroll', 'Via Payroll'),
        ('vendor_bill', 'Via Vendor Bill'),
        ('journal_entry', 'Via Journal Entry'),
        ('manual', 'Manual'),
    ], string='Settlement Method', default='payroll', required=True)

    # ── Statistics ────────────────────────────────────────────────────────────
    total_commission_paid = fields.Monetary(
        string='Total Paid',
        compute='_compute_statistics',
        currency_field='currency_id',
    )
    settlement_count = fields.Integer(
        string='Settlements', compute='_compute_statistics'
    )
    employee_count = fields.Integer(
        string='# Employees', compute='_compute_employee_count'
    )

    # ── Constraints ───────────────────────────────────────────────────────────
    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        'Commission plan code must be unique per company.',
    )

    # ── Computes ──────────────────────────────────────────────────────────────
    @api.depends('rule_ids')
    def _compute_rule_count(self):
        for plan in self:
            plan.rule_count = len(plan.rule_ids)

    @api.depends('date_from', 'date_to', 'active')
    def _compute_is_active_now(self):
        today = fields.Date.today()
        for plan in self:
            plan.is_active_now = (
                plan.active and
                plan.date_from <= today and
                (not plan.date_to or plan.date_to >= today)
            )

    @api.model
    def _search_is_active_now(self, operator, value):
        today = fields.Date.today()
        if (operator == '=' and value) or (operator == '!=' and not value):
            return [
                ('active', '=', True),
                ('date_from', '<=', today),
                '|', ('date_to', '=', False), ('date_to', '>=', today),
            ]
        else:
            return [
                '|', ('active', '=', False),
                '|', ('date_from', '>', today),
                ('date_to', '<', today),
            ]

    def _compute_statistics(self):
        SettlementLine = self.env['commission.line']
        for plan in self:
            lines = SettlementLine.search([
                ('plan_id', '=', plan.id),
                ('state', '=', 'paid'),
            ])
            plan.total_commission_paid = sum(lines.mapped('commission_amount'))
            settlements = lines.mapped('settlement_id')
            plan.settlement_count = len(settlements)

    def _compute_employee_count(self):
        for plan in self:
            employees = plan._get_eligible_employees()
            plan.employee_count = len(employees)

    # ── Onchange ──────────────────────────────────────────────────────────────
    @api.onchange('plan_type')
    def _onchange_plan_type(self):
        if self.plan_type == 'fixed_percent':
            self.formula = False
        elif self.plan_type == 'formula' and not self.formula:
            self.formula = "amount * rate / 100"

    @api.onchange('formula', 'formula_test_amount')
    def _onchange_formula_test(self):
        if self.formula and self.formula_test_amount:
            try:
                from ..services.formula_engine import FormulaEngine
                engine = FormulaEngine(self.env)
                result = engine.evaluate(self.formula, {
                    'amount': self.formula_test_amount,
                    'rate': self.fixed_rate or 5.0,
                    'margin': 0.3,
                    'quantity': 1,
                    'target': 10000,
                    'achieved': self.formula_test_amount,
                })
                self.formula_test_result = result
            except Exception as e:
                self.formula_test_result = 0.0

    # ── Validation ────────────────────────────────────────────────────────────
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for plan in self:
            if plan.date_to and plan.date_from > plan.date_to:
                raise ValidationError(
                    _('Valid From must be before Valid To for plan "%s".') % plan.name
                )

    @api.constrains('fixed_rate')
    def _check_fixed_rate(self):
        for plan in self:
            if plan.plan_type == 'fixed_percent' and not (0 <= plan.fixed_rate <= 100):
                raise ValidationError(
                    _('Fixed rate must be between 0 and 100 for plan "%s".') % plan.name
                )

    @api.constrains('formula')
    def _check_formula(self):
        for plan in self:
            if plan.plan_type == 'formula' and plan.formula:
                from ..services.formula_engine import FormulaEngine
                engine = FormulaEngine(self.env)
                try:
                    engine.validate(plan.formula)
                except Exception as e:
                    raise ValidationError(
                        _('Invalid formula in plan "%s": %s') % (plan.name, str(e))
                    )

    # ── Business Logic ────────────────────────────────────────────────────────
    def _get_eligible_employees(self):
        """Return all employees eligible for this plan."""
        self.ensure_one()
        Employee = self.env['hr.employee']
        if self.assignment_type == 'all':
            return Employee.search([('company_id', '=', self.company_id.id)])
        elif self.assignment_type == 'employee':
            return self.employee_ids
        elif self.assignment_type == 'team':
            return Employee.search([
                ('sale_team_id', 'in', self.team_ids.ids),
                ('company_id', '=', self.company_id.id),
            ])
        elif self.assignment_type == 'department':
            return Employee.search([
                ('department_id', 'in', self.department_ids.ids),
                ('company_id', '=', self.company_id.id),
            ])
        elif self.assignment_type == 'job_position':
            return Employee.search([
                ('job_id', 'in', self.job_ids.ids),
                ('company_id', '=', self.company_id.id),
            ])
        return Employee.browse()

    def compute_commission(self, amount, employee=None, context_vals=None):
        """
        Main entry point: compute commission for a given amount.
        Returns a float representing the commission amount.
        """
        self.ensure_one()
        if not context_vals:
            context_vals = {}
        ctx = {
            'amount': amount,
            'rate': self.fixed_rate,
            'plan': self,
            'employee': employee,
            **context_vals,
        }
        if self.plan_type == 'fixed_percent':
            commission = amount * self.fixed_rate / 100.0
        elif self.plan_type in ('tiered', 'slab'):
            commission = self._compute_tiered_commission(amount, ctx)
        elif self.plan_type == 'formula':
            from ..services.formula_engine import FormulaEngine
            engine = FormulaEngine(self.env)
            commission = engine.evaluate(self.formula, ctx)
        elif self.plan_type == 'kpi':
            commission = self._compute_kpi_commission(amount, employee, ctx)
        elif self.plan_type in ('margin', 'profit', 'gross_profit'):
            margin = context_vals.get('margin', 0)
            commission = margin * self.fixed_rate / 100.0
        else:
            commission = amount * self.fixed_rate / 100.0

        # Apply applicable rules
        for rule in self.rule_ids.filtered('active').sorted('priority'):
            if rule._evaluate_conditions(ctx):
                commission = rule.apply(commission, ctx)

        # Apply cap/floor
        if self.has_floor and commission < self.floor_amount:
            commission = self.floor_amount
        if self.has_cap and commission > self.cap_amount:
            commission = self.cap_amount

        return max(0.0, commission)

    def _compute_tiered_commission(self, amount, ctx):
        """Compute tiered/slab commission using rules sorted by from_amount."""
        rules = self.rule_ids.filtered(
            lambda r: r.rule_type in ('tier', 'slab') and r.active
        ).sorted('from_amount')
        commission = 0.0
        remaining = amount
        for rule in rules:
            if remaining <= 0:
                break
            tier_max = rule.to_amount if rule.to_amount > 0 else float('inf')
            applicable = min(remaining, tier_max - rule.from_amount)
            if applicable > 0 and amount >= rule.from_amount:
                if rule.rule_type == 'slab':
                    # Slab: rate applies to total amount if it falls in bracket
                    if rule.from_amount <= amount <= (rule.to_amount or float('inf')):
                        return amount * rule.rate / 100.0
                else:
                    # Tiered: incremental calculation
                    commission += applicable * rule.rate / 100.0
                    remaining -= applicable
        return commission

    def _compute_kpi_commission(self, amount, employee, ctx):
        """Compute KPI-based commission."""
        if not self.kpi_ids or not employee:
            return 0.0
        total_weight = sum(self.kpi_ids.mapped('weight'))
        achievement = 0.0
        for kpi in self.kpi_ids:
            kpi_achieved = kpi.get_achievement(employee)
            if total_weight > 0:
                achievement += (kpi_achieved * kpi.weight / total_weight)
        return amount * self.fixed_rate / 100.0 * (achievement / 100.0)

    def action_new_version(self):
        """Create a new version of this plan."""
        self.ensure_one()
        new_plan = self.copy({
            'name': self.name,
            'version': self.version + 1,
            'parent_plan_id': self.id,
            'date_from': fields.Date.today(),
            'date_to': False,
            'code': self.code,
        })
        self.write({'date_to': fields.Date.today(), 'active': False})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'commission.plan',
            'res_id': new_plan.id,
            'view_mode': 'form',
        }

    def action_view_settlements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Settlements'),
            'res_model': 'commission.settlement',
            'view_mode': 'list,form',
            'domain': [('plan_id', '=', self.id)],
        }

    def action_view_rules(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rules'),
            'res_model': 'commission.rule',
            'view_mode': 'list,form',
            'domain': [('plan_id', '=', self.id)],
            'context': {'default_plan_id': self.id},
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code'):
                vals['code'] = self.env['ir.sequence'].next_by_code('commission.plan') or '/'
        return super().create(vals_list)


class CommissionTag(models.Model):
    _name = 'commission.tag'
    _description = 'Commission Tag'

    name = fields.Char(required=True)
    color = fields.Integer()

    _name_uniq = models.Constraint(
        'UNIQUE(name)',
        'Tag name must be unique.',
    )
