# -*- coding: utf-8 -*-
"""
asc.commission.plan — Master commission plan configuration.
Supports: Fixed, Percentage, Tiered, Target-based, Margin-based,
          Product/Category-based, Team, Manager Override, Bonus/Accelerators, Clawbacks.
"""
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class AscCommissionPlan(models.Model):
    _name = 'asc.commission.plan'
    _description = 'Commission Plan'
    _inherit = ['asc.multi.company.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'
    _rec_name = 'name'

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(string='Plan Name', required=True, tracking=True)
    code = fields.Char(string='Code', copy=False, readonly=True,
                       default=lambda self: self.env['ir.sequence'].next_by_code('asc.commission.plan'))
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True, tracking=True)
    color = fields.Integer(string='Color Index')

    # ── Plan Type ─────────────────────────────────────────────────────────────
    plan_type = fields.Selection([
        ('fixed', 'Fixed Amount'),
        ('percentage', 'Percentage of Sale'),
        ('tiered', 'Tiered'),
        ('target_based', 'Target-Based'),
        ('margin_based', 'Margin-Based'),
        ('product_based', 'Product / Category'),
        ('team', 'Team Commission'),
        ('mixed', 'Mixed Rules'),
    ], string='Plan Type', required=True, default='percentage', tracking=True)

    # ── Assignment ────────────────────────────────────────────────────────────
    user_ids = fields.Many2many(
        'res.users', 'asc_plan_user_rel', 'plan_id', 'user_id',
        string='Assigned Salespersons',
        domain=[('share', '=', False)],
    )
    team_ids = fields.Many2many(
        'crm.team', 'asc_plan_team_rel', 'plan_id', 'team_id',
        string='Assigned Sales Teams',
    )
    job_position_ids = fields.Many2many(
        'hr.job', 'asc_plan_job_rel', 'plan_id', 'job_id',
        string='Applicable Job Positions',
    )

    # ── Validity ──────────────────────────────────────────────────────────────
    date_from = fields.Date(string='Effective From', required=True, tracking=True)
    date_to = fields.Date(string='Effective To', tracking=True)

    # ── Calculation Base ──────────────────────────────────────────────────────
    calculation_base = fields.Selection([
        ('invoiced', 'Invoiced Amount'),
        ('ordered', 'Ordered Amount'),
        ('collected', 'Collected/Paid Amount'),
    ], string='Calculation Base', default='invoiced', required=True)

    # ── Fixed Amount ─────────────────────────────────────────────────────────
    fixed_amount = fields.Monetary(string='Fixed Amount', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', required=True,
        default=lambda self: self.env.company.currency_id,
    )

    # ── Percentage ────────────────────────────────────────────────────────────
    commission_rate = fields.Float(string='Commission Rate (%)', digits=(16, 4))

    # ── Margin ────────────────────────────────────────────────────────────────
    margin_rate = fields.Float(string='Margin Rate (%)', digits=(16, 4))
    min_margin_pct = fields.Float(string='Minimum Margin % to Qualify', digits=(16, 2))

    # ── Target / Accelerators ─────────────────────────────────────────────────
    has_target = fields.Boolean(string='Enable Targets')
    target_period = fields.Selection([
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('annual', 'Annual'),
    ], string='Target Period', default='monthly')

    # ── Clawback ──────────────────────────────────────────────────────────────
    has_clawback = fields.Boolean(string='Enable Clawback')
    clawback_days = fields.Integer(string='Clawback Window (Days)', default=90)
    clawback_trigger = fields.Selection([
        ('credit_note', 'Credit Note'),
        ('cancellation', 'Order Cancellation'),
        ('non_payment', 'Non-Payment'),
    ], string='Clawback Trigger', default='credit_note')

    # ── Manager Override ──────────────────────────────────────────────────────
    allow_manager_override = fields.Boolean(string='Allow Manager Override')
    max_override_pct = fields.Float(string='Max Override (%)', digits=(16, 2), default=20.0)

    # ── Team Split ────────────────────────────────────────────────────────────
    team_split_method = fields.Selection([
        ('equal', 'Equal Split'),
        ('weighted', 'Weighted by Role'),
        ('custom', 'Custom %'),
    ], string='Team Split Method', default='equal')

    # ── Rules ─────────────────────────────────────────────────────────────────
    rule_ids = fields.One2many(
        'asc.commission.rule', 'plan_id',
        string='Commission Rules',
    )
    rule_count = fields.Integer(compute='_compute_rule_count', store=True)

    # ── Settlement ────────────────────────────────────────────────────────────
    settlement_frequency = fields.Selection([
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('on_approval', 'On Approval'),
    ], string='Settlement Frequency', default='monthly')

    payroll_input_type_id = fields.Many2one(
        'hr.payslip.input.type', string='Payroll Input Type',
        help='Used when pushing commissions to payroll.',
    )

    # ── Accounting ────────────────────────────────────────────────────────────
    commission_account_id = fields.Many2one(
        'account.account', string='Commission Expense Account',
    )
    payable_account_id = fields.Many2one(
        'account.account', string='Commission Payable Account',
    )
    journal_id = fields.Many2one(
        'account.journal', string='Commission Journal',
    )

    # ── Notes ─────────────────────────────────────────────────────────────────
    description = fields.Html(string='Description')
    notes = fields.Text(string='Internal Notes')

    # ─────────────────────────────────────────────────────────────────────────
    # Computed
    # ─────────────────────────────────────────────────────────────────────────
    @api.depends('rule_ids')
    def _compute_rule_count(self):
        for plan in self:
            plan.rule_count = len(plan.rule_ids)

    # ─────────────────────────────────────────────────────────────────────────
    # Constraints
    # ─────────────────────────────────────────────────────────────────────────
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for plan in self:
            if plan.date_to and plan.date_from and plan.date_to < plan.date_from:
                raise ValidationError(_('Effective To must be after Effective From.'))

    @api.constrains('commission_rate')
    def _check_rate(self):
        for plan in self:
            if plan.commission_rate < 0 or plan.commission_rate > 100:
                raise ValidationError(_('Commission rate must be between 0 and 100.'))

    @api.constrains('max_override_pct')
    def _check_override(self):
        for plan in self:
            if plan.max_override_pct < 0 or plan.max_override_pct > 100:
                raise ValidationError(_('Max override must be between 0 and 100.'))

    # ─────────────────────────────────────────────────────────────────────────
    # Business Methods
    # ─────────────────────────────────────────────────────────────────────────
    def is_valid_for_date(self, date):
        """Check if plan is active on a given date."""
        self.ensure_one()
        if date < self.date_from:
            return False
        if self.date_to and date > self.date_to:
            return False
        return True

    def action_view_rules(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Commission Rules'),
            'res_model': 'asc.commission.rule',
            'view_mode': 'list,form',
            'domain': [('plan_id', '=', self.id)],
            'context': {'default_plan_id': self.id},
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Constraints
    # ─────────────────────────────────────────────────────────────────────────
    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        'Commission plan code must be unique per company.',
    )
