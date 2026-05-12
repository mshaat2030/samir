# -*- coding: utf-8 -*-
"""
asc.bonus — Standalone bonus/incentive records (SPIFs, contests, etc.)
"""
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class AscBonus(models.Model):
    _name = 'asc.bonus'
    _description = 'Sales Bonus / SPIF'
    _inherit = ['asc.multi.company.mixin', 'asc.state.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc, name'

    name = fields.Char(string='Bonus Name', required=True, tracking=True)
    code = fields.Char(
        string='Code', copy=False,
        default=lambda self: self.env['ir.sequence'].next_by_code('asc.bonus'),
    )
    active = fields.Boolean(default=True)

    # ── Bonus Type ────────────────────────────────────────────────────────────
    bonus_type = fields.Selection([
        ('spif', 'SPIF (Product Incentive)'),
        ('contest', 'Sales Contest'),
        ('milestone', 'Milestone Bonus'),
        ('retention', 'Retention Bonus'),
        ('referral', 'Referral Bonus'),
    ], string='Bonus Type', required=True, default='spif', tracking=True)

    # ── Applicability ─────────────────────────────────────────────────────────
    user_ids = fields.Many2many(
        'res.users', 'asc_bonus_user_rel', 'bonus_id', 'user_id',
        string='Eligible Salespersons',
    )
    team_ids = fields.Many2many(
        'crm.team', 'asc_bonus_team_rel', 'bonus_id', 'team_id',
        string='Eligible Teams',
    )
    product_ids = fields.Many2many(
        'product.product', 'asc_bonus_prod_rel', 'bonus_id', 'product_id',
        string='Applicable Products',
    )

    # ── Period ────────────────────────────────────────────────────────────────
    date_from = fields.Date(string='From', required=True, tracking=True)
    date_to = fields.Date(string='To', required=True, tracking=True)

    # ── Amount ────────────────────────────────────────────────────────────────
    currency_id = fields.Many2one(
        'res.currency', required=True,
        default=lambda self: self.env.company.currency_id,
    )
    amount_type = fields.Selection([
        ('fixed', 'Fixed Amount'),
        ('percentage', 'Percentage of Commission'),
        ('per_unit', 'Per Unit Sold'),
    ], string='Amount Type', required=True, default='fixed')
    amount = fields.Monetary(string='Bonus Amount', currency_field='currency_id')
    percentage = fields.Float(string='Percentage (%)', digits=(16, 4))
    per_unit_amount = fields.Monetary(
        string='Per Unit Amount', currency_field='currency_id',
    )

    # ── Conditions ────────────────────────────────────────────────────────────
    min_qty = fields.Float(string='Minimum Quantity', default=0.0)
    min_revenue = fields.Monetary(
        string='Minimum Revenue', currency_field='currency_id',
    )
    max_payout = fields.Monetary(
        string='Maximum Payout', currency_field='currency_id',
    )

    description = fields.Html(string='Description')
    notes = fields.Text(string='Internal Notes')

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for bonus in self:
            if bonus.date_to < bonus.date_from:
                raise ValidationError(_('Bonus end date must be after start date.'))

    def is_applicable(self, user, date, product=None):
        """Pure Python check — no extra ORM queries."""
        self.ensure_one()
        if not (self.date_from <= date <= self.date_to):
            return False
        if self.user_ids and user not in self.user_ids:
            return False
        if product and self.product_ids and product not in self.product_ids:
            return False
        return True

    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        'Bonus code must be unique per company.',
    )
