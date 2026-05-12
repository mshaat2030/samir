# -*- coding: utf-8 -*-
"""
asc.target — Sales targets per salesperson / team / period.
"""
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class AscTarget(models.Model):
    _name = 'asc.target'
    _description = 'Commission Target'
    _inherit = ['asc.multi.company.mixin', 'mail.thread']
    _order = 'year desc, period_type, salesperson_id'

    name = fields.Char(string='Target Name', required=True, compute='_compute_name', store=True)

    # ── Assignment ────────────────────────────────────────────────────────────
    salesperson_id = fields.Many2one(
        'res.users', string='Salesperson', index=True, ondelete='restrict',
    )
    team_id = fields.Many2one(
        'crm.team', string='Sales Team', index=True, ondelete='restrict',
    )
    plan_id = fields.Many2one(
        'asc.commission.plan', string='Commission Plan',
        required=True, index=True, ondelete='restrict',
    )

    # ── Period ────────────────────────────────────────────────────────────────
    period_type = fields.Selection([
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('annual', 'Annual'),
    ], string='Period Type', required=True, default='monthly')
    month = fields.Selection([
        ('1', 'January'), ('2', 'February'), ('3', 'March'),
        ('4', 'April'), ('5', 'May'), ('6', 'June'),
        ('7', 'July'), ('8', 'August'), ('9', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December'),
    ], string='Month')
    quarter = fields.Selection([
        ('1', 'Q1'), ('2', 'Q2'), ('3', 'Q3'), ('4', 'Q4'),
    ], string='Quarter')
    year = fields.Integer(string='Year', required=True, default=lambda self: fields.Date.today().year)

    # ── Target Values ─────────────────────────────────────────────────────────
    currency_id = fields.Many2one(
        related='plan_id.currency_id', store=True, readonly=True,
    )
    target_revenue = fields.Monetary(
        string='Revenue Target', currency_field='currency_id',
    )
    target_margin = fields.Monetary(
        string='Margin Target', currency_field='currency_id',
    )
    target_units = fields.Integer(string='Units Target')

    # ── Achievement (Computed) ─────────────────────────────────────────────────
    achieved_revenue = fields.Monetary(
        string='Achieved Revenue', currency_field='currency_id',
        compute='_compute_achievement', store=False,
    )
    achievement_pct = fields.Float(
        string='Achievement %', digits=(16, 2),
        compute='_compute_achievement', store=False,
    )
    achievement_status = fields.Selection([
        ('below', 'Below Target'),
        ('on_track', 'On Track'),
        ('achieved', 'Achieved'),
        ('exceeded', 'Exceeded'),
    ], string='Status', compute='_compute_achievement', store=False)

    # ── Accelerator Tiers ─────────────────────────────────────────────────────
    accelerator_ids = fields.One2many(
        'asc.target.accelerator', 'target_id',
        string='Accelerator Tiers',
    )

    # ─────────────────────────────────────────────────────────────────────────
    @api.depends('salesperson_id', 'team_id', 'period_type', 'month', 'quarter', 'year')
    def _compute_name(self):
        for t in self:
            who = t.salesperson_id.name or t.team_id.name or 'Unknown'
            if t.period_type == 'monthly':
                period = f"M{t.month}/{t.year}"
            elif t.period_type == 'quarterly':
                period = f"Q{t.quarter}/{t.year}"
            else:
                period = str(t.year)
            t.name = f"{who} - {period}"

    def _compute_achievement(self):
        """Compute actual revenue vs target from commission lines."""
        for target in self:
            domain = [
                ('company_id', '=', target.company_id.id),
                ('period_year', '=', target.year),
                ('state', 'not in', ['draft', 'cancelled']),
                ('is_simulation', '=', False),
            ]
            if target.salesperson_id:
                domain.append(('salesperson_id', '=', target.salesperson_id.id))
            if target.team_id:
                domain.append(('team_id', '=', target.team_id.id))
            if target.period_type == 'monthly' and target.month:
                domain.append(('period_month', '=', int(target.month)))

            result = self.env['asc.commission.line'].read_group(
                domain, ['base_amount:sum'], [],
            )
            achieved = result[0]['base_amount'] if result else 0.0
            target.achieved_revenue = achieved
            if target.target_revenue:
                pct = (achieved / target.target_revenue) * 100
                target.achievement_pct = pct
                if pct >= 110:
                    target.achievement_status = 'exceeded'
                elif pct >= 100:
                    target.achievement_status = 'achieved'
                elif pct >= 75:
                    target.achievement_status = 'on_track'
                else:
                    target.achievement_status = 'below'
            else:
                target.achievement_pct = 0.0
                target.achievement_status = 'below'

    @api.constrains('salesperson_id', 'team_id')
    def _check_assignment(self):
        for t in self:
            if not t.salesperson_id and not t.team_id:
                raise ValidationError(_('Target must be assigned to a salesperson or a team.'))


class AscTargetAccelerator(models.Model):
    """Accelerator bonus tiers based on target achievement percentage."""
    _name = 'asc.target.accelerator'
    _description = 'Target Accelerator Tier'
    _order = 'from_pct'

    target_id = fields.Many2one(
        'asc.target', string='Target',
        required=True, ondelete='cascade',
    )
    from_pct = fields.Float(string='From (%)', required=True, digits=(16, 2))
    to_pct = fields.Float(string='To (%)', digits=(16, 2))
    accelerator_rate = fields.Float(
        string='Accelerator Rate (%)', required=True, digits=(16, 4),
        help='Additional commission rate applied when achievement is in this range.',
    )
    bonus_fixed = fields.Monetary(
        string='Bonus Fixed Amount', currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        related='target_id.currency_id', store=True, readonly=True,
    )

    @api.constrains('from_pct', 'to_pct')
    def _check_pct(self):
        for acc in self:
            if acc.to_pct and acc.to_pct <= acc.from_pct:
                raise ValidationError(_('Accelerator "To %" must be greater than "From %".'))
