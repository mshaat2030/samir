# -*- coding: utf-8 -*-
"""Forecast service — projects payout amounts for future periods."""

import logging
import statistics
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class CommissionForecastService(models.AbstractModel):
    """Service to compute and persist commission payout forecasts."""

    _name = 'commission.forecast.service'
    _description = 'Commission Forecast Service'

    def run_all_forecasts(self):
        """Compute forecasts for all employee/plan combinations with history."""
        employees = self.env['hr.employee'].search([('active', '=', True)])
        plans = self.env['commission.plan'].search([('active', '=', True)])
        future_period = self._get_next_open_period()
        if not future_period:
            _logger.info('No upcoming period for forecast.')
            return

        for employee in employees:
            for plan in plans:
                if employee not in plan.employee_ids and plan.employee_ids:
                    continue
                try:
                    self._create_or_update_forecast(employee, plan, future_period)
                except Exception as e:
                    _logger.warning('Forecast failed for %s/%s: %s', employee.name, plan.name, e)

    def compute_forecast(self, forecast_record):
        """Recompute a single forecast record."""
        self._create_or_update_forecast(
            forecast_record.employee_id,
            forecast_record.plan_id,
            forecast_record.period_id,
            method=forecast_record.method,
        )

    def _create_or_update_forecast(self, employee, plan, period, method='moving_average'):
        """Create or update a forecast record."""
        historical = self._get_historical_commissions(employee, plan, n_periods=6)
        pipeline_value = self._get_pipeline_value(employee)
        target = self.env['commission.target'].search([
            ('employee_id', '=', employee.id),
            ('period_id', '=', period.id),
            ('plan_id', '=', plan.id),
        ], limit=1)

        forecast_amount = self._compute_forecast(historical, pipeline_value, target, method)
        low, high = self._compute_range(historical, forecast_amount)
        confidence = self._compute_confidence(historical)

        existing = self.env['commission.forecast'].search([
            ('employee_id', '=', employee.id),
            ('period_id', '=', period.id),
            ('plan_id', '=', plan.id),
            ('method', '=', method),
        ], limit=1)

        vals = {
            'employee_id': employee.id,
            'period_id': period.id,
            'plan_id': plan.id,
            'method': method,
            'forecast_amount': forecast_amount,
            'forecast_low': low,
            'forecast_high': high,
            'confidence_pct': confidence,
            'historical_avg': statistics.mean(historical) if historical else 0.0,
            'pipeline_value': pipeline_value,
            'target_amount': target.target_amount if target else 0.0,
            'periods_used': len(historical),
            'computed_at': fields.Datetime.now(),
        }
        if existing:
            existing.write(vals)
        else:
            self.env['commission.forecast'].create(vals)

    def _get_historical_commissions(self, employee, plan, n_periods=6):
        """Return list of past commission totals for this employee/plan."""
        settlements = self.env['commission.settlement'].search([
            ('employee_id', '=', employee.id),
            ('plan_id', '=', plan.id),
            ('state', 'in', ('paid', 'payroll_processed', 'finance_approved')),
        ], order='period_id desc', limit=n_periods)
        return [s.total_commission for s in settlements]

    def _get_pipeline_value(self, employee):
        """Return CRM pipeline weighted value for an employee."""
        leads = self.env['crm.lead'].search([
            ('user_id', '=', employee.user_id.id),
            ('active', '=', True),
            ('stage_id.is_won', '=', False),
        ])
        return sum(l.prorated_revenue or l.expected_revenue for l in leads)

    def _get_next_open_period(self):
        """Return the next available period."""
        today = fields.Date.today()
        return self.env['commission.period'].search([
            ('date_start', '>=', str(today)),
            ('state', 'in', ('draft', 'open')),
        ], order='date_start', limit=1)

    def _compute_forecast(self, historical, pipeline_value, target, method):
        """Compute forecast using selected method."""
        if method == 'linear':
            if len(historical) >= 2:
                growth = (historical[0] - historical[-1]) / max(len(historical) - 1, 1)
                return max(0, historical[0] + growth)
            return historical[0] if historical else 0.0

        if method == 'moving_average':
            if historical:
                return statistics.mean(historical[:3])
            return 0.0

        if method == 'target_based':
            if target and target.target_amount:
                avg_achievement = statistics.mean(historical) if historical else 0
                avg_pct = (
                    (avg_achievement / (statistics.mean(historical) or 1)) * 100
                    if historical else 80.0
                )
                return target.estimated_commission * (avg_pct / 100.0)
            return statistics.mean(historical) if historical else 0.0

        if method == 'pipeline_based':
            if pipeline_value and historical:
                hist_avg = statistics.mean(historical)
                rate = hist_avg / max(pipeline_value, 1)
                return pipeline_value * rate * 0.3  # 30% weighted probability
            return statistics.mean(historical) if historical else 0.0

        if method == 'ml_placeholder':
            # AI placeholder — fall back to moving average
            return statistics.mean(historical[:3]) if historical else 0.0

        return statistics.mean(historical) if historical else 0.0

    def _compute_range(self, historical, forecast):
        """Compute pessimistic / optimistic range."""
        if len(historical) >= 2:
            try:
                std = statistics.stdev(historical)
            except statistics.StatisticsError:
                std = forecast * 0.2
        else:
            std = forecast * 0.2
        return max(0, forecast - std), forecast + std

    def _compute_confidence(self, historical):
        """Compute confidence % based on data volume."""
        if len(historical) >= 6:
            return 85.0
        if len(historical) >= 3:
            return 65.0
        if len(historical) >= 1:
            return 40.0
        return 20.0
