# -*- coding: utf-8 -*-
"""Commission formula definitions evaluated by the formula engine service."""

import ast
import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Allowed AST node types for safe formula evaluation
_SAFE_NODES = frozenset({
    ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.IfExp,
    ast.Compare, ast.Call, ast.Constant, ast.Name, ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Tuple, ast.List,
})

_SAFE_BUILTINS = {
    'abs': abs, 'max': max, 'min': min, 'round': round,
    'sum': sum, 'len': len, 'int': int, 'float': float,
    'bool': bool, 'str': str,
}


class CommissionFormula(models.Model):
    """Named, versioned, sandboxed formula for dynamic commission calculation."""

    _name = 'commission.formula'
    _description = 'Commission Formula'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Formula Name', required=True, tracking=True)
    code = fields.Char(string='Technical Code', required=True, index=True)
    description = fields.Text(string='Description')
    expression = fields.Text(
        string='Expression', required=True, tracking=True,
        help='Python expression. Available variables defined in the Variables field.',
    )
    variables = fields.Char(
        string='Variables',
        help='Comma-separated list of variable names available in this formula.',
    )
    test_values = fields.Text(
        string='Test Values (JSON)',
        help='JSON object with sample values for testing the formula.',
    )
    last_test_result = fields.Float(string='Last Test Result', readonly=True)
    last_test_error = fields.Char(string='Last Test Error', readonly=True)
    active = fields.Boolean(default=True)
    version = fields.Integer(string='Version', default=1)
    is_valid = fields.Boolean(string='Valid', compute='_compute_is_valid', store=True)

    _sql_constraints = [
        ('code_uniq', 'UNIQUE(code)', 'Formula code must be unique.'),
    ]

    @api.depends('expression')
    def _compute_is_valid(self):
        for rec in self:
            try:
                rec._validate_expression(rec.expression)
                rec.is_valid = True
            except Exception:
                rec.is_valid = False

    @api.constrains('expression')
    def _check_expression_safety(self):
        for rec in self:
            try:
                rec._validate_expression(rec.expression)
            except SyntaxError as e:
                raise ValidationError(f'Formula syntax error: {e}') from e
            except ValueError as e:
                raise ValidationError(f'Formula security violation: {e}') from e

    def _validate_expression(self, expression):
        """Parse and validate expression using AST whitelist."""
        tree = ast.parse(expression.strip(), mode='eval')
        for node in ast.walk(tree):
            if type(node) not in _SAFE_NODES:
                raise ValueError(
                    f'Unsafe AST node {type(node).__name__} in formula. '
                    'Only arithmetic, comparison, and conditional expressions are allowed.'
                )
            if isinstance(node, ast.Name) and node.id not in _SAFE_BUILTINS:
                # Variable names are allowed — they come from context
                pass
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name):
                    raise ValueError('Only simple function calls are allowed.')
                if node.func.id not in _SAFE_BUILTINS:
                    raise ValueError(f"Function '{node.func.id}' is not allowed.")

    def evaluate(self, context_vars):
        """Safely evaluate this formula with the given context variables.

        Args:
            context_vars: dict of variable name → numeric value

        Returns:
            float result
        """
        self.ensure_one()
        self._validate_expression(self.expression)
        safe_globals = {'__builtins__': {}, **_SAFE_BUILTINS}
        safe_globals.update({k: float(v) for k, v in context_vars.items() if isinstance(v, (int, float))})
        try:
            result = eval(compile(ast.parse(self.expression.strip(), mode='eval'), '<formula>', 'eval'), safe_globals)  # noqa: S307
            return float(result)
        except Exception as e:
            _logger.error('Formula %s evaluation error: %s | vars=%s', self.code, e, context_vars)
            raise ValidationError(f'Formula evaluation error: {e}') from e

    def action_test_formula(self):
        """Test the formula with test_values JSON and store result."""
        import json
        self.ensure_one()
        if not self.test_values:
            raise ValidationError('Please enter test values (JSON) before testing.')
        try:
            test_vars = json.loads(self.test_values)
            result = self.evaluate(test_vars)
            self.write({'last_test_result': result, 'last_test_error': False})
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Formula Test',
                    'message': f'Result: {result}',
                    'type': 'success',
                },
            }
        except Exception as e:
            self.write({'last_test_error': str(e)})
            raise ValidationError(str(e)) from e

    def action_increment_version(self):
        """Bump version counter on formula change."""
        self.ensure_one()
        self.write({'version': self.version + 1})

    @api.model
    def get_by_code(self, code):
        """Fetch active formula by technical code."""
        return self.search([('code', '=', code), ('active', '=', True)], limit=1)
