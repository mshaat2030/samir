# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class CommissionForecast(models.Model):
    _name = 'commission.forecast'
    _description = 'Commission Forecast'
    _inherit = ['mail.thread', 'commission.mixin']
    _order = 'period_id desc, employee_id'

    name = fields.Char(
        string='Forecast Name', compute='_compute_name', store=True
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, index=True,
    )
    period_id = fields.Many2one(
        'commission.period', string='Period',
        required=True, index=True,
    )
    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan',
        required=True, index=True,
    )
    forecast_date = fields.Date(
        string='Forecast Date', default=fields.Date.today
    )

    # ── Forecast Inputs ───────────────────────────────────────────────────────
    forecasted_revenue = fields.Monetary(
        string='Forecasted Revenue',
        currency_field='currency_id',
    )
    pipeline_value = fields.Monetary(
        string='CRM Pipeline Value',
        currency_field='currency_id',
        compute='_compute_pipeline',
        store=True,
    )
    pipeline_probability = fields.Float(
        string='Weighted Pipeline',
        compute='_compute_pipeline',
        store=True,
    )
    historical_avg = fields.Monetary(
        string='Historical Average',
        currency_field='currency_id',
        compute='_compute_historical',
        store=True,
    )

    # ── Forecast Methods ──────────────────────────────────────────────────────
    forecast_method = fields.Selection([
        ('manual', 'Manual Input'),
        ('pipeline', 'CRM Pipeline'),
        ('historical', 'Historical Average'),
        ('ml', 'ML Prediction (AI)'),
        ('blended', 'Blended'),
    ], string='Forecast Method', default='blended')

    blended_weights = fields.Text(
        string='Blended Weights (JSON)',
        default='{"pipeline": 0.5, "historical": 0.3, "manual": 0.2}',
    )

    # ── Forecast Results ──────────────────────────────────────────────────────
    forecasted_commission = fields.Monetary(
        string='Forecasted Commission',
        currency_field='currency_id',
        compute='_compute_forecast',
        store=True,
    )
    optimistic_commission = fields.Monetary(
        string='Optimistic (120%)',
        currency_field='currency_id',
        compute='_compute_forecast',
        store=True,
    )
    pessimistic_commission = fields.Monetary(
        string='Pessimistic (80%)',
        currency_field='currency_id',
        compute='_compute_forecast',
        store=True,
    )
    confidence_level = fields.Float(
        string='Confidence Level (%)',
        default=80.0,
        digits=(5, 2),
    )

    # ── Actuals ───────────────────────────────────────────────────────────────
    actual_commission = fields.Monetary(
        string='Actual Commission',
        currency_field='currency_id',
        compute='_compute_actuals',
        store=True,
    )
    variance = fields.Monetary(
        string='Variance',
        currency_field='currency_id',
        compute='_compute_actuals',
        store=True,
    )
    variance_percent = fields.Float(
        string='Variance %',
        compute='_compute_actuals',
        store=True,
        digits=(5, 2),
    )

    ai_prediction = fields.Monetary(
        string='AI Prediction',
        currency_field='currency_id',
        readonly=True,
        help='Prediction from the AI/ML engine hook',
    )
    ai_confidence = fields.Float(
        string='AI Confidence %', readonly=True
    )
    ai_last_updated = fields.Datetime(string='AI Last Updated', readonly=True)

    @api.depends('employee_id', 'period_id', 'plan_id')
    def _compute_name(self):
        for f in self:
            f.name = 'Forecast: %s / %s' % (
                f.employee_id.name or '', f.period_id.name or ''
            )

    @api.depends('employee_id', 'period_id')
    def _compute_pipeline(self):
        for forecast in self:
            if not forecast.employee_id or not forecast.employee_id.user_id:
                forecast.pipeline_value = 0.0
                forecast.pipeline_probability = 0.0
                continue
            leads = self.env['crm.lead'].search([
                ('user_id', '=', forecast.employee_id.user_id.id),
                ('probability', '>', 0),
                ('stage_id.is_won', '=', False),
                ('company_id', '=', forecast.company_id.id),
            ])
            forecast.pipeline_value = sum(leads.mapped('expected_revenue'))
            total_weighted = sum(
                l.expected_revenue * l.probability / 100 for l in leads
            )
            forecast.pipeline_probability = total_weighted

    @api.depends('employee_id', 'period_id', 'plan_id')
    def _compute_historical(self):
        for forecast in self:
            if not forecast.employee_id or not forecast.period_id:
                forecast.historical_avg = 0.0
                continue
            past_lines = self.env['commission.line'].search([
                ('employee_id', '=', forecast.employee_id.id),
                ('plan_id', '=', forecast.plan_id.id),
                ('state', '=', 'paid'),
                ('line_type', '=', 'commission'),
            ])
            if past_lines:
                forecast.historical_avg = sum(
                    past_lines.mapped('commission_amount')
                ) / len(past_lines)
            else:
                forecast.historical_avg = 0.0

    @api.depends(
        'forecasted_revenue', 'pipeline_probability', 'historical_avg',
        'forecast_method', 'blended_weights', 'plan_id', 'ai_prediction',
    )
    def _compute_forecast(self):
        for forecast in self:
            if forecast.forecast_method == 'manual':
                base = forecast.forecasted_revenue
            elif forecast.forecast_method == 'pipeline':
                base = forecast.pipeline_probability
            elif forecast.forecast_method == 'historical':
                base = forecast.historical_avg / (forecast.plan_id.fixed_rate / 100.0) if forecast.plan_id and forecast.plan_id.fixed_rate else 0
            elif forecast.forecast_method == 'ml':
                base = forecast.ai_prediction / (forecast.plan_id.fixed_rate / 100.0) if forecast.plan_id and forecast.plan_id.fixed_rate else 0
            elif forecast.forecast_method == 'blended':
                import json
                try:
                    weights = json.loads(forecast.blended_weights or '{}')
                except Exception:
                    weights = {}
                w_pipeline = weights.get('pipeline', 0.5)
                w_historical_base = (forecast.historical_avg / (forecast.plan_id.fixed_rate / 100.0)) if forecast.plan_id and forecast.plan_id.fixed_rate else 0
                w_manual = weights.get('manual', 0.2)
                base = (
                    forecast.pipeline_probability * w_pipeline +
                    w_historical_base * weights.get('historical', 0.3) +
                    forecast.forecasted_revenue * w_manual
                )
            else:
                base = forecast.forecasted_revenue

            if forecast.plan_id:
                commission = forecast.plan_id.compute_commission(
                    base, employee=forecast.employee_id
                )
            else:
                commission = 0.0

            forecast.forecasted_commission = commission
            forecast.optimistic_commission = commission * 1.20
            forecast.pessimistic_commission = commission * 0.80

    @api.depends('forecasted_commission', 'employee_id', 'period_id')
    def _compute_actuals(self):
        for forecast in self:
            actual_lines = self.env['commission.line'].search([
                ('employee_id', '=', forecast.employee_id.id),
                ('period_id', '=', forecast.period_id.id),
                ('plan_id', '=', forecast.plan_id.id),
                ('state', '!=', 'cancelled'),
                ('line_type', '=', 'commission'),
            ])
            forecast.actual_commission = sum(actual_lines.mapped('commission_amount'))
            forecast.variance = forecast.actual_commission - forecast.forecasted_commission
            if forecast.forecasted_commission:
                forecast.variance_percent = (
                    forecast.variance / forecast.forecasted_commission
                ) * 100
            else:
                forecast.variance_percent = 0.0

    def action_refresh_ai_prediction(self):
        """Hook for AI/ML prediction engine."""
        for forecast in self:
            from ..services.ai_hooks import AIHooks
            hooks = AIHooks(self.env)
            prediction, confidence = hooks.predict_commission(
                employee=forecast.employee_id,
                plan=forecast.plan_id,
                period=forecast.period_id,
            )
            forecast.write({
                'ai_prediction': prediction,
                'ai_confidence': confidence,
                'ai_last_updated': fields.Datetime.now(),
            })
