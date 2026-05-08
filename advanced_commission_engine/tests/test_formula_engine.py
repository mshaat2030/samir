# -*- coding: utf-8 -*-
"""Tests for the formula engine – safe evaluation and error handling."""

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged('post_install', '-at_install', 'commission', 'commission_formula')
class TestFormulaEngine(TransactionCase):
    """Tests for commission formula creation and evaluation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

    def _get_engine(self):
        from odoo.addons.advanced_commission_engine.services.formula_engine import FormulaEngine
        return FormulaEngine(self.env)

    def test_01_simple_fixed_percent(self):
        """Simple fixed percentage formula."""
        formula = self.env['commission.formula'].create({
            'name': 'Simple 5%',
            'code': 'T01',
            'formula_type': 'python',
            'formula_code': 'result = base_amount * rate / 100',
        })
        engine = self._get_engine()
        result = engine.evaluate(formula, base_amount=10000.0, rate=5.0)
        self.assertAlmostEqual(result, 500.0, places=2)

    def test_02_margin_boosted_formula(self):
        """Formula that boosts commission based on margin."""
        formula = self.env['commission.formula'].create({
            'name': 'Margin Boosted',
            'code': 'T02',
            'formula_type': 'python',
            'formula_code': '''
if margin_pct >= 40:
    boost = 1.5
elif margin_pct >= 25:
    boost = 1.2
else:
    boost = 1.0
result = base_amount * rate / 100 * boost
''',
        })
        engine = self._get_engine()
        # margin = 20% -> boost = 1.0
        r1 = engine.evaluate(formula, base_amount=10000.0, rate=5.0, margin_pct=20.0)
        self.assertAlmostEqual(r1, 500.0, places=2)
        # margin = 30% -> boost = 1.2
        r2 = engine.evaluate(formula, base_amount=10000.0, rate=5.0, margin_pct=30.0)
        self.assertAlmostEqual(r2, 600.0, places=2)
        # margin = 45% -> boost = 1.5
        r3 = engine.evaluate(formula, base_amount=10000.0, rate=5.0, margin_pct=45.0)
        self.assertAlmostEqual(r3, 750.0, places=2)

    def test_03_syntax_error_validation(self):
        """Formula with syntax error should raise ValidationError."""
        with self.assertRaises(ValidationError):
            self.env['commission.formula'].create({
                'name': 'Bad Syntax',
                'code': 'T03',
                'formula_type': 'python',
                'formula_code': 'result = base_amount * (rate / 100',  # missing closing paren
            })

    def test_04_division_by_zero_safety(self):
        """Formula with division by zero should return 0, not crash."""
        formula = self.env['commission.formula'].create({
            'name': 'Div Zero',
            'code': 'T04',
            'formula_type': 'python',
            'formula_code': 'result = base_amount / 0',  # will raise ZeroDivisionError
        })
        engine = self._get_engine()
        result = engine.evaluate(formula, base_amount=1000.0, rate=5.0)
        self.assertEqual(result, 0.0, 'Formula errors should return 0.0')

    def test_05_negative_result_clamped_to_zero(self):
        """Formula returning negative value should be clamped to 0."""
        formula = self.env['commission.formula'].create({
            'name': 'Negative',
            'code': 'T05',
            'formula_type': 'python',
            'formula_code': 'result = -500.0',
        })
        engine = self._get_engine()
        result = engine.evaluate(formula, base_amount=1000.0, rate=5.0)
        self.assertEqual(result, 0.0, 'Negative commission should be clamped to 0')

    def test_06_access_restriction(self):
        """Formula cannot access dangerous builtins."""
        formula = self.env['commission.formula'].create({
            'name': 'OS Access',
            'code': 'T06',
            'formula_type': 'python',
            'formula_code': 'import os; result = 1',
        })
        engine = self._get_engine()
        # Should fail safely and return 0
        result = engine.evaluate(formula, base_amount=1000.0, rate=5.0)
        self.assertEqual(result, 0.0)

    def test_07_attainment_based_formula(self):
        """Formula based on target attainment."""
        formula = self.env['commission.formula'].create({
            'name': 'Attainment Based',
            'code': 'T07',
            'formula_type': 'python',
            'formula_code': '''
if attainment >= 1.0:
    bonus_multiplier = 1.5
elif attainment >= 0.9:
    bonus_multiplier = 1.2
else:
    bonus_multiplier = attainment
result = base_amount * rate / 100 * bonus_multiplier
''',
        })
        engine = self._get_engine()
        # Full attainment
        r1 = engine.evaluate(formula, base_amount=10000.0, rate=5.0, attainment=1.0)
        self.assertAlmostEqual(r1, 750.0, places=2)
        # 95% attainment
        r2 = engine.evaluate(formula, base_amount=10000.0, rate=5.0, attainment=0.95)
        self.assertAlmostEqual(r2, 600.0, places=2)
        # 70% attainment
        r3 = engine.evaluate(formula, base_amount=10000.0, rate=5.0, attainment=0.7)
        self.assertAlmostEqual(r3, 350.0, places=2)

    def test_08_formula_validation_method(self):
        """Test formula validation helper."""
        engine = self._get_engine()
        valid, msg = engine.validate_formula('result = base_amount * rate / 100')
        self.assertTrue(valid)
        self.assertIn('500', msg)  # 10000 * 5 / 100 = 500

        invalid, msg = engine.validate_formula('result = base_amount * rate / (')
        self.assertFalse(invalid)

    def test_09_formula_unique_code(self):
        """Formula code must be unique per company."""
        self.env['commission.formula'].create({
            'name': 'Unique 1',
            'code': 'UNIQ_CODE',
            'formula_type': 'python',
            'formula_code': 'result = base_amount',
        })
        from odoo.exceptions import ValidationError
        with self.assertRaises(Exception):
            self.env['commission.formula'].create({
                'name': 'Unique 2',
                'code': 'UNIQ_CODE',
                'formula_type': 'python',
                'formula_code': 'result = base_amount',
            })
