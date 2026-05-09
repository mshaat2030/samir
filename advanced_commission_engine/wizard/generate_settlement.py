# -*- coding: utf-8 -*-
"""Wizard: Generate settlements for a period."""

import logging
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WizardCommissionGenerateSettlement(models.TransientModel):
    """Wizard to generate/recalculate settlements for a commission period."""

    _name = 'wizard.commission.generate.settlement'
    _description = 'Generate Commission Settlements'

    # ── Selection ─────────────────────────────────────────────────────────────
    period_id = fields.Many2one(
        'commission.period', string='Commission Period',
        required=True,
        default=lambda self: self.env['commission.period'].get_current_period(),
    )
    plan_ids = fields.Many2many(
        'commission.plan', string='Commission Plans',
        help='Leave empty to include all active plans for this period.',
    )
    employee_ids = fields.Many2many(
        'hr.employee', string='Employees',
        help='Leave empty to include all employees assigned to selected plans.',
    )

    # ── Options ───────────────────────────────────────────────────────────────
    recalculate_existing = fields.Boolean(
        string='Recalculate Existing Settlements', default=False,
        help='If enabled, existing draft/calculated settlements will be reset and recalculated.',
    )
    auto_submit = fields.Boolean(
        string='Auto-Submit After Calculation', default=False,
        help='Automatically submit calculated settlements for approval.',
    )
    send_notification = fields.Boolean(
        string='Notify Employees', default=True,
    )

    # ── Preview ───────────────────────────────────────────────────────────────
    employee_count = fields.Integer(compute='_compute_preview', string='Employees')
    plan_count = fields.Integer(compute='_compute_preview', string='Plans')
    estimated_settlements = fields.Integer(compute='_compute_preview', string='Estimated Settlements')

    # ── Compute ───────────────────────────────────────────────────────────────

    @api.depends('period_id', 'plan_ids', 'employee_ids')
    def _compute_preview(self):
        for rec in self:
            if not rec.period_id:
                rec.employee_count = 0
                rec.plan_count = 0
                rec.estimated_settlements = 0
                continue
            plans = rec.plan_ids or self.env['commission.plan'].search([
                ('active', '=', True),
                ('company_id', 'in', [rec.period_id.company_id.id, False]),
            ])
            employees = rec.employee_ids or self.env['hr.employee'].search([
                ('company_id', '=', rec.period_id.company_id.id),
                ('active', '=', True),
            ])
            rec.employee_count = len(employees)
            rec.plan_count = len(plans)
            rec.estimated_settlements = len(employees) * len(plans)

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('period_id')
    def _check_period_state(self):
        for rec in self:
            if rec.period_id.state == 'locked':
                raise UserError('Cannot generate settlements for a locked period.')

    # ── Action ────────────────────────────────────────────────────────────────

    def action_generate(self):
        """Execute settlement generation."""
        self.ensure_one()
        period = self.period_id
        if period.state == 'draft':
            period.action_open()

        plans = self.plan_ids or self.env['commission.plan'].search([
            ('active', '=', True),
            ('company_id', 'in', [period.company_id.id, False]),
        ])
        employees = self.employee_ids or self.env['hr.employee'].search([
            ('company_id', '=', period.company_id.id),
            ('active', '=', True),
        ])

        created = 0
        recalculated = 0
        svc = self.env['commission.calculation.service']

        for plan in plans:
            plan_employees = employees & plan.employee_ids if plan.employee_ids else employees
            for employee in plan_employees:
                existing = self.env['commission.settlement'].search([
                    ('employee_id', '=', employee.id),
                    ('period_id', '=', period.id),
                    ('plan_id', '=', plan.id),
                ], limit=1)

                if existing:
                    if self.recalculate_existing and existing.state in ('draft', 'calculated'):
                        existing.line_ids.unlink()
                        svc.calculate_settlement(existing)
                        recalculated += 1
                else:
                    stl = self.env['commission.settlement'].create({
                        'employee_id': employee.id,
                        'period_id': period.id,
                        'plan_id': plan.id,
                    })
                    svc.calculate_settlement(stl)
                    if self.auto_submit and stl.state == 'calculated':
                        stl.action_submit()
                    created += 1

        message = f'Generated {created} settlement(s). Recalculated {recalculated}.'
        _logger.info(message)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Settlements Generated',
                'message': message,
                'type': 'success',
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'commission.settlement',
                    'view_mode': 'list,kanban,form',
                    'domain': [('period_id', '=', period.id)],
                    'name': f'Settlements — {period.name}',
                },
            },
        }
