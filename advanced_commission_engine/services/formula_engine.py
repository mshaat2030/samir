# -*- coding: utf-8 -*-
"""
Safe formula evaluation engine for commission calculations.
Uses a restricted execution environment to prevent code injection.
"""
import ast
import math
import logging
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)

# Safe builtins that formulas are allowed to use
SAFE_BUILTINS = {
    'abs': abs,
    'min': min,
    'max': max,
    'round': round,
    'int': int,
    'float': float,
    'sum': sum,
    'len': len,
    'bool': bool,
    'str': str,
    'pow': pow,
    'divmod': divmod,
    'True': True,
    'False': False,
    'None': None,
}

# Math functions available in formulas
SAFE_MATH = {
    'sqrt': math.sqrt,
    'ceil': math.ceil,
    'floor': math.floor,
    'log': math.log,
    'exp': math.exp,
    'pi': math.pi,
    'e': math.e,
}

# AST node types that are considered safe
SAFE_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.IfExp,
    ast.Compare,
    ast.Call,
    ast.Constant,
    ast.Name,
    ast.Attribute,
    ast.Subscript,
    ast.Index,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Tuple,
    ast.List,
    ast.Dict,
)


class FormulaEngine:
    """
    Safe formula engine for commission calculations.

    Supported variables:
    - amount: base amount (float)
    - rate: commission rate (float, e.g. 5.0 for 5%)
    - margin: margin amount (float)
    - margin_percent: margin as decimal (float, e.g. 0.3 for 30%)
    - quantity: number of units (float)
    - target: target amount (float)
    - achieved: achieved amount (float)
    - achieved_percent: achievement percentage (float)
    - commission: current commission amount (for rule formulas)
    - employee: hr.employee record (for access to employee fields)
    """

    def __init__(self, env):
        self.env = env

    def validate(self, formula):
        """
        Validate formula syntax and safety.
        Raises ValidationError if invalid.
        """
        if not formula:
            raise ValidationError('Formula cannot be empty.')
        try:
            tree = ast.parse(formula, mode='eval')
        except SyntaxError as e:
            raise ValidationError('Formula syntax error: %s' % str(e))
        self._check_ast_safety(tree)
        return True

    def _check_ast_safety(self, node):
        """Recursively verify all AST nodes are safe."""
        if not isinstance(node, SAFE_NODES):
            raise ValidationError(
                'Unsafe operation in formula: %s. '
                'Only basic arithmetic and comparisons are allowed.' % type(node).__name__
            )
        # For function calls, verify the function name is in the safe list
        if isinstance(node, ast.Call):
            func = node.func
            safe_names = set(SAFE_BUILTINS.keys()) | set(SAFE_MATH.keys())
            if isinstance(func, ast.Name):
                if func.id not in safe_names:
                    raise ValidationError(
                        'Unsafe function call in formula: %s. '
                        'Only safe math and builtin functions are allowed.' % func.id
                    )
            elif isinstance(func, ast.Attribute):
                raise ValidationError(
                    'Attribute access not allowed in formula: %s. '
                    'Only safe math and builtin functions are allowed.' % func.attr
                )
            else:
                raise ValidationError(
                    'Unsafe function call pattern in formula. '
                    'Only safe math and builtin functions are allowed.'
                )
        for child in ast.iter_child_nodes(node):
            self._check_ast_safety(child)

    def evaluate(self, formula, context):
        """
        Evaluate formula safely.
        Returns a float result.
        Raises UserError on evaluation failure.
        """
        if not formula:
            return 0.0
        # Build safe evaluation namespace
        safe_globals = {'__builtins__': {}}
        safe_globals.update(SAFE_BUILTINS)
        safe_globals.update(SAFE_MATH)

        # Build local variables from context
        local_vars = {
            'amount': float(context.get('amount', 0)),
            'rate': float(context.get('rate', 0)),
            'margin': float(context.get('margin', 0)),
            'margin_percent': float(context.get('margin_percent', 0)),
            'quantity': float(context.get('quantity', 1)),
            'target': float(context.get('target', 0)),
            'achieved': float(context.get('achieved', 0)),
            'achieved_percent': float(context.get('achieved_percent', 100)),
            'commission': float(context.get('commission', 0)),
        }

        # Add employee-derived fields if available
        employee = context.get('employee')
        if employee and hasattr(employee, 'id'):
            local_vars['employee_level'] = 1
            local_vars['years_of_service'] = 0
            if hasattr(employee, 'km_home_work'):
                local_vars['employee_level'] = getattr(employee, 'km_home_work', 1) or 1

        try:
            result = eval(
                compile(formula, '<commission_formula>', 'eval'),
                safe_globals,
                local_vars,
            )
            return float(result)
        except ZeroDivisionError:
            return 0.0
        except Exception as e:
            _logger.warning('Formula evaluation error: %s | Formula: %s', str(e), formula)
            raise UserError(
                'Commission formula evaluation failed: %s\nFormula: %s' % (str(e), formula)
            )

    def build_context_from_invoice(self, invoice, employee):
        """Build formula context from an invoice."""
        margin = getattr(invoice, 'margin', 0) or 0
        base = invoice.amount_untaxed or 0
        return {
            'amount': base,
            'margin': margin,
            'margin_percent': (margin / base) if base else 0,
            'invoice': invoice,
            'employee': employee,
        }

    def build_context_from_sale_order(self, order, employee):
        """Build formula context from a sale order."""
        margin = getattr(order, 'margin', 0) or 0
        base = order.amount_untaxed or 0
        return {
            'amount': base,
            'margin': margin,
            'margin_percent': (margin / base) if base else 0,
            'order': order,
            'employee': employee,
            'quantity': sum(order.order_line.mapped('product_uom_qty')),
        }
