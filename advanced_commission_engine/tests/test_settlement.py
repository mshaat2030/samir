# -*- coding: utf-8 -*-
"""Tests for commission settlement lifecycle, state machine, and workflow."""

from datetime import date

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install', 'commission', 'commission_settlement')
class TestCommissionSettlement(TransactionCase):
    """Tests for settlement state machine and lifecycle transitions."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        # Groups
        cls.group_manager = cls.env.ref(
            'advanced_commission_engine.group_commission_manager'
        )
        cls.group_finance = cls.env.ref(
            'advanced_commission_engine.group_commission_finance_manager'
        )
        cls.group_admin = cls.env.ref(
            'advanced_commission_engine.group_commission_admin'
        )

        # Create manager user
        cls.manager_user = cls.env['res.users'].create({
            'name': 'Commission Manager',
            'login': 'commission_manager_test',
            'email': 'cm@test.com',
            'group_ids': [(4, cls.group_manager.id), (4, cls.group_finance.id), (4, cls.group_admin.id)],
        })

        cls.employee = cls.env['hr.employee'].create({
            'name': 'Settlement Test Employee',
            'user_id': cls.manager_user.id,
            'company_id': cls.company.id,
        })

        today = date.today()
        cls.period = cls.env['commission.period'].create({
            'name': 'Settlement Test Period',
            'period_type': 'monthly',
            'date_start': today.replace(day=1),
            'date_end': today.replace(day=28),
            'company_id': cls.company.id,
        })

        cls.plan = cls.env['commission.plan'].create({
            'name': 'Settlement Test Plan',
            'commission_type': 'sales',
            'calculation_method': 'fixed_percent',
            'period_type': 'monthly',
            'source_document': 'invoice',
            'state': 'active',
            'approval_required': True,
            'finance_approval_required': True,
            'company_id': cls.company.id,
        })
        cls.env['commission.rule'].create({
            'name': '5% Rule',
            'plan_id': cls.plan.id,
            'rate': 5.0,
        })

    def _make_settlement_with_lines(self, amount=500.0):
        """Create a settlement in 'calculated' state with commission lines."""
        settlement = self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'plan_id': self.plan.id,
            'period_id': self.period.id,
            'company_id': self.company.id,
        })
        self.env['commission.line'].create({
            'settlement_id': settlement.id,
            'source_type': 'invoice',
            'base_amount': amount * 20,
            'commission_rate': 5.0,
            'commission_amount': amount,
            'date': date.today(),
            'state': 'confirmed',
        })
        settlement.write({'state': 'calculated'})
        return settlement

    def test_01_initial_state(self):
        """Settlement starts in draft state."""
        settlement = self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'plan_id': self.plan.id,
            'period_id': self.period.id,
            'company_id': self.company.id,
        })
        self.assertEqual(settlement.state, 'draft')

    def test_02_submit_requires_calculated(self):
        """Submission requires settlement in calculated state."""
        settlement = self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'plan_id': self.plan.id,
            'period_id': self.period.id,
            'company_id': self.company.id,
        })
        with self.assertRaises(UserError):
            settlement.action_submit()

    def test_03_submit_requires_positive_amount(self):
        """Submission requires a positive final amount."""
        settlement = self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'plan_id': self.plan.id,
            'period_id': self.period.id,
            'company_id': self.company.id,
        })
        settlement.write({'state': 'calculated'})
        with self.assertRaises(UserError):
            settlement.action_submit()

    def test_04_full_lifecycle(self):
        """Test the complete draft → paid lifecycle."""
        settlement = self._make_settlement_with_lines(amount=1000.0)

        # Submit
        settlement.with_user(self.manager_user).action_submit()
        self.assertEqual(settlement.state, 'submitted')

        # Approve
        settlement.with_user(self.manager_user).action_approve()
        self.assertEqual(settlement.state, 'approved')

        # Finance Approve
        settlement.with_user(self.manager_user).action_finance_approve()
        self.assertEqual(settlement.state, 'finance_approved')

        # Mark Paid
        settlement.with_user(self.manager_user).action_mark_paid()
        self.assertEqual(settlement.state, 'paid')
        self.assertTrue(settlement.paid_date)

    def test_05_cannot_delete_paid(self):
        """Cannot delete a paid settlement."""
        settlement = self._make_settlement_with_lines()
        settlement.with_user(self.manager_user).action_submit()
        settlement.with_user(self.manager_user).action_approve()
        settlement.with_user(self.manager_user).action_finance_approve()
        settlement.with_user(self.manager_user).action_mark_paid()
        with self.assertRaises(UserError):
            settlement.unlink()

    def test_06_cancellation(self):
        """Test settlement cancellation."""
        settlement = self._make_settlement_with_lines()
        settlement.action_cancel()
        self.assertEqual(settlement.state, 'cancelled')

    def test_07_cannot_cancel_paid(self):
        """Cannot cancel a paid settlement."""
        settlement = self._make_settlement_with_lines()
        settlement.with_user(self.manager_user).action_submit()
        settlement.with_user(self.manager_user).action_approve()
        settlement.with_user(self.manager_user).action_finance_approve()
        settlement.with_user(self.manager_user).action_mark_paid()
        with self.assertRaises(UserError):
            settlement.action_cancel()

    def test_08_dispute_workflow(self):
        """Test dispute raising and resolution."""
        settlement = self._make_settlement_with_lines(amount=500.0)
        settlement.with_user(self.manager_user).action_submit()
        settlement.with_user(self.manager_user).action_approve()

        # Raise dispute
        settlement.action_dispute()
        self.assertEqual(settlement.state, 'disputed')

        # Create dispute record
        dispute = self.env['commission.dispute'].create({
            'settlement_id': settlement.id,
            'reason': 'Incorrect base amount',
            'dispute_type': 'wrong_amount',
            'requested_amount': 600.0,
        })

        # Resolve
        dispute.with_user(self.manager_user).action_resolve_accept()
        self.assertEqual(dispute.state, 'resolved')
        self.assertTrue(dispute.adjustment_id)
        # Settlement should be back to calculated
        self.assertEqual(settlement.state, 'calculated')

    def test_09_adjustment_impact(self):
        """Test that adjustments correctly change final amount."""
        settlement = self._make_settlement_with_lines(amount=1000.0)
        initial_gross = settlement.gross_amount
        self.assertAlmostEqual(initial_gross, 1000.0, places=2)

        self.env['commission.adjustment'].create({
            'name': 'Bonus',
            'settlement_id': settlement.id,
            'adjustment_type': 'bonus',
            'amount': 200.0,
            'reason': 'Excellent performance',
            'state': 'approved',
        })
        self.assertAlmostEqual(settlement.final_amount, 1200.0, places=2)

    def test_10_held_amount_reduces_payable(self):
        """Test that held amount reduces payable amount."""
        settlement = self._make_settlement_with_lines(amount=1000.0)
        self.env['commission.adjustment'].create({
            'name': 'Hold',
            'settlement_id': settlement.id,
            'adjustment_type': 'hold',
            'amount': 300.0,
            'reason': 'Pending verification',
            'state': 'approved',
        })
        self.assertAlmostEqual(settlement.final_amount, 1000.0, places=2)
        self.assertAlmostEqual(settlement.payable_amount, 700.0, places=2)

    def test_11_auto_approve_below_threshold(self):
        """Test auto-approval when settlement is below threshold."""
        auto_plan = self.env['commission.plan'].create({
            'name': 'Auto Approve Plan',
            'commission_type': 'sales',
            'calculation_method': 'fixed_percent',
            'period_type': 'monthly',
            'source_document': 'invoice',
            'state': 'active',
            'approval_required': True,
            'auto_approve_below': 5000.0,
            'company_id': self.company.id,
        })
        self.env['commission.rule'].create({'name': 'R', 'plan_id': auto_plan.id, 'rate': 5.0})
        settlement = self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'plan_id': auto_plan.id,
            'period_id': self.period.id,
            'company_id': self.company.id,
        })
        self.env['commission.line'].create({
            'settlement_id': settlement.id,
            'source_type': 'invoice',
            'base_amount': 5000.0,
            'commission_rate': 5.0,
            'commission_amount': 250.0,  # < threshold 5000
            'date': date.today(),
            'state': 'confirmed',
        })
        settlement.write({'state': 'calculated'})
        settlement.action_submit()
        # Should auto-approve since 250 < 5000
        self.assertEqual(settlement.state, 'approved')
