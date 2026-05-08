# -*- coding: utf-8 -*-
"""Commission Badge – gamification achievements."""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CommissionBadge(models.Model):
    """Defines an achievement badge that can be awarded to employees
    based on performance criteria (rank, amount, streak).
    """

    _name = 'commission.badge'
    _description = 'Commission Badge'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(
        string='Badge Name',
        required=True,
        tracking=True,
    )
    code = fields.Char(
        string='Code',
        required=True,
        index=True,
    )
    description = fields.Text(string='Description')
    badge_type = fields.Selection(
        [
            ('monthly_top', 'Monthly Top Performer'),
            ('quarterly_top', 'Quarterly Top Performer'),
            ('milestone', 'Milestone Achievement'),
            ('streak', 'Consecutive Target Achievement'),
            ('team', 'Team Achievement'),
            ('special', 'Special Recognition'),
        ],
        string='Badge Type',
        required=True,
        default='milestone',
        index=True,
    )
    criteria_type = fields.Selection(
        [
            ('rank', 'Rank Position'),
            ('amount', 'Commission Amount'),
            ('streak', 'Achievement Streak'),
            ('attainment', 'Target Attainment %'),
            ('manual', 'Manual Award'),
        ],
        string='Criteria Type',
        required=True,
        default='amount',
    )
    criteria_value = fields.Float(
        string='Criteria Value',
        default=0.0,
        help='For rank: 1 = top, 3 = top 3. For amount: threshold amount. For streak: periods.',
    )
    icon = fields.Char(
        string='Icon',
        default='fa-trophy',
        help='FontAwesome icon class (e.g., fa-trophy, fa-star, fa-medal).',
    )
    color = fields.Char(
        string='Color',
        default='#FFD700',
    )
    points = fields.Integer(
        string='Gamification Points',
        default=100,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        index=True,
    )

    award_ids = fields.One2many(
        'commission.badge.award',
        'badge_id',
        string='Awards',
    )
    award_count = fields.Integer(
        compute='_compute_award_count',
        string='Times Awarded',
    )


    def _compute_award_count(self):
        data = self.env['commission.badge.award'].read_group(
            [('badge_id', 'in', self.ids)],
            ['badge_id'],
            ['badge_id'],
        )
        mapping = {d['badge_id'][0]: d['badge_id_count'] for d in data}
        for badge in self:
            badge.award_count = mapping.get(badge.id, 0)

    def action_award_count(self):
        """Open list of badge awards for this badge."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Awards – {self.name}',
            'res_model': 'commission.badge.award',
            'view_mode': 'list,form',
            'domain': [('badge_id', '=', self.id)],
            'context': {'default_badge_id': self.id},
        }

    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        'Badge code must be unique per company.',
    )


    @api.model
    def _cron_check_and_award_badges(self):
        """Evaluate badge criteria and award badges to qualifying employees."""
        from ..services.recommendation_service import RecommendationService
        service = RecommendationService(self.env)
        service.evaluate_badges()


class CommissionBadgeAward(models.Model):
    """Records when a badge was awarded to an employee."""

    _name = 'commission.badge.award'
    _description = 'Commission Badge Award'
    _order = 'date_awarded desc'

    badge_id = fields.Many2one(
        'commission.badge',
        string='Badge',
        required=True,
        index=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True,
    )
    period_id = fields.Many2one(
        'commission.period',
        string='Period',
        index=True,
    )
    date_awarded = fields.Date(
        string='Date Awarded',
        default=fields.Date.today,
        required=True,
        index=True,
    )
    awarded_by_id = fields.Many2one(
        'res.users',
        string='Awarded By',
        default=lambda self: self.env.user,
    )
    notes = fields.Text(string='Notes')
    notified = fields.Boolean(
        string='Employee Notified',
        default=False,
    )
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        index=True,
    )

    def action_notify_employee(self):
        """Send notification email to employee."""
        template = self.env.ref(
            'advanced_commission_engine.mail_template_badge_awarded',
            raise_if_not_found=False,
        )
        for award in self:
            if template and not award.notified:
                template.send_mail(award.id, force_send=True)
                award.notified = True
