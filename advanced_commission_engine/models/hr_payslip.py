# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
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

    @api.model
    def get_inputs(self, contract_ids, date_from, date_to):
        """Override to inject commission inputs into payslip."""
        res = super().get_inputs(contract_ids, date_from, date_to)
        commission_input_type = self.env.ref(
            'advanced_commission_engine.commission_payslip_input_type',
            raise_if_not_found=False,
        )
        if not commission_input_type:
            return res

        for contract in self.env['hr.contract'].browse(contract_ids):
            employee = contract.employee_id
            # Find approved settlements in the payslip period
            settlements = self.env['commission.settlement'].search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'approved'),
                ('settlement_method', '=', 'payroll'),
                ('payment_date', '>=', date_from),
                ('payment_date', '<=', date_to),
                ('payslip_id', '=', False),
            ])
            if settlements:
                commission_amount = sum(settlements.mapped('net_commission'))
                existing = next(
                    (r for r in res if r.get('code') == commission_input_type.code),
                    None,
                )
                if existing:
                    existing['amount'] += commission_amount
                else:
                    res.append({
                        'name': commission_input_type.name,
                        'code': commission_input_type.code,
                        'amount': commission_amount,
                        'contract_id': contract.id,
                        'input_type_id': commission_input_type.id,
                    })
        return res

    def action_payslip_done(self):
        res = super().action_payslip_done()
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
        return res
