# -*- coding: utf-8 -*-
"""
AI/ML hooks for advanced commission analytics.
Provides interfaces for prediction, anomaly detection, and recommendations.
These are placeholders/interfaces ready to be connected to an ML backend.
"""
import logging
import math

_logger = logging.getLogger(__name__)


class AIHooks:
    """
    AI/ML integration hooks for the commission engine.
    Replace stub implementations with real ML model calls.
    """

    def __init__(self, env):
        self.env = env

    def predict_commission(self, employee, plan, period):
        """
        Predict commission amount for an employee in a period.
        Returns (predicted_amount, confidence_percent).

        Stub: Uses 3-period moving average as baseline prediction.
        Replace with ML model call: self._call_ml_endpoint(...)
        """
        past_lines = self.env['commission.line'].search([
            ('employee_id', '=', employee.id),
            ('plan_id', '=', plan.id),
            ('state', '=', 'paid'),
            ('line_type', '=', 'commission'),
        ], order='date desc', limit=3)

        if not past_lines:
            return 0.0, 50.0

        amounts = past_lines.mapped('commission_amount')
        avg = sum(amounts) / len(amounts)

        # Simple trend calculation
        if len(amounts) >= 2:
            trend = (amounts[0] - amounts[-1]) / (len(amounts) - 1) if amounts[-1] else 0
            predicted = avg + trend
        else:
            predicted = avg

        # Confidence based on variance
        if len(amounts) > 1:
            variance = sum((a - avg) ** 2 for a in amounts) / len(amounts)
            std_dev = math.sqrt(variance)
            cv = (std_dev / avg * 100) if avg > 0 else 50
            confidence = max(10.0, min(95.0, 100 - cv))
        else:
            confidence = 60.0

        return max(0.0, predicted), confidence

    def detect_anomalies(self, period_id, threshold_sigma=2.0):
        """
        Detect anomalous commission lines in a period.
        Returns list of (line, reason) tuples.

        Stub: Uses statistical z-score method.
        Replace with ML anomaly detection model.
        """
        lines = self.env['commission.line'].search([
            ('period_id', '=', period_id),
            ('state', '!=', 'cancelled'),
            ('line_type', '=', 'commission'),
        ])
        if len(lines) < 3:
            return []

        amounts = lines.mapped('commission_amount')
        avg = sum(amounts) / len(amounts)
        variance = sum((a - avg) ** 2 for a in amounts) / len(amounts)
        std = math.sqrt(variance)

        anomalies = []
        for line, amount in zip(lines, amounts):
            if std > 0:
                z_score = abs((amount - avg) / std)
                if z_score > threshold_sigma:
                    anomalies.append((
                        line,
                        'Z-score: %.2f (threshold: %.2f). Amount: %.2f, Average: %.2f' % (
                            z_score, threshold_sigma, amount, avg
                        )
                    ))
        return anomalies

    def recommend_plan(self, employee):
        """
        Recommend the optimal commission plan for an employee.
        Returns (plan, score, reasoning).

        Stub: Scores plans by historical payout.
        Replace with recommendation engine.
        """
        plans = self.env['commission.plan'].search([
            ('company_id', '=', employee.company_id.id),
            ('active', '=', True),
        ])
        best_plan = None
        best_score = 0
        best_reason = ''

        for plan in plans:
            lines = self.env['commission.line'].search([
                ('employee_id', '=', employee.id),
                ('plan_id', '=', plan.id),
                ('state', '=', 'paid'),
            ])
            if lines:
                avg = sum(lines.mapped('commission_amount')) / len(lines)
                if avg > best_score:
                    best_score = avg
                    best_plan = plan
                    best_reason = 'Historical average payout: %.2f' % avg

        return best_plan, best_score, best_reason

    def forecast_team_performance(self, team_id, period_id):
        """
        Forecast total team commission for a period.
        Returns dict with team metrics.

        AI-ready: Connect to team forecasting model.
        """
        members = self.env['hr.employee'].search([
            ('sale_team_id', '=', team_id),
        ])
        forecasts = {}
        total_predicted = 0.0

        for employee in members:
            plans = employee.commission_plan_ids
            for plan in plans:
                period = self.env['commission.period'].browse(period_id)
                predicted, confidence = self.predict_commission(employee, plan, period)
                total_predicted += predicted
                forecasts[employee.name] = {
                    'predicted': predicted,
                    'confidence': confidence,
                }

        return {
            'team_total': total_predicted,
            'member_forecasts': forecasts,
            'member_count': len(members),
        }

    def get_optimization_suggestions(self, plan):
        """
        Suggest optimizations for a commission plan.
        AI-ready hook: Returns list of suggestion strings.
        """
        suggestions = []
        lines = self.env['commission.line'].search([
            ('plan_id', '=', plan.id),
            ('state', '=', 'paid'),
        ], limit=100)

        if not lines:
            suggestions.append('No historical data available for optimization.')
            return suggestions

        amounts = lines.mapped('commission_amount')
        avg = sum(amounts) / len(amounts)

        if avg < 100:
            suggestions.append('Low average commission (%.2f). Consider increasing the base rate.' % avg)

        zero_lines = self.env['commission.line'].search_count([
            ('plan_id', '=', plan.id),
            ('commission_amount', '=', 0),
            ('state', '!=', 'cancelled'),
        ])
        if zero_lines > len(lines) * 0.2:
            suggestions.append(
                'More than 20%% of transactions yield zero commission. '
                'Review minimum thresholds or eligibility criteria.'
            )

        return suggestions
