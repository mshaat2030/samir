# -*- coding: utf-8 -*-
"""Wizard: Bulk recalculation of commission settlements."""

import logging
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WizardCommissionRecalculate(models.TransientModel):
    """Wizard to recalculate one or many settlements."""

    _name = 'wizard.commission.recalculate'
    _description = 'Recalculate Commission Settlements'

    # ── Scope ─────────────────────────────────────────────────────────────────
    recalculate_mode = fields.Selection([
        ('selected', 'Selected Settlements'),
        ('period', 'Entire Period'),
        ('employee', 'All Settlements for Employee'),
    ], string='Recalculate Mode', required=True, default='selected')

    settlement_ids = fields.Many2many(
        'commission.settlement', string='Settlements',
        domain=[('state', 'in', ('draft', 'calculated'))],
    )
    period_id = fields.Many2one(
        'commission.period', string='Period',
        domain=[('state', 'not in', ('locked',))],
    )
    employee_id = fields.Many2one('hr.employee', string='Employee')

    # ── Options ───────────────────────────────────────────────────────────────
    reason = fields.Text(string='Reason for Recalculation', required=True)
    reset_to_draft = fields.Boolean(
        string='Reset Submitted/Approved to Draft', default=False,
        help='If enabled, settlements in submitted/approved state will be reset to draft.',
    )

    # ── Preview ───────────────────────────────────────────────────────────────
    count = fields.Integer(compute='_compute_count', string='Settlements to Recalculate')

    @api.depends('recalculate_mode', 'settlement_ids', 'period_id', 'employee_id')
    def _compute_count(self):
        for rec in self:
            settlements = rec._get_target_settlements()
            rec.count = len(settlements)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_target_settlements(self):
        if self.recalculate_mode == 'selected':
            return self.settlement_ids
        if self.recalculate_mode == 'period' and self.period_id:
            domain = [('period_id', '=', self.period_id.id)]
            if not self.reset_to_draft:
                domain.append(('state', 'in', ('draft', 'calculated')))
            return self.env['commission.settlement'].search(domain)
        if self.recalculate_mode == 'employee' and self.employee_id:
            domain = [('employee_id', '=', self.employee_id.id)]
            if not self.reset_to_draft:
                domain.append(('state', 'in', ('draft', 'calculated')))
            return self.env['commission.settlement'].search(domain)
        return self.env['commission.settlement']

    # ── Action ────────────────────────────────────────────────────────────────

    def action_recalculate(self):
        """Execute recalculation on target settlements."""
        self.ensure_one()
        settlements = self._get_target_settlements()
        if not settlements:
            raise UserError('No settlements matched your selection.')

        protected_states = ('paid', 'payroll_processed', 'cancelled')
        if not self.reset_to_draft:
            protected_states = ('submitted', 'approved', 'finance_approved') + protected_states

        blocked = settlements.filtered(lambda s: s.state in protected_states)
        if blocked:
            raise UserError(
                f'Cannot recalculate {len(blocked)} settlement(s) in protected states: '
                + ', '.join(blocked.mapped('name'))
            )

        svc = self.env['commission.calculation.service']
        recalculated = 0

        for stl in settlements:
            try:
                if stl.state not in ('draft',):
                    stl.line_ids.unlink()
                    stl.write({'state': 'draft'})
                svc.calculate_settlement(stl)
                stl.message_post(body=f'Recalculated by {self.env.user.name}. Reason: {self.reason}')
                recalculated += 1
            except Exception as e:
                _logger.error('Recalculate failed for %s: %s', stl.name, e)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Recalculation Complete',
                'message': f'{recalculated} of {len(settlements)} settlement(s) recalculated.',
                'type': 'success',
            },
        }
