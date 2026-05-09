# -*- coding: utf-8 -*-
"""Commission Leaderboard — period rankings refreshed by cron."""

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class CommissionLeaderboard(models.Model):
    """Ranked leaderboard entry per period refreshed by daily cron."""

    _name = 'commission.leaderboard'
    _description = 'Commission Leaderboard'
    _order = 'period_id desc, rank'

    # ── Scope ─────────────────────────────────────────────────────────────────
    period_id = fields.Many2one(
        'commission.period', string='Period',
        required=True, index=True, ondelete='cascade',
    )
    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan',
        required=True, index=True,
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, index=True,
    )
    company_id = fields.Many2one(
        'res.company', related='period_id.company_id',
        store=True, readonly=True, index=True,
    )
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id',
        store=True, readonly=True,
    )
    department_id = fields.Many2one(
        'hr.department', related='employee_id.department_id',
        store=True, readonly=True, index=True,
    )

    # ── Ranking ───────────────────────────────────────────────────────────────
    rank = fields.Integer(string='Rank', index=True)
    prev_rank = fields.Integer(string='Previous Rank')
    rank_change = fields.Integer(
        string='Rank Change', compute='_compute_rank_change', store=True,
    )
    rank_change_icon = fields.Char(compute='_compute_rank_change')

    # ── Metrics ───────────────────────────────────────────────────────────────
    total_commission = fields.Monetary(
        string='Total Commission', currency_field='currency_id',
    )
    total_base_amount = fields.Monetary(
        string='Total Revenue', currency_field='currency_id',
    )
    achievement_pct = fields.Float(string='Achievement %', digits=(16, 1))
    transaction_count = fields.Integer(string='Transactions')
    kpi_score = fields.Float(string='Avg KPI Score', digits=(16, 1))

    # ── Streak ────────────────────────────────────────────────────────────────
    consecutive_top10 = fields.Integer(string='Consecutive Top-10 Periods')
    streak_badge = fields.Char(string='Streak Badge', compute='_compute_streak_badge')

    # ── Computed ──────────────────────────────────────────────────────────────

    @api.depends('rank', 'prev_rank')
    def _compute_rank_change(self):
        for rec in self:
            if rec.prev_rank and rec.rank:
                change = rec.prev_rank - rec.rank
                rec.rank_change = change
                if change > 0:
                    rec.rank_change_icon = f'▲ {change}'
                elif change < 0:
                    rec.rank_change_icon = f'▼ {abs(change)}'
                else:
                    rec.rank_change_icon = '─'
            else:
                rec.rank_change = 0
                rec.rank_change_icon = 'NEW'

    def _compute_streak_badge(self):
        for rec in self:
            n = rec.consecutive_top10
            if n >= 12:
                rec.streak_badge = '👑 Annual Champion'
            elif n >= 6:
                rec.streak_badge = '🔥 Half-Year Streak'
            elif n >= 3:
                rec.streak_badge = '⭐ Quarter Streak'
            elif n >= 1:
                rec.streak_badge = '✓ Top 10'
            else:
                rec.streak_badge = ''

    # ── Cron ──────────────────────────────────────────────────────────────────

    @api.model
    def cron_refresh_leaderboard(self):
        """Recompute all leaderboards for open periods."""
        open_periods = self.env['commission.period'].search([
            ('state', '=', 'open'),
        ])
        for period in open_periods:
            self._refresh_period_leaderboard(period)

    @api.model
    def _refresh_period_leaderboard(self, period):
        """Recompute leaderboard for a single period."""
        plans = period.plan_ids or self.env['commission.plan'].search([
            ('active', '=', True),
            ('enable_leaderboard', '=', True),
            ('company_id', 'in', [period.company_id.id, False]),
        ])
        for plan in plans:
            self._refresh_plan_leaderboard(period, plan)

    @api.model
    def _refresh_plan_leaderboard(self, period, plan):
        """Rebuild leaderboard rows for one period/plan combination."""
        settlements = self.env['commission.settlement'].search([
            ('period_id', '=', period.id),
            ('plan_id', '=', plan.id),
            ('state', 'not in', ('cancelled',)),
        ])

        # Aggregate per employee
        rows = {}
        for stl in settlements:
            emp_id = stl.employee_id.id
            if emp_id not in rows:
                rows[emp_id] = {
                    'total_commission': 0.0,
                    'total_base_amount': 0.0,
                    'transaction_count': 0,
                    'achievement_pct': 0.0,
                }
            rows[emp_id]['total_commission'] += stl.total_commission
            rows[emp_id]['total_base_amount'] += sum(stl.line_ids.mapped('base_amount'))
            rows[emp_id]['transaction_count'] += len(stl.line_ids)
            # Find target achievement
            target = self.env['commission.target'].search([
                ('employee_id', '=', emp_id),
                ('period_id', '=', period.id),
                ('plan_id', '=', plan.id),
            ], limit=1)
            rows[emp_id]['achievement_pct'] = target.achievement_pct if target else 0.0

        # Sort by total_commission desc → assign ranks
        sorted_rows = sorted(rows.items(), key=lambda x: x[1]['total_commission'], reverse=True)
        for rank, (emp_id, data) in enumerate(sorted_rows, start=1):
            existing = self.search([
                ('period_id', '=', period.id),
                ('plan_id', '=', plan.id),
                ('employee_id', '=', emp_id),
            ], limit=1)
            vals = {
                'period_id': period.id,
                'plan_id': plan.id,
                'employee_id': emp_id,
                'rank': rank,
                'prev_rank': existing.rank if existing else rank,
                'total_commission': data['total_commission'],
                'total_base_amount': data['total_base_amount'],
                'transaction_count': data['transaction_count'],
                'achievement_pct': data['achievement_pct'],
            }
            if existing:
                existing.write(vals)
            else:
                self.create(vals)

        _logger.info(
            'Leaderboard refreshed: period=%s plan=%s rows=%d',
            period.name, plan.name, len(sorted_rows),
        )

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_view_employee_settlements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Settlements — {self.employee_id.name}',
            'res_model': 'commission.settlement',
            'view_mode': 'list,form',
            'domain': [
                ('employee_id', '=', self.employee_id.id),
                ('period_id', '=', self.period_id.id),
            ],
        }

    @api.model
    def get_top_n(self, period_id, plan_id=None, n=10):
        """Return top N leaderboard records for a period."""
        domain = [('period_id', '=', period_id), ('rank', '<=', n)]
        if plan_id:
            domain.append(('plan_id', '=', plan_id))
        return self.search(domain, order='rank')
