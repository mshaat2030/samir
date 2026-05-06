# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class CommissionRule(models.Model):
    _name = 'commission.rule'
    _description = 'Commission Rule'
    _order = 'priority, sequence'

    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan',
        required=True, ondelete='cascade', index=True,
    )
    name = fields.Char(string='Rule Name', required=True)
    sequence = fields.Integer(default=10)
    priority = fields.Integer(
        string='Priority',
        default=10,
        help='Lower number = higher priority. Rules are applied in priority order.',
    )
    active = fields.Boolean(default=True)
    color = fields.Integer(default=0)
    description = fields.Text(string='Description')
    company_id = fields.Many2one(related='plan_id.company_id', store=True, index=True)

    # ── Rule Type ─────────────────────────────────────────────────────────────
    rule_type = fields.Selection([
        ('rate_override', 'Rate Override'),
        ('tier', 'Tier'),
        ('slab', 'Slab'),
        ('multiplier', 'Multiplier'),
        ('flat_bonus', 'Flat Bonus'),
        ('formula', 'Formula'),
        ('exclude', 'Exclude'),
        ('accelerator', 'Accelerator'),
        ('decelerator', 'Decelerator'),
    ], string='Rule Type', required=True, default='rate_override')

    # ── Rate & Amount ─────────────────────────────────────────────────────────
    rate = fields.Float(string='Rate (%)', digits=(5, 4))
    flat_amount = fields.Monetary(
        string='Flat Amount',
        currency_field='currency_id',
    )
    multiplier = fields.Float(string='Multiplier', default=1.0)
    currency_id = fields.Many2one(related='plan_id.currency_id', store=True)

    # ── Tier/Slab Ranges ──────────────────────────────────────────────────────
    from_amount = fields.Monetary(
        string='From Amount',
        currency_field='currency_id',
        default=0.0,
    )
    to_amount = fields.Monetary(
        string='To Amount',
        currency_field='currency_id',
        default=0.0,
        help='0 means unlimited',
    )
    from_percent = fields.Float(
        string='From (%)',
        help='From percentage of target achieved',
    )
    to_percent = fields.Float(
        string='To (%)',
        help='To percentage of target achieved (0 = unlimited)',
    )

    # ── Formula ───────────────────────────────────────────────────────────────
    formula = fields.Text(
        string='Formula',
        help='Python expression. Available: commission, amount, rate, margin, employee',
    )

    # ── Conditions ────────────────────────────────────────────────────────────
    condition_type = fields.Selection([
        ('always', 'Always'),
        ('amount_gte', 'Amount ≥ Value'),
        ('amount_lte', 'Amount ≤ Value'),
        ('product_category', 'Product Category'),
        ('customer_type', 'Customer Type'),
        ('region', 'Region/Country'),
        ('team', 'Sales Team'),
        ('target_percent', 'Target Achievement %'),
        ('formula', 'Custom Formula Condition'),
    ], string='Condition', default='always')

    condition_value = fields.Float(string='Condition Value')
    condition_ids = fields.One2many(
        'commission.rule.condition', 'rule_id', string='Conditions'
    )
    condition_formula = fields.Text(
        string='Condition Formula',
        help='Python expression returning True/False. Variables: amount, employee, order, invoice',
    )

    # ── Applicability ─────────────────────────────────────────────────────────
    product_category_ids = fields.Many2many(
        'product.category',
        'commission_rule_product_categ_rel',
        'rule_id', 'categ_id',
        string='Product Categories',
    )
    country_ids = fields.Many2many(
        'res.country',
        'commission_rule_country_rel',
        'rule_id', 'country_id',
        string='Countries',
    )
    team_ids = fields.Many2many(
        'crm.team',
        'commission_rule_team_rel',
        'rule_id', 'team_id',
        string='Sales Teams',
    )
    customer_tag_ids = fields.Many2many(
        'res.partner.category',
        'commission_rule_customer_tag_rel',
        'rule_id', 'tag_id',
        string='Customer Tags',
    )

    # ── Date Validity ─────────────────────────────────────────────────────────
    date_from = fields.Date(string='Valid From')
    date_to = fields.Date(string='Valid To')

    # ── Constraints ───────────────────────────────────────────────────────────
    _name_plan_uniq = models.Constraint(
        'UNIQUE(name, plan_id)',
        'Rule name must be unique within a commission plan.',
    )

    # ── Validation ────────────────────────────────────────────────────────────
    @api.constrains('from_amount', 'to_amount')
    def _check_amounts(self):
        for rule in self:
            if rule.to_amount > 0 and rule.from_amount > rule.to_amount:
                raise ValidationError(
                    _('Rule "%s": From Amount cannot exceed To Amount.') % rule.name
                )

    @api.constrains('from_percent', 'to_percent')
    def _check_percents(self):
        for rule in self:
            if rule.to_percent > 0 and rule.from_percent > rule.to_percent:
                raise ValidationError(
                    _('Rule "%s": From % cannot exceed To %.') % rule.name
                )

    # ── Business Logic ────────────────────────────────────────────────────────
    def _evaluate_conditions(self, ctx):
        """
        Evaluate whether this rule applies given context.
        ctx: dict with amount, employee, order, invoice, etc.
        """
        self.ensure_one()
        today = fields.Date.today()
        if self.date_from and today < self.date_from:
            return False
        if self.date_to and today > self.date_to:
            return False

        if self.condition_type == 'always':
            return True
        elif self.condition_type == 'amount_gte':
            return ctx.get('amount', 0) >= self.condition_value
        elif self.condition_type == 'amount_lte':
            return ctx.get('amount', 0) <= self.condition_value
        elif self.condition_type == 'target_percent':
            achieved_pct = ctx.get('achieved_percent', 0)
            return achieved_pct >= self.condition_value
        elif self.condition_type == 'formula' and self.condition_formula:
            from ...services.formula_engine import FormulaEngine
            engine = FormulaEngine(self.env)
            try:
                return bool(engine.evaluate(self.condition_formula, ctx))
            except Exception:
                return False
        elif self.condition_type == 'product_category':
            product_categ = ctx.get('product_category_id')
            if product_categ and self.product_category_ids:
                return product_categ in self.product_category_ids.ids
        elif self.condition_type == 'region':
            country = ctx.get('country_id')
            if country and self.country_ids:
                return country in self.country_ids.ids
        elif self.condition_type == 'team':
            team = ctx.get('team_id')
            if team and self.team_ids:
                return team in self.team_ids.ids

        # Evaluate all detailed conditions
        for cond in self.condition_ids:
            if not cond.evaluate(ctx):
                return False
        return True

    def apply(self, commission, ctx):
        """Apply this rule to the current commission amount."""
        self.ensure_one()
        if self.rule_type == 'rate_override':
            return ctx.get('amount', 0) * self.rate / 100.0
        elif self.rule_type == 'multiplier':
            return commission * self.multiplier
        elif self.rule_type == 'flat_bonus':
            return commission + self.flat_amount
        elif self.rule_type == 'accelerator':
            return commission * (1 + self.multiplier - 1)
        elif self.rule_type == 'decelerator':
            return commission * self.multiplier
        elif self.rule_type == 'formula' and self.formula:
            from ...services.formula_engine import FormulaEngine
            engine = FormulaEngine(self.env)
            ctx_with_commission = {**ctx, 'commission': commission}
            try:
                return engine.evaluate(self.formula, ctx_with_commission)
            except Exception:
                return commission
        elif self.rule_type == 'exclude':
            return 0.0
        return commission


