# -*- coding: utf-8 -*-
"""Commission Target — employee quota / goal per period and plan."""

import logging
from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class CommissionTarget(models.Model):
    """Sales target linked to an employee, period, and plan."""

    _name = 'commission.target'
    _description = 'Commission Target'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_id desc, employee_id'

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(string='Target Name', compute='_compute_name', store=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, tracking=True, index=True,
    )
    period_id = fields.Many2one(
        'commission.period', string='Period',
        required=True, tracking=True, index=True,
    )
    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan',
        required=True, tracking=True, index=True,
    )
    company_id = fields.Many2one(
        'res.company', related='period_id.company_id',
        store=True, readonly=True, index=True,
    )
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id',
        store=True, readonly=True,
    )

    # ── Target Amounts ────────────────────────────────────────────────────────
    target_amount = fields.Monetary(
        string='Target Amount', currency_field='currency_id',
        required=True, tracking=True,
        help='Revenue / sales target for this employee in this period.',
    )
    achieved_amount = fields.Monetary(
        string='Achieved Amount', currency_field='currency_id',
        compute='_compute_achieved', store=True,
    )
    remaining_amount = fields.Monetary(
        string='Remaining Amount', currency_field='currency_id',
        compute='_compute_achieved', store=True,
    )
    achievement_pct = fields.Float(
        string='Achievement %', digits=(16, 2),
        compute='_compute_achieved', store=True,
    )

    # ── Stretch Goals ─────────────────────────────────────────────────────────
    stretch_target = fields.Monetary(
        string='Stretch Target', currency_field='currency_id',
        tracking=True, help='Aspirational target above the base target.',
    )
    stretch_achievement_pct = fields.Float(
        string='Stretch Achievement %', digits=(16, 2),
        compute='_compute_achieved', store=True,
    )

    # ── Commission Estimate ───────────────────────────────────────────────────
    estimated_commission = fields.Monetary(
        string='Estimated Commission', currency_field='currency_id',
        compute='_compute_estimated_commission', store=True,
    )

    # ── Status ────────────────────────────────────────────────────────────────
    state = fields.Selection([
        ('active', 'Active'),
        ('achieved', 'Achieved'),
        ('overachieved', 'Overachieved'),
        ('missed', 'Missed'),
    ], compute='_compute_state', store=True, string='Status')

    # ── Streak Tracking ───────────────────────────────────────────────────────
    consecutive_periods_achieved = fields.Integer(
        string='Consecutive Periods Achieved',
        compute='_compute_streak', store=True,
    )

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = fields.Text(string='Notes')

    _sql_constraints = [
        ('unique_employee_period_plan', 'UNIQUE(employee_id, period_id, plan_id)',
         'Target already exists for this employee/period/plan.'),
        ('target_positive', 'CHECK(target_amount > 0)', 'Target amount must be positive.'),
    ]

    # ── Compute ───────────────────────────────────────────────────────────────

    @api.depends('employee_id', 'period_id', 'plan_id')
    def _compute_name(self):
        for rec in self:
            parts = [
                rec.employee_id.name or '',
                rec.period_id.name or '',
                rec.plan_id.name or '',
            ]
            rec.name = ' / '.join(filter(None, parts))

    @api.depends('employee_id', 'period_id', 'plan_id', 'target_amount', 'stretch_target')
    def _compute_achieved(self):
        Settlement = self.env['commission.settlement']
        for rec in self:
            if not rec.employee_id or not rec.period_id:
                rec.achieved_amount = 0.0
                rec.remaining_amount = rec.target_amount
                rec.achievement_pct = 0.0
                rec.stretch_achievement_pct = 0.0
                continue

            # Sum base amounts from commission lines in matching settlements
            settlements = Settlement.search([
                ('employee_id', '=', rec.employee_id.id),
                ('period_id', '=', rec.period_id.id),
                ('plan_id', '=', rec.plan_id.id),
                ('state', 'not in', ('cancelled',)),
            ])
            achieved = sum(settlements.mapped(lambda s: sum(s.line_ids.mapped('base_amount'))))
            rec.achieved_amount = achieved
            rec.remaining_amount = max(0, rec.target_amount - achieved)
            rec.achievement_pct = (achieved / rec.target_amount * 100) if rec.target_amount else 0.0
            rec.stretch_achievement_pct = (achieved / rec.stretch_target * 100) if rec.stretch_target else 0.0

    @api.depends('achievement_pct')
    def _compute_state(self):
        for rec in self:
            pct = rec.achievement_pct
            if pct >= 120:
                rec.state = 'overachieved'
            elif pct >= 100:
                rec.state = 'achieved'
            elif rec.period_id and rec.period_id.date_end < fields.Date.today():
                rec.state = 'missed'
            else:
                rec.state = 'active'

    @api.depends('achievement_pct', 'target_amount', 'plan_id')
    def _compute_estimated_commission(self):
        for rec in self:
            if not rec.plan_id or not rec.achieved_amount:
                rec.estimated_commission = 0.0
                continue
            # Use plan rules to estimate commission on achieved amount
            rules = rec.plan_id.rule_ids.filtered('active').sorted('sequence')
            total = 0.0
            for rule in rules:
                total += rule.calculate_commission(
                    rec.achieved_amount,
                    {'achievement_pct': rec.achievement_pct},
                )
                if rule.stop_further_rules:
                    break
            rec.estimated_commission = rec.plan_id.apply_commission_cap(total)

    @api.depends('employee_id', 'period_id')
    def _compute_streak(self):
        for rec in self:
            if not rec.employee_id or not rec.period_id:
                rec.consecutive_periods_achieved = 0
                continue
            streak = 0
            period = rec.period_id
            while period:
                target = self.search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('period_id', '=', period.id),
                    ('state', 'in', ('achieved', 'overachieved')),
                ], limit=1)
                if not target:
                    break
                streak += 1
                # Find previous period
                period = self.env['commission.period'].search([
                    ('date_end', '<', period.date_start),
                    ('company_id', '=', period.company_id.id),
                ], order='date_end desc', limit=1)
            rec.consecutive_periods_achieved = streak

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_notify_achievement(self):
        """Send achievement notification email."""
        self.ensure_one()
        template = self.env.ref('advanced_commission_engine.mail_template_target_achieved', False)
        if template and self.achievement_pct >= 100:
            template.send_mail(self.id, force_send=True)

    @api.model
    def create_bulk_targets(self, period_id, plan_id, employee_ids, target_amount):
        """Bulk create targets for multiple employees."""
        created = self.env['commission.target']
        for emp_id in employee_ids:
            existing = self.search([
                ('employee_id', '=', emp_id),
                ('period_id', '=', period_id),
                ('plan_id', '=', plan_id),
            ], limit=1)
            if not existing:
                created |= self.create({
                    'employee_id': emp_id,
                    'period_id': period_id,
                    'plan_id': plan_id,
                    'target_amount': target_amount,
                })
        return created
