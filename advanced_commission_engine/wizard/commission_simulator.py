# -*- coding: utf-8 -*-
"""Wizard – Interactive Commission Simulator."""

from odoo import api, fields, models


class WizardCommissionSimulator(models.TransientModel):
    """Interactive wizard for running commission simulations.

    Allows testing different scenarios and comparing plans.
    """

    _name = 'wizard.commission.simulator'
    _description = 'Commission Simulator'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
    )
    plan_id = fields.Many2one(
        'commission.plan',
        string='Commission Plan',
        required=True,
    )
    period_id = fields.Many2one(
        'commission.period',
        string='Period',
    )
    formula_id = fields.Many2one(
        'commission.formula',
        string='Formula to Test',
    )

    # ── Scenario Parameters ───────────────────────────────────────────────────
    base_amount = fields.Monetary(
        string='Base Amount',
        currency_field='currency_id',
        default=10000.0,
    )
    margin_pct = fields.Float(
        string='Margin %',
        default=30.0,
        digits=(16, 1),
    )
    kpi_score = fields.Float(
        string='KPI Score',
        default=80.0,
        digits=(16, 1),
    )
    use_actual_data = fields.Boolean(
        string='Use Actual Period Data',
        default=False,
    )

    # ── Results ───────────────────────────────────────────────────────────────
    simulation_id = fields.Many2one(
        'commission.simulation',
        string='Simulation',
        readonly=True,
    )
    result_html = fields.Html(
        string='Simulation Results',
        readonly=True,
    )
    total_commission = fields.Monetary(
        string='Total Commission',
        currency_field='currency_id',
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )

    @api.onchange('plan_id')
    def _onchange_plan_id(self):
        if self.plan_id:
            self.currency_id = self.plan_id.currency_id

    def action_simulate(self):
        """Run the simulation and display results."""
        self.ensure_one()

        # Clean up previous simulation
        if self.simulation_id:
            self.simulation_id.unlink()

        from ..services.simulation_service import SimulationService
        service = SimulationService(self.env)

        sim = self.env['commission.simulation'].create({
            'name': f'Simulation – {self.plan_id.name}',
            'plan_id': self.plan_id.id,
            'employee_id': self.employee_id.id if self.employee_id else False,
            'period_id': self.period_id.id if self.period_id else False,
            'base_amount': self.base_amount,
            'margin_pct': self.margin_pct,
            'kpi_score': self.kpi_score,
            'use_actual_data': self.use_actual_data,
        })
        service.run_simulation(sim)

        self.simulation_id = sim
        self.total_commission = sim.total_commission

        # Build HTML result
        lines_html = ''
        for line in sim.line_ids:
            lines_html += f'''
            <tr>
                <td>{line.description or (line.rule_id.name if line.rule_id else '')}</td>
                <td>{self.env['res.currency'].browse(self.currency_id.id).symbol} {line.base_amount:,.2f}</td>
                <td>{line.commission_rate:.2f}%</td>
                <td><strong>{self.env['res.currency'].browse(self.currency_id.id).symbol} {line.commission_amount:,.2f}</strong></td>
            </tr>'''

        self.result_html = f'''
        <div class="o_commission_simulation_result">
            <table class="table table-striped table-sm">
                <thead>
                    <tr>
                        <th>Rule</th>
                        <th>Base Amount</th>
                        <th>Rate</th>
                        <th>Commission</th>
                    </tr>
                </thead>
                <tbody>
                    {lines_html}
                </tbody>
                <tfoot>
                    <tr class="table-success">
                        <td colspan="3"><strong>Total Commission</strong></td>
                        <td><strong>{self.env['res.currency'].browse(self.currency_id.id).symbol} {sim.total_commission:,.2f}</strong></td>
                    </tr>
                </tfoot>
            </table>
        </div>'''

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'wizard.commission.simulator',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_simulation(self):
        """Open the full simulation record."""
        self.ensure_one()
        if self.simulation_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'commission.simulation',
                'res_id': self.simulation_id.id,
                'view_mode': 'form',
            }
