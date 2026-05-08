# -*- coding: utf-8 -*-
"""Commission Simulation – what-if scenario modelling without creating real records."""

from odoo import api, fields, models


class CommissionSimulation(models.Model):
    """What-if simulation for commission plans.

    Allows testing different scenarios without affecting real data.
    Results are stored as :class:`CommissionSimulationLine` records.
    """

    _name = 'commission.simulation'
    _description = 'Commission Simulation'
    _inherit = ['mail.thread']
    _order = 'create_date desc'

    name = fields.Char(
        string='Simulation Name',
        required=True,
        default='New Simulation',
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        index=True,
    )
    plan_id = fields.Many2one(
        'commission.plan',
        string='Commission Plan',
        required=True,
        index=True,
    )
    period_id = fields.Many2one(
        'commission.period',
        string='Period',
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )

    # ── Simulation Parameters ─────────────────────────────────────────────────
    base_amount = fields.Monetary(
        string='Base Amount',
        currency_field='currency_id',
        default=0.0,
    )
    margin_pct = fields.Float(
        string='Margin %',
        digits=(16, 2),
        default=30.0,
    )
    revenue = fields.Monetary(
        string='Revenue',
        currency_field='currency_id',
        default=0.0,
    )
    kpi_score = fields.Float(
        string='KPI Score',
        digits=(16, 1),
        default=80.0,
    )
    use_actual_data = fields.Boolean(
        string='Use Actual Period Data',
        default=False,
        help='Pull real invoices/orders from the selected period instead of manual input.',
    )

    # ── Results ───────────────────────────────────────────────────────────────
    line_ids = fields.One2many(
        'commission.simulation.line',
        'simulation_id',
        string='Simulation Lines',
    )
    total_commission = fields.Monetary(
        string='Total Simulated Commission',
        currency_field='currency_id',
        compute='_compute_total',
        store=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('done', 'Computed'),
        ],
        default='draft',
    )
    notes = fields.Text(string='Notes')

    @api.depends('line_ids.commission_amount')
    def _compute_total(self):
        for sim in self:
            sim.total_commission = sum(sim.line_ids.mapped('commission_amount'))

    def action_run(self):
        """Run the simulation using the service layer."""
        from ..services.simulation_service import SimulationService
        service = SimulationService(self.env)
        for sim in self:
            service.run_simulation(sim)
            sim.state = 'done'

    def action_reset(self):
        """Reset simulation to draft."""
        self.line_ids.unlink()
        self.write({'state': 'draft'})


class CommissionSimulationLine(models.Model):
    """One line in a simulation, corresponding to one rule evaluation."""

    _name = 'commission.simulation.line'
    _description = 'Commission Simulation Line'
    _order = 'simulation_id, rule_id'

    simulation_id = fields.Many2one(
        'commission.simulation',
        required=True,
        ondelete='cascade',
        index=True,
    )
    rule_id = fields.Many2one(
        'commission.rule',
        string='Rule',
    )
    currency_id = fields.Many2one(
        related='simulation_id.currency_id',
        readonly=True,
    )
    description = fields.Char(string='Description')
    base_amount = fields.Monetary(
        string='Base Amount',
        currency_field='currency_id',
        default=0.0,
    )
    commission_rate = fields.Float(
        string='Rate (%)',
        digits=(16, 4),
        default=0.0,
    )
    commission_amount = fields.Monetary(
        string='Commission',
        currency_field='currency_id',
        default=0.0,
    )
    notes = fields.Text(string='Notes')
