# -*- coding: utf-8 -*-
"""Forecast Service – predicts future commission payouts using historical data."""

import logging
from datetime import date
from statistics import mean, stdev

_logger = logging.getLogger(__name__)


class ForecastService:
    """Generates commission payout forecasts using moving average and trend analysis.

    AI-ready: the ``ml_forecast`` hook can be replaced with an actual ML model.
    """

    def __init__(self, env):
        self.env = env

    def update_all_forecasts(self):
        """Refresh forecasts for all active plans/employees for upcoming periods."""
        config = self.env['ir.config_parameter'].sudo()
        horizon = int(config.get_param('advanced_commission_engine.forecast_months', '3'))
        plans = self.env['commission.plan'].search([('state', '=', 'active')])

        for plan in plans:
            employees = self._get_plan_employees(plan)
            future_periods = self._get_future_periods(plan, horizon)
            for employee in employees:
                for period in future_periods:
                    self._update_forecast(employee, plan, period)

    def _update_forecast(self, employee, plan, period):
        """Update or create forecast for one employee/plan/period."""
        historical = self._get_historical_amounts(employee, plan, months=6)
        if not historical:
            return

        avg = mean(historical)
        try:
            std = stdev(historical) if len(historical) > 1 else avg * 0.2
        except Exception:
            std = avg * 0.2

        forecast_amount = self._moving_average_forecast(historical)
        confidence = min(95.0, max(50.0, 100.0 - (std / avg * 100) if avg else 50.0))

        existing = self.env['commission.forecast'].search([
            ('employee_id', '=', employee.id),
            ('plan_id', '=', plan.id),
            ('period_id', '=', period.id),
        ], limit=1)

        vals = {
            'forecast_amount': forecast_amount,
            'forecast_low': max(0, forecast_amount - std),
            'forecast_high': forecast_amount + std,
            'confidence_pct': confidence,
            'avg_historical': avg,
            'months_history_used': len(historical),
            'forecast_method': 'moving_average',
            'last_computed': self.env.cr.now(),
        }

        if existing:
            existing.write(vals)
        else:
            self.env['commission.forecast'].create({
                'employee_id': employee.id,
                'plan_id': plan.id,
                'period_id': period.id,
                'company_id': plan.company_id.id,
                **vals,
            })

    def _get_historical_amounts(self, employee, plan, months=6):
        """Get last N months of final commission amounts."""
        self.env.cr.execute("""
            SELECT cs.final_amount
            FROM commission_settlement cs
            JOIN commission_period cp ON cp.id = cs.period_id
            WHERE cs.employee_id = %s
              AND cs.plan_id = %s
              AND cs.state IN ('paid', 'payroll_processed', 'finance_approved')
            ORDER BY cp.date_start DESC
            LIMIT %s
        """, (employee.id, plan.id, months))
        rows = self.env.cr.fetchall()
        return [float(r[0]) for r in rows if r[0]]

    def _moving_average_forecast(self, values, window=3):
        """Compute moving average forecast."""
        if not values:
            return 0.0
        recent = values[:window]
        return mean(recent)

    def _get_plan_employees(self, plan):
        """Get all employees enrolled in a plan."""
        if plan.employee_ids:
            return plan.employee_ids
        # Fall back to employees in eligible teams/departments
        employees = self.env['hr.employee'].search([
            ('active', '=', True),
            ('company_id', '=', plan.company_id.id),
        ])
        return employees[:50]  # Limit for performance

    def _get_future_periods(self, plan, months=3):
        """Get or create future periods for a plan."""
        today = date.today()
        periods = []
        period_model = self.env['commission.period']
        for i in range(1, months + 1):
            if plan.period_type == 'monthly':
                year = today.year + (today.month + i - 1) // 12
                month = (today.month + i - 1) % 12 + 1
                p = period_model._create_period_for_date(
                    date(year, month, 1), 'monthly', plan.company_id
                )
                if p:
                    periods.append(p)
        return periods

    def get_team_forecast(self, team_id, period_id):
        """Get aggregated forecast for a sales team."""
        forecasts = self.env['commission.forecast'].search([
            ('period_id', '=', period_id),
        ])
        if team_id:
            team = self.env['crm.team'].browse(team_id)
            member_employee_ids = team.member_ids.mapped('employee_id.id')
            forecasts = forecasts.filtered(
                lambda f: f.employee_id.id in member_employee_ids
            )
        return {
            'total_forecast': sum(forecasts.mapped('forecast_amount')),
            'total_low': sum(forecasts.mapped('forecast_low')),
            'total_high': sum(forecasts.mapped('forecast_high')),
            'employee_count': len(forecasts),
        }
