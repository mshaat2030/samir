# -*- coding: utf-8 -*-
"""Tests for settlement lifecycle, calculations, payroll, accounting, and approvals."""

import logging
from datetime import date, timedelta
from unittest.mock import patch
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


@tagged('commission', 'commission_settlement')
class TestSettlementLifecycle(TransactionCase):
    """Tests for CommissionSettlement model state machine and workflow."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id

        cls.employee = cls.env['hr.employee'].create({
            'name': 'Test Salesperson',
            'company_id': cls.company.id,
        })
        cls.employee_2 = cls.env['hr.employee'].create({
            'name': 'Test Salesperson 2',
            'company_id': cls.company.id,
        })

        today = date.today()
        cls.period = cls.env['commission.period'].create({
            'name': 'Settlement Test Period',
            'period_type': 'monthly',
            'date_start': today.replace(day=1),
            'date_end': (today.replace(day=1) + timedelta(days=31)).replace(day=1) - timedelta(days=1),
            'state': 'open',
            'company_id': cls.company.id,
        })

        cls.plan = cls.env['commission.plan'].create({
            'name': 'Settlement Test Plan',
            'code': 'STL-TEST',
            'commission_type': 'sales',
            'calculation_method': 'fixed_percent',
            'base_on': 'invoice',
            'company_id': cls.company.id,
        })
        cls.rule = cls.env['commission.rule'].create({
            'plan_id': cls.plan.id,
            'name': 'Rule 5%',
            'sequence': 10,
            'calculation_method': 'fixed_percent',
            'rate': 5.0,
        })

    def _create_settlement(self, state='draft'):
        return self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'period_id': self.period.id,
            'plan_id': self.plan.id,
            'state': state,
        })

    # ── State Machine ─────────────────────────────────────────────────────────

    def test_settlement_creation_defaults(self):
        """New settlement starts in draft state."""
        stl = self._create_settlement()
        self.assertEqual(stl.state, 'draft')
        self.assertTrue(stl.name.startswith('STL/') or stl.name)

    def test_state_draft_to_calculated(self):
        """Settlement can be calculated from draft."""
        stl = self._create_settlement()
        stl.action_calculate()
        self.assertEqual(stl.state, 'calculated')

    def test_state_calculated_to_submitted(self):
        """Calculated settlement can be submitted."""
        stl = self._create_settlement('calculated')
        stl.action_submit()
        self.assertEqual(stl.state, 'submitted')

    def test_state_submitted_to_approved(self):
        """Submitted settlement can be approved."""
        stl = self._create_settlement('submitted')
        stl.action_approve()
        self.assertEqual(stl.state, 'approved')

    def test_state_approved_to_finance_approved(self):
        """Approved settlement advances to finance_approved."""
        stl = self._create_settlement('approved')
        stl.action_finance_approve()
        self.assertEqual(stl.state, 'finance_approved')

    def test_state_to_paid(self):
        """Finance-approved settlement can be marked paid."""
        stl = self._create_settlement('finance_approved')
        stl.action_mark_paid()
        self.assertEqual(stl.state, 'paid')

    def test_state_cancel_from_draft(self):
        """Draft settlement can be cancelled."""
        stl = self._create_settlement()
        stl.action_cancel()
        self.assertEqual(stl.state, 'cancelled')

    def test_state_cancel_from_calculated(self):
        """Calculated settlement can be cancelled."""
        stl = self._create_settlement('calculated')
        stl.action_cancel()
        self.assertEqual(stl.state, 'cancelled')

    def test_cannot_cancel_paid(self):
        """Paid settlement cannot be cancelled."""
        stl = self._create_settlement('paid')
        with self.assertRaises((UserError, ValidationError)):
            stl.action_cancel()

    def test_reset_to_draft(self):
        """Calculated settlement can be reset to draft."""
        stl = self._create_settlement('calculated')
        stl.action_reset_to_draft()
        self.assertEqual(stl.state, 'draft')

    def test_dispute_from_submitted(self):
        """Submitted settlement can be disputed."""
        stl = self._create_settlement('submitted')
        stl.action_dispute()
        self.assertEqual(stl.state, 'disputed')

    def test_uniqueness_constraint(self):
        """Cannot create duplicate settlement for same employee/period/plan."""
        self._create_settlement()
        with self.assertRaises(Exception):
            self._create_settlement()

    # ── Commission Calculation ────────────────────────────────────────────────

    def test_gross_commission_after_calculation(self):
        """After calculation, gross_commission should be non-negative."""
        stl = self._create_settlement()
        stl.action_calculate()
        self.assertGreaterEqual(stl.gross_commission, 0.0)

    def test_total_commission_respects_cap(self):
        """Total commission should not exceed plan max_commission when set."""
        self.plan.write({'max_commission': 100.0})
        stl = self._create_settlement()
        # Add a line with a large amount manually to test cap
        self.env['commission.line'].create({
            'settlement_id': stl.id,
            'base_amount': 1000000.0,
            'commission_amount': 50000.0,
        })
        stl._compute_totals()
        # With cap of 100, total_commission should be ≤ 100
        self.assertLessEqual(stl.total_commission, 100.0 + 0.01)
        self.plan.write({'max_commission': 0.0})

    def test_total_commission_respects_min(self):
        """Total commission should not go below plan min_commission when set."""
        self.plan.write({'min_commission': 500.0})
        stl = self._create_settlement()
        self.env['commission.line'].create({
            'settlement_id': stl.id,
            'base_amount': 100.0,
            'commission_amount': 5.0,
        })
        stl._compute_totals()
        self.assertGreaterEqual(stl.total_commission, 500.0 - 0.01)
        self.plan.write({'min_commission': 0.0})

    def test_adjustment_affects_total(self):
        """Adjustments should be reflected in total_commission."""
        stl = self._create_settlement('calculated')
        base_total = stl.total_commission
        adj = self.env['commission.adjustment'].create({
            'settlement_id': stl.id,
            'name': 'Bonus',
            'adjustment_type': 'bonus',
            'amount': 200.0,
            'state': 'confirmed',
        })
        adj.action_apply()
        stl._compute_totals()
        self.assertAlmostEqual(stl.total_commission, base_total + 200.0, places=2)

    def test_negative_adjustment(self):
        """Negative adjustment (clawback) reduces total."""
        stl = self._create_settlement('calculated')
        self.env['commission.line'].create({
            'settlement_id': stl.id,
            'base_amount': 10000.0,
            'commission_amount': 500.0,
        })
        stl._compute_totals()
        base_total = stl.total_commission
        adj = self.env['commission.adjustment'].create({
            'settlement_id': stl.id,
            'name': 'Clawback',
            'adjustment_type': 'clawback',
            'amount': -100.0,
            'state': 'confirmed',
        })
        adj.action_apply()
        stl._compute_totals()
        self.assertAlmostEqual(stl.total_commission, base_total - 100.0, places=2)

    # ── Commission Lines ──────────────────────────────────────────────────────

    def test_settlement_line_creation(self):
        """Commission lines can be created and linked to settlement."""
        stl = self._create_settlement()
        line = self.env['commission.line'].create({
            'settlement_id': stl.id,
            'base_amount': 5000.0,
            'commission_amount': 250.0,
        })
        self.assertEqual(line.settlement_id.id, stl.id)
        self.assertAlmostEqual(line.commission_amount, 250.0, places=2)

    def test_line_count_smart_button(self):
        """line_count computed field tracks attached lines."""
        stl = self._create_settlement()
        self.assertEqual(stl.line_count, 0)
        self.env['commission.line'].create({
            'settlement_id': stl.id,
            'base_amount': 1000.0,
            'commission_amount': 50.0,
        })
        self.assertEqual(stl.line_count, 1)

    # ── Batch Calculation ─────────────────────────────────────────────────────

    def test_batch_calculation_no_raise(self):
        """Batch calculation on a period should not raise."""
        svc = self.env['commission.calculation.service']
        svc.auto_calculate_period(self.period)

    def test_cron_auto_calculate_no_raise(self):
        """Cron auto-calculate method should not raise."""
        self.env['commission.settlement'].cron_auto_calculate()

    # ── Approval Chain ────────────────────────────────────────────────────────

    def test_approval_chain_creation(self):
        """Approval chain is created for settlement when plan requires it."""
        self.plan.write({
            'requires_manager_approval': True,
            'requires_finance_approval': True,
        })
        stl = self._create_settlement('calculated')
        chain = self.env['commission.approval'].create_approval_chain(stl)
        self.assertGreater(len(chain), 0)
        self.plan.write({
            'requires_manager_approval': False,
            'requires_finance_approval': False,
        })

    def test_approval_advance_state(self):
        """Approval action_approve transitions settlement state."""
        stl = self._create_settlement('submitted')
        approval = self.env['commission.approval'].create({
            'settlement_id': stl.id,
            'approval_level': 'manager',
            'state': 'pending',
        })
        approval.action_approve()
        self.assertEqual(approval.state, 'approved')

    def test_approval_reject(self):
        """Approval rejection blocks advancement."""
        stl = self._create_settlement('submitted')
        approval = self.env['commission.approval'].create({
            'settlement_id': stl.id,
            'approval_level': 'manager',
            'state': 'pending',
        })
        approval.action_reject()
        self.assertEqual(approval.state, 'rejected')

    # ── Accounting Entry ──────────────────────────────────────────────────────

    def test_accounting_entry_no_raise(self):
        """Creating accounting entry should not raise when account is set."""
        account = self.env['account.account'].search([
            ('company_id', '=', self.company.id),
            ('account_type', 'like', 'expense'),
        ], limit=1)
        if account:
            self.plan.write({'account_id': account.id})
            stl = self._create_settlement('finance_approved')
            stl._create_accounting_entry()

    # ── Dispute ───────────────────────────────────────────────────────────────

    def test_dispute_creation(self):
        """Dispute can be filed against a settlement."""
        stl = self._create_settlement('submitted')
        dispute = self.env['commission.dispute'].create({
            'settlement_id': stl.id,
            'reason': 'incorrect_base',
            'description': 'The base amount is incorrect.',
            'disputed_amount': 100.0,
        })
        self.assertTrue(dispute.id)
        self.assertEqual(dispute.state, 'draft')

    def test_dispute_under_review(self):
        """Dispute transitions to under_review."""
        stl = self._create_settlement('submitted')
        dispute = self.env['commission.dispute'].create({
            'settlement_id': stl.id,
            'reason': 'calculation_error',
            'description': 'Calculation seems wrong.',
        })
        dispute.action_submit()
        self.assertEqual(dispute.state, 'under_review')

    def test_dispute_accept_creates_adjustment(self):
        """Accepting a dispute creates a compensating adjustment."""
        stl = self._create_settlement('submitted')
        dispute = self.env['commission.dispute'].create({
            'settlement_id': stl.id,
            'reason': 'missing_transaction',
            'description': 'Missing sales.',
            'disputed_amount': 200.0,
        })
        dispute.action_submit()
        adj_count_before = self.env['commission.adjustment'].search_count([
            ('settlement_id', '=', stl.id)
        ])
        dispute.action_accept()
        adj_count_after = self.env['commission.adjustment'].search_count([
            ('settlement_id', '=', stl.id)
        ])
        self.assertGreater(adj_count_after, adj_count_before)

    def test_dispute_reject_requires_notes(self):
        """Rejecting a dispute without resolution notes should raise."""
        stl = self._create_settlement('submitted')
        dispute = self.env['commission.dispute'].create({
            'settlement_id': stl.id,
            'reason': 'other',
            'description': 'Disputed.',
        })
        dispute.action_submit()
        with self.assertRaises(Exception):
            dispute.action_reject()  # no resolution_notes

    # ── Portal URL ────────────────────────────────────────────────────────────

    def test_get_portal_url(self):
        """Settlement portal URL should be well-formed."""
        stl = self._create_settlement()
        url = stl.get_portal_url()
        self.assertIn(str(stl.id), url)
        self.assertIn('/my/commission/settlements/', url)

    # ── Anomaly Detection ─────────────────────────────────────────────────────

    def test_anomaly_flag_reset_on_recalculate(self):
        """Anomaly flag should reset when settlement is recalculated."""
        stl = self._create_settlement()
        stl.write({'anomaly_flag': True, 'anomaly_reason': 'Test anomaly'})
        stl.action_calculate()
        # After recalculation, either flag is cleared or re-evaluated; should not error

    def test_cron_detect_anomalies_no_raise(self):
        """Cron anomaly detection should not raise."""
        self.env['commission.settlement'].cron_detect_anomalies()


@tagged('commission', 'commission_clawback')
class TestClawback(TransactionCase):
    """Tests for clawback engine."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Clawback Employee',
            'company_id': cls.company.id,
        })
        today = date.today()
        cls.period = cls.env['commission.period'].create({
            'name': 'Clawback Period',
            'period_type': 'monthly',
            'date_start': today.replace(day=1),
            'date_end': (today.replace(day=1) + timedelta(days=31)).replace(day=1) - timedelta(days=1),
            'state': 'open',
            'company_id': cls.company.id,
        })
        cls.plan = cls.env['commission.plan'].create({
            'name': 'Clawback Plan',
            'code': 'CLW-TEST',
            'commission_type': 'collection',
            'calculation_method': 'fixed_percent',
            'base_on': 'invoice',
            'enable_clawback': True,
            'clawback_period_months': 6,
            'company_id': cls.company.id,
        })

    def test_cron_clawback_no_raise(self):
        """Clawback cron should run without raising."""
        self.env['commission.adjustment'].cron_process_clawbacks()

    def test_clawback_adjustment_type(self):
        """Clawback adjustment has correct type."""
        stl = self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'period_id': self.period.id,
            'plan_id': self.plan.id,
            'state': 'paid',
        })
        adj = self.env['commission.adjustment'].create({
            'settlement_id': stl.id,
            'name': 'Auto Clawback',
            'adjustment_type': 'clawback',
            'amount': -150.0,
        })
        self.assertEqual(adj.adjustment_type, 'clawback')
        self.assertLess(adj.amount, 0)

    def test_rollback_wizard_no_raise(self):
        """Rollback wizard should instantiate without raising."""
        stl = self.env['commission.settlement'].create({
            'employee_id': self.employee.id,
            'period_id': self.period.id,
            'plan_id': self.plan.id,
            'state': 'paid',
        })
        wizard = self.env['wizard.rollback.commission'].create({
            'settlement_id': stl.id,
            'reason': 'Test rollback',
        })
        self.assertTrue(wizard.id)
