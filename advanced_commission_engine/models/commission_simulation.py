# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class CommissionSimulation(models.Model):
    _name = 'commission.simulation'
    _description = 'Commission Simulation'
    _inherit = ['mail.thread', 'commission.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='Simulation Name', required=True,
        default=lambda self: _('New Simulation'),
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', index=True
    )
    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan',
        required=True, index=True,
    )
    simulation_date = fields.Date(
        string='Simulation Date', default=fields.Date.today
    )

    # ── Input Parameters ──────────────────────────────────────────────────────
    base_amount = fields.Monetary(
        string='Base Amount',
        currency_field='currency_id',
        required=True,
    )
    margin_percent = fields.Float(string='Margin %', default=30.0, digits=(5, 2))
    target_amount = fields.Monetary(
        string='Target Amount', currency_field='currency_id'
    )
    achieved_percent = fields.Float(
        string='Target Achievement %', default=100.0, digits=(5, 2)
    )
    quantity = fields.Float(string='Quantity', default=1.0)

    # ── Scenario Lines ────────────────────────────────────────────────────────
    simulation_line_ids = fields.One2many(
        'commission.simulation.line', 'simulation_id',
        string='Scenarios',
    )

    # ── Results ───────────────────────────────────────────────────────────────
    computed_commission = fields.Monetary(
        string='Computed Commission',
        currency_field='currency_id',
        compute='_compute_result',
        store=True,
    )
    effective_rate = fields.Float(
        string='Effective Rate (%)',
        compute='_compute_result',
        store=True,
        digits=(5, 4),
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('computed', 'Computed'),
    ], default='draft')

    note = fields.Text(string='Notes')

    @api.depends('plan_id', 'base_amount', 'simulation_line_ids.commission_amount')
    def _compute_result(self):
        for sim in self:
            if sim.simulation_line_ids:
                sim.computed_commission = sum(
                    sim.simulation_line_ids.mapped('commission_amount')
                )
            else:
                sim.computed_commission = 0.0
            if sim.base_amount > 0:
                sim.effective_rate = (sim.computed_commission / sim.base_amount) * 100
            else:
                sim.effective_rate = 0.0

    def action_compute(self):
        """Run simulation for current parameters."""
        for sim in self:
            if not sim.plan_id:
                raise UserError(_('Please select a commission plan.'))
            ctx = {
                'amount': sim.base_amount,
                'margin': sim.base_amount * sim.margin_percent / 100,
                'margin_percent': sim.margin_percent / 100,
                'quantity': sim.quantity,
                'target': sim.target_amount,
                'achieved_percent': sim.achieved_percent,
                'achieved': sim.base_amount * sim.achieved_percent / 100,
            }
            commission = sim.plan_id.compute_commission(
                sim.base_amount,
                employee=sim.employee_id,
                context_vals=ctx,
            )
            # Remove old lines and create new one
            sim.simulation_line_ids.unlink()
            self.env['commission.simulation.line'].create({
                'simulation_id': sim.id,
                'name': _('Base Scenario'),
                'base_amount': sim.base_amount,
                'commission_amount': commission,
                'rate': sim.plan_id.fixed_rate,
                'plan_id': sim.plan_id.id,
            })
            sim.write({'state': 'computed'})

    def action_run_scenarios(self):
        """Run multiple scenarios with varying amounts."""
        self.ensure_one()
        self.simulation_line_ids.unlink()
        amounts = [
            self.base_amount * 0.5,
            self.base_amount * 0.75,
            self.base_amount,
            self.base_amount * 1.25,
            self.base_amount * 1.5,
        ]
        labels = ['50%', '75%', '100%', '125%', '150%']
        lines = []
        for amount, label in zip(amounts, labels):
            ctx = {
                'amount': amount,
                'margin': amount * self.margin_percent / 100,
                'achieved_percent': self.achieved_percent,
            }
            commission = self.plan_id.compute_commission(
                amount, employee=self.employee_id, context_vals=ctx
            )
            lines.append({
                'simulation_id': self.id,
                'name': _('Scenario %s of Target') % label,
                'base_amount': amount,
                'commission_amount': commission,
                'rate': (commission / amount * 100) if amount else 0,
                'plan_id': self.plan_id.id,
            })
        self.env['commission.simulation.line'].create(lines)
        self.write({'state': 'computed'})


class CommissionSimulationLine(models.Model):
    _name = 'commission.simulation.line'
    _description = 'Commission Simulation Line'
    _order = 'sequence, id'

    simulation_id = fields.Many2one(
        'commission.simulation', required=True, ondelete='cascade'
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Scenario', required=True)
    plan_id = fields.Many2one('commission.plan', string='Plan')
    base_amount = fields.Monetary(
        string='Base Amount',
        currency_field='currency_id',
    )
    commission_amount = fields.Monetary(
        string='Commission',
        currency_field='currency_id',
    )
    rate = fields.Float(string='Effective Rate (%)', digits=(5, 4))
    currency_id = fields.Many2one(
        related='simulation_id.currency_id', store=True
    )
    note = fields.Char(string='Note')
