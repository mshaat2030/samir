# -*- coding: utf-8 -*-
"""Wizard: Interactive commission scenario simulator."""

import json
import logging
from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class WizardCommissionSimulator(models.TransientModel):
    """Quick-access simulation wizard — results shown inline."""

    _name = 'wizard.commission.simulator'
    _description = 'Commission Simulator Wizard'

    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan', required=True,
    )
    employee_id = fields.Many2one('hr.employee', string='Employee (Optional)')

    # ── Parameters ────────────────────────────────────────────────────────────
    base_amount = fields.Monetary(string='Revenue / Base Amount', currency_field='currency_id')
    margin_pct = fields.Float(string='Gross Margin %', default=30.0)
    achievement_pct = fields.Float(string='Target Achievement %', default=100.0)
    kpi_score = fields.Float(string='KPI Score', default=80.0)
    currency_id = fields.Many2one(
        'res.currency', related='plan_id.currency_id', readonly=True,
    )

    # ── Results ───────────────────────────────────────────────────────────────
    result_commission = fields.Monetary(string='Estimated Commission', currency_field='currency_id', readonly=True)
    result_breakdown = fields.Text(string='Rule Breakdown', readonly=True)
    has_result = fields.Boolean(default=False)

    # ── Action ────────────────────────────────────────────────────────────────

    def action_simulate(self):
        """Run simulation and display result."""
        self.ensure_one()
        svc = self.env['commission.simulation.service']

        # Build transient simulation record
        sim = self.env['commission.simulation'].new({
            'plan_id': self.plan_id.id,
            'employee_id': self.employee_id.id if self.employee_id else False,
            'base_amount': self.base_amount,
            'margin_pct': self.margin_pct,
            'achievement_pct': self.achievement_pct,
            'kpi_score': self.kpi_score,
            'simulate_range': False,
        })
        result = svc.run(sim)

        self.write({
            'result_commission': result.get('total_commission', 0.0),
            'result_breakdown': result.get('breakdown_text', ''),
            'has_result': True,
        })
        # Return same form to show results
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'wizard.commission.simulator',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
            'context': self.env.context,
        }

    def action_save_simulation(self):
        """Persist as a commission.simulation record."""
        self.ensure_one()
        sim = self.env['commission.simulation'].create({
            'plan_id': self.plan_id.id,
            'employee_id': self.employee_id.id if self.employee_id else False,
            'base_amount': self.base_amount,
            'margin_pct': self.margin_pct,
            'achievement_pct': self.achievement_pct,
            'kpi_score': self.kpi_score,
            'state': 'computed',
            'result_commission': self.result_commission,
            'result_breakdown': self.result_breakdown,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'commission.simulation',
            'view_mode': 'form',
            'res_id': sim.id,
        }
