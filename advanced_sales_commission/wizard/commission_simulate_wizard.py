# -*- coding: utf-8 -*-
"""Simulate commission calculation without persisting."""
from odoo import models, fields, api, _


class AscCommissionSimulateWizard(models.TransientModel):
    _name = 'asc.commission.simulate.wizard'
    _description = 'Commission Simulation Wizard'

    simulation_type = fields.Selection([
        ('order', 'Sale Order'),
        ('invoice', 'Invoice'),
        ('manual', 'Manual Amount'),
    ], string='Simulate On', required=True, default='order')

    sale_order_id = fields.Many2one('sale.order', string='Sale Order')
    invoice_id = fields.Many2one('account.move', string='Invoice',
                                  domain=[('move_type', 'in', ['out_invoice', 'out_refund'])])
    plan_id = fields.Many2one('asc.commission.plan', string='Commission Plan', required=True)
    salesperson_id = fields.Many2one('res.users', string='Salesperson')
    manual_amount = fields.Monetary(string='Manual Amount', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
    )
    simulation_date = fields.Date(string='Simulation Date', default=fields.Date.today)

    # Results
    result_ids = fields.One2many(
        'asc.commission.simulate.result', 'wizard_id',
        string='Simulation Results', readonly=True,
    )
    has_results = fields.Boolean(default=False)

    def action_simulate(self):
        self.ensure_one()
        engine = self.env['asc.commission.engine']
        results = []

        if self.simulation_type == 'order' and self.sale_order_id:
            results = engine.calculate_for_order(self.sale_order_id, simulate=True)
        elif self.simulation_type == 'invoice' and self.invoice_id:
            results = engine.calculate_for_invoice(self.invoice_id, simulate=True)
        elif self.simulation_type == 'manual' and self.manual_amount:
            results = engine._apply_plan(
                plan=self.plan_id,
                salesperson=self.salesperson_id or self.env.user,
                date=self.simulation_date,
                base_amount=self.manual_amount,
                margin_amount=0.0,
                source_lines=self.env['sale.order.line'],
                context_label='simulation',
            )

        # Clear old results and create new ones
        self.result_ids.unlink()
        to_create = []
        for r in results:
            sp = self.env['res.users'].browse(r['salesperson_id'])
            to_create.append({
                'wizard_id': self.id,
                'salesperson_id': r['salesperson_id'],
                'plan_id': r['plan_id'],
                'base_amount': r['base_amount'],
                'commission_amount': r['commission_amount'],
                'bonus_amount': r['bonus_amount'],
                'net_commission': r['commission_amount'] + r['bonus_amount'],
                'rate_applied': r['rate_applied'],
                'calculation_method': r['calculation_method'],
                'currency_id': r['currency_id'],
            })
        if to_create:
            self.env['asc.commission.simulate.result'].create(to_create)
        self.has_results = True

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'asc.commission.simulate.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }


class AscCommissionSimulateResult(models.TransientModel):
    _name = 'asc.commission.simulate.result'
    _description = 'Simulation Result Line'

    wizard_id = fields.Many2one('asc.commission.simulate.wizard', ondelete='cascade')
    salesperson_id = fields.Many2one('res.users', string='Salesperson')
    plan_id = fields.Many2one('asc.commission.plan', string='Plan')
    base_amount = fields.Monetary(currency_field='currency_id')
    commission_amount = fields.Monetary(currency_field='currency_id')
    bonus_amount = fields.Monetary(currency_field='currency_id')
    net_commission = fields.Monetary(currency_field='currency_id')
    rate_applied = fields.Float(digits=(16, 4))
    calculation_method = fields.Char()
    currency_id = fields.Many2one('res.currency')
