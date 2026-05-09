# -*- coding: utf-8 -*-
"""Commission Adjustment — manual and automatic modifications to a settlement."""

import logging
from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)

ADJUSTMENT_TYPES = [
    ('bonus', 'Bonus'),
    ('penalty', 'Penalty'),
    ('clawback', 'Clawback'),
    ('correction', 'Correction'),
    ('negative', 'Negative Adjustment'),
    ('deferred', 'Deferred Payout'),
    ('hold', 'Payment Hold'),
    ('advance', 'Advance'),
    ('split', 'Split Payout'),
    ('other', 'Other'),
]

ADJUSTMENT_STATES = [
    ('draft', 'Draft'),
    ('confirmed', 'Confirmed'),
    ('applied', 'Applied'),
    ('cancelled', 'Cancelled'),
]


class CommissionAdjustment(models.Model):
    """Manual or system adjustment applied to a commission settlement."""

    _name = 'commission.adjustment'
    _description = 'Commission Adjustment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'settlement_id, date desc'

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Reference', required=True, copy=False,
        default=lambda self: self.env['ir.sequence'].next_by_code('commission.adjustment'),
    )
    settlement_id = fields.Many2one(
        'commission.settlement', string='Settlement',
        required=True, ondelete='cascade', index=True,
    )
    currency_id = fields.Many2one(
        'res.currency', related='settlement_id.currency_id',
        store=True, readonly=True,
    )

    # ── Type & Amount ─────────────────────────────────────────────────────────
    adjustment_type = fields.Selection(
        ADJUSTMENT_TYPES, string='Adjustment Type',
        required=True, tracking=True, default='correction',
    )
    amount = fields.Monetary(
        string='Amount', currency_field='currency_id',
        required=True, tracking=True,
        help='Positive = increase. Negative = decrease.',
    )
    date = fields.Date(
        string='Effective Date', required=True,
        default=fields.Date.today, tracking=True,
    )
    state = fields.Selection(
        ADJUSTMENT_STATES, string='Status',
        default='draft', tracking=True,
    )

    # ── Clawback Specifics ────────────────────────────────────────────────────
    clawback_source_settlement_id = fields.Many2one(
        'commission.settlement', string='Original Settlement (Clawback)',
        help='The previously paid settlement being clawed back.',
    )
    clawback_reason = fields.Selection([
        ('customer_default', 'Customer Default / Bad Debt'),
        ('credit_note', 'Credit Note / Return'),
        ('contract_cancellation', 'Contract Cancellation'),
        ('fraud', 'Fraud / Policy Violation'),
        ('other', 'Other'),
    ], string='Clawback Reason')

    # ── Hold Specifics ────────────────────────────────────────────────────────
    hold_until = fields.Date(string='Hold Until', tracking=True)

    # ── Deferred Specifics ────────────────────────────────────────────────────
    defer_to_period_id = fields.Many2one(
        'commission.period', string='Defer To Period',
        help='Period in which the deferred amount will be released.',
    )
    is_released = fields.Boolean(string='Released', readonly=True)

    # ── Approval ──────────────────────────────────────────────────────────────
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True)
    approved_at = fields.Datetime(string='Approved At', readonly=True)

    # ── Reason & Evidence ─────────────────────────────────────────────────────
    reason = fields.Text(string='Reason / Justification', required=True, tracking=True)
    attachment_ids = fields.Many2many(
        'ir.attachment', 'commission_adjustment_attachment_rel',
        'adjustment_id', 'attachment_id',
        string='Supporting Documents',
    )

    _sql_constraints = [
        ('amount_nonzero', 'CHECK(amount != 0)', 'Adjustment amount cannot be zero.'),
    ]

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('hold_until', 'adjustment_type')
    def _check_hold_date(self):
        for rec in self:
            if rec.adjustment_type == 'hold' and not rec.hold_until:
                raise ValidationError('A hold date is required for Payment Hold adjustments.')

    @api.constrains('defer_to_period_id', 'adjustment_type')
    def _check_defer_period(self):
        for rec in self:
            if rec.adjustment_type == 'deferred' and not rec.defer_to_period_id:
                raise ValidationError('A target period is required for Deferred Payout adjustments.')

    # ── State Transitions ─────────────────────────────────────────────────────

    def action_confirm(self):
        """Confirm adjustment, requiring finance manager for large amounts."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError('Only draft adjustments can be confirmed.')
            if abs(rec.amount) > 10000 and not self.env.user.has_group(
                'advanced_commission_engine.group_commission_finance_manager'
            ):
                raise UserError('Adjustments over 10,000 require finance manager approval.')
            rec.write({
                'state': 'confirmed',
                'approved_by': self.env.user.id,
                'approved_at': fields.Datetime.now(),
            })
            rec.message_post(body=f'Adjustment confirmed by {self.env.user.name}.')

    def action_apply(self):
        """Apply the adjustment to the settlement (auto-triggers amount recompute)."""
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError('Only confirmed adjustments can be applied.')
            if rec.settlement_id.state in ('paid', 'cancelled'):
                raise UserError('Cannot apply adjustment to a paid or cancelled settlement.')
            rec.write({'state': 'applied'})
            # Recompute settlement totals (triggered via computed fields on line_ids change)
            rec.settlement_id._compute_amounts()
            rec.message_post(
                body=f'Adjustment applied: {rec.adjustment_type} {rec.currency_id.symbol}{rec.amount:,.2f}'
            )

    def action_cancel(self):
        """Cancel an adjustment."""
        for rec in self:
            if rec.state == 'applied':
                raise UserError('Applied adjustments cannot be cancelled directly. Create a reversal.')
            rec.write({'state': 'cancelled'})
            rec.message_post(body='Adjustment cancelled.')

    def action_create_reversal(self):
        """Create an equal and opposite adjustment to reverse this one."""
        self.ensure_one()
        reversal = self.copy({
            'amount': -self.amount,
            'reason': f'Reversal of {self.name}: {self.reason}',
            'state': 'draft',
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'commission.adjustment',
            'view_mode': 'form',
            'res_id': reversal.id,
        }

    # ── Cron ──────────────────────────────────────────────────────────────────

    @api.model
    def cron_process_clawbacks(self):
        """Check for bad-debt invoices and auto-create clawback adjustments."""
        # Find settled commissions where invoice is now credit-noted or unpaid >180 days
        today = fields.Date.today()
        invoices_in_default = self.env['account.move'].search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('invoice_date', '<=', fields.Date.from_string(str(today)[:7] + '-01'),),
        ])
        for invoice in invoices_in_default:
            age = (today - invoice.invoice_date).days
            if age < 180:
                continue
            # Find related commission lines
            lines = self.env['commission.line'].search([
                ('invoice_id', '=', invoice.id),
                ('is_clawback', '=', False),
            ])
            for line in lines:
                settlement = line.settlement_id
                if settlement.state != 'paid':
                    continue
                if not settlement.plan_id.enable_clawback:
                    continue
                # Check clawback window
                clawback_months = settlement.plan_id.clawback_period_months
                if settlement.payment_date:
                    months_since_payment = (today - settlement.payment_date).days / 30
                    if months_since_payment > clawback_months:
                        continue
                existing = self.search([
                    ('settlement_id', '=', settlement.id),
                    ('adjustment_type', '=', 'clawback'),
                    ('clawback_source_settlement_id', '=', settlement.id),
                ], limit=1)
                if existing:
                    continue
                self.create({
                    'settlement_id': settlement.id,
                    'adjustment_type': 'clawback',
                    'amount': -line.commission_amount,
                    'date': today,
                    'clawback_source_settlement_id': settlement.id,
                    'clawback_reason': 'customer_default',
                    'reason': f'Auto-clawback: invoice {invoice.name} unpaid {age} days.',
                    'state': 'draft',
                })
                _logger.info('Auto-clawback created for settlement %s', settlement.name)
