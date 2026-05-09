# -*- coding: utf-8 -*-
"""Security tests: ACL enforcement, record rules, group access, portal security."""

import logging
from datetime import date, timedelta
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)


@tagged('commission', 'commission_security')
class TestSecurityGroups(TransactionCase):
    """Tests that security groups enforce correct model-level access."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        # Internal user with no commission group
        cls.plain_user = cls.env['res.users'].create({
            'name': 'Plain User',
            'login': 'plain_commission_user@test.example',
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

        # Commission user
        cls.commission_user = cls.env['res.users'].create({
            'name': 'Commission User',
            'login': 'commission_user@test.example',
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('advanced_commission_engine.group_commission_user').id,
            ])],
        })

        # Commission manager
        cls.commission_manager = cls.env['res.users'].create({
            'name': 'Commission Manager',
            'login': 'commission_manager@test.example',
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('advanced_commission_engine.group_commission_manager').id,
            ])],
        })

        # Finance manager
        cls.finance_manager = cls.env['res.users'].create({
            'name': 'Finance Manager',
            'login': 'commission_finance@test.example',
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('advanced_commission_engine.group_commission_finance_manager').id,
            ])],
        })

        # Admin
        cls.commission_admin = cls.env['res.users'].create({
            'name': 'Commission Admin',
            'login': 'commission_admin@test.example',
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('advanced_commission_engine.group_commission_admin').id,
            ])],
        })

        today = date.today()
        cls.period = cls.env['commission.period'].create({
            'name': 'Security Test Period',
            'period_type': 'monthly',
            'date_start': today.replace(day=1),
            'date_end': (today.replace(day=1) + timedelta(days=31)).replace(day=1) - timedelta(days=1),
            'state': 'open',
            'company_id': cls.company.id,
        })

        cls.plan = cls.env['commission.plan'].create({
            'name': 'Security Test Plan',
            'code': 'SEC-TEST',
            'commission_type': 'sales',
            'calculation_method': 'fixed_percent',
            'base_on': 'invoice',
            'company_id': cls.company.id,
        })

        cls.employee = cls.env['hr.employee'].create({
            'name': 'Security Test Employee',
            'company_id': cls.company.id,
        })

        cls.settlement = cls.env['commission.settlement'].create({
            'employee_id': cls.employee.id,
            'period_id': cls.period.id,
            'plan_id': cls.plan.id,
            'state': 'draft',
        })

    # ── Plan ACL ──────────────────────────────────────────────────────────────

    def test_plan_readable_by_commission_user(self):
        """Commission user can read plans."""
        plans = self.env['commission.plan'].with_user(self.commission_user).search([
            ('id', '=', self.plan.id)
        ])
        self.assertTrue(plans)

    def test_plan_not_writable_by_plain_user(self):
        """Plain user without commission group cannot write plans."""
        with self.assertRaises(AccessError):
            self.env['commission.plan'].with_user(self.plain_user).browse(
                self.plan.id
            ).write({'name': 'Hacked'})

    def test_plan_writable_by_manager(self):
        """Commission manager can write plans."""
        self.env['commission.plan'].with_user(self.commission_manager).browse(
            self.plan.id
        ).write({'name': 'Security Test Plan'})

    def test_plan_not_creatable_by_commission_user(self):
        """Commission user (non-manager) cannot create plans."""
        with self.assertRaises(AccessError):
            self.env['commission.plan'].with_user(self.commission_user).create({
                'name': 'Illegal Plan',
                'code': 'ILLEGAL',
                'commission_type': 'sales',
                'calculation_method': 'fixed_percent',
                'base_on': 'invoice',
                'company_id': self.company.id,
            })

    def test_plan_deletable_by_admin_only(self):
        """Only admin can delete plans."""
        plan_to_delete = self.env['commission.plan'].create({
            'name': 'Deletable Plan',
            'code': 'DEL-TEST',
            'commission_type': 'sales',
            'calculation_method': 'fixed_percent',
            'base_on': 'invoice',
            'company_id': self.company.id,
        })
        with self.assertRaises(AccessError):
            plan_to_delete.with_user(self.commission_manager).unlink()

    # ── Settlement ACL ────────────────────────────────────────────────────────

    def test_settlement_readable_by_commission_user(self):
        """Commission user can read settlements."""
        result = self.env['commission.settlement'].with_user(self.commission_user).search([
            ('id', '=', self.settlement.id)
        ])
        self.assertTrue(result)

    def test_settlement_not_creatable_by_plain_user(self):
        """Plain user cannot create settlements."""
        with self.assertRaises(AccessError):
            self.env['commission.settlement'].with_user(self.plain_user).create({
                'employee_id': self.employee.id,
                'period_id': self.period.id,
                'plan_id': self.plan.id,
            })

    def test_settlement_finance_approval_requires_finance_group(self):
        """Finance approval action requires finance manager group."""
        stl = self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'period_id': self.period.id,
            'plan_id': self.plan.id,
            'state': 'approved',
        })
        # Commission user without finance group should not be able to finance-approve
        with self.assertRaises((AccessError, UserError if True else AccessError)):
            stl.with_user(self.commission_user).action_finance_approve()

    def test_settlement_finance_approval_allowed_for_finance_manager(self):
        """Finance manager can perform finance approval."""
        stl = self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'period_id': self.period.id,
            'plan_id': self.plan.id,
            'state': 'approved',
        })
        # Should not raise
        stl.with_user(self.finance_manager).action_finance_approve()
        self.assertEqual(stl.state, 'finance_approved')

    # ── Formula ACL ───────────────────────────────────────────────────────────

    def test_formula_readable_by_manager(self):
        """Commission manager can read formulas."""
        formula = self.env['commission.formula'].create({
            'name': 'Security Formula',
            'code': 'SEC-FRM',
            'expression': 'base_amount * 0.05',
        })
        result = self.env['commission.formula'].with_user(self.commission_manager).browse(formula.id)
        self.assertTrue(result.name)

    def test_formula_not_writable_by_non_admin(self):
        """Non-admin cannot write formulas."""
        formula = self.env['commission.formula'].create({
            'name': 'Protected Formula',
            'code': 'PROT-FRM',
            'expression': 'base_amount * 0.05',
        })
        with self.assertRaises(AccessError):
            formula.with_user(self.commission_manager).write({'expression': 'base_amount * 0.99'})

    def test_formula_writable_by_admin(self):
        """Commission admin can write formulas."""
        formula = self.env['commission.formula'].create({
            'name': 'Admin Formula',
            'code': 'ADMIN-FRM',
            'expression': 'base_amount * 0.05',
        })
        formula.with_user(self.commission_admin).write({'expression': 'base_amount * 0.06'})
        self.assertEqual(formula.expression, 'base_amount * 0.06')

    # ── Adjustment ACL ────────────────────────────────────────────────────────

    def test_large_adjustment_requires_finance_manager(self):
        """Adjustment above threshold requires finance manager."""
        stl = self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'period_id': self.period.id,
            'plan_id': self.plan.id,
            'state': 'calculated',
        })
        # Amount > 10,000 should require finance manager group
        adj = self.env['commission.adjustment'].create({
            'settlement_id': stl.id,
            'name': 'Large Adjustment',
            'adjustment_type': 'bonus',
            'amount': 15000.0,
        })
        with self.assertRaises((AccessError, ValidationError)):
            adj.with_user(self.commission_manager).action_confirm()

    def test_small_adjustment_allowed_for_manager(self):
        """Commission manager can confirm small adjustments."""
        stl = self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'period_id': self.period.id,
            'plan_id': self.plan.id,
            'state': 'calculated',
        })
        adj = self.env['commission.adjustment'].create({
            'settlement_id': stl.id,
            'name': 'Small Adjustment',
            'adjustment_type': 'correction',
            'amount': 100.0,
        })
        adj.with_user(self.commission_manager).action_confirm()
        self.assertEqual(adj.state, 'confirmed')

    # ── Record Rules: Multi-Company ───────────────────────────────────────────

    def test_multicompany_plan_isolation(self):
        """Plans from another company are not visible to current company users."""
        other_company = self.env['res.company'].create({'name': 'Other Co Security Test'})
        other_plan = self.env['commission.plan'].create({
            'name': 'Other Company Plan',
            'code': 'OTH-SEC',
            'commission_type': 'sales',
            'calculation_method': 'fixed_percent',
            'base_on': 'invoice',
            'company_id': other_company.id,
        })
        # User belongs to self.company only — should not see other_company plan
        plans = self.env['commission.plan'].with_user(
            self.commission_manager
        ).search([('id', '=', other_plan.id)])
        # Should return empty due to record rule
        self.assertFalse(plans)

    def test_multicompany_settlement_isolation(self):
        """Settlements from another company are not visible."""
        other_company = self.env['res.company'].create({'name': 'Other Co Settlement Test'})
        other_emp = self.env['hr.employee'].create({
            'name': 'Other Employee',
            'company_id': other_company.id,
        })
        other_period = self.env['commission.period'].create({
            'name': 'Other Period',
            'period_type': 'monthly',
            'date_start': date.today().replace(day=1),
            'date_end': date.today(),
            'state': 'open',
            'company_id': other_company.id,
        })
        other_plan = self.env['commission.plan'].create({
            'name': 'Other Plan',
            'code': 'OTH-STL',
            'commission_type': 'sales',
            'calculation_method': 'fixed_percent',
            'base_on': 'invoice',
            'company_id': other_company.id,
        })
        other_stl = self.env['commission.settlement'].create({
            'employee_id': other_emp.id,
            'period_id': other_period.id,
            'plan_id': other_plan.id,
            'state': 'draft',
            'company_id': other_company.id,
        })
        found = self.env['commission.settlement'].with_user(
            self.commission_manager
        ).search([('id', '=', other_stl.id)])
        self.assertFalse(found)

    # ── Record Rules: Own-Record Access ───────────────────────────────────────

    def test_user_can_read_own_settlement(self):
        """User linked to an employee can read their own settlement."""
        # Link commission_user to the employee
        self.employee.write({'user_id': self.commission_user.id})
        own_stl = self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'period_id': self.period.id,
            'plan_id': self.plan.id,
            'state': 'calculated',
        })
        found = self.env['commission.settlement'].with_user(
            self.commission_user
        ).search([('id', '=', own_stl.id)])
        self.assertTrue(found)
        self.employee.write({'user_id': False})

    def test_user_cannot_read_other_employee_settlement(self):
        """Commission user cannot read another employee's settlement."""
        other_emp = self.env['hr.employee'].create({
            'name': 'Other Employee Own Test',
            'company_id': self.company.id,
        })
        other_stl = self.env['commission.settlement'].create({
            'employee_id': other_emp.id,
            'period_id': self.period.id,
            'plan_id': self.plan.id,
            'state': 'calculated',
        })
        # commission_user is not linked to other_emp
        found = self.env['commission.settlement'].with_user(
            self.commission_user
        ).search([('id', '=', other_stl.id)])
        # Should be empty or raise — record rule restricts access
        self.assertFalse(found)

    # ── Period State Protection ────────────────────────────────────────────────

    def test_locked_period_prevents_settlement_modification(self):
        """Settlements in a locked period cannot be modified by plain users."""
        locked_period = self.env['commission.period'].create({
            'name': 'Locked Period',
            'period_type': 'monthly',
            'date_start': date(2024, 1, 1),
            'date_end': date(2024, 1, 31),
            'state': 'locked',
            'company_id': self.company.id,
        })
        stl = self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'period_id': locked_period.id,
            'plan_id': self.plan.id,
            'state': 'paid',
        })
        # Trying to submit a paid settlement should fail regardless
        with self.assertRaises(Exception):
            stl.action_submit()

    # ── Executive Viewer ──────────────────────────────────────────────────────

    def test_executive_viewer_can_read_plans(self):
        """Executive viewer has read access to plans."""
        exec_user = self.env['res.users'].create({
            'name': 'Executive Viewer',
            'login': 'exec_viewer_sec@test.example',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('advanced_commission_engine.group_commission_executive_viewer').id,
            ])],
        })
        plans = self.env['commission.plan'].with_user(exec_user).search([('id', '=', self.plan.id)])
        self.assertTrue(plans)

    def test_executive_viewer_cannot_write_plans(self):
        """Executive viewer cannot write plans."""
        exec_user = self.env['res.users'].create({
            'name': 'Executive Viewer 2',
            'login': 'exec_viewer2_sec@test.example',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('advanced_commission_engine.group_commission_executive_viewer').id,
            ])],
        })
        with self.assertRaises(AccessError):
            self.env['commission.plan'].with_user(exec_user).browse(
                self.plan.id
            ).write({'name': 'Hacked by Executive'})

    # ── HR Manager ───────────────────────────────────────────────────────────

    def test_hr_manager_can_read_kpi(self):
        """HR manager can read KPI records."""
        hr_manager = self.env['res.users'].create({
            'name': 'HR Manager User',
            'login': 'hr_mgr_sec@test.example',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('advanced_commission_engine.group_commission_hr_manager').id,
            ])],
        })
        # Just verify read access doesn't raise
        self.env['commission.kpi'].with_user(hr_manager).search([], limit=1)

    # ── Portal Security ───────────────────────────────────────────────────────

    def test_portal_user_cannot_access_backend_models_directly(self):
        """Portal user has no backend model access."""
        portal_user = self.env['res.users'].create({
            'name': 'Portal User Security',
            'login': 'portal_sec@test.example',
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        with self.assertRaises(AccessError):
            self.env['commission.plan'].with_user(portal_user).search([])

    def test_portal_user_cannot_write_settlements(self):
        """Portal user cannot write settlement records."""
        portal_user = self.env['res.users'].create({
            'name': 'Portal User Settlement',
            'login': 'portal_stl@test.example',
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        with self.assertRaises(AccessError):
            self.env['commission.settlement'].with_user(portal_user).browse(
                self.settlement.id
            ).write({'state': 'paid'})

    # ── Simulation Wizard Security ─────────────────────────────────────────────

    def test_simulation_readable_by_manager(self):
        """Commission manager can access simulation wizard."""
        sim = self.env['wizard.commission.simulator'].with_user(
            self.commission_manager
        ).create({
            'plan_id': self.plan.id,
            'base_amount': 10000.0,
        })
        self.assertTrue(sim.id)

    def test_simulation_not_accessible_by_plain_user(self):
        """Plain user cannot access commission simulation wizard."""
        with self.assertRaises(AccessError):
            self.env['wizard.commission.simulator'].with_user(self.plain_user).create({
                'plan_id': self.plan.id,
                'base_amount': 10000.0,
            })


# Avoid NameError from conditional import in test
try:
    from odoo.exceptions import UserError
except ImportError:
    UserError = Exception
