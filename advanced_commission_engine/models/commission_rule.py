# -*- coding: utf-8 -*-
"""Commission Rule — individual rule within a plan with slab support."""

import logging
from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

CALC_METHODS = [
    ('fixed_percent', 'Fixed Percentage'),
    ('fixed_amount', 'Fixed Amount'),
    ('progressive_slabs', 'Progressive Slabs'),
    ('tiered', 'Tiered'),
    ('margin_based', 'Margin Based'),
    ('revenue_based', 'Revenue Based'),
    ('profit_based', 'Profit Based'),
    ('weighted_kpi', 'Weighted KPI Score'),
    ('hybrid', 'Hybrid'),
    ('dynamic_formula', 'Dynamic Formula'),
]

FILTER_TYPES = [
    ('all', 'All Transactions'),
    ('customer', 'Specific Customers'),
    ('customer_category', 'Customer Category'),
    ('product', 'Specific Products'),
    ('product_category', 'Product Category'),
    ('brand', 'Brand'),
    ('region', 'Sales Region'),
    ('payment_term', 'Payment Term'),
    ('salesperson', 'Salesperson'),
    ('domain', 'Dynamic Domain Filter'),
]


class CommissionRule(models.Model):
    """Rule within a commission plan. Ordered by sequence, evaluated top-down."""

    _name = 'commission.rule'
    _description = 'Commission Rule'
    _inherit = ['mail.thread']
    _order = 'plan_id, sequence, id'

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(string='Rule Name', required=True, tracking=True)
    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan',
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(string='Priority', default=10, index=True)
    active = fields.Boolean(default=True, tracking=True)
    color = fields.Integer(string='Color Index', default=0)

    # ── Method ────────────────────────────────────────────────────────────────
    calculation_method = fields.Selection(
        CALC_METHODS, string='Calculation Method',
        required=True, tracking=True,
        default='fixed_percent',
    )
    rate = fields.Float(string='Rate (%)', digits=(16, 4))
    amount = fields.Monetary(
        string='Fixed Amount',
        currency_field='currency_id',
        help='Used when calculation_method = fixed_amount.',
    )
    currency_id = fields.Many2one(
        'res.currency', related='plan_id.currency_id', readonly=True,
    )
    formula_id = fields.Many2one(
        'commission.formula', string='Formula',
        domain=[('active', '=', True)],
    )

    # ── Slabs (for progressive / tiered) ─────────────────────────────────────
    slab_ids = fields.One2many('commission.rule.slab', 'rule_id', string='Slabs')

    # ── Filters ───────────────────────────────────────────────────────────────
    filter_type = fields.Selection(
        FILTER_TYPES, string='Filter Type',
        default='all', required=True, tracking=True,
    )
    customer_ids = fields.Many2many(
        'res.partner', 'commission_rule_customer_rel',
        'rule_id', 'partner_id',
        string='Customers',
        domain=[('is_company', '=', True)],
    )
    customer_category_ids = fields.Many2many(
        'res.partner.category', 'commission_rule_cust_cat_rel',
        'rule_id', 'category_id',
        string='Customer Categories',
    )
    product_ids = fields.Many2many(
        'product.product', 'commission_rule_product_rel',
        'rule_id', 'product_id',
        string='Products',
    )
    product_category_ids = fields.Many2many(
        'product.category', 'commission_rule_prod_cat_rel',
        'rule_id', 'category_id',
        string='Product Categories',
    )
    payment_term_ids = fields.Many2many(
        'account.payment.term', 'commission_rule_payment_term_rel',
        'rule_id', 'payment_term_id',
        string='Payment Terms',
    )
    salesperson_ids = fields.Many2many(
        'res.users', 'commission_rule_salesperson_rel',
        'rule_id', 'user_id',
        string='Salespersons',
    )
    region = fields.Char(string='Region')

    # ── Dynamic Domain ────────────────────────────────────────────────────────
    domain_filter = fields.Text(
        string='Domain Filter',
        default='[]',
        help='Odoo domain expression applied to the source document.',
    )

    # ── Additional Conditions ─────────────────────────────────────────────────
    min_amount = fields.Monetary(
        string='Minimum Transaction Amount',
        currency_field='currency_id',
        help='Rule applies only if transaction amount >= this value.',
    )
    max_amount = fields.Monetary(
        string='Maximum Transaction Amount',
        currency_field='currency_id',
        help='Rule applies only if transaction amount <= this value (0 = no limit).',
    )
    min_quantity = fields.Float(string='Minimum Quantity', digits=(16, 2))
    max_invoice_age_days = fields.Integer(
        string='Max Invoice Age (Days)',
        default=0,
        help='0 = no limit.',
    )
    collection_delay_penalty_rate = fields.Float(
        string='Collection Delay Penalty (% / month)',
    )

    # ── Achievement Conditions ────────────────────────────────────────────────
    min_achievement_pct = fields.Float(
        string='Min Achievement %',
        help='Rule activates only when target achievement >= this %.',
    )
    max_achievement_pct = fields.Float(
        string='Max Achievement %',
        default=0.0,
        help='Rule activates only when target achievement <= this % (0 = no limit).',
    )

    # ── Behavior Flags ────────────────────────────────────────────────────────
    stop_further_rules = fields.Boolean(
        string='Stop Further Rules',
        help='When matched, no subsequent rules are evaluated.',
    )
    is_additive = fields.Boolean(
        string='Additive',
        default=True,
        help='If False, this rule replaces prior rules instead of adding.',
    )

    # ── Notes ─────────────────────────────────────────────────────────────────
    description = fields.Text(string='Rule Description')

    _sql_constraints = [
        ('rate_range', 'CHECK(rate >= 0 AND rate <= 100)', 'Rate must be between 0 and 100%.'),
        ('amount_positive', 'CHECK(amount >= 0)', 'Fixed amount must be non-negative.'),
        ('min_amount_positive', 'CHECK(min_amount >= 0)', 'Minimum amount must be non-negative.'),
    ]

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('domain_filter')
    def _check_domain_filter(self):
        for rec in self:
            if rec.domain_filter and rec.domain_filter.strip() != '[]':
                try:
                    domain = safe_eval(rec.domain_filter)
                    if not isinstance(domain, list):
                        raise ValidationError('Domain filter must be a list.')
                except Exception as e:
                    raise ValidationError(f'Invalid domain filter: {e}') from e

    @api.constrains('min_amount', 'max_amount')
    def _check_amounts(self):
        for rec in self:
            if rec.max_amount and rec.min_amount > rec.max_amount:
                raise ValidationError('Minimum amount cannot exceed maximum amount.')

    @api.constrains('calculation_method', 'formula_id')
    def _check_formula(self):
        for rec in self:
            if rec.calculation_method == 'dynamic_formula' and not rec.formula_id:
                raise ValidationError('Formula is required for Dynamic Formula method.')

    @api.constrains('calculation_method', 'slab_ids')
    def _check_slabs(self):
        for rec in self:
            if rec.calculation_method in ('progressive_slabs', 'tiered') and not rec.slab_ids:
                raise ValidationError('At least one slab is required for Progressive/Tiered method.')

    # ── Matching Logic ────────────────────────────────────────────────────────

    def matches_context(self, employee=None, invoice=None, sale_order=None, **kwargs):
        """Return True if this rule applies to the given context."""
        self.ensure_one()

        # Filter by customer
        if self.filter_type == 'customer' and self.customer_ids:
            partner = None
            if invoice:
                partner = invoice.partner_id.commercial_partner_id
            elif sale_order:
                partner = sale_order.partner_id.commercial_partner_id
            if partner and partner not in self.customer_ids:
                return False

        # Filter by customer category
        if self.filter_type == 'customer_category' and self.customer_category_ids:
            partner = None
            if invoice:
                partner = invoice.partner_id
            elif sale_order:
                partner = sale_order.partner_id
            if partner:
                partner_cats = partner.category_id
                if not (partner_cats & self.customer_category_ids):
                    return False

        # Filter by salesperson
        if self.filter_type == 'salesperson' and self.salesperson_ids:
            salesperson = None
            if invoice:
                salesperson = invoice.invoice_user_id
            elif sale_order:
                salesperson = sale_order.user_id
            if salesperson and salesperson not in self.salesperson_ids:
                return False

        # Filter by payment term
        if self.filter_type == 'payment_term' and self.payment_term_ids:
            pt = None
            if invoice:
                pt = invoice.invoice_payment_term_id
            elif sale_order:
                pt = sale_order.payment_term_id
            if pt and pt not in self.payment_term_ids:
                return False

        # Dynamic domain filter
        if self.filter_type == 'domain' and self.domain_filter and self.domain_filter.strip() != '[]':
            obj = invoice or sale_order
            if obj:
                try:
                    domain = safe_eval(self.domain_filter)
                    matching = type(obj).search(domain & [('id', '=', obj.id)])
                    if not matching:
                        return False
                except Exception as e:
                    _logger.warning('Rule %s domain eval error: %s', self.name, e)

        return True

    # ── Calculation ───────────────────────────────────────────────────────────

    def calculate_commission(self, base_amount, context_vars=None):
        """Compute commission amount for a given base_amount using this rule.

        Args:
            base_amount: float — the transaction amount to commission
            context_vars: optional dict of extra variables for formulas

        Returns:
            float commission amount
        """
        self.ensure_one()
        ctx = context_vars or {}
        ctx['base_amount'] = base_amount

        if self.calculation_method == 'fixed_percent':
            return base_amount * self.rate / 100.0

        if self.calculation_method == 'fixed_amount':
            return self.amount

        if self.calculation_method in ('progressive_slabs', 'tiered'):
            return self._calc_slabs(base_amount)

        if self.calculation_method == 'margin_based':
            margin = ctx.get('margin_amount', 0.0)
            return margin * self.rate / 100.0

        if self.calculation_method == 'revenue_based':
            revenue = ctx.get('revenue_amount', base_amount)
            return revenue * self.rate / 100.0

        if self.calculation_method == 'profit_based':
            profit = ctx.get('profit_amount', 0.0)
            return profit * self.rate / 100.0

        if self.calculation_method == 'weighted_kpi':
            kpi_score = ctx.get('kpi_score', 0.0)
            base_pool = ctx.get('base_pool', base_amount)
            return base_pool * (kpi_score / 100.0)

        if self.calculation_method == 'dynamic_formula':
            if not self.formula_id:
                return 0.0
            return self.formula_id.evaluate(ctx)

        if self.calculation_method == 'hybrid':
            pct_part = base_amount * self.rate / 100.0
            fixed_part = self.amount
            return pct_part + fixed_part

        return 0.0

    def _calc_slabs(self, amount):
        """Progressive or tiered slab calculation."""
        self.ensure_one()
        slabs = self.slab_ids.sorted('from_amount')
        commission = 0.0

        if self.calculation_method == 'progressive_slabs':
            remaining = amount
            for slab in slabs:
                if remaining <= 0:
                    break
                slab_from = slab.from_amount
                slab_to = slab.to_amount or float('inf')
                slab_width = min(remaining, slab_to - slab_from)
                if slab_width <= 0:
                    continue
                commission += slab_width * slab.rate / 100.0
                remaining -= slab_width

        elif self.calculation_method == 'tiered':
            # Apply the rate of the matching slab to the full amount
            for slab in reversed(slabs):
                if amount >= slab.from_amount:
                    commission = amount * slab.rate / 100.0
                    break

        return commission


class CommissionRuleSlab(models.Model):
    """Amount slab for progressive or tiered commission rules."""

    _name = 'commission.rule.slab'
    _description = 'Commission Rule Slab'
    _order = 'rule_id, from_amount'

    rule_id = fields.Many2one(
        'commission.rule', string='Rule',
        required=True, ondelete='cascade', index=True,
    )
    from_amount = fields.Float(string='From Amount', required=True)
    to_amount = fields.Float(string='To Amount', help='Leave 0 for unlimited.')
    rate = fields.Float(string='Rate (%)', required=True, digits=(16, 4))
    flat_bonus = fields.Float(string='Flat Bonus', help='Additional fixed bonus for reaching this slab.')
    description = fields.Char(string='Slab Label')

    _sql_constraints = [
        ('rate_range', 'CHECK(rate >= 0 AND rate <= 100)', 'Rate must be between 0 and 100%.'),
        ('from_positive', 'CHECK(from_amount >= 0)', 'From amount must be non-negative.'),
    ]

    @api.constrains('from_amount', 'to_amount')
    def _check_slab_range(self):
        for rec in self:
            if rec.to_amount and rec.from_amount >= rec.to_amount:
                raise ValidationError('Slab "To Amount" must be greater than "From Amount".')
