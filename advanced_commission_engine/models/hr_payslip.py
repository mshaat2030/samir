# -*- coding: utf-8 -*-
from odoo import models, fields, api, Command, _
import logging

_logger = logging.getLogger(__name__)


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    commission_settlement_ids = fields.One2many(
        'commission.settlement',
        'payslip_id',
        string='Commission Settlements',
    )
    commission_total = fields.Monetary(
        string='Commission Total',
        compute='_compute_commission_total',
        currency_field='currency_id',
    )

    def _compute_commission_total(self):
        for slip in self:
            settlements = slip.commission_settlement_ids.filtered(
                lambda s: s.state == 'approved'
            )
            slip.commission_total = sum(settlements.mapped('net_commission'))

    @api.depends('employee_id', 'date_from', 'date_to', 'struct_id')
    def _compute_input_line_ids(self):
        """Override to inject approved commission settlement inputs into payslips."""
        super()._compute_input_line_ids()

        commission_input_type = self.env.ref(
            'advanced_commission_engine.commission_payslip_input_type',
            raise_if_not_found=False,
        )
        if not commission_input_type:
            return

        for slip in self:
            if not slip.employee_id or not slip.date_from or not slip.date_to:
                continue

            # Find approved commission settlements for this employee in the payslip period
            settlements = self.env['commission.settlement'].search([
                ('employee_id', '=', slip.employee_id.id),
                ('state', '=', 'approved'),
                ('settlement_method', '=', 'payroll'),
                ('payslip_id', '=', False),
            ])
            if not settlements:
                continue

            commission_amount = sum(settlements.mapped('net_commission'))

            # Check if a commission input line already exists
            existing = slip.input_line_ids.filtered(
                lambda l: l.input_type_id == commission_input_type
            )
            if existing:
                slip.update({
                    'input_line_ids': [Command.update(existing[0].id, {'amount': commission_amount})]
                })
            else:
                slip.update({
                    'input_line_ids': [Command.create({
                        'name': commission_input_type.name,
                        'amount': commission_amount,
                        'input_type_id': commission_input_type.id,
                    })]
                })

    def action_payslip_done(self):
        super().action_payslip_done()
        for slip in self:
            settlements = self.env['commission.settlement'].search([
                ('employee_id', '=', slip.employee_id.id),
                ('state', '=', 'approved'),
                ('settlement_method', '=', 'payroll'),
                ('payslip_id', '=', False),
            ])
            settlements.write({
                'payslip_id': slip.id,
                'state': 'paid',
                'payment_date': slip.date_to,
            })
            for s in settlements:
                s.line_ids.write({'state': 'paid'})
