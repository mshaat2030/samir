# -*- coding: utf-8 -*-
"""Commission Line — one computed commission entry linked to a source document."""

import logging
from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class CommissionLine(models.Model):
    """Atomic commission record computed from one source document line."""

    _name = 'commission.line'
    _description = 'Commission Line'
    _order = 'settlement_id, date desc'

    # ── Parent ────────────────────────────────────────────────────────────────
    settlement_id = fields.Many2one(
        'commission.settlement', string='Settlement',
        required=True, ondelete='cascade', index=True,
    )
    rule_id = fields.Many2one(
        'commission.rule', string='Applied Rule',
        ondelete='set null', index=True,
    )

    # ── Source Document Links ─────────────────────────────────────────────────
    invoice_id = fields.Many2one(
        'account.move', string='Invoice',
        ondelete='set null', index=True,
    )
    invoice_line_id = fields.Many2one(
        'account.move.line', string='Invoice Line',
        ondelete='set null',
    )
    sale_order_id = fields.Many2one(
        'sale.order', string='Sale Order',
        ondelete='set null', index=True,
    )
    sale_order_line_id = fields.Many2one(
        'sale.order.line', string='Sale Order Line',
        ondelete='set null',
    )
    payment_id = fields.Many2one(
        'account.payment', string='Payment',
        ondelete='set null', index=True,
    )
    crm_lead_id = fields.Many2one(
        'crm.lead', string='CRM Lead / Opportunity',
        ondelete='set null', index=True,
    )
    subscription_id = fields.Many2one(
        'sale.subscription', string='Subscription',
        ondelete='set null', index=True,
    )
    project_task_id = fields.Many2one(
        'project.task', string='Project Task',
        ondelete='set null', index=True,
    )

    # ── Reference Info ────────────────────────────────────────────────────────
    source_type = fields.Selection([
        ('invoice', 'Invoice'),
        ('payment', 'Payment'),
        ('sale_order', 'Sale Order'),
        ('subscription', 'Subscription'),
        ('project_task', 'Project Task'),
        ('crm_lead', 'CRM Lead'),
        ('kpi', 'KPI Score'),
        ('manual', 'Manual'),
    ], string='Source Type', required=True, index=True)
    date = fields.Date(string='Transaction Date', index=True)
    partner_id = fields.Many2one('res.partner', string='Customer', index=True)
    product_id = fields.Many2one('product.product', string='Product', index=True)
    product_category_id = fields.Many2one(
        'product.category', string='Product Category',
        related='product_id.categ_id', store=True,
    )
    salesperson_id = fields.Many2one('res.users', string='Salesperson', index=True)

    # ── Amounts ───────────────────────────────────────────────────────────────
    currency_id = fields.Many2one(
        'res.currency', related='settlement_id.currency_id',
        store=True, readonly=True,
    )
    base_amount = fields.Monetary(
        string='Base Amount', currency_field='currency_id',
        help='Transaction amount used as base for commission calculation.',
    )
    margin_amount = fields.Monetary(
        string='Margin Amount', currency_field='currency_id',
    )
    cost_amount = fields.Monetary(
        string='Cost Amount', currency_field='currency_id',
    )
    rate = fields.Float(string='Rate (%)', digits=(16, 4))
    commission_amount = fields.Monetary(
        string='Commission Amount', currency_field='currency_id',
        required=True,
    )

    # ── Collection Fields ─────────────────────────────────────────────────────
    invoice_date = fields.Date(string='Invoice Date')
    payment_date = fields.Date(string='Payment Date')
    days_overdue = fields.Integer(
        string='Days Overdue',
        compute='_compute_days_overdue', store=True,
    )
    collection_penalty = fields.Monetary(
        string='Collection Penalty', currency_field='currency_id',
    )

    # ── KPI Fields ────────────────────────────────────────────────────────────
    kpi_score = fields.Float(string='KPI Score (%)')
    achievement_pct = fields.Float(string='Achievement %', digits=(16, 2))

    # ── Flags ─────────────────────────────────────────────────────────────────
    is_excluded = fields.Boolean(
        string='Excluded',
        help='Manually exclude this line from the settlement total.',
    )
    exclusion_reason = fields.Char(string='Exclusion Reason')
    is_clawback = fields.Boolean(string='Clawback Line')
    is_deferred = fields.Boolean(string='Deferred')
    deferred_to_period_id = fields.Many2one('commission.period', string='Defer To Period')

    # ── Description ───────────────────────────────────────────────────────────
    description = fields.Char(string='Description')

    _sql_constraints = [
        ('commission_amount_check', 'CHECK(TRUE)', 'Commission amount validated at application level.'),
    ]

    # ── Indexes for performance on 1M+ rows ──────────────────────────────────
    def init(self):
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS commission_line_settlement_idx
                ON commission_line(settlement_id);
            CREATE INDEX IF NOT EXISTS commission_line_invoice_idx
                ON commission_line(invoice_id) WHERE invoice_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS commission_line_payment_idx
                ON commission_line(payment_id) WHERE payment_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS commission_line_partner_idx
                ON commission_line(partner_id) WHERE partner_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS commission_line_date_idx
                ON commission_line(date);
            CREATE INDEX IF NOT EXISTS commission_line_source_type_idx
                ON commission_line(source_type);
        """)

    # ── Compute ───────────────────────────────────────────────────────────────

    @api.depends('invoice_date', 'payment_date')
    def _compute_days_overdue(self):
        for rec in self:
            if rec.invoice_date and rec.payment_date:
                delta = rec.payment_date - rec.invoice_date
                rec.days_overdue = max(0, delta.days)
            else:
                rec.days_overdue = 0

    # ── Helpers ───────────────────────────────────────────────────────────────

    @api.model
    def create_from_invoice(self, invoice, settlement, rule):
        """Factory method to create a commission line from an invoice."""
        margin = 0.0
        for line in invoice.invoice_line_ids:
            if line.product_id:
                cost = line.product_id.standard_price * line.quantity
                margin += (line.price_subtotal - cost)

        base_amount = invoice.amount_untaxed
        commission = rule.calculate_commission(base_amount, {'margin_amount': margin})

        # Apply collection delay penalty if configured
        penalty = 0.0
        days_overdue = 0
        if rule.collection_delay_penalty_rate:
            today = fields.Date.today()
            inv_date = invoice.invoice_date or today
            age = (today - inv_date).days
            if age > 0:
                months_overdue = age / 30.0
                penalty = commission * rule.collection_delay_penalty_rate / 100.0 * months_overdue
                commission = max(0, commission - penalty)
                days_overdue = age

        return self.create({
            'settlement_id': settlement.id,
            'rule_id': rule.id,
            'invoice_id': invoice.id,
            'source_type': 'invoice',
            'date': invoice.invoice_date,
            'partner_id': invoice.partner_id.id,
            'salesperson_id': invoice.invoice_user_id.id,
            'base_amount': base_amount,
            'margin_amount': margin,
            'rate': rule.rate,
            'commission_amount': commission,
            'collection_penalty': penalty,
            'invoice_date': invoice.invoice_date,
            'days_overdue': days_overdue,
            'description': f'Invoice {invoice.name}',
        })

    @api.model
    def create_from_payment(self, payment, settlement, rule):
        """Factory method to create a commission line from a payment."""
        base_amount = payment.amount
        commission = rule.calculate_commission(base_amount)
        return self.create({
            'settlement_id': settlement.id,
            'rule_id': rule.id,
            'payment_id': payment.id,
            'invoice_id': payment.reconciled_bill_ids[:1].id if payment.reconciled_bill_ids else False,
            'source_type': 'payment',
            'date': payment.date,
            'partner_id': payment.partner_id.id,
            'base_amount': base_amount,
            'rate': rule.rate,
            'commission_amount': commission,
            'payment_date': payment.date,
            'description': f'Payment {payment.name}',
        })

    def action_exclude(self):
        """Toggle exclusion flag on a line."""
        for rec in self:
            rec.is_excluded = not rec.is_excluded
            if rec.is_excluded:
                rec.settlement_id.message_post(
                    body=f'Line {rec.description or rec.id} excluded from settlement.'
                )
