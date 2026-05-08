# -*- coding: utf-8 -*-
"""Formula Engine – safe evaluation of custom commission formulas.

Uses Odoo's safe_eval to sandbox formula execution.
"""

import logging

from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class FormulaEngine:
    """Evaluates :class:`commission.formula` records safely.

    The formula code is executed in a restricted Python environment.
    The formula must set a variable ``result`` to the commission amount.

    Example formula code::

        margin_factor = 1.5 if margin_pct >= 40 else 1.0
        result = base_amount * rate / 100 * margin_factor
    """

    def __init__(self, env):
        self.env = env
        # Read timeout from system parameters
        try:
            timeout = int(
                env['ir.config_parameter'].sudo().get_param(
                    'advanced_commission_engine.formula_timeout', '5'
                )
            )
        except Exception:
            timeout = 5
        self.timeout = timeout

    def evaluate(self, formula, base_amount=0.0, rate=0.0, **kwargs):
        """Evaluate a formula record and return the commission amount.

        :param formula: commission.formula record
        :param base_amount: float, base amount for commission calculation
        :param rate: float, commission rate from rule
        :param kwargs: additional context variables
        :return: float commission amount, or 0.0 on error
        """
        if not formula or not formula.formula_code:
            return 0.0

        context = {
            'base_amount': float(base_amount),
            'rate': float(rate),
            'result': 0.0,
            'min': min,
            'max': max,
            'abs': abs,
            'round': round,
            'int': int,
            'float': float,
            'bool': bool,
            'len': len,
            'sum': sum,
            'sorted': sorted,
            'range': range,
            'enumerate': enumerate,
            'zip': zip,
            'list': list,
            'dict': dict,
            'str': str,
            'isinstance': isinstance,
        }

        # Add safe scalar kwargs
        for k, v in kwargs.items():
            if self._is_safe_value(v):
                context[k] = v

        # Extract scalar values from record objects
        employee = kwargs.get('employee')
        if employee and hasattr(employee, 'id'):
            context['employee_id'] = employee.id
            context['employee_name'] = employee.name

        period = kwargs.get('period')
        if period and hasattr(period, 'id'):
            context['period_id'] = period.id
            context['period_name'] = period.name if period else ''

        try:
            safe_eval(
                formula.formula_code,
                context,
                mode='exec',
            )
            result = context.get('result', 0.0)
            if not isinstance(result, (int, float)):
                _logger.warning(
                    'Formula %s returned non-numeric result: %r', formula.name, result
                )
                return 0.0
            return float(max(0.0, result))
        except Exception as e:
            _logger.error(
                'Error evaluating formula %s [%s]: %s',
                formula.name, formula.code, str(e),
            )
            return 0.0

    @staticmethod
    def _is_safe_value(val):
        """Check if a value is safe to pass to the formula context."""
        return isinstance(val, (int, float, str, bool, type(None)))

    def validate_formula(self, formula_code):
        """Validate formula syntax and test evaluation.

        :return: (bool, str) – (is_valid, error_message)
        """
        try:
            compile(formula_code, '<formula>', 'exec')
        except SyntaxError as e:
            return False, str(e)

        context = {
            'base_amount': 10000.0,
            'rate': 5.0,
            'margin_pct': 30.0,
            'revenue': 10000.0,
            'profit': 3000.0,
            'target': 10000.0,
            'achieved': 8000.0,
            'attainment': 0.8,
            'kpi_score': 75.0,
            'result': 0.0,
            'min': min,
            'max': max,
            'abs': abs,
            'round': round,
            'int': int,
            'float': float,
        }
        try:
            safe_eval(formula_code, context, mode='exec')
            result = context.get('result', 0.0)
            if not isinstance(result, (int, float)):
                return False, f'Formula did not produce a numeric result (got {type(result).__name__})'
            return True, f'Test result: {result}'
        except Exception as e:
            return False, str(e)
