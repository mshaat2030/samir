# -*- coding: utf-8 -*-
"""Commission Simulation — what-if scenario calculator."""

import json
import logging
from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class CommissionSimulation(models.Model):
    """What-if commission simulation sandbox."""

    _name = 'commission.simulation'
    _description = 'Commission Simulation'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Simulation Name', required=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('commission.simulation'),
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        index=True,
        help='Leave empty to simulate for plan in general.',
    )
    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan',
        required=True, index=True,
    )
    company_id = fields.Many2one(
        'res.company', related='plan_id.company_id',
        store=True, readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id',
        store=True, readonly=True,
    )

    # ── Scenario Parameters ───────────────────────────────────────────────────
    scenario_type = fields.Selection([
        ('revenue', 'Revenue Scenario'),
        ('achievement', 'Achievement % Scenario'),
        ('rate_change', 'Rate Change Scenario'),
        ('multi_slab', 'Multi-Slab Comparison'),
        ('custom', 'Custom Parameters'),
    ], string='Scenario Type', default='revenue', required=True)

    base_amount = fields.Monetary(
        string='Base Transaction Amount', currency_field='currency_id',
    )
    achievement_pct = fields.Float(string='Achievement %', digits=(16, 1), default=100.0)
    margin_pct = fields.Float(string='Gross Margin %', digits=(16, 1), default=30.0)
    kpi_score = fields.Float(string='KPI Score', digits=(16, 1), default=80.0)
    custom_params = fields.Text(
        string='Custom Parameters (JSON)',
        default='{}',
        help='JSON object with parameter key-values for custom scenarios.',
    )

    # ── Range Simulation ──────────────────────────────────────────────────────
    simulate_range = fields.Boolean(string='Simulate Range', default=False)
    range_from = fields.Float(string='Range From', default=0.0)
    range_to = fields.Float(string='Range To', default=0.0)
    range_step = fields.Float(string='Range Step', default=10000.0)

    # ── Results ───────────────────────────────────────────────────────────────
    state = fields.Selection([
        ('draft', 'Draft'),
        ('computed', 'Computed'),
    ], string='State', default='draft')
    result_json = fields.Text(string='Result JSON', readonly=True)
    result_commission = fields.Monetary(
        string='Simulated Commission', currency_field='currency_id',
        readonly=True,
    )
    result_breakdown = fields.Text(string='Rule Breakdown', readonly=True)

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = fields.Text(string='Notes / Assumptions')

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('custom_params')
    def _check_custom_params(self):
        for rec in self:
            if rec.custom_params:
                try:
                    json.loads(rec.custom_params)
                except (json.JSONDecodeError, TypeError) as e:
                    raise ValidationError(f'Custom parameters must be valid JSON: {e}') from e

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_run_simulation(self):
        """Execute the simulation using the simulation service."""
        for rec in self:
            svc = self.env['commission.simulation.service']
            result = svc.run(rec)
            rec.write({
                'state': 'computed',
                'result_commission': result.get('total_commission', 0.0),
                'result_json': json.dumps(result, indent=2),
                'result_breakdown': result.get('breakdown_text', ''),
            })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Simulation Complete',
                'message': f'Commission: {self.currency_id.symbol}{self.result_commission:,.2f}',
                'type': 'success',
            },
        }

    def action_reset(self):
        """Reset simulation to draft."""
        self.write({'state': 'draft', 'result_json': False, 'result_commission': 0.0})

    def action_save_as_new(self):
        """Duplicate this simulation with a new name."""
        new = self.copy({'name': self.name + ' (Copy)', 'state': 'draft'})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'commission.simulation',
            'view_mode': 'form',
            'res_id': new.id,
        }
