# -*- coding: utf-8 -*-
"""Unit tests for the commission calculation engine."""

from datetime import date, timedelta

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'commission', 'commission_engine')
class TestCommissionEngine(TransactionCase):
    """Tests for commission plan creation, rule application, and line generation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create company
        cls.company = cls.env.company

        # Create employee with user
        cls.user = cls.env['res.users'].create({
            'name': 'Test Sales User',
            'login': 'test_sales_engine',
            'email': 'test_sales_engine@test.com',
            'group_ids': [(4, cls.env.ref('base.group_user').id)],
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Test Sales Employee',
            'user_id': cls.user.id,
            'company_id': cls.company.id,
        })

        # Create period
        today = date.today()
        cls.period = cls.env['commission.period'].create({
            'name': 'Test Period',
            'period_type': 'monthly',
            'date_start': today.replace(day=1),
            'date_end': today.replace(day=28),
            'company_id': cls.company.id,
        })

        # Create plan with fixed % rule
        cls.plan_fixed = cls.env['commission.plan'].create({
            'name': 'Test Fixed Plan',
            'commission_type': 'sales',
            'calculation_method': 'fixed_percent',
            'period_type': 'monthly',
            'source_document': 'invoice',
            'invoice_state_trigger': 'posted',
            'state': 'active',
            'company_id': cls.company.id,
        })
        cls.rule_5pct = cls.env['commission.rule'].create({
            'name': '5% Rule',
            'plan_id': cls.plan_fixed.id,
            'calculation_method': 'fixed_percent',
            'rate': 5.0,
            'sequence': 10,
        })

        # Create plan with tiered rules
        cls.plan_tiered = cls.env['commission.plan'].create({
            'name': 'Test Tiered Plan',
            'commission_type': 'sales',
            'calculation_method': 'tiered',
            'period_type': 'monthly',
            'source_document': 'invoice',
            'invoice_state_trigger': 'posted',
            'state': 'active',
            'company_id': cls.company.id,
        })
        cls.env['commission.rule'].create({
            'name': '3% up to 10k',
            'plan_id': cls.plan_tiered.id,
            'calculation_method': 'tiered',
            'rate': 3.0,
            'slab_from': 0,
            'slab_to': 10000,
            'sequence': 10,
        })
        cls.env['commission.rule'].create({
            'name': '5% above 10k',
            'plan_id': cls.plan_tiered.id,
            'calculation_method': 'tiered',
            'rate': 5.0,
            'slab_from': 10000,
            'slab_to': 0,
            'sequence': 20,
        })

    def _create_invoice(self, amount=5000.0):
        """Create a customer invoice for testing."""
        partner = self.env['res.partner'].create({'name': 'Test Customer'})
        product = self.env['product.product'].search([], limit=1)
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_user_id': self.user.id,
            'company_id': self.company.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Test Service',
                'quantity': 1,
                'price_unit': amount,
                'product_id': product.id if product else False,
            })],
        })
        invoice.action_post()
        return invoice

    def test_01_plan_creation(self):
        """Test commission plan creation with required fields."""
        plan = self.env['commission.plan'].create({
            'name': 'Test Creation Plan',
            'commission_type': 'sales',
            'calculation_method': 'fixed_percent',
            'period_type': 'monthly',
            'company_id': self.company.id,
        })
        self.assertTrue(plan.id)
        self.assertEqual(plan.state, 'draft')
        self.assertTrue(plan.code, 'Code should be auto-generated')

    def test_02_plan_activation(self):
        """Test plan activation requires at least one rule."""
        plan = self.env['commission.plan'].create({
            'name': 'Plan No Rules',
            'commission_type': 'sales',
            'calculation_method': 'fixed_percent',
            'period_type': 'monthly',
            'company_id': self.company.id,
        })
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            plan.action_activate()

        self.env['commission.rule'].create({
            'name': 'Rule',
            'plan_id': plan.id,
            'rate': 5.0,
        })
        plan.action_activate()
        self.assertEqual(plan.state, 'active')

    def test_03_fixed_percent_calculation(self):
        """Test commission calculation with fixed percentage rule."""
        rule = self.rule_5pct
        result = rule.compute_commission(10000.0)
        self.assertAlmostEqual(result, 500.0, places=2)

    def test_04_tiered_calculation(self):
        """Test tiered commission calculation."""
        # 15000: 3% on first 10000 = 300, 5% on next 5000 = 250, total = 550
        rules = self.plan_tiered.rule_ids.sorted('sequence')
        rule_low = rules[0]  # 3% up to 10k
        rule_high = rules[1]  # 5% above 10k

        # Rule low: slab portion is min(15000, 10000) - 0 = 10000
        low_base = rule_low._get_slab_portion(15000)
        self.assertAlmostEqual(low_base, 10000.0, places=2)

        high_base = rule_high._get_slab_portion(15000)
        self.assertAlmostEqual(high_base, 5000.0, places=2)

        low_commission = rule_low.compute_commission(15000)
        high_commission = rule_high.compute_commission(15000)

        self.assertAlmostEqual(low_commission, 300.0, places=2)
        self.assertAlmostEqual(high_commission, 250.0, places=2)

    def test_05_settlement_creation(self):
        """Test settlement creation."""
        settlement = self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'plan_id': self.plan_fixed.id,
            'period_id': self.period.id,
            'company_id': self.company.id,
        })
        self.assertNotEqual(settlement.name, '/')
        self.assertEqual(settlement.state, 'draft')

    def test_06_settlement_uniqueness(self):
        """Test that duplicate settlements are prevented."""
        self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'plan_id': self.plan_fixed.id,
            'period_id': self.period.id,
            'company_id': self.company.id,
        })
        from odoo.exceptions import ValidationError
        with self.assertRaises(Exception):
            self.env['commission.settlement'].create({
                'employee_id': self.employee.id,
                'plan_id': self.plan_fixed.id,
                'period_id': self.period.id,
                'company_id': self.company.id,
            })

    def test_07_commission_line_amounts(self):
        """Test commission line amount computation."""
        settlement = self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'plan_id': self.plan_fixed.id,
            'period_id': self.period.id,
            'company_id': self.company.id,
        })
        self.env['commission.line'].create({
            'settlement_id': settlement.id,
            'source_type': 'invoice',
            'base_amount': 10000.0,
            'commission_rate': 5.0,
            'commission_amount': 500.0,
            'date': date.today(),
            'state': 'confirmed',
        })
        self.assertAlmostEqual(settlement.gross_amount, 500.0, places=2)
        self.assertAlmostEqual(settlement.final_amount, 500.0, places=2)

    def test_08_adjustment_computation(self):
        """Test that adjustments are correctly reflected in final amount."""
        settlement = self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'plan_id': self.plan_fixed.id,
            'period_id': self.period.id,
            'company_id': self.company.id,
        })
        self.env['commission.line'].create({
            'settlement_id': settlement.id,
            'source_type': 'invoice',
            'base_amount': 10000.0,
            'commission_rate': 5.0,
            'commission_amount': 500.0,
            'date': date.today(),
            'state': 'confirmed',
        })
        self.env['commission.adjustment'].create({
            'name': 'Bonus',
            'settlement_id': settlement.id,
            'adjustment_type': 'bonus',
            'amount': 100.0,
            'reason': 'Performance bonus',
            'state': 'approved',
        })
        self.env['commission.adjustment'].create({
            'name': 'Penalty',
            'settlement_id': settlement.id,
            'adjustment_type': 'penalty',
            'amount': 50.0,
            'reason': 'Late delivery',
            'state': 'approved',
        })
        # Gross = 500, +100 bonus, -50 penalty = 550
        self.assertAlmostEqual(settlement.gross_amount, 500.0, places=2)
        self.assertAlmostEqual(settlement.total_adjustment, 50.0, places=2)  # 100 - 50
        self.assertAlmostEqual(settlement.final_amount, 550.0, places=2)

    def test_09_period_auto_creation(self):
        """Test automatic period creation."""
        today = date.today()
        period = self.env['commission.period']._create_period_for_date(
            today, 'monthly', self.company
        )
        if period:
            self.assertEqual(period.period_type, 'monthly')
            self.assertLessEqual(period.date_start, today)
            self.assertGreaterEqual(period.date_end, today)

    def test_10_rule_cap_enforcement(self):
        """Test that rule caps are enforced."""
        rule = self.env['commission.rule'].create({
            'name': 'Capped Rule',
            'plan_id': self.plan_fixed.id,
            'calculation_method': 'fixed_percent',
            'rate': 10.0,
            'cap_amount': 200.0,
            'cap_period': 'per_document',
        })
        # 10% of 5000 = 500, but capped at 200
        result = rule.compute_commission(5000.0)
        self.assertAlmostEqual(result, 200.0, places=2)

    def test_11_collection_delay_penalty(self):
        """Test collection delay penalty application."""
        rule = self.env['commission.rule'].create({
            'name': 'Delay Penalty Rule',
            'plan_id': self.plan_fixed.id,
            'calculation_method': 'fixed_percent',
            'rate': 5.0,
            'apply_delay_penalty': True,
            'delay_penalty_days': 30,
            'delay_penalty_pct': 50.0,
        })
        # No delay: normal commission
        normal = rule.compute_commission(10000.0, {'payment_delay_days': 10})
        self.assertAlmostEqual(normal, 500.0, places=2)

        # 60 day delay (>30): 50% penalty on 500 = 250
        delayed = rule.compute_commission(10000.0, {'payment_delay_days': 60})
        self.assertAlmostEqual(delayed, 250.0, places=2)
