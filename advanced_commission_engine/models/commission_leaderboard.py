# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class CommissionLeaderboard(models.Model):
    _name = 'commission.leaderboard'
    _description = 'Commission Leaderboard'
    _inherit = ['commission.mixin']
    _order = 'rank, commission_amount desc'
    _rec_name = 'employee_id'

    period_id = fields.Many2one(
        'commission.period', string='Period',
        required=True, index=True, ondelete='cascade',
    )
    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan', index=True
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, index=True,
    )
    department_id = fields.Many2one(
        related='employee_id.department_id', store=True
    )
    team_id = fields.Many2one(
        'crm.team', string='Sales Team', store=True
    )

    # ── Metrics ───────────────────────────────────────────────────────────────
    rank = fields.Integer(string='Rank', default=0)
    previous_rank = fields.Integer(string='Previous Rank', default=0)
    rank_change = fields.Integer(
        string='Rank Change', compute='_compute_rank_change', store=True
    )
    rank_trend = fields.Selection([
        ('up', 'Up'),
        ('down', 'Down'),
        ('same', 'Same'),
        ('new', 'New Entry'),
    ], string='Trend', compute='_compute_rank_change', store=True)

    commission_amount = fields.Monetary(
        string='Commission Earned',
        currency_field='currency_id',
    )
    base_amount = fields.Monetary(
        string='Revenue Generated',
        currency_field='currency_id',
    )
    achievement_percent = fields.Float(
        string='Target Achievement %',
        digits=(5, 2),
    )
    lines_count = fields.Integer(string='Transactions')

    # ── Badges / Gamification ─────────────────────────────────────────────────
    badge_ids = fields.Many2many(
        'gamification.badge',
        'commission_leaderboard_badge_rel',
        'leaderboard_id', 'badge_id',
        string='Badges',
    )
    streak_days = fields.Integer(string='Streak (Days)', default=0)
    is_top_performer = fields.Boolean(string='Top Performer', default=False)
    is_most_improved = fields.Boolean(string='Most Improved', default=False)

    _employee_period_plan_uniq = models.Constraint(
        'UNIQUE(employee_id, period_id, plan_id, company_id)',
        'Only one leaderboard entry per employee/period/plan.',
    )

    @api.depends('rank', 'previous_rank')
    def _compute_rank_change(self):
        for entry in self:
            if entry.previous_rank == 0:
                entry.rank_change = 0
                entry.rank_trend = 'new'
            elif entry.rank < entry.previous_rank:
                entry.rank_change = entry.previous_rank - entry.rank
                entry.rank_trend = 'up'
            elif entry.rank > entry.previous_rank:
                entry.rank_change = entry.rank - entry.previous_rank
                entry.rank_trend = 'down'
            else:
                entry.rank_change = 0
                entry.rank_trend = 'same'

    @api.model
    def refresh_leaderboard(self, period_id, plan_id=None, company_id=None):
        """
        Recompute leaderboard for a period.
        Can be called from cron or manually.
        """
        company = self.env['res.company'].browse(company_id) if company_id else self.env.company
        domain = [
            ('period_id', '=', period_id),
            ('state', '!=', 'cancelled'),
            ('line_type', '=', 'commission'),
            ('company_id', '=', company.id),
        ]
        if plan_id:
            domain.append(('plan_id', '=', plan_id))

        lines = self.env['commission.line'].read_group(
            domain=domain,
            fields=['employee_id', 'commission_amount:sum', 'base_amount:sum', 'id:count'],
            groupby=['employee_id'],
            orderby='commission_amount desc',
        )

        # Save current ranks as previous
        existing = self.search([
            ('period_id', '=', period_id),
            ('company_id', '=', company.id),
        ])
        prev_ranks = {e.employee_id.id: e.rank for e in existing}

        # Delete existing
        existing.unlink()

        # Create new leaderboard entries
        max_commission = max((l['commission_amount'] for l in lines), default=0)
        entries = []
        for rank, line in enumerate(lines, start=1):
            emp_id = line['employee_id'][0]
            commission = line['commission_amount']
            base = line['base_amount']

            # Compute achievement %
            target = self.env['commission.target'].search([
                ('employee_id', '=', emp_id),
                ('period_id', '=', period_id),
            ], limit=1)
            achievement = target.achievement_percent if target else 0.0

            entries.append({
                'period_id': period_id,
                'plan_id': plan_id,
                'employee_id': emp_id,
                'rank': rank,
                'previous_rank': prev_ranks.get(emp_id, 0),
                'commission_amount': commission,
                'base_amount': base,
                'achievement_percent': achievement,
                'lines_count': line['id'],
                'is_top_performer': rank <= 3,
                'company_id': company.id,
                'currency_id': company.currency_id.id,
            })

        if entries:
            self.create(entries)

        # Mark most improved
        created_entries = self.search([
            ('period_id', '=', period_id),
            ('company_id', '=', company.id),
            ('previous_rank', '>', 0),
        ])
        if created_entries:
            most_improved = created_entries.sorted(
                lambda e: e.previous_rank - e.rank, reverse=True
            )[:1]
            most_improved.write({'is_most_improved': True})

        _logger.info('Leaderboard refreshed for period %s: %d entries', period_id, len(entries))

    @api.model
    def cron_refresh_all_leaderboards(self):
        """Called by cron: refresh leaderboards for all open periods."""
        periods = self.env['commission.period'].search([('state', '=', 'open')])
        for period in periods:
            self.refresh_leaderboard(period.id)

    @api.model
    def get_dashboard_data(self, period_id, company_id=None):
        """Return leaderboard data for OWL dashboard."""
        company = self.env['res.company'].browse(company_id) if company_id else self.env.company
        entries = self.search([
            ('period_id', '=', period_id),
            ('company_id', '=', company.id),
        ], order='rank', limit=20)
        return [{
            'rank': e.rank,
            'employee_name': e.employee_id.name,
            'employee_image': '/web/image/hr.employee/%d/avatar_128' % e.employee_id.id,
            'commission_amount': e.commission_amount,
            'base_amount': e.base_amount,
            'achievement_percent': e.achievement_percent,
            'rank_trend': e.rank_trend,
            'rank_change': e.rank_change,
            'is_top_performer': e.is_top_performer,
            'is_most_improved': e.is_most_improved,
            'currency_symbol': e.currency_id.symbol,
        } for e in entries]
