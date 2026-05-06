# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError
from ..services.formula_engine import FormulaEngine
import datetime


class TestFormulaEngine(TransactionCase):
    """Tests for the FormulaEngine service."""

    def setUp(self):
        super().setUp()
        self.engine = FormulaEngine(self.env)

    def test_basic_formula(self):
        """Test basic arithmetic formula."""
        result = self.engine.evaluate('amount * rate / 100', {'amount': 1000, 'rate': 5})
        self.assertAlmostEqual(result, 50.0, places=4)

    def test_formula_with_min_max(self):
        """Test formula using min/max builtins."""
        result = self.engine.evaluate('min(amount * rate / 100, 100)', {'amount': 1000, 'rate': 20})
        self.assertAlmostEqual(result, 100.0, places=4)

    def test_formula_with_if_expression(self):
        """Test conditional formula."""
        result = self.engine.evaluate(
            'amount * 0.1 if amount > 5000 else amount * 0.05',
            {'amount': 10000, 'rate': 5}
        )
        self.assertAlmostEqual(result, 1000.0, places=4)

    def test_formula_zero_division(self):
        """Test that division by zero returns 0."""
        result = self.engine.evaluate('amount / 0', {'amount': 100})
        self.assertEqual(result, 0.0)

    def test_unsafe_formula_import(self):
        """Test that import is blocked."""
        with self.assertRaises(Exception):
            self.engine.validate('__import__("os").system("ls")')

    def test_unsafe_formula_exec(self):
        """Test that exec-like patterns are blocked."""
        with self.assertRaises(Exception):
            self.engine.validate('open("/etc/passwd").read()')

    def test_formula_with_margin(self):
        """Test formula using margin."""
        result = self.engine.evaluate(
            'amount * rate / 100 * (1 + margin_percent)',
            {'amount': 10000, 'rate': 5, 'margin_percent': 0.3}
        )
        self.assertAlmostEqual(result, 650.0, places=4)

    def test_formula_math_functions(self):
        """Test math functions in formula."""
        result = self.engine.evaluate('round(sqrt(amount), 2)', {'amount': 100})
        self.assertAlmostEqual(result, 10.0, places=4)

    def test_validate_valid_formula(self):
        """Test that valid formula passes validation."""
        self.assertTrue(self.engine.validate('amount * rate / 100'))

    def test_validate_empty_formula(self):
        """Test that empty formula fails validation."""
        with self.assertRaises(Exception):
            self.engine.validate('')


class TestCommissionEngine(TransactionCase):
    """Tests for commission.engine service model."""

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.engine = self.env['commission.engine']

        # Create employee with user
        self.user = self.env['res.users'].create({
            'name': 'Test Sales User',
            'login': 'test_sales_commission',
            'email': 'test_sales@example.com',
            'groups_id': [(4, self.env.ref('sales_team.group_sale_salesman').id)],
        })
        self.employee = self.env['hr.employee'].create({
            'name': 'Test Sales Employee',
            'user_id': self.user.id,
            'company_id': self.company.id,
        })

        # Create commission plan
        self.plan = self.env['commission.plan'].create({
            'name': 'Engine Test Plan',
            'plan_type': 'fixed_percent',
            'fixed_rate': 5.0,
            'base_metric': 'invoiced_amount',
            'commission_base': 'pre_tax',
            'trigger_type': 'invoice_validate',
            'settlement_method': 'payroll',
            'date_from': datetime.date.today().replace(month=1, day=1),
            'assignment_type': 'all',
            'company_id': self.company.id,
        })

        # Create period
        today = datetime.date.today()
        self.period = self.env['commission.period'].create({
            'name': 'Test Period',
            'period_type': 'monthly',
            'date_from': today.replace(day=1),
            'date_to': (today.replace(day=1) + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1),
            'company_id': self.company.id,
        })

    def test_generate_settlements(self):
        """Test automatic settlement generation."""
        # Create validated commission lines
        self.env['commission.line'].create([
            {
                'name': 'Test Commission 1',
                'employee_id': self.employee.id,
                'period_id': self.period.id,
                'plan_id': self.plan.id,
                'date': datetime.date.today(),
                'line_type': 'commission',
                'base_amount': 10000,
                'rate': 5.0,
                'commission_amount': 500.0,
                'company_id': self.company.id,
                'currency_id': self.company.currency_id.id,
                'state': 'validated',
            },
            {
                'name': 'Test Commission 2',
                'employee_id': self.employee.id,
                'period_id': self.period.id,
                'plan_id': self.plan.id,
                'date': datetime.date.today(),
                'line_type': 'commission',
                'base_amount': 5000,
                'rate': 5.0,
                'commission_amount': 250.0,
                'company_id': self.company.id,
                'currency_id': self.company.currency_id.id,
                'state': 'validated',
            },
        ])
        settlements = self.engine.generate_settlements(self.period)
        self.assertEqual(len(settlements), 1)
        settlement = settlements[0]
        self.assertEqual(settlement.employee_id, self.employee)
        self.assertAlmostEqual(settlement.gross_commission, 750.0, places=2)

    def test_recalculate_lines(self):
        """Test commission line recalculation."""
        line = self.env['commission.line'].create({
            'name': 'Test Recalc Line',
            'employee_id': self.employee.id,
            'period_id': self.period.id,
            'plan_id': self.plan.id,
            'date': datetime.date.today(),
            'line_type': 'commission',
            'base_amount': 10000,
            'rate': 5.0,
            'commission_amount': 100.0,  # Wrong amount
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'state': 'draft',
        })
        adjusted = self.engine.recalculate(line)
        self.assertIn(line, adjusted)
        self.assertAlmostEqual(line.commission_amount, 500.0, places=2)

    def test_rollback_period(self):
        """Test rollback of commission lines."""
        lines = self.env['commission.line'].create([
            {
                'name': 'Line %d' % i,
                'employee_id': self.employee.id,
                'period_id': self.period.id,
                'plan_id': self.plan.id,
                'date': datetime.date.today(),
                'line_type': 'commission',
                'base_amount': 1000,
                'rate': 5.0,
                'commission_amount': 50.0,
                'company_id': self.company.id,
                'currency_id': self.company.currency_id.id,
                'state': 'draft',
            } for i in range(3)
        ])
        count = self.engine.rollback_period(self.period)
        self.assertEqual(count, 3)
        for line in lines:
            self.assertEqual(line.state, 'cancelled')
