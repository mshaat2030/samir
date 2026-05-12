# -*- coding: utf-8 -*-
"""
asc.commission.rule — Individual rule within a commission plan.
Supports: fixed, percentage, tiered brackets, product/category filters,
          bonus/accelerator triggers, priority engine, effective dates.
"""
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class AscCommissionRule(models.Model):
    _name = 'asc.commission.rule'
    _description = 'Commission Rule'
    _order = 'priority, sequence'

    plan_id = fields.Many2one(
        'asc.commission.plan', string='Commission Plan',
        required=True, ondelete='cascade', index=True,
    )
    name = fields.Char(string='Rule Name', required=True)
    sequence = fields.Integer(default=10)
    priority = fields.Integer(
        string='Priority', default=10,
        help='Lower number = higher priority. Rules are evaluated in ascending priority order.',
    )
    active = fields.Boolean(default=True)

    # ── Rule Type ─────────────────────────────────────────────────────────────
    rule_type = fields.Selection([
        ('fixed', 'Fixed Amount'),
        ('percentage', 'Percentage'),
        ('tiered', 'Tiered Brackets'),
        ('bonus', 'Bonus / Accelerator'),
        ('clawback', 'Clawback'),
        ('override', 'Manager Override'),
    ], string='Rule Type', required=True, default='percentage')

    # ── Filters ───────────────────────────────────────────────────────────────
    product_ids = fields.Many2many(
        'product.product', 'asc_rule_product_rel', 'rule_id', 'product_id',
        string='Applicable Products',
    )
    product_category_ids = fields.Many2many(
        'product.category', 'asc_rule_categ_rel', 'rule_id', 'categ_id',
        string='Applicable Product Categories',
    )
    customer_tag_ids = fields.Many2many(
        'res.partner.category', 'asc_rule_ctag_rel', 'rule_id', 'tag_id',
        string='Customer Tags',
    )
    pricelist_ids = fields.Many2many(
        'product.pricelist', 'asc_rule_pl_rel', 'rule_id', 'pl_id',
        string='Applicable Pricelists',
    )

    # ── Effective Dates ───────────────────────────────────────────────────────
    date_from = fields.Date(string='Effective From')
    date_to = fields.Date(string='Effective To')

    # ── Fixed ─────────────────────────────────────────────────────────────────
    fixed_amount = fields.Monetary(string='Fixed Amount', currency_field='currency_id')
    currency_id = fields.Many2one(
        related='plan_id.currency_id', store=True, readonly=True,
    )

    # ── Percentage ────────────────────────────────────────────────────────────
    rate = fields.Float(string='Rate (%)', digits=(16, 4))
    rate_on = fields.Selection([
        ('subtotal', 'Sale Subtotal'),
        ('margin', 'Sale Margin'),
        ('collected', 'Amount Collected'),
    ], string='Rate Applied On', default='subtotal')

    # ── Tiered Brackets ───────────────────────────────────────────────────────
    tier_ids = fields.One2many(
        'asc.commission.rule.tier', 'rule_id',
        string='Tier Brackets',
    )

    # ── Bonus / Accelerator ───────────────────────────────────────────────────
    bonus_trigger = fields.Selection([
        ('target_pct', 'Target Achievement %'),
        ('revenue_threshold', 'Revenue Threshold'),
        ('units_sold', 'Units Sold'),
    ], string='Bonus Trigger')
    bonus_threshold = fields.Float(string='Trigger Threshold', digits=(16, 2))
    bonus_type = fields.Selection([
        ('fixed', 'Fixed Bonus'),
        ('pct_of_commission', '% of Earned Commission'),
        ('extra_rate', 'Extra Commission Rate'),
    ], string='Bonus Type', default='fixed')
    bonus_value = fields.Float(string='Bonus Value', digits=(16, 4))

    # ── Minimum / Maximum ─────────────────────────────────────────────────────
    min_amount = fields.Monetary(string='Minimum Commission', currency_field='currency_id')
    max_amount = fields.Monetary(string='Maximum Commission (Cap)', currency_field='currency_id')
    apply_cap = fields.Boolean(string='Apply Maximum Cap')

    # ── Stacking ──────────────────────────────────────────────────────────────
    is_exclusive = fields.Boolean(
        string='Exclusive Rule',
        help='If checked, no other rules will be applied once this rule matches.',
    )
    stack_with_plan = fields.Boolean(
        string='Stack with Plan Base Rate',
        help='Add this rule amount on top of the plan base rate.',
        default=True,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Constraints
    # ─────────────────────────────────────────────────────────────────────────
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rule in self:
            if rule.date_from and rule.date_to and rule.date_to < rule.date_from:
                raise ValidationError(_('Effective To must be after Effective From.'))

    @api.constrains('rate')
    def _check_rate(self):
        for rule in self:
            if rule.rate and (rule.rate < 0 or rule.rate > 100):
                raise ValidationError(_('Rate must be between 0 and 100.'))

    # ─────────────────────────────────────────────────────────────────────────
    # Business Methods
    # ─────────────────────────────────────────────────────────────────────────
    def matches_line(self, sale_line, date=None):
        """
        Check if this rule applies to a given sale order line.
        Efficient: pure Python, no additional DB queries.
        """
        self.ensure_one()
        # Date filter
        if date:
            if self.date_from and date < self.date_from:
                return False
            if self.date_to and date > self.date_to:
                return False
        # Product filter
        if self.product_ids and sale_line.product_id not in self.product_ids:
            return False
        # Category filter
        if self.product_category_ids:
            categ = sale_line.product_id.categ_id
            # Check category and all parents
            categ_ids = set()
            c = categ
            while c:
                categ_ids.add(c.id)
                c = c.parent_id
            if not categ_ids.intersection(self.product_category_ids.ids):
                return False
        # Customer tag filter
        if self.customer_tag_ids:
            partner_tags = sale_line.order_id.partner_id.category_id.ids
            if not set(partner_tags).intersection(self.customer_tag_ids.ids):
                return False
        return True


class AscCommissionRuleTier(models.Model):
    """Tiered bracket definition for a commission rule."""
    _name = 'asc.commission.rule.tier'
    _description = 'Commission Rule Tier Bracket'
    _order = 'amount_from'

    rule_id = fields.Many2one(
        'asc.commission.rule', string='Rule',
        required=True, ondelete='cascade', index=True,
    )
    amount_from = fields.Monetary(
        string='From Amount', required=True,
        currency_field='currency_id',
    )
    amount_to = fields.Monetary(
        string='To Amount',
        currency_field='currency_id',
        help='Leave empty for open-ended top tier.',
    )
    rate = fields.Float(string='Rate (%)', required=True, digits=(16, 4))
    fixed_amount = fields.Monetary(
        string='Fixed Amount',
        currency_field='currency_id',
        help='Alternative to rate — fixed amount for amounts in this bracket.',
    )
    tier_method = fields.Selection([
        ('rate', 'Percentage Rate'),
        ('fixed', 'Fixed Amount'),
    ], string='Tier Method', default='rate', required=True)
    currency_id = fields.Many2one(
        related='rule_id.currency_id', store=True, readonly=True,
    )

    @api.constrains('amount_from', 'amount_to')
    def _check_bracket(self):
        for tier in self:
            if tier.amount_to and tier.amount_to <= tier.amount_from:
                raise ValidationError(_('Bracket "To" must be greater than "From".'))
