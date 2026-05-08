# -*- coding: utf-8 -*-
"""Commission Line – individual earning record linked to a source document."""

from odoo import api, fields, models
from odoo.exceptions import UserError


class CommissionLine(models.Model):
    """Each commission line represents a single earning event – e.g., one invoice
    or one sale order – and stores the base amount, rate, and calculated commission.

    Lines are linked to a settlement and may reference source documents
    (sale.order, account.move, pos.order, project.task, etc.).
    """

    _name = 'commission.line'
    _description = 'Commission Line'
    _order = 'settlement_id, date desc, id'
    _check_company_auto = True

    # ── Identity ──────────────────────────────────────────────────────────────
    settlement_id = fields.Many2one(
        'commission.settlement',
        string='Settlement',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(
        related='settlement_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    currency_id = fields.Many2one(
        related='settlement_id.currency_id',
        store=True,
        readonly=True,
    )
    employee_id = fields.Many2one(
        related='settlement_id.employee_id',
        store=True,
        readonly=True,
        index=True,
    )
    plan_id = fields.Many2one(
        related='settlement_id.plan_id',
        store=True,
        readonly=True,
        index=True,
    )
    period_id = fields.Many2one(
        related='settlement_id.period_id',
        store=True,
        readonly=True,
        index=True,
    )
    rule_id = fields.Many2one(
        'commission.rule',
        string='Applied Rule',
        index=True,
    )

    # ── Source Document References ────────────────────────────────────────────
    source_type = fields.Selection(
        [
            ('sale_order', 'Sales Order'),
            ('invoice', 'Invoice'),
            ('payment', 'Payment'),
            ('pos_order', 'POS Order'),
            ('project_task', 'Project Task'),
            ('subscription', 'Subscription'),
            ('crm_lead', 'CRM Lead'),
            ('manual', 'Manual'),
        ],
        string='Source Type',
        required=True,
        default='invoice',
        index=True,
    )
    # Generic reference field (model+id)
    res_model = fields.Char(string='Source Model', index=True)
    res_id = fields.Integer(string='Source ID', index=True)
    res_name = fields.Char(
        string='Source Document',
        compute='_compute_res_name',
        store=True,
    )

    # Specific FK references for fast joins
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sales Order',
        index=True,
        ondelete='set null',
    )
    invoice_id = fields.Many2one(
        'account.move',
        string='Invoice',
        index=True,
        ondelete='set null',
    )
    project_task_id = fields.Many2one(
        'project.task',
        string='Project Task',
        index=True,
        ondelete='set null',
    )
    crm_lead_id = fields.Many2one(
        'crm.lead',
        string='CRM Lead',
        index=True,
        ondelete='set null',
    )

    # ── Amounts ───────────────────────────────────────────────────────────────
    date = fields.Date(
        string='Transaction Date',
        required=True,
        default=fields.Date.today,
        index=True,
    )
    base_amount = fields.Monetary(
        string='Base Amount',
        currency_field='currency_id',
        required=True,
        default=0.0,
    )
    commission_rate = fields.Float(
        string='Rate (%)',
        digits=(16, 4),
        default=0.0,
    )
    commission_amount = fields.Monetary(
        string='Commission Amount',
        currency_field='currency_id',
        required=True,
        default=0.0,
    )

    # ── Additional financial data ─────────────────────────────────────────────
    margin_amount = fields.Monetary(
        string='Margin Amount',
        currency_field='currency_id',
        default=0.0,
    )
    margin_pct = fields.Float(
        string='Margin %',
        digits=(16, 2),
        default=0.0,
    )
    cost_amount = fields.Monetary(
        string='Cost Amount',
        currency_field='currency_id',
        default=0.0,
    )

    # ── Payment / Collection ──────────────────────────────────────────────────
    invoice_date = fields.Date(
        string='Invoice Date',
        index=True,
    )
    payment_date = fields.Date(
        string='Payment Date',
        index=True,
    )
    payment_delay_days = fields.Integer(
        string='Payment Delay (Days)',
        compute='_compute_payment_delay',
        store=True,
    )
    delay_penalty_amount = fields.Monetary(
        string='Delay Penalty',
        currency_field='currency_id',
        default=0.0,
    )

    # ── Product / Partner ─────────────────────────────────────────────────────
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        index=True,
    )
    salesperson_id = fields.Many2one(
        'res.users',
        string='Salesperson',
        index=True,
    )

    # ── State ─────────────────────────────────────────────────────────────────
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('cancelled', 'Cancelled'),
        ],
        string='State',
        default='draft',
        index=True,
    )
    notes = fields.Text(string='Notes')

    # ── Computes ──────────────────────────────────────────────────────────────
    @api.depends('res_model', 'res_id')
    def _compute_res_name(self):
        for line in self:
            if line.res_model and line.res_id:
                try:
                    record = self.env[line.res_model].browse(line.res_id)
                    line.res_name = record.display_name if record.exists() else '/'
                except Exception:
                    line.res_name = f'{line.res_model},{line.res_id}'
            else:
                line.res_name = '/'

    @api.depends('invoice_date', 'payment_date')
    def _compute_payment_delay(self):
        for line in self:
            if line.invoice_date and line.payment_date:
                delta = (line.payment_date - line.invoice_date).days
                line.payment_delay_days = max(0, delta)
            else:
                line.payment_delay_days = 0

    # ── ORM ───────────────────────────────────────────────────────────────────
    def unlink(self):
        for line in self:
            if line.settlement_id.state not in ('draft', 'calculated', 'cancelled'):
                raise UserError(
                    'Cannot delete commission lines from a submitted or approved settlement.'
                )
        return super().unlink()

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})
