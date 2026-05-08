# -*- coding: utf-8 -*-
"""Recommendation Service – smart suggestions and badge evaluation.

AI-ready placeholder for compensation optimisation recommendations.
"""

import logging
from datetime import date

_logger = logging.getLogger(__name__)


class RecommendationService:
    """Provides smart commission recommendations and evaluates badge criteria."""

    def __init__(self, env):
        self.env = env

    # ── Badge Evaluation ──────────────────────────────────────────────────────

    def evaluate_badges(self):
        """Evaluate all active badges and award them to qualifying employees."""
        badges = self.env['commission.badge'].search([('active', '=', True)])
        for badge in badges:
            self._evaluate_badge(badge)

    def _evaluate_badge(self, badge):
        """Check which employees qualify for this badge today."""
        today = date.today()
        criteria_type = badge.criteria_type
        criteria_value = badge.criteria_value

        if criteria_type == 'manual':
            return  # Only awarded manually

        # Find the current period
        period = self.env['commission.period'].search([
            ('date_start', '<=', today),
            ('date_end', '>=', today),
            ('state', '=', 'open'),
        ], limit=1)
        if not period:
            return

        candidates = []

        if criteria_type == 'rank':
            # Award to employees ranked <= criteria_value
            leaderboard = self.env['commission.leaderboard'].search([
                ('period_id', '=', period.id),
                ('rank', '<=', int(criteria_value)),
            ])
            candidates = leaderboard.mapped('employee_id')

        elif criteria_type == 'amount':
            # Award to employees with total_commission >= criteria_value
            leaderboard = self.env['commission.leaderboard'].search([
                ('period_id', '=', period.id),
                ('total_commission', '>=', criteria_value),
            ])
            candidates = leaderboard.mapped('employee_id')

        elif criteria_type == 'attainment':
            # Award to employees with attainment >= criteria_value%
            leaderboard = self.env['commission.leaderboard'].search([
                ('period_id', '=', period.id),
                ('target_attainment', '>=', criteria_value),
            ])
            candidates = leaderboard.mapped('employee_id')

        elif criteria_type == 'streak':
            # Award to employees with streak >= criteria_value periods
            leaderboard = self.env['commission.leaderboard'].search([
                ('period_id', '=', period.id),
                ('streak', '>=', int(criteria_value)),
            ])
            candidates = leaderboard.mapped('employee_id')

        for employee in candidates:
            self._award_badge_if_new(badge, employee, period)

    def _award_badge_if_new(self, badge, employee, period):
        """Award a badge to an employee if not already awarded this period."""
        existing = self.env['commission.badge.award'].search([
            ('badge_id', '=', badge.id),
            ('employee_id', '=', employee.id),
            ('period_id', '=', period.id),
        ], limit=1)
        if not existing:
            award = self.env['commission.badge.award'].create({
                'badge_id': badge.id,
                'employee_id': employee.id,
                'period_id': period.id,
                'date_awarded': date.today(),
                'notes': f'Auto-awarded: {badge.criteria_type} criteria met.',
            })
            award.action_notify_employee()
            _logger.info(
                'Awarded badge %s to employee %s', badge.name, employee.name
            )

    # ── Smart Recommendations ─────────────────────────────────────────────────

    def get_plan_recommendations(self, employee_id, company_id):
        """Return plan recommendations for an employee based on their profile.

        AI placeholder: returns basic rule-based suggestions.
        """
        employee = self.env['hr.employee'].browse(employee_id)
        recommendations = []

        # Suggestion 1: Check if employee is enrolled in any plan
        settlements = self.env['commission.settlement'].search([
            ('employee_id', '=', employee_id),
        ], limit=1)
        if not settlements:
            recommendations.append({
                'type': 'enrolment',
                'message': f'{employee.name} is not enrolled in any commission plan.',
                'severity': 'warning',
            })

        # Suggestion 2: Check for unclaimed commissions
        unclaimed = self.env['commission.settlement'].search([
            ('employee_id', '=', employee_id),
            ('state', '=', 'calculated'),
        ])
        if unclaimed:
            recommendations.append({
                'type': 'submit',
                'message': f'{len(unclaimed)} settlement(s) pending submission.',
                'severity': 'info',
            })

        # Suggestion 3: Target attainment recommendations
        today = date.today()
        current_period = self.env['commission.period'].search([
            ('date_start', '<=', today),
            ('date_end', '>=', today),
        ], limit=1)
        if current_period:
            target = self.env['commission.target'].search([
                ('employee_id', '=', employee_id),
                ('period_id', '=', current_period.id),
            ], limit=1)
            if target and target.overall_attainment < 50:
                recommendations.append({
                    'type': 'performance',
                    'message': f'Current attainment is {target.overall_attainment:.0f}%. '
                               f'Need {100 - target.overall_attainment:.0f}% more to hit target.',
                    'severity': 'warning',
                })

        return recommendations

    def get_plan_effectiveness(self, plan_id, months=6):
        """Analyse plan effectiveness metrics.

        :return: dict with effectiveness metrics
        """
        self.env.cr.execute("""
            SELECT
                COUNT(DISTINCT cs.employee_id) AS employees_enrolled,
                COUNT(cs.id) AS total_settlements,
                SUM(cs.final_amount) AS total_paid,
                AVG(cs.final_amount) AS avg_payout,
                SUM(CASE WHEN cs.state = 'paid' THEN 1 ELSE 0 END) AS paid_count,
                SUM(cs.total_base_amount) AS total_revenue
            FROM commission_settlement cs
            JOIN commission_period cp ON cp.id = cs.period_id
            WHERE cs.plan_id = %s
              AND cs.state NOT IN ('cancelled')
              AND cp.date_start >= (CURRENT_DATE - INTERVAL '%s months')
        """, (plan_id, months))
        row = self.env.cr.fetchone()
        if not row:
            return {}

        employees_enrolled, total_settlements, total_paid, avg_payout, paid_count, total_revenue = row
        commission_ratio = (
            (total_paid / total_revenue * 100) if total_revenue else 0
        )
        return {
            'employees_enrolled': employees_enrolled or 0,
            'total_settlements': total_settlements or 0,
            'total_paid': float(total_paid or 0),
            'avg_payout': float(avg_payout or 0),
            'paid_count': paid_count or 0,
            'total_revenue': float(total_revenue or 0),
            'commission_ratio': float(commission_ratio),
        }
