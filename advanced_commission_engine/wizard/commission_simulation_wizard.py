# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class CommissionSimulationWizard(models.TransientModel):
    _name = 'commission.simulation.wizard'
    _description = 'Commission Simulation Wizard'

    employee_id = fields.Many2one('hr.employee', string='Employee')
    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan', required=True
    )
    base_amount = fields.Float(string='Base Amount', required=True, default=10000.0)
    margin_percent = fields.Float(string='Margin %', default=30.0)
    achieved_percent = fields.Float(string='Target Achievement %', default=100.0)
    run_scenarios = fields.Boolean(
        string='Run Multiple Scenarios', default=False
    )

    def action_simulate(self):
        self.ensure_one()
        sim = self.env['commission.simulation'].create({
            'name': _('Simulation: %s') % self.plan_id.name,
            'plan_id': self.plan_id.id,
            'employee_id': self.employee_id.id if self.employee_id else False,
            'base_amount': self.base_amount,
            'margin_percent': self.margin_percent,
            'achieved_percent': self.achieved_percent,
            'company_id': self.env.company.id,
            'currency_id': self.env.company.currency_id.id,
        })
        if self.run_scenarios:
            sim.action_run_scenarios()
        else:
            sim.action_compute()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'commission.simulation',
            'res_id': sim.id,
            'view_mode': 'form',
        }
