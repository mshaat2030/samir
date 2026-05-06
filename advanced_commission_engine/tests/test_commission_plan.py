# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError
import datetime


class TestCommissionPlan(TransactionCase):
    """Tests for commission.plan model."""

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.currency = self.company.currency_id

        # Base plan
        self.plan = self.env['commission.plan'].create({
            'name': 'Test Fixed Plan',
            'plan_type': 'fixed_percent',
            'fixed_rate': 5.0,
            'base_metric': 'invoiced_amount',
            'commission_base': 'pre_tax',
            'trigger_type': 'invoice_validate',
            'settlement_method': 'payroll',
            'date_from': datetime.date.today(),
            'assignment_type': 'all',
            'company_id': self.company.id,
        })

    def test_plan_creation(self):
        """Test that a commission plan can be created."""
        self.assertIsNotNone(self.plan.id)
        self.assertEqual(self.plan.name, 'Test Fixed Plan')
        self.assertEqual(self.plan.plan_type, 'fixed_percent')
        self.assertEqual(self.plan.fixed_rate, 5.0)

    def test_plan_code_auto_generated(self):
        """Test that plan code is auto-generated."""
        self.assertTrue(self.plan.code)
        self.assertNotEqual(self.plan.code, '/')

    def test_compute_commission_fixed(self):
        """Test fixed percentage commission calculation."""
        commission = self.plan.compute_commission(10000.0)
        self.assertAlmostEqual(commission, 500.0, places=2)

    def test_compute_commission_zero_amount(self):
        """Test that zero amount yields zero commission."""
        commission = self.plan.compute_commission(0.0)
        self.assertEqual(commission, 0.0)

    def test_compute_commission_with_cap(self):
        """Test commission respects the cap."""
        self.plan.write({'has_cap': True, 'cap_amount': 100.0})
        commission = self.plan.compute_commission(10000.0)
        self.assertAlmostEqual(commission, 100.0, places=2)

    def test_compute_commission_with_floor(self):
        """Test commission respects the floor."""
        self.plan.write({'has_floor': True, 'floor_amount': 200.0})
        commission = self.plan.compute_commission(100.0)  # Would be 5.0
        self.assertAlmostEqual(commission, 200.0, places=2)

    def test_invalid_date_range(self):
        """Test that invalid date range raises ValidationError."""
        with self.assertRaises(ValidationError):
            self.env['commission.plan'].create({
                'name': 'Bad Date Plan',
                'plan_type': 'fixed_percent',
                'fixed_rate': 5.0,
                'base_metric': 'invoiced_amount',
                'commission_base': 'pre_tax',
                'trigger_type': 'invoice_validate',
                'settlement_method': 'payroll',
                'date_from': datetime.date(2025, 12, 31),
                'date_to': datetime.date(2025, 1, 1),
                'assignment_type': 'all',
                'company_id': self.company.id,
            })

    def test_invalid_fixed_rate(self):
        """Test that rate > 100 raises ValidationError."""
        with self.assertRaises(ValidationError):
            self.env['commission.plan'].create({
                'name': 'Bad Rate Plan',
                'plan_type': 'fixed_percent',
                'fixed_rate': 150.0,
                'base_metric': 'invoiced_amount',
                'commission_base': 'pre_tax',
                'trigger_type': 'invoice_validate',
                'settlement_method': 'payroll',
                'date_from': datetime.date.today(),
                'assignment_type': 'all',
                'company_id': self.company.id,
            })

    def test_formula_plan(self):
        """Test formula-based commission."""
        plan = self.env['commission.plan'].create({
            'name': 'Formula Plan Test',
            'plan_type': 'formula',
            'formula': 'amount * 0.05 + 100',
            'fixed_rate': 5.0,
            'base_metric': 'invoiced_amount',
            'commission_base': 'pre_tax',
            'trigger_type': 'invoice_validate',
            'settlement_method': 'payroll',
            'date_from': datetime.date.today(),
            'assignment_type': 'all',
            'company_id': self.company.id,
        })
        commission = plan.compute_commission(1000.0)
        self.assertAlmostEqual(commission, 150.0, places=2)

    def test_tiered_plan(self):
        """Test tiered commission calculation."""
        plan = self.env['commission.plan'].create({
            'name': 'Tiered Plan Test',
            'plan_type': 'tiered',
            'fixed_rate': 3.0,
            'base_metric': 'invoiced_amount',
            'commission_base': 'pre_tax',
            'trigger_type': 'invoice_validate',
            'settlement_method': 'payroll',
            'date_from': datetime.date.today(),
            'assignment_type': 'all',
            'company_id': self.company.id,
        })
        # Add tier rules
        self.env['commission.rule'].create([
            {
                'plan_id': plan.id,
                'name': 'Tier 1',
                'rule_type': 'tier',
                'from_amount': 0,
                'to_amount': 10000,
                'rate': 3.0,
                'priority': 10,
            },
            {
                'plan_id': plan.id,
                'name': 'Tier 2',
                'rule_type': 'tier',
                'from_amount': 10000,
                'to_amount': 0,
                'rate': 5.0,
                'priority': 20,
            },
        ])
        # 10k at 3% + 5k at 5% = 300 + 250 = 550
        commission = plan.compute_commission(15000.0)
        self.assertAlmostEqual(commission, 550.0, places=2)

    def test_new_version(self):
        """Test plan versioning."""
        old_id = self.plan.id
        self.plan.action_new_version()
        # Old plan should be archived
        self.assertFalse(self.plan.active)
        # Find new version
        new_plan = self.env['commission.plan'].search([
            ('parent_plan_id', '=', old_id)
        ], limit=1)
        self.assertTrue(new_plan)
        self.assertEqual(new_plan.version, self.plan.version + 1)

    def test_duplicate_code_constraint(self):
        """Test unique code constraint within company."""
        with self.assertRaises(Exception):
            self.env['commission.plan'].create({
                'name': 'Duplicate Code Plan',
                'code': self.plan.code,
                'plan_type': 'fixed_percent',
                'fixed_rate': 5.0,
                'base_metric': 'invoiced_amount',
                'commission_base': 'pre_tax',
                'trigger_type': 'invoice_validate',
                'settlement_method': 'payroll',
                'date_from': datetime.date.today(),
                'assignment_type': 'all',
                'company_id': self.company.id,
            })
