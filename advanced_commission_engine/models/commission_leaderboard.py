# -*- coding: utf-8 -*-
"""Commission Leaderboard – real-time rankings per period."""

from odoo import api, fields, models


class CommissionLeaderboard(models.Model):
    """Stores ranked leaderboard entries per period.

    Updated by cron every 6 hours via :meth:`_cron_refresh_leaderboards`.
    Supports individual, team, and plan-specific rankings.
    """

    _name = 'commission.leaderboard'
    _description = 'Commission Leaderboard'
    _order = 'period_id desc, rank asc'
    _check_company_auto = True

    period_id = fields.Many2one(
        'commission.period',
        string='Period',
        required=True,
        index=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
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

    # ── Ranking ───────────────────────────────────────────────────────────────
    rank = fields.Integer(
        string='Rank',
        default=0,
        index=True,
    )
    previous_rank = fields.Integer(
        string='Previous Rank',
        default=0,
    )
    rank_change = fields.Integer(
        string='Rank Change',
        compute='_compute_rank_change',
    )
    rank_change_icon = fields.Char(
        compute='_compute_rank_change',
    )

    # ── Metrics ───────────────────────────────────────────────────────────────
    total_commission = fields.Monetary(
        string='Total Commission',
        currency_field='currency_id',
        default=0.0,
    )
    total_base_amount = fields.Monetary(
        string='Total Revenue',
        currency_field='currency_id',
        default=0.0,
    )
    line_count = fields.Integer(
        string='Deals / Invoices',
        default=0,
    )
    target_attainment = fields.Float(
        string='Target Attainment %',
        digits=(16, 1),
        default=0.0,
    )
    streak = fields.Integer(
        string='Target Streak (Periods)',
        default=0,
        help='Consecutive periods in which the employee met their target.',
    )
    badge_count = fields.Integer(
        string='Badges Earned',
        default=0,
    )


    _employee_plan_period_uniq = models.Constraint(
        'UNIQUE(employee_id, plan_id, period_id)',
        'Duplicate leaderboard entry.',
    )


    @api.depends('rank', 'previous_rank')
    def _compute_rank_change(self):
        for entry in self:
            if entry.previous_rank and entry.rank:
                change = entry.previous_rank - entry.rank
                entry.rank_change = change
                if change > 0:
                    entry.rank_change_icon = '▲'
                elif change < 0:
                    entry.rank_change_icon = '▼'
                else:
                    entry.rank_change_icon = '='
            else:
                entry.rank_change = 0
                entry.rank_change_icon = 'NEW'

    @api.model
    def _cron_refresh_leaderboards(self):
        """Refresh all leaderboard entries for active and recently closed periods."""
        periods = self.env['commission.period'].search([
            ('state', 'in', ('open', 'locked')),
        ])
        for period in periods:
            self._refresh_period_leaderboard(period)

    @api.model
    def _refresh_period_leaderboard(self, period):
        """Compute and upsert leaderboard entries for a given period."""
        # Aggregate commission by employee/plan for this period
        self.env.cr.execute("""
            SELECT
                cs.employee_id,
                cs.plan_id,
                SUM(cl.commission_amount) AS total_commission,
                SUM(cl.base_amount) AS total_base,
                COUNT(cl.id) AS line_count
            FROM commission_settlement cs
            LEFT JOIN commission_line cl
                ON cl.settlement_id = cs.id
                AND cl.state != 'cancelled'
            WHERE cs.period_id = %s
              AND cs.state NOT IN ('cancelled')
            GROUP BY cs.employee_id, cs.plan_id
            ORDER BY total_commission DESC NULLS LAST
        """, (period.id,))
        rows = self.env.cr.fetchall()

        # Store previous ranks
        existing = self.search([('period_id', '=', period.id)])
        prev_rank_map = {
            (e.employee_id.id, e.plan_id.id): e.rank for e in existing
        }
        existing.unlink()

        for idx, (employee_id, plan_id, total_commission, total_base, line_count) in enumerate(rows, 1):
            prev_rank = prev_rank_map.get((employee_id, plan_id or 0), 0)
            # Get target attainment
            target = self.env['commission.target'].search([
                ('employee_id', '=', employee_id),
                ('period_id', '=', period.id),
                ('plan_id', '=', plan_id),
            ], limit=1)
            attainment = target.overall_attainment if target else 0.0

            # Count badges
            badge_count = self.env['commission.badge.award'].search_count([
                ('employee_id', '=', employee_id),
                ('date_awarded', '>=', period.date_start),
                ('date_awarded', '<=', period.date_end),
            ])

            self.create({
                'period_id': period.id,
                'employee_id': employee_id,
                'plan_id': plan_id,
                'company_id': period.company_id.id,
                'rank': idx,
                'previous_rank': prev_rank,
                'total_commission': total_commission or 0.0,
                'total_base_amount': total_base or 0.0,
                'line_count': line_count or 0,
                'target_attainment': attainment,
                'badge_count': badge_count,
            })
