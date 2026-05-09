# -*- coding: utf-8 -*-
"""Recommendation service — AI-ready compensation optimization suggestions."""

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class CommissionRecommendationService(models.AbstractModel):
    """Placeholder AI recommendation engine for commission optimization.

    Architecture is AI-ready: swap _infer() for an ML model call
    (e.g. Anthropic Claude API, OpenAI, or internal ML microservice).
    """

    _name = 'commission.recommendation.service'
    _description = 'Commission Recommendation Service'

    def get_plan_recommendations(self, plan):
        """Analyze a plan and return improvement suggestions.

        Args:
            plan: commission.plan record

        Returns:
            list of dict with keys: type, title, detail, priority
        """
        plan.ensure_one()
        recommendations = []

        # Rule: check if any employees are consistently under-achieving
        underachievers = self._find_underachievers(plan)
        if underachievers:
            recommendations.append({
                'type': 'coaching',
                'title': f'{len(underachievers)} employees consistently under target',
                'detail': 'Consider coaching sessions or quota adjustment. '
                          f'Affected: {", ".join(e.name for e in underachievers[:3])}',
                'priority': 'high',
            })

        # Rule: plan effectiveness (avg achievement)
        avg_achievement = self._avg_plan_achievement(plan)
        if avg_achievement < 70:
            recommendations.append({
                'type': 'plan_design',
                'title': f'Low plan effectiveness: avg achievement {avg_achievement:.0f}%',
                'detail': 'Consider revising targets, rates, or adding accelerators above 100%.',
                'priority': 'high',
            })
        elif avg_achievement > 130:
            recommendations.append({
                'type': 'cost_control',
                'title': f'Over-achievement trend: avg {avg_achievement:.0f}%',
                'detail': 'Consider tightening quotas or adding commission caps to manage cost.',
                'priority': 'medium',
            })

        # Rule: high anomaly rate
        anomaly_rate = self._anomaly_rate(plan)
        if anomaly_rate > 0.1:
            recommendations.append({
                'type': 'data_quality',
                'title': f'{anomaly_rate*100:.0f}% of settlements flagged as anomalous',
                'detail': 'High anomaly rate may indicate data quality issues or unusual sales patterns.',
                'priority': 'medium',
            })

        # Rule: no gamification enabled
        if not plan.enable_gamification:
            recommendations.append({
                'type': 'engagement',
                'title': 'Gamification is disabled for this plan',
                'detail': 'Enabling leaderboards and badges can improve engagement by up to 30%.',
                'priority': 'low',
            })

        # AI placeholder
        ai_suggestions = self._infer(plan, recommendations)
        recommendations.extend(ai_suggestions)

        return sorted(recommendations, key=lambda r: {'high': 0, 'medium': 1, 'low': 2}.get(r['priority'], 3))

    def get_employee_recommendations(self, employee, period):
        """Return personalized recommendations for an employee."""
        target = self.env['commission.target'].search([
            ('employee_id', '=', employee.id),
            ('period_id', '=', period.id),
        ], limit=1)
        recs = []
        if target and target.achievement_pct < 50:
            recs.append({
                'type': 'focus',
                'title': 'Focus on high-value deals',
                'detail': f'You are at {target.achievement_pct:.0f}% of target. '
                          'Prioritize deals in your pipeline with >30% margin.',
                'priority': 'high',
            })
        return recs

    # ── Analysis Helpers ──────────────────────────────────────────────────────

    def _find_underachievers(self, plan, threshold_pct=70, min_periods=3):
        """Return employees who missed target in most recent periods."""
        employees = plan.employee_ids or self.env['hr.employee'].search([('active', '=', True)])
        underachievers = self.env['hr.employee']
        for emp in employees:
            targets = self.env['commission.target'].search([
                ('employee_id', '=', emp.id),
                ('plan_id', '=', plan.id),
                ('achievement_pct', '<', threshold_pct),
            ], limit=min_periods)
            if len(targets) >= min_periods:
                underachievers |= emp
        return underachievers

    def _avg_plan_achievement(self, plan):
        """Return average achievement % across all targets for this plan."""
        targets = self.env['commission.target'].search([('plan_id', '=', plan.id)])
        if not targets:
            return 100.0
        return sum(targets.mapped('achievement_pct')) / len(targets)

    def _anomaly_rate(self, plan):
        """Return fraction of settlements flagged as anomalous."""
        total = self.env['commission.settlement'].search_count([('plan_id', '=', plan.id)])
        if not total:
            return 0.0
        anomalous = self.env['commission.settlement'].search_count([
            ('plan_id', '=', plan.id),
            ('anomaly_flag', '=', True),
        ])
        return anomalous / total

    def _infer(self, plan, existing_recommendations):
        """AI inference placeholder.

        In production, replace this body with a call to:
        - Anthropic Claude API (structured output)
        - Internal ML microservice
        - Rule-based expert system

        Args:
            plan: commission.plan
            existing_recommendations: list of already-generated recommendations

        Returns:
            list of additional recommendation dicts
        """
        # Placeholder: always return empty — no external API calls in base module
        return []
