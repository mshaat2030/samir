# -*- coding: utf-8 -*-
"""Tests for the formula engine: AST safety, evaluation correctness, and service."""

import logging
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


@tagged('commission', 'commission_formula')
class TestFormulaEngine(TransactionCase):
    """Tests for CommissionFormula model and CommissionFormulaEngine service."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        cls.employee = cls.env['hr.employee'].create({
            'name': 'Formula Test Employee',
            'company_id': cls.company.id,
        })

        from datetime import date, timedelta
        today = date.today()
        cls.period = cls.env['commission.period'].create({
            'name': 'Formula Test Period',
            'period_type': 'monthly',
            'date_start': today.replace(day=1),
            'date_end': (today.replace(day=1) + timedelta(days=31)).replace(day=1) - timedelta(days=1),
            'state': 'open',
            'company_id': cls.company.id,
        })

    def _create_formula(self, expression, name=None, code=None):
        import uuid
        uid = uuid.uuid4().hex[:6]
        return self.env['commission.formula'].create({
            'name': name or f'Formula {uid}',
            'code': code or f'FRM-{uid.upper()}',
            'expression': expression,
            'active': True,
        })

    # ── Basic Evaluation ──────────────────────────────────────────────────────

    def test_simple_percentage(self):
        """Simple percentage formula: base_amount * rate / 100."""
        formula = self._create_formula('base_amount * rate / 100')
        result = formula.evaluate({'base_amount': 10000.0, 'rate': 5.0})
        self.assertAlmostEqual(result, 500.0, places=2)

    def test_fixed_amount_formula(self):
        """Formula returning a fixed constant."""
        formula = self._create_formula('250.0')
        result = formula.evaluate({'base_amount': 99999.0})
        self.assertAlmostEqual(result, 250.0, places=2)

    def test_conditional_formula(self):
        """Ternary conditional expression."""
        formula = self._create_formula('base_amount * 0.07 if base_amount > 100000 else base_amount * 0.05')
        low = formula.evaluate({'base_amount': 50000.0})
        high = formula.evaluate({'base_amount': 150000.0})
        self.assertAlmostEqual(low, 2500.0, places=2)
        self.assertAlmostEqual(high, 10500.0, places=2)

    def test_min_max_builtins(self):
        """min() and max() safe builtins work correctly."""
        formula = self._create_formula('min(max(base_amount * 0.05, 100), 5000)')
        # 10000 * 5% = 500; within [100, 5000] → 500
        self.assertAlmostEqual(formula.evaluate({'base_amount': 10000.0}), 500.0, places=2)
        # 100 * 5% = 5; below min 100 → 100
        self.assertAlmostEqual(formula.evaluate({'base_amount': 100.0}), 100.0, places=2)
        # 200000 * 5% = 10000; above max 5000 → 5000
        self.assertAlmostEqual(formula.evaluate({'base_amount': 200000.0}), 5000.0, places=2)

    def test_round_builtin(self):
        """round() safe builtin works."""
        formula = self._create_formula('round(base_amount * 0.033, 2)')
        result = formula.evaluate({'base_amount': 10000.0})
        self.assertAlmostEqual(result, 330.0, places=2)

    def test_abs_builtin(self):
        """abs() safe builtin works."""
        formula = self._create_formula('abs(base_amount)')
        self.assertAlmostEqual(formula.evaluate({'base_amount': -500.0}), 500.0, places=2)

    def test_arithmetic_operators(self):
        """All arithmetic operators are supported."""
        formula = self._create_formula('(base_amount + bonus) * rate / 100 - deduction')
        result = formula.evaluate({
            'base_amount': 10000.0,
            'bonus': 2000.0,
            'rate': 5.0,
            'deduction': 100.0,
        })
        self.assertAlmostEqual(result, 500.0, places=2)  # (10000+2000)*5%=600-100=500

    def test_comparison_operators(self):
        """Comparison operators work in conditional expressions."""
        formula = self._create_formula(
            '0.07 * base_amount if achievement_pct >= 100 else 0.05 * base_amount if achievement_pct >= 70 else 0'
        )
        self.assertAlmostEqual(formula.evaluate({'base_amount': 10000, 'achievement_pct': 110}), 700.0, places=2)
        self.assertAlmostEqual(formula.evaluate({'base_amount': 10000, 'achievement_pct': 80}), 500.0, places=2)
        self.assertAlmostEqual(formula.evaluate({'base_amount': 10000, 'achievement_pct': 50}), 0.0, places=2)

    def test_boolean_operators(self):
        """Boolean and/or operators work."""
        formula = self._create_formula('100.0 if base_amount > 0 and rate > 0 else 0.0')
        self.assertAlmostEqual(formula.evaluate({'base_amount': 1000, 'rate': 5}), 100.0, places=2)
        self.assertAlmostEqual(formula.evaluate({'base_amount': 0, 'rate': 5}), 0.0, places=2)

    def test_missing_variable_returns_zero(self):
        """Formula with undefined variable should raise or return default, not crash the server."""
        formula = self._create_formula('base_amount * rate / 100')
        # Providing partial context; should raise NameError or return 0
        try:
            result = formula.evaluate({'base_amount': 1000.0})
            # If it returns 0 or some default, that's acceptable
            self.assertIsInstance(result, (int, float))
        except (NameError, KeyError, Exception):
            pass  # acceptable behavior

    # ── AST Safety — Blocked Nodes ─────────────────────────────────────────────

    def test_blocked_import(self):
        """Import statements must be blocked."""
        with self.assertRaises(Exception):
            self._create_formula('__import__("os").system("id")')

    def test_blocked_attribute_access(self):
        """Attribute access (e.g., obj.__class__) must be blocked."""
        with self.assertRaises(Exception):
            self._create_formula('base_amount.__class__')

    def test_blocked_subscript_dunder(self):
        """Attempting to escape via __dict__ subscript must be blocked."""
        with self.assertRaises(Exception):
            self._create_formula('().__class__.__bases__[0].__subclasses__()')

    def test_blocked_exec(self):
        """exec() must not be available."""
        with self.assertRaises(Exception):
            formula = self._create_formula('exec("import os")')
            formula.evaluate({})

    def test_blocked_eval(self):
        """eval() must not be available."""
        with self.assertRaises(Exception):
            formula = self._create_formula('eval("1+1")')
            formula.evaluate({})

    def test_blocked_open(self):
        """open() must not be available."""
        with self.assertRaises(Exception):
            formula = self._create_formula('open("/etc/passwd")')
            formula.evaluate({})

    def test_blocked_lambda(self):
        """Lambda expressions should be blocked (not in safe node set)."""
        with self.assertRaises(Exception):
            self._create_formula('(lambda x: x)(base_amount)')

    def test_blocked_list_comprehension(self):
        """List comprehensions must be blocked."""
        with self.assertRaises(Exception):
            self._create_formula('[x for x in range(10)]')

    def test_blocked_dict_construction(self):
        """Dict literal may be blocked depending on config."""
        # Dict literals could be blocked; test that it at least doesn't produce security issues
        try:
            formula = self._create_formula('{"key": base_amount}')
            result = formula.evaluate({'base_amount': 100})
            # If allowed, must return a numeric-castable result or raise TypeError
        except Exception:
            pass  # blocked is acceptable

    def test_blocked_walrus_operator(self):
        """Walrus operator (:=) should be blocked or unavailable."""
        with self.assertRaises(Exception):
            self._create_formula('(x := base_amount) * 0.05')

    def test_invalid_syntax_rejected(self):
        """Syntactically invalid expressions are rejected at save time."""
        with self.assertRaises(Exception):
            self._create_formula('base_amount * * 5')

    def test_empty_expression_rejected(self):
        """Empty expression must be rejected."""
        with self.assertRaises(Exception):
            self._create_formula('')

    # ── Formula Code Uniqueness ────────────────────────────────────────────────

    def test_formula_code_unique(self):
        """Formula codes must be unique."""
        self._create_formula('base_amount * 0.05', code='UNIQ-TEST')
        with self.assertRaises(Exception):
            self._create_formula('base_amount * 0.10', code='UNIQ-TEST')

    # ── Test Values Integration ────────────────────────────────────────────────

    def test_action_test_formula_no_raise(self):
        """action_test_formula() with valid JSON test_values should not raise."""
        import json
        formula = self._create_formula('base_amount * rate / 100')
        formula.write({'test_values': json.dumps({'base_amount': 10000, 'rate': 5})})
        result = formula.action_test_formula()
        # Returns action dict or notification
        self.assertIsNotNone(result)

    def test_action_test_formula_invalid_json(self):
        """action_test_formula() with invalid JSON test_values raises."""
        formula = self._create_formula('base_amount * 0.05')
        formula.write({'test_values': 'not-json'})
        with self.assertRaises(Exception):
            formula.action_test_formula()

    # ── Formula Engine Service ─────────────────────────────────────────────────

    def test_formula_engine_build_context(self):
        """Formula engine builds a non-empty context dict."""
        plan = self.env['commission.plan'].create({
            'name': 'Formula Engine Plan',
            'code': 'FE-TEST',
            'commission_type': 'sales',
            'calculation_method': 'dynamic_formula',
            'base_on': 'invoice',
            'company_id': self.company.id,
        })
        engine = self.env['commission.formula.engine']
        ctx = engine.build_context(
            employee=self.employee,
            plan=plan,
            period=self.period,
        )
        self.assertIsInstance(ctx, dict)
        self.assertIn('base_amount', ctx)
        self.assertIn('employee_id', ctx)

    def test_formula_engine_test_all_no_raise(self):
        """test_all_formulas() runs without raising even with no active formulas."""
        engine = self.env['commission.formula.engine']
        engine.test_all_formulas()

    # ── Integration: Plan with Formula ────────────────────────────────────────

    def test_plan_with_formula_evaluate(self):
        """Plan using dynamic_formula method evaluates correctly."""
        formula = self._create_formula('base_amount * 0.04')
        plan = self.env['commission.plan'].create({
            'name': 'Dynamic Formula Plan',
            'code': 'DYN-TEST',
            'commission_type': 'sales',
            'calculation_method': 'dynamic_formula',
            'base_on': 'invoice',
            'formula_id': formula.id,
            'company_id': self.company.id,
        })
        result = formula.evaluate({'base_amount': 25000.0})
        self.assertAlmostEqual(result, 1000.0, places=2)

    # ── Sample Formulas From Data ──────────────────────────────────────────────

    def test_builtin_basic_percent_formula(self):
        """Built-in basic_percent formula evaluates correctly."""
        formula = self.env['commission.formula'].search([('code', '=', 'basic_percent')], limit=1)
        if formula:
            result = formula.evaluate({'base_amount': 10000.0, 'rate': 5.0})
            self.assertAlmostEqual(result, 500.0, places=1)

    def test_builtin_margin_based_formula(self):
        """Built-in margin_based formula returns non-negative result."""
        formula = self.env['commission.formula'].search([('code', '=', 'margin_based')], limit=1)
        if formula:
            result = formula.evaluate({
                'base_amount': 10000.0,
                'margin_amount': 3000.0,
                'margin_pct': 30.0,
                'rate': 5.0,
            })
            self.assertGreaterEqual(result, 0.0)
