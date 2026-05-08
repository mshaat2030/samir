# -*- coding: utf-8 -*-
"""Commission Target – employee targets for a given period and plan."""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CommissionTarget(models.Model):
    """Defines revenue/commission targets for an employee in a period under a plan.

    Tracks achievement in real-time and shows progress towards targets.
    """

    _name = 'commission.target'
    _description = 'Commission Target'
    _inherit = ['mail.thread']
    _order = 'period_id desc, employee_id'
    _check_company_auto = True

    name = fields.Char(
        string='Target Name',
        compute='_compute_name',
        store=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True,
        tracking=True,
    )
    plan_id = fields.Many2one(
        'commission.plan',
        string='Commission Plan',
        required=True,
        index=True,
    )
    period_id = fields.Many2one(
        'commission.period',
        string='Period',
        required=True,
        index=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )

    # ── Targets ───────────────────────────────────────────────────────────────
    revenue_target = fields.Monetary(
        string='Revenue Target',
        currency_field='currency_id',
        default=0.0,
        tracking=True,
    )
    commission_target = fields.Monetary(
        string='Commission Target',
        currency_field='currency_id',
        default=0.0,
        tracking=True,
    )
    units_target = fields.Float(
        string='Units Target',
        default=0.0,
    )
    new_customers_target = fields.Integer(
        string='New Customers Target',
        default=0,
    )
    collection_target = fields.Monetary(
        string='Collection Target',
        currency_field='currency_id',
        default=0.0,
    )

    # ── Achievements ──────────────────────────────────────────────────────────
    revenue_achieved = fields.Monetary(
        string='Revenue Achieved',
        currency_field='currency_id',
        compute='_compute_achievements',
        store=True,
    )
    commission_achieved = fields.Monetary(
        string='Commission Achieved',
        currency_field='currency_id',
        compute='_compute_achievements',
        store=True,
    )

    # ── Progress ──────────────────────────────────────────────────────────────
    revenue_attainment = fields.Float(
        string='Revenue Attainment %',
        compute='_compute_attainment',
        store=True,
        digits=(16, 1),
    )
    commission_attainment = fields.Float(
        string='Commission Attainment %',
        compute='_compute_attainment',
        store=True,
        digits=(16, 1),
    )
    overall_attainment = fields.Float(
        string='Overall Attainment %',
        compute='_compute_attainment',
        store=True,
        digits=(16, 1),
    )
    progress_bar_value = fields.Float(
        string='Progress Bar Value',
        compute='_compute_attainment',
        store=True,
    )
    progress_color = fields.Char(
        string='Progress Color',
        compute='_compute_progress_color',
    )

    # ── KPI Values ────────────────────────────────────────────────────────────
    kpi_value_ids = fields.One2many(
        'commission.kpi.value',
        'target_id',
        string='KPI Values',
    )

    # ── State ─────────────────────────────────────────────────────────────────
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('closed', 'Closed'),
        ],
        default='draft',
        tracking=True,
    )
    notes = fields.Text(string='Notes')


    _employee_plan_period_uniq = models.Constraint(
        'UNIQUE(employee_id, plan_id, period_id)',
        'A target already exists for this employee/plan/period.',
    )


    @api.depends('employee_id', 'period_id', 'plan_id')
    def _compute_name(self):
        for target in self:
            parts = []
            if target.employee_id:
                parts.append(target.employee_id.name)
            if target.plan_id:
                parts.append(target.plan_id.name)
            if target.period_id:
                parts.append(target.period_id.name)
            target.name = ' – '.join(parts) or 'Target'

    @api.depends(
        'employee_id',
        'period_id',
        'plan_id',
    )
    def _compute_achievements(self):
        for target in self:
            # Sum from commission settlements
            settlements = self.env['commission.settlement'].search([
                ('employee_id', '=', target.employee_id.id),
                ('period_id', '=', target.period_id.id),
                ('plan_id', '=', target.plan_id.id),
                ('state', 'not in', ('cancelled',)),
            ])
            target.commission_achieved = sum(settlements.mapped('final_amount'))
            # Sum base amount as revenue proxy
            target.revenue_achieved = sum(
                self.env['commission.line'].search([
                    ('employee_id', '=', target.employee_id.id),
                    ('period_id', '=', target.period_id.id),
                    ('plan_id', '=', target.plan_id.id),
                    ('state', '!=', 'cancelled'),
                ]).mapped('base_amount')
            )

    @api.depends('revenue_target', 'revenue_achieved', 'commission_target', 'commission_achieved')
    def _compute_attainment(self):
        for target in self:
            if target.revenue_target:
                target.revenue_attainment = min(
                    100.0, (target.revenue_achieved / target.revenue_target) * 100
                )
            else:
                target.revenue_attainment = 0.0

            if target.commission_target:
                target.commission_attainment = min(
                    100.0, (target.commission_achieved / target.commission_target) * 100
                )
            else:
                target.commission_attainment = 0.0

            # Overall: average of non-zero targets
            attainments = []
            if target.revenue_target:
                attainments.append(target.revenue_attainment)
            if target.commission_target:
                attainments.append(target.commission_attainment)

            target.overall_attainment = (
                sum(attainments) / len(attainments) if attainments else 0.0
            )
            target.progress_bar_value = min(100.0, target.overall_attainment)

    @api.depends('overall_attainment')
    def _compute_progress_color(self):
        for target in self:
            pct = target.overall_attainment
            if pct >= 100:
                target.progress_color = 'success'
            elif pct >= 75:
                target.progress_color = 'info'
            elif pct >= 50:
                target.progress_color = 'warning'
            else:
                target.progress_color = 'danger'

    @api.constrains('revenue_target', 'commission_target')
    def _check_targets(self):
        for target in self:
            if target.revenue_target < 0:
                raise ValidationError('Revenue target cannot be negative.')
            if target.commission_target < 0:
                raise ValidationError('Commission target cannot be negative.')

    def action_activate(self):
        self.write({'state': 'active'})

    def action_close(self):
        self.write({'state': 'closed'})
