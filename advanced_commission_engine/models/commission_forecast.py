# -*- coding: utf-8 -*-
"""Commission Forecast — projected payout for an employee in a future period."""

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

FORECAST_METHODS = [
    ('linear', 'Linear Projection'),
    ('moving_average', '3-Period Moving Average'),
    ('target_based', 'Target-Based Projection'),
    ('pipeline_based', 'CRM Pipeline Based'),
    ('ml_placeholder', 'AI Prediction (Placeholder)'),
]


class CommissionForecast(models.Model):
    """Payout forecast computed by the forecast service."""

    _name = 'commission.forecast'
    _description = 'Commission Forecast'
    _inherit = ['mail.thread']
    _order = 'period_id desc, employee_id'

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(string='Forecast', compute='_compute_name', store=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, index=True,
    )
    period_id = fields.Many2one(
        'commission.period', string='Forecast Period',
        required=True, index=True,
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

    # ── Forecast ──────────────────────────────────────────────────────────────
    method = fields.Selection(
        FORECAST_METHODS, string='Forecast Method',
        required=True, default='moving_average',
    )
    forecast_amount = fields.Monetary(
        string='Forecast Commission', currency_field='currency_id',
        tracking=True,
    )
    forecast_low = fields.Monetary(
        string='Pessimistic', currency_field='currency_id',
    )
    forecast_high = fields.Monetary(
        string='Optimistic', currency_field='currency_id',
    )
    confidence_pct = fields.Float(
        string='Confidence %', digits=(16, 1),
        help='Model confidence in this forecast.',
    )

    # ── Basis ─────────────────────────────────────────────────────────────────
    historical_avg = fields.Monetary(
        string='Historical Average', currency_field='currency_id',
        readonly=True,
    )
    pipeline_value = fields.Monetary(
        string='Pipeline Value', currency_field='currency_id',
        readonly=True,
    )
    target_amount = fields.Monetary(
        string='Target Amount', currency_field='currency_id',
    )
    periods_used = fields.Integer(string='Periods Used in Average')

    # ── Run Metadata ──────────────────────────────────────────────────────────
    computed_at = fields.Datetime(string='Computed At', readonly=True)
    is_stale = fields.Boolean(
        string='Stale',
        compute='_compute_is_stale',
        help='True if forecast is older than 7 days.',
    )

    # ── Variance vs Actuals ───────────────────────────────────────────────────
    actual_commission = fields.Monetary(
        string='Actual Commission', currency_field='currency_id',
        compute='_compute_actual', store=True,
    )
    variance = fields.Monetary(
        string='Variance', currency_field='currency_id',
        compute='_compute_actual', store=True,
    )
    variance_pct = fields.Float(
        string='Variance %', digits=(16, 1),
        compute='_compute_actual', store=True,
    )

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = fields.Text(string='Analyst Notes')

    _sql_constraints = [
        ('unique_emp_period_plan_method',
         'UNIQUE(employee_id, period_id, plan_id, method)',
         'Forecast already exists for this combination.'),
    ]

    # ── Compute ───────────────────────────────────────────────────────────────

    @api.depends('employee_id', 'period_id', 'plan_id')
    def _compute_name(self):
        for rec in self:
            rec.name = ' / '.join(filter(None, [
                rec.employee_id.name or '',
                rec.period_id.name or '',
                rec.plan_id.name or '',
                dict(FORECAST_METHODS).get(rec.method, ''),
            ]))

    def _compute_is_stale(self):
        now = fields.Datetime.now()
        for rec in self:
            if not rec.computed_at:
                rec.is_stale = True
            else:
                age = (now - rec.computed_at).days
                rec.is_stale = age >= 7

    @api.depends('employee_id', 'period_id', 'plan_id')
    def _compute_actual(self):
        Settlement = self.env['commission.settlement']
        for rec in self:
            settlements = Settlement.search([
                ('employee_id', '=', rec.employee_id.id),
                ('period_id', '=', rec.period_id.id),
                ('plan_id', '=', rec.plan_id.id),
                ('state', 'not in', ('cancelled',)),
            ])
            actual = sum(settlements.mapped('total_commission'))
            rec.actual_commission = actual
            rec.variance = actual - rec.forecast_amount
            rec.variance_pct = (
                (actual - rec.forecast_amount) / rec.forecast_amount * 100
                if rec.forecast_amount else 0.0
            )

    # ── Cron ──────────────────────────────────────────────────────────────────

    @api.model
    def cron_update_forecasts(self):
        """Weekly cron to refresh all forecasts."""
        svc = self.env['commission.forecast.service']
        svc.run_all_forecasts()

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_recompute(self):
        """Manually trigger forecast recompute."""
        svc = self.env['commission.forecast.service']
        for rec in self:
            svc.compute_forecast(rec)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': 'Forecast Updated', 'message': 'Forecasts recomputed.', 'type': 'success'},
        }
