# -*- coding: utf-8 -*-
"""Commission Forecast – predicted payouts for future periods."""

from odoo import api, fields, models


class CommissionForecast(models.Model):
    """Stores commission payout forecasts per employee per future period.

    Forecasts are computed by the :class:`services.forecast_service.ForecastService`
    using historical data and optionally ML-based prediction.
    """

    _name = 'commission.forecast'
    _description = 'Commission Forecast'
    _order = 'period_id, employee_id'
    _check_company_auto = True

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True,
    )
    period_id = fields.Many2one(
        'commission.period',
        string='Period',
        required=True,
        index=True,
    )
    plan_id = fields.Many2one(
        'commission.plan',
        string='Commission Plan',
        index=True,
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

    # ── Forecast Values ───────────────────────────────────────────────────────
    forecast_amount = fields.Monetary(
        string='Forecast Amount',
        currency_field='currency_id',
        default=0.0,
    )
    forecast_low = fields.Monetary(
        string='Forecast Low',
        currency_field='currency_id',
        default=0.0,
    )
    forecast_high = fields.Monetary(
        string='Forecast High',
        currency_field='currency_id',
        default=0.0,
    )
    confidence_pct = fields.Float(
        string='Confidence %',
        default=70.0,
        digits=(16, 1),
    )
    forecast_method = fields.Selection(
        [
            ('moving_average', 'Moving Average'),
            ('linear_regression', 'Linear Regression'),
            ('ml_model', 'ML Model'),
            ('manual', 'Manual Override'),
        ],
        string='Method',
        default='moving_average',
    )

    # ── Historical Basis ──────────────────────────────────────────────────────
    months_history_used = fields.Integer(
        string='Months of History Used',
        default=3,
    )
    avg_historical = fields.Monetary(
        string='Historical Average',
        currency_field='currency_id',
        default=0.0,
    )

    # ── Computed ──────────────────────────────────────────────────────────────
    variance_pct = fields.Float(
        string='Forecast vs Historical %',
        compute='_compute_variance',
        digits=(16, 1),
    )

    last_computed = fields.Datetime(
        string='Last Computed',
        readonly=True,
    )
    notes = fields.Text(string='Notes')


    _employee_plan_period_uniq = models.Constraint(
        'UNIQUE(employee_id, plan_id, period_id)',
        'A forecast already exists for this employee/plan/period.',
    )


    @api.depends('forecast_amount', 'avg_historical')
    def _compute_variance(self):
        for f in self:
            if f.avg_historical:
                f.variance_pct = (
                    (f.forecast_amount - f.avg_historical) / f.avg_historical
                ) * 100
            else:
                f.variance_pct = 0.0

    @api.model
    def _cron_update_forecasts(self):
        """Update forecasts for all active plans and employees."""
        from ..services.forecast_service import ForecastService
        service = ForecastService(self.env)
        service.update_all_forecasts()
