# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
import datetime


class TestCommissionSettlement(TransactionCase):
    """Tests for commission settlement workflow."""

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        # Add commission groups to current user for approval tests
        manager_group = self.env.ref('advanced_commission_engine.group_commission_manager', raise_if_not_found=False)
        finance_group = self.env.ref('advanced_commission_engine.group_commission_finance', raise_if_not_found=False)
        if manager_group:
            self.env.user.sudo().write({'group_ids': [(4, manager_group.id)]})
        if finance_group:
            self.env.user.sudo().write({'group_ids': [(4, finance_group.id)]})

        self.employee = self.env['hr.employee'].create({
            'name': 'Settlement Test Employee',
            'company_id': self.company.id,
        })
        self.plan = self.env['commission.plan'].create({
            'name': 'Settlement Test Plan',
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
        today = datetime.date.today()
        self.period = self.env['commission.period'].create({
            'name': 'Settlement Test Period',
            'period_type': 'monthly',
            'date_from': today.replace(day=1),
            'date_to': (today.replace(day=1) + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1),
            'company_id': self.company.id,
        })
        self.settlement = self.env['commission.settlement'].create({
            'period_id': self.period.id,
            'plan_id': self.plan.id,
            'employee_id': self.employee.id,
            'settlement_method': 'payroll',
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
        })
        self.line = self.env['commission.line'].create({
            'name': 'Test Commission',
            'employee_id': self.employee.id,
            'period_id': self.period.id,
            'plan_id': self.plan.id,
            'settlement_id': self.settlement.id,
            'date': datetime.date.today(),
            'line_type': 'commission',
            'base_amount': 10000,
            'rate': 5.0,
            'commission_amount': 500.0,
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'state': 'validated',
        })

    def test_settlement_creation(self):
        """Test settlement is created with correct reference."""
        self.assertIsNotNone(self.settlement.id)
        self.assertNotEqual(self.settlement.name, '/')

    def test_settlement_amounts(self):
        """Test that settlement totals compute correctly."""
        self.assertAlmostEqual(self.settlement.gross_commission, 500.0, places=2)
        self.assertAlmostEqual(self.settlement.net_commission, 500.0, places=2)

    def test_settlement_submit(self):
        """Test submission workflow."""
        self.settlement.action_submit()
        self.assertEqual(self.settlement.state, 'submitted')
        self.assertEqual(self.settlement.submitted_by.id, self.env.uid)

    def test_settlement_cannot_submit_without_lines(self):
        """Test that empty settlement cannot be submitted."""
        empty_settlement = self.env['commission.settlement'].create({
            'period_id': self.period.id,
            'plan_id': self.plan.id,
            'employee_id': self.employee.id,
            'settlement_method': 'payroll',
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
        })
        with self.assertRaises(UserError):
            empty_settlement.action_submit()

    def test_settlement_full_approval_flow(self):
        """Test the full approval workflow."""
        self.settlement.action_submit()
        self.assertEqual(self.settlement.state, 'submitted')

        self.settlement.action_manager_approve()
        self.assertEqual(self.settlement.state, 'manager_approved')

        self.settlement.action_finance_approve()
        self.assertEqual(self.settlement.state, 'finance_approved')

        self.settlement.action_final_approve()
        self.assertEqual(self.settlement.state, 'approved')

    def test_settlement_rejection(self):
        """Test rejection workflow."""
        self.settlement.action_submit()
        self.settlement.action_reject('Test rejection reason')
        self.assertEqual(self.settlement.state, 'rejected')

    def test_settlement_reset_to_draft(self):
        """Test reset to draft after rejection."""
        self.settlement.action_submit()
        self.settlement.action_reject('Rejected for testing')
        self.settlement.action_reset_to_draft()
        self.assertEqual(self.settlement.state, 'draft')


class TestCommissionPeriod(TransactionCase):
    """Tests for commission.period model."""

    def setUp(self):
        super().setUp()
        self.company = self.env.company

    def test_period_generation_monthly(self):
        """Test auto-generation of monthly periods."""
        # Use a far-future year to avoid conflicts with demo data periods
        periods = self.env['commission.period'].generate_periods(
            'monthly', 2099, company_id=self.company.id
        )
        self.assertEqual(len(periods), 12)

    def test_period_generation_quarterly(self):
        """Test auto-generation of quarterly periods."""
        # Use a far-future year to avoid conflicts with demo data periods
        periods = self.env['commission.period'].generate_periods(
            'quarterly', 2099, company_id=self.company.id
        )
        self.assertEqual(len(periods), 4)

    def test_period_lock(self):
        """Test period locking."""
        period = self.env['commission.period'].create({
            'name': 'Lock Test',
            'period_type': 'monthly',
            'date_from': datetime.date.today().replace(day=1),
            'date_to': datetime.date.today(),
            'company_id': self.company.id,
        })
        period.action_lock()
        self.assertEqual(period.state, 'locked')
        self.assertTrue(period.locked_by)

    def test_period_cannot_lock_twice(self):
        """Test that a locked period cannot be locked again."""
        period = self.env['commission.period'].create({
            'name': 'Double Lock Test',
            'period_type': 'monthly',
            'date_from': datetime.date.today().replace(day=1),
            'date_to': datetime.date.today(),
            'company_id': self.company.id,
        })
        period.action_lock()
        with self.assertRaises(UserError):
            period.action_lock()

    def test_invalid_date_range(self):
        """Test that date_from > date_to raises ValidationError."""
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.env['commission.period'].create({
                'name': 'Bad Period',
                'period_type': 'monthly',
                'date_from': datetime.date(2025, 12, 31),
                'date_to': datetime.date(2025, 1, 1),
                'company_id': self.company.id,
            })


class TestCommissionAdjustment(TransactionCase):
    """Tests for commission.adjustment workflow."""

    def setUp(self):
        super().setUp()
        self.company = self.env.company
        # Add commission manager group for approval tests
        manager_group = self.env.ref('advanced_commission_engine.group_commission_manager', raise_if_not_found=False)
        if manager_group:
            self.env.user.sudo().write({'group_ids': [(4, manager_group.id)]})
        self.employee = self.env['hr.employee'].create({
            'name': 'Adjustment Test Employee',
            'company_id': self.company.id,
        })
        self.plan = self.env['commission.plan'].create({
            'name': 'Adj Test Plan',
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
        today = datetime.date.today()
        self.period = self.env['commission.period'].create({
            'name': 'Adj Test Period',
            'period_type': 'monthly',
            'date_from': today.replace(day=1),
            'date_to': (today.replace(day=1) + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1),
            'company_id': self.company.id,
        })

    def test_adjustment_create_and_apply(self):
        """Test creating and applying an adjustment."""
        adj = self.env['commission.adjustment'].create({
            'employee_id': self.employee.id,
            'plan_id': self.plan.id,
            'period_id': self.period.id,
            'adjustment_type': 'manual_bonus',
            'amount': 500.0,
            'sign': 'positive',
            'reason': 'Test bonus',
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
        })
        self.assertAlmostEqual(adj.effective_amount, 500.0, places=2)
        adj.action_submit()
        adj.action_approve()
        adj.action_apply()
        self.assertEqual(adj.state, 'applied')
        self.assertTrue(adj.resulting_line_id)
        self.assertAlmostEqual(adj.resulting_line_id.commission_amount, 500.0, places=2)

    def test_negative_adjustment(self):
        """Test negative adjustment (deduction)."""
        adj = self.env['commission.adjustment'].create({
            'employee_id': self.employee.id,
            'plan_id': self.plan.id,
            'period_id': self.period.id,
            'adjustment_type': 'deduction',
            'amount': 100.0,
            'sign': 'negative',
            'reason': 'Test deduction',
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
        })
        self.assertAlmostEqual(adj.effective_amount, -100.0, places=2)
