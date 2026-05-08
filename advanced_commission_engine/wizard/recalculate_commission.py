# -*- coding: utf-8 -*-
"""Wizard – Recalculate commissions in bulk."""

from odoo import api, fields, models
from odoo.exceptions import UserError


class WizardRecalculateCommission(models.TransientModel):
    """Bulk recalculation wizard for commission settlements.

    Allows managers to recalculate multiple settlements at once,
    optionally filtered by period, plan, or employees.
    """

    _name = 'wizard.recalculate.commission'
    _description = 'Recalculate Commission'

    period_id = fields.Many2one(
        'commission.period',
        string='Period',
        domain=[('state', '=', 'open')],
    )
    plan_id = fields.Many2one(
        'commission.plan',
        string='Commission Plan',
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        'wizard_recalc_emp_rel',
        'wizard_id',
        'employee_id',
        string='Employees',
        help='Leave empty to recalculate all settlements matching the above criteria.',
    )
    recalculate_states = fields.Many2many(
        'ir.model.fields.selection',
        string='Recalculate In States',
    )
    include_states = fields.Selection(
        [
            ('draft_only', 'Draft Only'),
            ('draft_calculated', 'Draft and Calculated'),
            ('all_open', 'All Open (not paid/cancelled)'),
        ],
        string='Include Settlements In',
        default='draft_calculated',
        required=True,
    )
    reason = fields.Text(
        string='Reason for Recalculation',
        required=True,
        default='Bulk recalculation.',
    )
    result_summary = fields.Text(
        string='Result',
        readonly=True,
    )

    def action_recalculate(self):
        """Recalculate all matching settlements."""
        self.ensure_one()
        if not self.env.user.has_group(
            'advanced_commission_engine.group_commission_manager'
        ):
            raise UserError('Only Commission Managers can trigger bulk recalculation.')

        domain = []
        if self.period_id:
            domain.append(('period_id', '=', self.period_id.id))
        if self.plan_id:
            domain.append(('plan_id', '=', self.plan_id.id))
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))

        state_map = {
            'draft_only': ('draft',),
            'draft_calculated': ('draft', 'calculated'),
            'all_open': ('draft', 'calculated', 'submitted'),
        }
        states = state_map.get(self.include_states, ('draft', 'calculated'))
        domain.append(('state', 'in', states))

        settlements = self.env['commission.settlement'].search(domain)
        if not settlements:
            raise UserError('No settlements found matching the criteria.')

        from ..services.calculation_service import CommissionCalculationService
        service = CommissionCalculationService(self.env)

        success = 0
        errors = []

        for settlement in settlements:
            try:
                service.calculate_settlement(settlement)
                settlement.write({
                    'state': 'calculated',
                    'calculation_date': fields.Datetime.now(),
                })
                settlement.message_post(
                    body=f'Recalculated by {self.env.user.name}. Reason: {self.reason}'
                )
                success += 1
            except Exception as e:
                errors.append(f'{settlement.name}: {e}')

        summary = f'Recalculated: {success} settlement(s).'
        if errors:
            summary += f'\nErrors ({len(errors)}):\n' + '\n'.join(errors[:10])
        self.result_summary = summary

        return {
            'type': 'ir.actions.act_window',
            'name': 'Recalculated Settlements',
            'res_model': 'commission.settlement',
            'view_mode': 'list,form',
            'domain': [('id', 'in', settlements.ids)],
        }
