# -*- coding: utf-8 -*-
"""Wizard – Rollback a commission settlement."""

from odoo import api, fields, models
from odoo.exceptions import UserError


class WizardRollbackCommission(models.TransientModel):
    """Rollback engine for commission settlements.

    Allows administrators to safely roll back a settlement to draft
    and optionally create a clawback adjustment for previously paid amounts.
    """

    _name = 'wizard.rollback.commission'
    _description = 'Rollback Commission Settlement'

    settlement_id = fields.Many2one(
        'commission.settlement',
        string='Settlement',
        required=True,
    )
    reason = fields.Text(
        string='Rollback Reason',
        required=True,
    )
    rollback_type = fields.Selection(
        [
            ('recalculate', 'Reset and Recalculate'),
            ('cancel', 'Cancel Settlement'),
            ('clawback', 'Create Clawback (if previously paid)'),
        ],
        string='Rollback Action',
        required=True,
        default='recalculate',
    )
    clawback_amount = fields.Monetary(
        string='Clawback Amount',
        currency_field='currency_id',
        compute='_compute_clawback_amount',
        store=True,
        readonly=False,
    )
    currency_id = fields.Many2one(
        related='settlement_id.currency_id',
        readonly=True,
    )
    new_settlement_id = fields.Many2one(
        'commission.settlement',
        string='Target Settlement for Clawback',
        help='Settlement where the clawback adjustment will be applied.',
    )

    @api.depends('settlement_id')
    def _compute_clawback_amount(self):
        for wizard in self:
            wizard.clawback_amount = wizard.settlement_id.final_amount if wizard.settlement_id else 0.0

    def action_rollback(self):
        """Execute the rollback."""
        self.ensure_one()
        if not self.env.user.has_group(
            'advanced_commission_engine.group_commission_admin'
        ):
            raise UserError('Only Commission Administrators can rollback settlements.')

        settlement = self.settlement_id
        action = self.rollback_type

        if action == 'recalculate':
            if settlement.state not in (
                'draft', 'calculated', 'submitted', 'approved', 'disputed', 'cancelled'
            ):
                raise UserError(
                    f"Cannot recalculate a settlement in '{settlement.state}' state."
                )
            settlement.line_ids.filtered(lambda l: l.state != 'cancelled').unlink()
            settlement.write({
                'state': 'draft',
                'calculation_date': False,
                'approved_by_id': False,
                'finance_approved_by_id': False,
            })
            settlement.message_post(
                body=f'Settlement rolled back to Draft by {self.env.user.name}. '
                     f'Reason: {self.reason}'
            )

        elif action == 'cancel':
            if settlement.state == 'paid':
                raise UserError('Cannot cancel a paid settlement. Use Clawback instead.')
            settlement.write({
                'state': 'cancelled',
                'cancellation_reason': self.reason,
            })
            settlement.message_post(
                body=f'Settlement cancelled by {self.env.user.name}. Reason: {self.reason}'
            )

        elif action == 'clawback':
            if settlement.state != 'paid':
                raise UserError('Clawback can only be applied to paid settlements.')

            target = self.new_settlement_id
            if not target:
                raise UserError('Please select a target settlement for the clawback.')

            clawback = self.env['commission.adjustment'].create({
                'name': f'Clawback from {settlement.name}',
                'settlement_id': target.id,
                'adjustment_type': 'clawback',
                'amount': self.clawback_amount,
                'reason': self.reason,
                'original_settlement_id': settlement.id,
                'state': 'approved',
                'approved_by_id': self.env.uid,
                'approved_date': fields.Date.today(),
            })
            settlement.message_post(
                body=f'Clawback of {self.clawback_amount} created on {target.name}. '
                     f'By {self.env.user.name}. Reason: {self.reason}'
            )
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'commission.adjustment',
                'res_id': clawback.id,
                'view_mode': 'form',
            }

        return {'type': 'ir.actions.act_window_close'}
