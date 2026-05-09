# -*- coding: utf-8 -*-
"""Commission Badge — gamification achievement awarded to employees."""

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

BADGE_TYPES = [
    ('top_performer', 'Top Performer'),
    ('target_achieved', 'Target Achieved'),
    ('target_exceeded', 'Target Exceeded 120%+'),
    ('streak_3', '3-Month Streak'),
    ('streak_6', '6-Month Streak'),
    ('streak_12', 'Annual Champion'),
    ('first_deal', 'First Deal'),
    ('highest_deal', 'Highest Single Deal'),
    ('most_improved', 'Most Improved'),
    ('team_mvp', 'Team MVP'),
    ('customer_champion', 'Customer Champion'),
    ('fast_closer', 'Fast Closer'),
    ('collection_hero', 'Collection Hero'),
    ('custom', 'Custom Award'),
]


class CommissionBadge(models.Model):
    """Achievement badge awarded to an employee for a commission milestone."""

    _name = 'commission.badge'
    _description = 'Commission Badge'
    _inherit = ['mail.thread']
    _order = 'awarded_date desc'

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(string='Badge Name', required=True)
    badge_type = fields.Selection(
        BADGE_TYPES, string='Badge Type',
        required=True, tracking=True,
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, index=True, tracking=True,
    )
    period_id = fields.Many2one(
        'commission.period', string='Period',
        index=True,
    )
    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan',
    )
    awarded_by = fields.Many2one(
        'res.users', string='Awarded By',
        default=lambda self: self.env.user,
    )
    awarded_date = fields.Date(
        string='Awarded Date',
        default=fields.Date.today,
        required=True, index=True,
    )
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company,
        index=True,
    )

    # ── Display ───────────────────────────────────────────────────────────────
    description = fields.Text(string='Description')
    icon = fields.Char(string='Icon', default='🏆', help='Emoji or font-awesome class.')
    color_hex = fields.Char(string='Color', default='#FFD700')

    # ── Validity ──────────────────────────────────────────────────────────────
    is_public = fields.Boolean(
        string='Show on Leaderboard', default=True,
        help='Display this badge on public leaderboards and portal.',
    )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @api.model
    def award(self, employee_id, badge_type, period_id=None, plan_id=None, description=None):
        """Convenient factory to award a badge and post a chatter message."""
        badge_labels = dict(BADGE_TYPES)
        badge = self.create({
            'name': badge_labels.get(badge_type, badge_type),
            'badge_type': badge_type,
            'employee_id': employee_id,
            'period_id': period_id,
            'plan_id': plan_id,
            'description': description or '',
        })
        employee = self.env['hr.employee'].browse(employee_id)
        if employee.user_id:
            badge.message_post(
                body=f'🏆 Congratulations {employee.name}! You earned the badge: {badge.name}',
                partner_ids=[employee.user_id.partner_id.id],
            )
        _logger.info('Badge %s awarded to employee %s', badge_type, employee_id)
        return badge

    @api.model
    def check_and_award_badges(self, settlement):
        """Auto-award badges after settlement is calculated."""
        emp_id = settlement.employee_id.id
        period_id = settlement.period_id.id
        plan_id = settlement.plan_id.id

        # Target achieved
        target = self.env['commission.target'].search([
            ('employee_id', '=', emp_id),
            ('period_id', '=', period_id),
            ('plan_id', '=', plan_id),
        ], limit=1)
        if target:
            if target.achievement_pct >= 120:
                self.award(emp_id, 'target_exceeded', period_id, plan_id,
                           f'Achieved {target.achievement_pct:.1f}% of target.')
            elif target.achievement_pct >= 100:
                self.award(emp_id, 'target_achieved', period_id, plan_id,
                           f'Hit target: {target.achievement_pct:.1f}%')

        # Streak badges
        streak = target.consecutive_periods_achieved if target else 0
        if streak >= 12:
            self.award(emp_id, 'streak_12', period_id, plan_id, '12-month streak!')
        elif streak >= 6:
            self.award(emp_id, 'streak_6', period_id, plan_id, '6-month streak!')
        elif streak >= 3:
            self.award(emp_id, 'streak_3', period_id, plan_id, '3-month streak!')

        # Top performer (rank 1 on leaderboard)
        lb = self.env['commission.leaderboard'].search([
            ('period_id', '=', period_id),
            ('employee_id', '=', emp_id),
            ('rank', '=', 1),
        ], limit=1)
        if lb:
            self.award(emp_id, 'top_performer', period_id, plan_id, 'Rank #1 this period!')
