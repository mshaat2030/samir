# -*- coding: utf-8 -*-
"""Formula engine service — provides higher-level formula orchestration."""

import logging
from odoo import api, models

_logger = logging.getLogger(__name__)


class CommissionFormulaEngine(models.AbstractModel):
    """Service wrapper around commission.formula for plan-level formula dispatch."""

    _name = 'commission.formula.engine'
    _description = 'Commission Formula Engine'

    def evaluate_plan_formula(self, plan, context_vars):
        """Evaluate a plan's attached formula with the given context.

        Falls back to fixed_percent rate if no formula is set.

        Args:
            plan: commission.plan record
            context_vars: dict

        Returns:
            float commission amount
        """
        if plan.calculation_method == 'dynamic_formula' and plan.formula_id:
            return plan.formula_id.evaluate(context_vars)
        base = context_vars.get('base_amount', 0.0)
        return base * (plan.rule_ids[:1].rate if plan.rule_ids else 0.0) / 100.0

    def evaluate_rule_formula(self, rule, context_vars):
        """Evaluate a rule-level formula.

        Args:
            rule: commission.rule record
            context_vars: dict

        Returns:
            float commission amount
        """
        if rule.calculation_method == 'dynamic_formula' and rule.formula_id:
            return rule.formula_id.evaluate(context_vars)
        return rule.calculate_commission(context_vars.get('base_amount', 0.0), context_vars)

    def build_context(self, employee=None, invoice=None, sale_order=None,
                      payment=None, period=None, target=None, kpis=None, **kwargs):
        """Build a rich context dictionary for formula evaluation.

        Args:
            All optional Odoo record args.

        Returns:
            dict suitable for passing to formula.evaluate()
        """
        ctx = dict(kwargs)

        if employee:
            ctx.update({
                'employee_id': employee.id,
                'employee_name': employee.name,
            })
        if invoice:
            ctx.update({
                'base_amount': invoice.amount_untaxed,
                'invoice_amount': invoice.amount_untaxed,
                'invoice_tax': invoice.amount_tax,
                'invoice_total': invoice.amount_total,
                'days_since_invoice': (
                    (__import__('odoo').fields.Date.today() - invoice.invoice_date).days
                    if invoice.invoice_date else 0
                ),
            })
        if sale_order:
            ctx.update({
                'base_amount': ctx.get('base_amount', sale_order.amount_untaxed),
                'order_amount': sale_order.amount_untaxed,
            })
        if payment:
            ctx.update({
                'base_amount': ctx.get('base_amount', payment.amount),
                'payment_amount': payment.amount,
            })
        if period:
            ctx['period_days'] = (period.date_end - period.date_start).days
        if target:
            ctx.update({
                'target_amount': target.target_amount,
                'achieved_amount': target.achieved_amount,
                'achievement_pct': target.achievement_pct,
                'remaining_amount': target.remaining_amount,
            })
        if kpis:
            ctx['kpi_score'] = sum(kpis.mapped('weighted_score'))

        return ctx

    def get_formula_by_code(self, code):
        """Convenience method to fetch a formula by code."""
        return self.env['commission.formula'].get_by_code(code)

    def test_all_formulas(self):
        """Run test_values evaluation on all active formulas. Returns dict of results."""
        results = {}
        for formula in self.env['commission.formula'].search([('active', '=', True)]):
            try:
                if formula.test_values:
                    import json
                    test_vars = json.loads(formula.test_values)
                    result = formula.evaluate(test_vars)
                    results[formula.code] = {'ok': True, 'result': result}
                else:
                    results[formula.code] = {'ok': None, 'result': 'no test values'}
            except Exception as e:
                results[formula.code] = {'ok': False, 'error': str(e)}
        return results
