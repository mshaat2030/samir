# -*- coding: utf-8 -*-
"""Commission KPI — weighted performance indicator for KPI-based plans."""

import logging
from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

KPI_TYPES = [
    ('revenue', 'Revenue'),
    ('margin', 'Gross Margin'),
    ('units', 'Units Sold'),
    ('customer_acquisition', 'Customer Acquisition'),
    ('customer_retention', 'Customer Retention'),
    ('collection_efficiency', 'Collection Efficiency'),
    ('nps', 'Net Promoter Score'),
    ('activity_count', 'Activity Count'),
    ('subscription_mrr', 'Subscription MRR'),
    ('project_completion', 'Project Completion'),
    ('custom', 'Custom Metric'),
]


class CommissionKPI(models.Model):
    """Key Performance Indicator linked to a commission plan and employee."""

    _name = 'commission.kpi'
    _description = 'Commission KPI'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_id desc, employee_id, weight desc'

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(string='KPI Name', required=True, tracking=True)
    kpi_type = fields.Selection(KPI_TYPES, string='KPI Type', default='revenue', required=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, index=True, tracking=True,
    )
    period_id = fields.Many2one(
        'commission.period', string='Period',
        required=True, index=True, tracking=True,
    )
    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan',
        required=True, index=True,
    )
    company_id = fields.Many2one(
        'res.company', related='period_id.company_id',
        store=True, readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id',
        store=True, readonly=True,
    )

    # ── Target & Achievement ──────────────────────────────────────────────────
    weight = fields.Float(
        string='Weight (%)', required=True,
        help='This KPI\'s weight in the overall commission score. All KPIs should sum to 100.',
    )
    target_value = fields.Float(string='Target Value', required=True)
    achieved_value = fields.Float(string='Achieved Value', tracking=True)
    unit = fields.Char(string='Unit', default='', help='e.g. USD, units, %, pts')

    # ── Computed Scores ───────────────────────────────────────────────────────
    achievement_pct = fields.Float(
        string='Achievement %', digits=(16, 2),
        compute='_compute_scores', store=True,
    )
    weighted_score = fields.Float(
        string='Weighted Score', digits=(16, 4),
        compute='_compute_scores', store=True,
    )
    score_color = fields.Char(
        string='Score Color', compute='_compute_score_color',
    )

    # ── Caps & Floors ─────────────────────────────────────────────────────────
    achievement_cap_pct = fields.Float(
        string='Achievement Cap (%)', default=150.0,
        help='Maximum achievement % counted. Prevents runaway over-achievement.',
    )
    achievement_floor_pct = fields.Float(
        string='Achievement Floor (%)', default=0.0,
        help='Minimum achievement % counted. Negative clamp.',
    )

    # ── Data Source ───────────────────────────────────────────────────────────
    auto_compute = fields.Boolean(
        string='Auto-Compute', default=False,
        help='If enabled, achieved value is computed automatically from source data.',
    )
    compute_domain = fields.Text(
        string='Compute Domain',
        help='Odoo domain to filter source records when auto-computing.',
    )

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = fields.Text(string='Notes')

    _sql_constraints = [
        ('weight_range', 'CHECK(weight > 0 AND weight <= 100)', 'Weight must be between 0 and 100.'),
        ('target_positive', 'CHECK(target_value > 0)', 'Target value must be positive.'),
    ]

    # ── Compute ───────────────────────────────────────────────────────────────

    @api.depends('achieved_value', 'target_value', 'weight', 'achievement_cap_pct', 'achievement_floor_pct')
    def _compute_scores(self):
        for rec in self:
            if rec.target_value:
                raw_pct = rec.achieved_value / rec.target_value * 100
                capped_pct = min(raw_pct, rec.achievement_cap_pct or 150.0)
                floored_pct = max(capped_pct, rec.achievement_floor_pct or 0.0)
                rec.achievement_pct = floored_pct
                rec.weighted_score = floored_pct * rec.weight / 100.0
            else:
                rec.achievement_pct = 0.0
                rec.weighted_score = 0.0

    def _compute_score_color(self):
        for rec in self:
            pct = rec.achievement_pct
            if pct >= 100:
                rec.score_color = '#28a745'   # green
            elif pct >= 80:
                rec.score_color = '#ffc107'   # amber
            else:
                rec.score_color = '#dc3545'   # red

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('weight', 'employee_id', 'period_id', 'plan_id')
    def _check_total_weight(self):
        for rec in self:
            siblings = self.search([
                ('employee_id', '=', rec.employee_id.id),
                ('period_id', '=', rec.period_id.id),
                ('plan_id', '=', rec.plan_id.id),
                ('id', '!=', rec.id),
            ])
            total = sum(siblings.mapped('weight')) + rec.weight
            if total > 100.1:   # allow tiny float rounding
                raise ValidationError(
                    f'Total KPI weight for this employee/period/plan exceeds 100%: {total:.1f}%'
                )

    # ── Auto-Compute ──────────────────────────────────────────────────────────

    def compute_achieved_value(self):
        """Auto-compute achieved_value from source data based on kpi_type."""
        for rec in self:
            if not rec.auto_compute:
                continue
            value = rec._fetch_achieved_value()
            rec.write({'achieved_value': value})

    def _fetch_achieved_value(self):
        """Fetch achieved value from Odoo data based on kpi_type."""
        self.ensure_one()
        emp = self.employee_id
        period = self.period_id
        domain_base = [
            ('date', '>=', period.date_start),
            ('date', '<=', period.date_end),
        ]

        if self.kpi_type == 'revenue':
            invoices = self.env['account.move'].search(
                domain_base + [
                    ('move_type', '=', 'out_invoice'),
                    ('state', '=', 'posted'),
                    ('invoice_user_id', '=', emp.user_id.id),
                ]
            )
            return sum(invoices.mapped('amount_untaxed'))

        if self.kpi_type == 'units':
            lines = self.env['sale.order.line'].search(
                [('order_id.date_order', '>=', period.date_start),
                 ('order_id.date_order', '<=', period.date_end),
                 ('order_id.user_id', '=', emp.user_id.id),
                 ('order_id.state', 'in', ('sale', 'done'))]
            )
            return sum(lines.mapped('product_uom_qty'))

        if self.kpi_type == 'customer_acquisition':
            leads = self.env['crm.lead'].search(
                [('user_id', '=', emp.user_id.id),
                 ('date_closed', '>=', period.date_start),
                 ('date_closed', '<=', period.date_end),
                 ('probability', '=', 100)]
            )
            return len(leads)

        if self.kpi_type == 'activity_count':
            activities = self.env['mail.activity'].search(
                [('user_id', '=', emp.user_id.id),
                 ('date_done', '>=', str(period.date_start)),
                 ('date_done', '<=', str(period.date_end))]
            )
            return len(activities)

        return 0.0

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_refresh_value(self):
        """Manually trigger auto-compute for selected KPIs."""
        self.filtered('auto_compute').compute_achieved_value()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': 'KPI Updated', 'message': 'Achieved values refreshed.', 'type': 'success'},
        }
