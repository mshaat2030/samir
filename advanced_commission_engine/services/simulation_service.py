# -*- coding: utf-8 -*-
"""Simulation service — executes what-if commission scenarios."""

import logging
from odoo import api, models

_logger = logging.getLogger(__name__)


class CommissionSimulationService(models.AbstractModel):
    """Executes commission simulations without touching real settlements."""

    _name = 'commission.simulation.service'
    _description = 'Commission Simulation Service'

    def run(self, simulation):
        """Run a simulation and return result dict.

        Args:
            simulation: commission.simulation record

        Returns:
            dict with keys: total_commission, rule_breakdown, breakdown_text, range_data
        """
        simulation.ensure_one()
        plan = simulation.plan_id

        import json
        ctx = {}
        if simulation.custom_params:
            try:
                ctx.update(json.loads(simulation.custom_params))
            except Exception:
                pass

        ctx.update({
            'base_amount': simulation.base_amount,
            'achievement_pct': simulation.achievement_pct,
            'margin_amount': simulation.base_amount * simulation.margin_pct / 100.0,
            'kpi_score': simulation.kpi_score,
        })

        if simulation.simulate_range:
            return self._run_range(simulation, plan, ctx)
        return self._run_single(simulation, plan, ctx)

    def _run_single(self, simulation, plan, ctx):
        """Evaluate a single scenario."""
        rules = plan.rule_ids.filtered('active').sorted('sequence')
        total = 0.0
        breakdown = []

        for rule in rules:
            commission = rule.calculate_commission(ctx.get('base_amount', 0.0), ctx)
            capped = plan.apply_commission_cap(commission) if commission else 0.0
            breakdown.append({
                'rule': rule.name,
                'method': rule.calculation_method,
                'rate': rule.rate,
                'commission': capped,
            })
            if rule.is_additive:
                total += capped
            else:
                total = capped
            if rule.stop_further_rules:
                break

        breakdown_text = '\n'.join(
            f'{b["rule"]}: {b["method"]} @ {b["rate"]}% → {plan.currency_id.symbol}{b["commission"]:,.2f}'
            for b in breakdown
        )
        return {
            'total_commission': total,
            'rule_breakdown': breakdown,
            'breakdown_text': breakdown_text,
        }

    def _run_range(self, simulation, plan, base_ctx):
        """Evaluate a range of base amounts."""
        results = []
        from_val = simulation.range_from
        to_val = simulation.range_to
        step = simulation.range_step or 10000.0
        if step <= 0:
            step = (to_val - from_val) / 10

        amount = from_val
        while amount <= to_val + 1e-6:
            ctx = dict(base_ctx, base_amount=amount)
            single = self._run_single(simulation, plan, ctx)
            results.append({'base_amount': amount, 'commission': single['total_commission']})
            amount += step

        total = results[-1]['commission'] if results else 0.0
        breakdown_text = '\n'.join(
            f'Base {plan.currency_id.symbol}{r["base_amount"]:,.0f} → '
            f'{plan.currency_id.symbol}{r["commission"]:,.2f}'
            for r in results
        )
        return {
            'total_commission': total,
            'rule_breakdown': [],
            'breakdown_text': breakdown_text,
            'range_data': results,
        }
