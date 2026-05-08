# -*- coding: utf-8 -*-
"""Commission Rule – individual rule within a plan, with slabs and conditions."""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CommissionRule(models.Model):
    """A commission rule belongs to a plan and defines how to compute commission.

    Rules support conditions (domain), slab configuration, formula references,
    and collection-delay penalties. Rules are evaluated in sequence order.
    """

    _name = 'commission.rule'
    _description = 'Commission Rule'
    _order = 'plan_id, sequence, id'
    _check_company_auto = True

    plan_id = fields.Many2one(
        'commission.plan',
        string='Commission Plan',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(
        related='plan_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    name = fields.Char(
        string='Rule Name',
        required=True,
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='Rules are evaluated from lowest to highest sequence.',
    )
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description')

    # ── Calculation ───────────────────────────────────────────────────────────
    calculation_method = fields.Selection(
        related='plan_id.calculation_method',
        store=True,
        readonly=True,
    )
    rate = fields.Float(
        string='Commission Rate (%)',
        digits=(16, 4),
        default=5.0,
    )
    fixed_amount = fields.Monetary(
        string='Fixed Commission Amount',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        related='plan_id.currency_id',
        store=True,
        readonly=True,
    )
    formula_id = fields.Many2one(
        'commission.formula',
        string='Custom Formula',
        help='Used when plan calculation_method = dynamic_formula.',
    )

    # ── Slab / Tiered ─────────────────────────────────────────────────────────
    slab_from = fields.Monetary(
        string='From Amount',
        currency_field='currency_id',
        default=0,
    )
    slab_to = fields.Monetary(
        string='To Amount (0 = unlimited)',
        currency_field='currency_id',
        default=0,
    )
    slab_ids = fields.One2many(
        'commission.rule.slab',
        'rule_id',
        string='Slabs',
        copy=True,
    )

    # ── Conditions ────────────────────────────────────────────────────────────
    condition_domain = fields.Char(
        string='Filter Domain',
        default='[]',
        help='Domain applied to the source document (sale.order / account.move).',
    )
    min_base_amount = fields.Monetary(
        string='Minimum Base Amount',
        currency_field='currency_id',
        default=0,
        help='Rule only applies when base amount is at or above this value.',
    )
    max_base_amount = fields.Monetary(
        string='Maximum Base Amount (0 = unlimited)',
        currency_field='currency_id',
        default=0,
    )

    # ── Filters ───────────────────────────────────────────────────────────────
    product_ids = fields.Many2many(
        'product.product',
        'commission_rule_product_rel',
        'rule_id',
        'product_id',
        string='Products',
    )
    product_category_ids = fields.Many2many(
        'product.category',
        'commission_rule_product_cat_rel',
        'rule_id',
        'category_id',
        string='Product Categories',
    )
    partner_ids = fields.Many2many(
        'res.partner',
        'commission_rule_partner_rel',
        'rule_id',
        'partner_id',
        string='Customers',
    )
    country_ids = fields.Many2many(
        'res.country',
        'commission_rule_country_rel',
        'rule_id',
        'country_id',
        string='Customer Countries',
    )
    payment_term_ids = fields.Many2many(
        'account.payment.term',
        'commission_rule_payment_term_rel',
        'rule_id',
        'payment_term_id',
        string='Payment Terms',
    )

    # ── Margin / Profit ───────────────────────────────────────────────────────
    min_margin_pct = fields.Float(
        string='Min Margin % Required',
        default=0.0,
    )
    max_margin_pct = fields.Float(
        string='Max Margin %',
        default=0.0,
        help='0 = no upper limit.',
    )

    # ── Collection Delay Penalty ──────────────────────────────────────────────
    apply_delay_penalty = fields.Boolean(
        string='Apply Collection Delay Penalty',
        default=False,
    )
    delay_penalty_days = fields.Integer(
        string='Penalty After (Days)',
        default=30,
    )
    delay_penalty_pct = fields.Float(
        string='Penalty %',
        default=10.0,
    )

    # ── Caps ──────────────────────────────────────────────────────────────────
    cap_amount = fields.Monetary(
        string='Commission Cap (0 = no cap)',
        currency_field='currency_id',
        default=0,
    )
    cap_period = fields.Selection(
        [
            ('none', 'No Cap'),
            ('per_document', 'Per Document'),
            ('per_period', 'Per Period'),
            ('per_year', 'Per Year'),
        ],
        string='Cap Period',
        default='none',
    )


    _rate_positive = models.Constraint(
        'CHECK(rate >= 0)',
        'Commission rate cannot be negative.',
    )
    _fixed_amount_positive = models.Constraint(
        'CHECK(fixed_amount >= 0)',
        'Fixed commission amount cannot be negative.',
    )


    @api.constrains('slab_from', 'slab_to')
    def _check_slab_range(self):
        for rule in self:
            if rule.slab_to and rule.slab_from >= rule.slab_to:
                raise ValidationError(
                    f"Rule '{rule.name}': Slab 'From' must be less than 'To'."
                )

    @api.constrains('min_base_amount', 'max_base_amount')
    def _check_base_amount_range(self):
        for rule in self:
            if rule.max_base_amount and rule.min_base_amount >= rule.max_base_amount:
                raise ValidationError(
                    f"Rule '{rule.name}': Min base amount must be less than max."
                )

    def compute_commission(self, base_amount, context_vals=None):
        """Compute commission amount for a given base amount using this rule.

        :param base_amount: The base amount to calculate commission on.
        :param context_vals: dict with extra context (margin_pct, employee, etc.).
        :return: float commission amount.
        """
        self.ensure_one()
        if context_vals is None:
            context_vals = {}

        method = self.calculation_method
        result = 0.0

        if method == 'fixed_percent':
            result = base_amount * self.rate / 100.0

        elif method == 'fixed_amount':
            result = self.fixed_amount

        elif method in ('progressive_slabs', 'tiered'):
            if self.slab_ids:
                result = self._compute_slab(base_amount)
            else:
                # Use rule's own slab_from/slab_to
                slab_base = self._get_slab_portion(base_amount)
                result = slab_base * self.rate / 100.0

        elif method == 'margin_based':
            margin = context_vals.get('margin_pct', 0)
            result = base_amount * self.rate / 100.0 * (margin / 100.0)

        elif method in ('revenue_based', 'profit_based'):
            result = base_amount * self.rate / 100.0

        elif method == 'weighted_kpi':
            kpi_score = context_vals.get('kpi_score', 0)
            result = (kpi_score / 100.0) * (self.fixed_amount or base_amount * self.rate / 100.0)

        elif method == 'dynamic_formula':
            if self.formula_id:
                from ..services.formula_engine import FormulaEngine
                engine = FormulaEngine(self.env)
                result = engine.evaluate(
                    self.formula_id,
                    base_amount=base_amount,
                    rate=self.rate,
                    **context_vals,
                )
            else:
                result = base_amount * self.rate / 100.0

        elif method == 'hybrid':
            # Fixed amount + percentage
            result = self.fixed_amount + (base_amount * self.rate / 100.0)

        # Apply cap
        if self.cap_amount and self.cap_period == 'per_document':
            result = min(result, self.cap_amount)

        # Apply collection delay penalty
        if self.apply_delay_penalty:
            delay_days = context_vals.get('payment_delay_days', 0)
            if delay_days > self.delay_penalty_days:
                penalty = result * self.delay_penalty_pct / 100.0
                result = max(0, result - penalty)

        return result

    def _compute_slab(self, base_amount):
        """Compute commission using tiered slab structure."""
        self.ensure_one()
        total = 0.0
        remaining = base_amount
        slabs = self.slab_ids.sorted('slab_from')
        for slab in slabs:
            if remaining <= 0:
                break
            lower = slab.slab_from
            upper = slab.slab_to if slab.slab_to else float('inf')
            slab_amount = min(remaining, upper - lower)
            if slab_amount > 0:
                if slab.rate_type == 'percent':
                    total += slab_amount * slab.rate / 100.0
                else:
                    total += slab.fixed_amount
            remaining -= slab_amount
        return total

    def _get_slab_portion(self, base_amount):
        """Return the portion of base_amount that falls within this rule's slab."""
        self.ensure_one()
        lower = self.slab_from or 0
        upper = self.slab_to or float('inf')
        if base_amount <= lower:
            return 0.0
        return min(base_amount, upper) - lower


class CommissionRuleSlab(models.Model):
    """Individual slab within a commission rule for progressive/tiered calculation."""

    _name = 'commission.rule.slab'
    _description = 'Commission Rule Slab'
    _order = 'rule_id, slab_from'

    rule_id = fields.Many2one(
        'commission.rule',
        string='Rule',
        required=True,
        ondelete='cascade',
        index=True,
    )
    slab_from = fields.Monetary(
        string='From',
        currency_field='currency_id',
        required=True,
        default=0,
    )
    slab_to = fields.Monetary(
        string='To (0 = unlimited)',
        currency_field='currency_id',
        default=0,
    )
    rate = fields.Float(
        string='Rate (%)',
        digits=(16, 4),
        default=5.0,
    )
    rate_type = fields.Selection(
        [('percent', 'Percentage'), ('fixed', 'Fixed Amount')],
        default='percent',
        required=True,
    )
    fixed_amount = fields.Monetary(
        string='Fixed Amount',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        related='rule_id.currency_id',
        store=True,
        readonly=True,
    )



    _rate_positive = models.Constraint(
        'CHECK(rate >= 0)',
        'Slab rate cannot be negative.',
    )

    @api.constrains('slab_from', 'slab_to')
    def _check_slab_range(self):
        for slab in self:
            if slab.slab_to and slab.slab_from >= slab.slab_to:
                raise ValidationError('Slab From must be less than To.')
