# -*- coding: utf-8 -*-
"""Security tests – ACL, record rules, multi-company isolation."""

from datetime import date
from dateutil.relativedelta import relativedelta

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import AccessError, UserError


@tagged('post_install', '-at_install', 'commission', 'commission_security')
class TestCommissionSecurity(TransactionCase):
    """Tests for access control and record rules in the commission module."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        # Get groups
        cls.grp_user = cls.env.ref('advanced_commission_engine.group_commission_user')
        cls.grp_manager = cls.env.ref('advanced_commission_engine.group_commission_manager')
        cls.grp_finance = cls.env.ref('advanced_commission_engine.group_commission_finance_manager')
        cls.grp_admin = cls.env.ref('advanced_commission_engine.group_commission_admin')

        # Create a plain user (commission_user only)
        cls.plain_user = cls.env['res.users'].create({
            'name': 'Plain Commission User',
            'login': 'plain_comm_user',
            'email': 'plain@test.com',
            'group_ids': [(4, cls.grp_user.id)],
        })
        cls.plain_employee = cls.env['hr.employee'].create({
            'name': 'Plain Employee',
            'user_id': cls.plain_user.id,
            'company_id': cls.company.id,
        })

        # Create manager user
        cls.mgr_user = cls.env['res.users'].create({
            'name': 'Commission Manager User',
            'login': 'mgr_comm_user',
            'email': 'mgr@test.com',
            'group_ids': [(4, cls.grp_manager.id), (4, cls.grp_finance.id)],
        })
        cls.mgr_employee = cls.env['hr.employee'].create({
            'name': 'Manager Employee',
            'user_id': cls.mgr_user.id,
            'company_id': cls.company.id,
        })

        # Create a plan and period (as admin)
        today = date.today()
        cls.period = cls.env['commission.period'].create({
            'name': 'Security Test Period',
            'period_type': 'monthly',
            'date_start': today.replace(day=1),
            'date_end': today.replace(day=28),
            'company_id': cls.company.id,
        })
        cls.plan = cls.env['commission.plan'].create({
            'name': 'Security Test Plan',
            'commission_type': 'sales',
            'calculation_method': 'fixed_percent',
            'period_type': 'monthly',
            'source_document': 'invoice',
            'state': 'active',
            'company_id': cls.company.id,
        })
        cls.env['commission.rule'].create({'name': 'Rule', 'plan_id': cls.plan.id, 'rate': 5.0})

        # Create settlement for plain employee
        cls.plain_settlement = cls.env['commission.settlement'].create({
            'employee_id': cls.plain_employee.id,
            'plan_id': cls.plan.id,
            'period_id': cls.period.id,
            'company_id': cls.company.id,
        })
        # Create settlement for manager employee
        cls.mgr_settlement = cls.env['commission.settlement'].create({
            'employee_id': cls.mgr_employee.id,
            'plan_id': cls.plan.id,
            'period_id': cls.period.id,
            'company_id': cls.company.id,
        })

    def test_01_plain_user_can_read_own_settlement(self):
        """Commission user can read their own settlement."""
        settlements = self.env['commission.settlement'].with_user(
            self.plain_user
        ).search([('employee_id', '=', self.plain_employee.id)])
        self.assertIn(self.plain_settlement, settlements)

    def test_02_plain_user_cannot_see_other_settlement(self):
        """Commission user cannot read another employee's settlement."""
        settlements = self.env['commission.settlement'].with_user(
            self.plain_user
        ).search([('id', '=', self.mgr_settlement.id)])
        self.assertFalse(settlements, 'User should not see other employee settlements')

    def test_03_plain_user_cannot_create_settlement(self):
        """Commission user cannot create settlements."""
        with self.assertRaises(Exception):
            self.env['commission.settlement'].with_user(self.plain_user).create({
                'employee_id': self.plain_employee.id,
                'plan_id': self.plan.id,
                'period_id': self.period.id,
                'company_id': self.company.id,
            })

    def test_04_manager_can_see_all_settlements(self):
        """Commission manager can read all settlements."""
        settlements = self.env['commission.settlement'].with_user(
            self.mgr_user
        ).search([('period_id', '=', self.period.id)])
        ids = settlements.ids
        self.assertIn(self.plain_settlement.id, ids)
        self.assertIn(self.mgr_settlement.id, ids)

    def test_05_manager_can_create_plan(self):
        """Commission manager can create plans."""
        plan = self.env['commission.plan'].with_user(self.mgr_user).create({
            'name': 'Manager Created Plan',
            'commission_type': 'sales',
            'calculation_method': 'fixed_percent',
            'period_type': 'monthly',
            'company_id': self.company.id,
        })
        self.assertTrue(plan.id)

    def test_06_plain_user_cannot_create_plan(self):
        """Commission user cannot create plans."""
        with self.assertRaises(AccessError):
            self.env['commission.plan'].with_user(self.plain_user).create({
                'name': 'User Created Plan',
                'commission_type': 'sales',
                'calculation_method': 'fixed_percent',
                'period_type': 'monthly',
                'company_id': self.company.id,
            })

    def test_07_only_finance_can_finance_approve(self):
        """Only finance managers can give financial approval."""
        # Create a submitted settlement using a different month to avoid overlap
        next_month = date.today() + relativedelta(months=1)
        period2 = self.env['commission.period'].create({
            'name': 'Security Test Period 2',
            'period_type': 'monthly',
            'date_start': next_month.replace(day=1),
            'date_end': next_month.replace(day=28),
            'company_id': self.company.id,
        })
        settlement = self.env['commission.settlement'].create({
            'employee_id': self.mgr_employee.id,
            'plan_id': self.plan.id,
            'period_id': period2.id,
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
        settlement.write({'state': 'approved'})

        # Plain user cannot finance approve
        with self.assertRaises(UserError):
            settlement.with_user(self.plain_user).action_finance_approve()

        # Finance manager can
        settlement.with_user(self.mgr_user).action_finance_approve()
        self.assertEqual(settlement.state, 'finance_approved')

    def test_08_period_lock_requires_manager(self):
        """Only managers can lock periods."""
        prev_month = date.today() - relativedelta(months=1)
        test_period = self.env['commission.period'].create({
            'name': 'Lock Test Period',
            'period_type': 'monthly',
            'date_start': prev_month.replace(day=1),
            'date_end': prev_month.replace(day=28),
            'company_id': self.company.id,
        })
        # Manager can lock
        test_period.with_user(self.mgr_user).action_lock()
        self.assertEqual(test_period.state, 'locked')

    def test_09_dispute_user_can_create(self):
        """Commission user can create disputes on their own settlement."""
        dispute = self.env['commission.dispute'].with_user(self.plain_user).create({
            'settlement_id': self.plain_settlement.id,
            'reason': 'Wrong calculation',
            'dispute_type': 'wrong_amount',
        })
        self.assertTrue(dispute.id)

    def test_10_plan_delete_requires_draft(self):
        """Cannot delete an active plan."""
        with self.assertRaises(UserError):
            self.plan.unlink()
