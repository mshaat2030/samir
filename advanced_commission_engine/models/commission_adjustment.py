# -*- coding: utf-8 -*-
"""Commission Adjustment – manual additions, deductions, clawbacks, holds."""

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class CommissionAdjustment(models.Model):
    """Manual adjustment to a commission settlement.

    Types: bonus (positive), manual (positive/negative), penalty (negative),
    clawback (negative – recovers a previously paid amount), hold, deferred.
    """

    _name = 'commission.adjustment'
    _description = 'Commission Adjustment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'settlement_id, date desc'

    name = fields.Char(
        string='Description',
        required=True,
        tracking=True,
    )
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
        readonly=True,
    )
    employee_id = fields.Many2one(
        related='settlement_id.employee_id',
        store=True,
        readonly=True,
        index=True,
    )

    adjustment_type = fields.Selection(
        [
            ('bonus', 'Bonus'),
            ('manual', 'Manual Adjustment'),
            ('penalty', 'Penalty'),
            ('clawback', 'Clawback'),
            ('hold', 'Hold'),
            ('deferred', 'Deferred Payout'),
        ],
        string='Type',
        required=True,
        default='manual',
        tracking=True,
        index=True,
    )
    amount = fields.Monetary(
        string='Amount',
        currency_field='currency_id',
        required=True,
        tracking=True,
    )
    date = fields.Date(
        string='Date',
        default=fields.Date.today,
        required=True,
        index=True,
    )
    reason = fields.Text(
        string='Reason / Justification',
        required=True,
    )
    reference = fields.Char(
        string='Reference',
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('approved', 'Approved'),
            ('cancelled', 'Cancelled'),
        ],
        default='draft',
        tracking=True,
    )
    approved_by_id = fields.Many2one(
        'res.users',
        string='Approved By',
        readonly=True,
    )
    approved_date = fields.Date(
        string='Approved On',
        readonly=True,
    )

    # ── Clawback reference ────────────────────────────────────────────────────
    original_settlement_id = fields.Many2one(
        'commission.settlement',
        string='Original Settlement (for clawback)',
    )

    # ── Hold/Defer details ────────────────────────────────────────────────────
    release_date = fields.Date(
        string='Release Date',
        help='For held/deferred amounts: when should this be released?',
    )


    _amount_positive = models.Constraint(
        'CHECK(amount >= 0)',
        'Adjustment amount must be non-negative.',
    )


    @api.constrains('settlement_id', 'adjustment_type')
    def _check_settlement_state(self):
        for adj in self:
            if adj.settlement_id.state in ('paid', 'cancelled'):
                raise ValidationError(
                    'Cannot add adjustments to a paid or cancelled settlement.'
                )

    def action_approve(self):
        if not self.env.user.has_group(
            'advanced_commission_engine.group_commission_finance_manager'
        ):
            raise UserError('Only Finance Managers can approve adjustments.')
        for adj in self:
            if adj.state != 'draft':
                raise UserError(f"Adjustment '{adj.name}' is not in draft state.")
            adj.write({
                'state': 'approved',
                'approved_by_id': self.env.uid,
                'approved_date': fields.Date.today(),
            })

    def action_cancel(self):
        for adj in self:
            if adj.state == 'approved':
                if not self.env.user.has_group(
                    'advanced_commission_engine.group_commission_finance_manager'
                ):
                    raise UserError('Only Finance Managers can cancel approved adjustments.')
            adj.write({'state': 'cancelled'})
