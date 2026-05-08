# -*- coding: utf-8 -*-
"""Wizard – Generate Commission Settlements for a period."""

import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WizardGenerateSettlement(models.TransientModel):
    """Wizard to batch-generate commission settlements for a period.

    Allows the manager to select a plan, period, and specific employees
    before running the calculation engine.
    """

    _name = 'wizard.generate.settlement'
    _description = 'Generate Commission Settlements'

    period_id = fields.Many2one(
        'commission.period',
        string='Period',
        required=True,
        domain=[('state', '=', 'open')],
    )
    plan_id = fields.Many2one(
        'commission.plan',
        string='Commission Plan',
        required=True,
        domain=[('state', '=', 'active')],
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        'wizard_gen_settlement_emp_rel',
        'wizard_id',
        'employee_id',
        string='Employees',
        help='Leave empty to generate for all eligible employees.',
    )
    only_new = fields.Boolean(
        string='Skip Existing Settlements',
        default=True,
        help='If checked, employees with existing settlements for this period/plan are skipped.',
    )
    auto_calculate = fields.Boolean(
        string='Auto-Calculate',
        default=True,
        help='Automatically calculate commission after creating settlements.',
    )
    result_summary = fields.Text(
        string='Result',
        readonly=True,
    )

    @api.onchange('plan_id')
    def _onchange_plan_id(self):
        if self.plan_id and self.plan_id.employee_ids:
            self.employee_ids = self.plan_id.employee_ids

    def action_generate(self):
        """Generate settlements and optionally calculate them."""
        self.ensure_one()

        if self.period_id.state != 'open':
            raise UserError('Cannot generate settlements for a locked/frozen period.')
        if self.plan_id.state != 'active':
            raise UserError('Commission plan must be Active.')

        employees = self.employee_ids or self._get_eligible_employees()
        if not employees:
            raise UserError('No eligible employees found for this plan.')

        created = 0
        calculated = 0
        skipped = 0
        errors = []

        from ..services.calculation_service import CommissionCalculationService
        service = CommissionCalculationService(self.env)

        for employee in employees:
            existing = self.env['commission.settlement'].search([
                ('employee_id', '=', employee.id),
                ('plan_id', '=', self.plan_id.id),
                ('period_id', '=', self.period_id.id),
            ], limit=1)

            if existing and self.only_new:
                skipped += 1
                continue

            if not existing:
                settlement = self.env['commission.settlement'].create({
                    'employee_id': employee.id,
                    'plan_id': self.plan_id.id,
                    'period_id': self.period_id.id,
                    'company_id': self.company_id.id,
                })
                created += 1
            else:
                settlement = existing

            if self.auto_calculate:
                try:
                    service.calculate_settlement(settlement)
                    settlement.write({
                        'state': 'calculated',
                        'calculation_date': fields.Datetime.now(),
                    })
                    calculated += 1
                except Exception as e:
                    errors.append(f'{employee.name}: {e}')
                    _logger.error('Error calculating for %s: %s', employee.name, e)

        summary_parts = [
            f'Created: {created}',
            f'Calculated: {calculated}',
            f'Skipped: {skipped}',
        ]
        if errors:
            summary_parts.append(f'Errors: {len(errors)}')
            summary_parts.extend(errors[:5])

        self.result_summary = '\n'.join(summary_parts)

        return {
            'type': 'ir.actions.act_window',
            'name': 'Generated Settlements',
            'res_model': 'commission.settlement',
            'view_mode': 'list,form',
            'domain': [
                ('period_id', '=', self.period_id.id),
                ('plan_id', '=', self.plan_id.id),
            ],
        }

    def _get_eligible_employees(self):
        """Get all eligible employees for the plan."""
        plan = self.plan_id
        if plan.employee_ids:
            return plan.employee_ids
        domain = [
            ('active', '=', True),
            ('company_id', '=', self.company_id.id),
        ]
        if plan.department_ids:
            domain.append(('department_id', 'in', plan.department_ids.ids))
        if plan.job_ids:
            domain.append(('job_id', 'in', plan.job_ids.ids))
        return self.env['hr.employee'].search(domain)