class CommissionRuleCondition(models.Model):
    _name = 'commission.rule.condition'
    _description = 'Commission Rule Condition'
    _order = 'sequence'

    rule_id = fields.Many2one(
        'commission.rule', required=True, ondelete='cascade'
    )
    sequence = fields.Integer(default=10)
    field_name = fields.Char(string='Field', required=True)
    operator = fields.Selection([
        ('=', '='),
        ('!=', '≠'),
        ('>', '>'),
        ('>=', '≥'),
        ('<', '<'),
        ('<=', '≤'),
        ('in', 'in'),
        ('not in', 'not in'),
        ('like', 'contains'),
        ('not like', 'does not contain'),
    ], required=True, default='=')
    value = fields.Char(string='Value')

    def evaluate(self, ctx):
        """Evaluate this condition against context."""
        self.ensure_one()
        field_value = ctx.get(self.field_name)
        if field_value is None:
            return False
        try:
            compare_value = type(field_value)(self.value) if self.value else None
            if self.operator == '=':
                return field_value == compare_value
            elif self.operator == '!=':
                return field_value != compare_value
            elif self.operator == '>':
                return field_value > compare_value
            elif self.operator == '>=':
                return field_value >= compare_value
            elif self.operator == '<':
                return field_value < compare_value
            elif self.operator == '<=':
                return field_value <= compare_value
            elif self.operator == 'in':
                values = [v.strip() for v in self.value.split(',')]
                return str(field_value) in values
            elif self.operator == 'not in':
                values = [v.strip() for v in self.value.split(',')]
                return str(field_value) not in values
            elif self.operator == 'like':
                return self.value.lower() in str(field_value).lower()
            elif self.operator == 'not like':
                return self.value.lower() not in str(field_value).lower()
        except (TypeError, ValueError):
            return False
        return False
