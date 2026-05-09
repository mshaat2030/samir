# -*- coding: utf-8 -*-
"""Wizard: Rollback a paid settlement and create reversal entries."""

import logging
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WizardCommissionRollback(models.TransientModel):
    """Rollback wizard for paid settlements — creates clawback adjustments."""

    _name = 'wizard.commission.rollback'
    _description = 'Commission Rollback Wizard'

    settlement_id = fields.Many2one(
        'commission.settlement', string='Settlement to Rollback',
        required=True,
        domain=[('state', '=', 'paid')],
    )
    rollback_reason = fields.Selection([
        ('data_error', 'Data / Calculation Error'),
        ('policy_change', 'Policy Change'),
        ('clawback', 'Customer Default / Clawback'),
        ('audit_finding', 'Audit Finding'),
        ('other', 'Other'),
    ], string='Rollback Reason', required=True)
    notes = fields.Text(string='Detailed Notes', required=True)
    create_accounting_reversal = fields.Boolean(
        string='Create Accounting Reversal', default=True,
    )
    create_payroll_reversal = fields.Boolean(
        string='Create Payroll Reversal / Deduction', default=False,
    )

    # ── Computed ──────────────────────────────────────────────────────────────
    paid_amount = fields.Monetary(
        related='settlement_id.total_commission',
        currency_field='currency_id',
        string='Amount Paid',
    )
    currency_id = fields.Many2one(
        related='settlement_id.currency_id', readonly=True,
    )

    # ── Action ────────────────────────────────────────────────────────────────

    def action_rollback(self):
        """Execute the rollback."""
        self.ensure_one()
        settlement = self.settlement_id

        if settlement.state != 'paid':
            raise UserError('Only paid settlements can be rolled back.')
        if not self.env.user.has_group('advanced_commission_engine.group_commission_finance_manager'):
            raise UserError('Only finance managers can perform rollbacks.')

        # 1. Create clawback adjustment
        adj = self.env['commission.adjustment'].create({
            'settlement_id': settlement.id,
            'adjustment_type': 'clawback',
            'amount': -settlement.total_commission,
            'date': fields.Date.today(),
            'reason': f'Rollback ({self.rollback_reason}): {self.notes}',
            'clawback_source_settlement_id': settlement.id,
            'clawback_reason': 'other' if self.rollback_reason == 'other' else 'customer_default',
            'state': 'confirmed',
        })
        adj.action_apply()

        # 2. Accounting reversal
        if self.create_accounting_reversal and settlement.move_id:
            reversal_wizard = self.env['account.move.reversal'].create({
                'move_ids': [(4, settlement.move_id.id)],
                'reason': f'Commission rollback: {self.notes}',
                'journal_id': settlement.plan_id.journal_id.id,
            })
            reversal_result = reversal_wizard.reverse_moves()
            _logger.info('Accounting reversal created for %s', settlement.name)

        # 3. Reset settlement state
        settlement.write({'state': 'calculated'})
        settlement.message_post(
            body=f'Settlement rolled back by {self.env.user.name}. '
                 f'Reason: {self.rollback_reason} — {self.notes}'
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Rollback Complete',
                'message': f'Settlement {settlement.name} has been rolled back.',
                'type': 'warning',
            },
        }
