# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class CommissionLine(models.Model):
    _name = 'commission.line'
    _description = 'Commission Line'
    _inherit = ['mail.thread', 'commission.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Description', required=True)
    settlement_id = fields.Many2one(
        'commission.settlement', string='Settlement',
        ondelete='cascade', index=True,
    )
    period_id = fields.Many2one(
        'commission.period', string='Period',
        index=True, required=True,
    )
    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan',
        required=True, index=True,
    )
    rule_id = fields.Many2one(
        'commission.rule', string='Applied Rule',
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, index=True,
    )
    date = fields.Date(string='Date', required=True, default=fields.Date.today)

    # ── Source ────────────────────────────────────────────────────────────────
    line_type = fields.Selection([
        ('commission', 'Commission'),
        ('adjustment', 'Adjustment'),
        ('clawback', 'Clawback'),
        ('bonus', 'Bonus'),
        ('deduction', 'Deduction'),
        ('advance', 'Advance'),
    ], string='Type', required=True, default='commission', index=True)

    source_type = fields.Selection([
        ('sale_order', 'Sale Order'),
        ('invoice', 'Invoice'),
        ('payment', 'Payment'),
        ('subscription', 'Subscription'),
        ('project', 'Project Milestone'),
        ('pos', 'POS Order'),
        ('manual', 'Manual'),
    ], string='Source', default='invoice')

    sale_order_id = fields.Many2one('sale.order', string='Sale Order', index=True)
    invoice_id = fields.Many2one('account.move', string='Invoice', index=True)
    payment_id = fields.Many2one('account.payment', string='Payment', index=True)

    # ── Amounts ───────────────────────────────────────────────────────────────
    base_amount = fields.Monetary(
        string='Base Amount',
        currency_field='currency_id',
    )
    original_currency_id = fields.Many2one(
        'res.currency', string='Original Currency'
    )
    original_amount = fields.Monetary(
        string='Original Amount',
        currency_field='original_currency_id',
    )
    rate = fields.Float(string='Rate (%)', digits=(5, 4))
    commission_amount = fields.Monetary(
        string='Commission Amount',
        currency_field='currency_id',
        tracking=True,
    )
    margin_amount = fields.Monetary(
        string='Margin Amount',
        currency_field='currency_id',
    )
    margin_percent = fields.Float(string='Margin %', digits=(5, 2))

    # ── Status ────────────────────────────────────────────────────────────────
    state = fields.Selection([
        ('draft', 'Draft'),
        ('validated', 'Validated'),
        ('disputed', 'Disputed'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, index=True)

    # ── Split ─────────────────────────────────────────────────────────────────
    is_split = fields.Boolean(string='Split Commission')
    split_percent = fields.Float(
        string='Split %', default=100.0, digits=(5, 2)
    )
    parent_line_id = fields.Many2one(
        'commission.line', string='Parent Line',
        ondelete='cascade',
    )
    split_line_ids = fields.One2many(
        'commission.line', 'parent_line_id', string='Split Lines'
    )

    # ── Clawback ──────────────────────────────────────────────────────────────
    is_clawback = fields.Boolean(string='Is Clawback')
    clawback_reason = fields.Text(string='Clawback Reason')
    original_line_id = fields.Many2one(
        'commission.line', string='Original Line',
        help='The original commission line that this clawback reverses',
    )

    # ── Deferred ─────────────────────────────────────────────────────────────
    is_deferred = fields.Boolean(string='Deferred')
    deferred_until = fields.Date(string='Deferred Until')

    # ── Notes ─────────────────────────────────────────────────────────────────
    note = fields.Text(string='Notes')

    # ── Validation ────────────────────────────────────────────────────────────
    @api.constrains('split_percent')
    def _check_split_percent(self):
        for line in self:
            if line.is_split and not (0 < line.split_percent <= 100):
                raise ValidationError(
                    _('Split percentage must be between 0 and 100.')
                )

    @api.constrains('commission_amount')
    def _check_commission_amount(self):
        for line in self:
            if line.line_type == 'commission' and line.commission_amount < 0:
                raise ValidationError(
                    _('Commission amount cannot be negative for line: %s') % line.name
                )

    # ── Onchange ──────────────────────────────────────────────────────────────
    @api.onchange('base_amount', 'rate')
    def _onchange_base_amount(self):
        if self.base_amount and self.rate:
            self.commission_amount = self.base_amount * self.rate / 100.0

    @api.onchange('invoice_id')
    def _onchange_invoice(self):
        if self.invoice_id:
            self.base_amount = self.invoice_id.amount_untaxed
            self.original_currency_id = self.invoice_id.currency_id
            self.original_amount = self.invoice_id.amount_untaxed

    # ── Business Logic ────────────────────────────────────────────────────────
    def action_validate(self):
        for line in self:
            if line.state not in ('draft',):
                raise UserError(_('Only draft lines can be validated.'))
            line.write({'state': 'validated'})

    def action_cancel(self):
        for line in self:
            if line.state == 'paid':
                raise UserError(_('Paid commission lines cannot be cancelled.'))
            line.write({'state': 'cancelled'})

    def action_dispute(self):
        """Create a dispute for this line."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Dispute'),
            'res_model': 'commission.dispute',
            'view_mode': 'form',
            'context': {
                'default_line_id': self.id,
                'default_employee_id': self.employee_id.id,
                'default_settlement_id': self.settlement_id.id,
            },
            'target': 'new',
        }

    def action_create_clawback(self):
        """Create a clawback line reversing this commission."""
        self.ensure_one()
        if not self.plan_id.has_clawback:
            raise UserError(
                _('Plan "%s" does not have clawback enabled.') % self.plan_id.name
            )
        clawback = self.copy({
            'name': _('Clawback: %s') % self.name,
            'line_type': 'clawback',
            'commission_amount': -self.commission_amount,
            'is_clawback': True,
            'original_line_id': self.id,
            'state': 'draft',
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'commission.line',
            'res_id': clawback.id,
            'view_mode': 'form',
        }

    def create_split_lines(self, splits):
        """
        Create split commission lines.
        splits: list of dicts with employee_id and percent keys.
        """
        self.ensure_one()
        total_percent = sum(s['percent'] for s in splits)
        if abs(total_percent - 100.0) > 0.01:
            raise UserError(_('Split percentages must sum to 100%.'))
        created = self.env['commission.line']
        for split in splits:
            created |= self.copy({
                'name': _('%s (Split)') % self.name,
                'employee_id': split['employee_id'],
                'commission_amount': self.commission_amount * split['percent'] / 100.0,
                'split_percent': split['percent'],
                'is_split': True,
                'parent_line_id': self.id,
                'state': 'draft',
            })
        return created
