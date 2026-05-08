# -*- coding: utf-8 -*-
"""Simulation Service – runs what-if commission scenarios."""

import logging

_logger = logging.getLogger(__name__)


class SimulationService:
    """Runs commission simulations against a plan without creating real data.

    Populates :class:`commission.simulation.line` records on the simulation.
    """

    def __init__(self, env):
        self.env = env

    def run_simulation(self, simulation):
        """Run the simulation and populate result lines.

        :param simulation: commission.simulation record
        """
        _logger.info('Running simulation %s', simulation.name)
        simulation.line_ids.unlink()

        plan = simulation.plan_id
        if not plan:
            return

        base_amount = simulation.base_amount or 0.0
        margin_pct = simulation.margin_pct or 0.0
        kpi_score = simulation.kpi_score or 0.0

        if simulation.use_actual_data and simulation.period_id and simulation.employee_id:
            base_amount = self._get_actual_revenue(
                plan, simulation.employee_id, simulation.period_id
            )
            margin_pct = self._get_actual_margin(
                plan, simulation.employee_id, simulation.period_id
            )

        lines = []
        for rule in plan.rule_ids.filtered('active').sorted('sequence'):
            context_vals = {
                'margin_pct': margin_pct,
                'kpi_score': kpi_score,
                'revenue': base_amount,
                'profit': base_amount * margin_pct / 100.0,
                'target': 0,
                'achieved': base_amount,
                'attainment': 1.0,
            }

            # Check if rule applies
            if rule.min_base_amount and base_amount < rule.min_base_amount:
                continue
            if rule.max_base_amount and base_amount > rule.max_base_amount:
                continue

            commission = rule.compute_commission(base_amount, context_vals)

            lines.append({
                'simulation_id': simulation.id,
                'rule_id': rule.id,
                'description': rule.name,
                'base_amount': base_amount,
                'commission_rate': rule.rate,
                'commission_amount': commission,
            })

        if lines:
            self.env['commission.simulation.line'].create(lines)

    def _get_actual_revenue(self, plan, employee, period):
        """Get actual revenue for an employee in a period."""
        domain = [
            ('employee_id', '=', employee.id),
            ('period_id', '=', period.id),
            ('plan_id', '=', plan.id),
            ('state', '!=', 'cancelled'),
        ]
        lines = self.env['commission.line'].search(domain)
        return sum(lines.mapped('base_amount'))

    def _get_actual_margin(self, plan, employee, period):
        """Get average margin percentage for an employee in a period."""
        domain = [
            ('employee_id', '=', employee.id),
            ('period_id', '=', period.id),
            ('state', '!=', 'cancelled'),
        ]
        lines = self.env['commission.line'].search(domain)
        if lines:
            return sum(lines.mapped('margin_pct')) / len(lines)
        return 0.0

    def simulate_plan_comparison(self, employee, period, plan_ids):
        """Compare commission outcomes across multiple plans.

        :return: list of dicts with plan_id, plan_name, total_commission
        """
        plans = self.env['commission.plan'].browse(plan_ids)
        results = []
        for plan in plans:
            sim = self.env['commission.simulation'].create({
                'name': f'Compare – {plan.name}',
                'plan_id': plan.id,
                'employee_id': employee.id,
                'period_id': period.id,
                'use_actual_data': True,
            })
            self.run_simulation(sim)
            results.append({
                'plan_id': plan.id,
                'plan_name': plan.name,
                'total_commission': sim.total_commission,
            })
            sim.unlink()
        return results
