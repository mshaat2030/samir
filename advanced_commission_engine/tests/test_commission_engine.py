# -*- coding: utf-8 -*-
"""Unit and integration tests for the commission calculation engine."""

import logging
from datetime import date, timedelta
from odoo.tests.common import TransactionCase, tagged

_logger = logging.getLogger(__name__)


@tagged('commission', 'commission_engine')
class TestCommissionPlan(TransactionCase):
    """Tests for CommissionPlan model."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id

        # Create employees
        cls.employee_1 = cls.env['hr.employee'].create({
            'name': 'Alice Sales',
            'company_id': cls.company.id,
        })
        cls.employee_2 = cls.env['hr.employee'].create({
            'name': 'Bob Sales',
            'company_id': cls.company.id,
        })

        # Create period
        today = date.today()
        cls.period = cls.env['commission.period'].create({
            'name': 'Test Period',
            'period_type': 'monthly',
            'date_start': today.replace(day=1),
            'date_end': (today.replace(day=1) + timedelta(days=31)).replace(day=1) - timedelta(days=1),
            'state': 'open',
            'company_id': cls.company.id,
        })

    def _create_plan(self, method='fixed_percent', rate=5.0):
        return self.env['commission.plan'].create({
            'name': f'Test Plan {method}',
            'code': f'TEST-{method.upper()[:6]}',
            'commission_type': 'sales',
            'calculation_method': method,
            'base_on': 'invoice',
            'company_id': self.company.id,
        })

    def _create_rule(self, plan, method='fixed_percent', rate=5.0):
        return self.env['commission.rule'].create({
            'plan_id': plan.id,
            'name': f'Rule {rate}%',
            'sequence': 10,
            'calculation_method': method,
            'rate': rate,
        })

    def test_plan_creation(self):
        """Test basic plan creation with required fields."""
        plan = self._create_plan()
        self.assertTrue(plan.id)
        self.assertEqual(plan.commission_type, 'sales')
        self.assertEqual(plan.calculation_method, 'fixed_percent')

    def test_plan_code_uniqueness(self):
        """Test that plan codes are unique per company."""
        self._create_plan()
        with self.assertRaises(Exception):
            self._create_plan()  # same code

    def test_plan_rule_count(self):
        """Test rule count computed field."""
        plan = self._create_plan()
        self.assertEqual(plan.rule_count, 0)
        self._create_rule(plan)
        self.assertEqual(plan.rule_count, 1)

    def test_fixed_percent_rule(self):
        """Test fixed percentage commission calculation."""
        plan = self._create_plan('fixed_percent')
        rule = self._create_rule(plan, 'fixed_percent', rate=5.0)
        result = rule.calculate_commission(10000.0)
        self.assertAlmostEqual(result, 500.0, places=2)

    def test_fixed_amount_rule(self):
        """Test fixed amount commission calculation."""
        plan = self._create_plan('fixed_amount')
        rule = self.env['commission.rule'].create({
            'plan_id': plan.id,
            'name': 'Fixed 250',
            'calculation_method': 'fixed_amount',
            'amount': 250.0,
        })
        result = rule.calculate_commission(99999.0)
        self.assertAlmostEqual(result, 250.0, places=2)

    def test_progressive_slabs(self):
        """Test progressive slab commission calculation."""
        plan = self._create_plan('progressive_slabs')
        rule = self.env['commission.rule'].create({
            'plan_id': plan.id,
            'name': 'Progressive',
            'calculation_method': 'progressive_slabs',
            'rate': 0.0,
        })
        # 0-50k @ 3%, 50k-100k @ 5%, 100k+ @ 7%
        self.env['commission.rule.slab'].create([
            {'rule_id': rule.id, 'from_amount': 0, 'to_amount': 50000, 'rate': 3.0},
            {'rule_id': rule.id, 'from_amount': 50000, 'to_amount': 100000, 'rate': 5.0},
            {'rule_id': rule.id, 'from_amount': 100000, 'to_amount': 0, 'rate': 7.0},
        ])
        # 10k: 10000 * 3% = 300
        self.assertAlmostEqual(rule.calculate_commission(10000), 300.0, places=2)
        # 75k: 50000*3% + 25000*5% = 1500+1250 = 2750
        self.assertAlmostEqual(rule.calculate_commission(75000), 2750.0, places=2)
        # 120k: 50000*3% + 50000*5% + 20000*7% = 1500+2500+1400 = 5400
        self.assertAlmostEqual(rule.calculate_commission(120000), 5400.0, places=2)

    def test_tiered_slabs(self):
        """Test tiered (not progressive) slab calculation."""
        plan = self._create_plan('tiered')
        rule = self.env['commission.rule'].create({
            'plan_id': plan.id,
            'name': 'Tiered',
            'calculation_method': 'tiered',
            'rate': 0.0,
        })
        self.env['commission.rule.slab'].create([
            {'rule_id': rule.id, 'from_amount': 0, 'to_amount': 50000, 'rate': 3.0},
            {'rule_id': rule.id, 'from_amount': 50000, 'to_amount': 100000, 'rate': 5.0},
            {'rule_id': rule.id, 'from_amount': 100000, 'to_amount': 0, 'rate': 7.0},
        ])
        # 75k falls in 50k-100k slab → 75000 * 5% = 3750
        self.assertAlmostEqual(rule.calculate_commission(75000), 3750.0, places=2)
        # 120k falls in 100k+ slab → 120000 * 7% = 8400
        self.assertAlmostEqual(rule.calculate_commission(120000), 8400.0, places=2)

    def test_hybrid_rule(self):
        """Test hybrid commission = percent + fixed amount."""
        plan = self._create_plan('hybrid')
        rule = self.env['commission.rule'].create({
            'plan_id': plan.id,
            'name': 'Hybrid',
            'calculation_method': 'hybrid',
            'rate': 2.0,
            'amount': 100.0,
        })
        # 10000 * 2% + 100 = 200 + 100 = 300
        self.assertAlmostEqual(rule.calculate_commission(10000), 300.0, places=2)

    def test_apply_commission_cap(self):
        """Test commission cap enforcement."""
        plan = self._create_plan()
        plan.write({'max_commission': 1000.0, 'min_commission': 50.0})
        self.assertEqual(plan.apply_commission_cap(2000.0), 1000.0)
        self.assertEqual(plan.apply_commission_cap(10.0), 50.0)
        self.assertEqual(plan.apply_commission_cap(500.0), 500.0)

    def test_plan_employee_assignment(self):
        """Test employee assignment to plan."""
        plan = self._create_plan()
        plan.write({'employee_ids': [(4, self.employee_1.id)]})
        self.assertIn(self.employee_1, plan.employee_ids)
        self.assertEqual(plan.employee_count, 1)

    def test_period_auto_create(self):
        """Test that auto period creation generates a new period."""
        self.env['commission.period'].cron_auto_create_periods()
        # Should not raise

    def test_period_state_transitions(self):
        """Test period state machine: draft → open → closed → locked."""
        period = self.env['commission.period'].create({
            'name': 'State Test Period',
            'period_type': 'monthly',
            'date_start': date(2025, 1, 1),
            'date_end': date(2025, 1, 31),
            'state': 'draft',
            'company_id': self.company.id,
        })
        self.assertEqual(period.state, 'draft')
        period.action_open()
        self.assertEqual(period.state, 'open')
        period.action_close()
        self.assertEqual(period.state, 'closed')

    def test_period_overlap_constraint(self):
        """Test that overlapping periods are rejected."""
        self.env['commission.period'].create({
            'name': 'Overlap Base',
            'period_type': 'monthly',
            'date_start': date(2025, 3, 1),
            'date_end': date(2025, 3, 31),
            'company_id': self.company.id,
        })
        with self.assertRaises(Exception):
            self.env['commission.period'].create({
                'name': 'Overlap Conflict',
                'period_type': 'monthly',
                'date_start': date(2025, 3, 15),
                'date_end': date(2025, 4, 15),
                'company_id': self.company.id,
            })

    def test_target_achievement_computation(self):
        """Test target achievement % calculation."""
        plan = self._create_plan()
        target = self.env['commission.target'].create({
            'employee_id': self.employee_1.id,
            'period_id': self.period.id,
            'plan_id': plan.id,
            'target_amount': 100000.0,
        })
        # No settlements → 0%
        self.assertAlmostEqual(target.achievement_pct, 0.0, places=1)

    def test_kpi_weighted_score(self):
        """Test KPI weighted score computation."""
        plan = self._create_plan('weighted_kpi')
        kpi1 = self.env['commission.kpi'].create({
            'name': 'Revenue KPI',
            'kpi_type': 'revenue',
            'employee_id': self.employee_1.id,
            'period_id': self.period.id,
            'plan_id': plan.id,
            'weight': 60.0,
            'target_value': 100000.0,
            'achieved_value': 80000.0,
        })
        kpi2 = self.env['commission.kpi'].create({
            'name': 'Units KPI',
            'kpi_type': 'units',
            'employee_id': self.employee_1.id,
            'period_id': self.period.id,
            'plan_id': plan.id,
            'weight': 40.0,
            'target_value': 100.0,
            'achieved_value': 100.0,
        })
        # kpi1: 80% achievement, weight=60 → 48 weighted score
        self.assertAlmostEqual(kpi1.weighted_score, 48.0, places=1)
        # kpi2: 100% achievement, weight=40 → 40 weighted score
        self.assertAlmostEqual(kpi2.weighted_score, 40.0, places=1)

    def test_kpi_weight_validation(self):
        """Test that KPI weights exceeding 100% are rejected."""
        plan = self._create_plan()
        self.env['commission.kpi'].create({
            'name': 'KPI 1',
            'kpi_type': 'revenue',
            'employee_id': self.employee_1.id,
            'period_id': self.period.id,
            'plan_id': plan.id,
            'weight': 80.0,
            'target_value': 1000.0,
        })
        with self.assertRaises(Exception):
            self.env['commission.kpi'].create({
                'name': 'KPI 2 Overweight',
                'kpi_type': 'units',
                'employee_id': self.employee_1.id,
                'period_id': self.period.id,
                'plan_id': plan.id,
                'weight': 30.0,  # 80 + 30 = 110 → should fail
                'target_value': 100.0,
            })

    def test_leaderboard_refresh(self):
        """Test leaderboard refresh doesn't raise."""
        self.env['commission.leaderboard']._refresh_period_leaderboard(self.period)

    def test_forecast_service_no_data(self):
        """Test forecast service gracefully handles no historical data."""
        plan = self._create_plan()
        svc = self.env['commission.forecast.service']
        # Should not raise even with zero history
        svc._create_or_update_forecast(self.employee_1, plan, self.period)
        forecast = self.env['commission.forecast'].search([
            ('employee_id', '=', self.employee_1.id),
            ('period_id', '=', self.period.id),
        ], limit=1)
        self.assertTrue(forecast)

    def test_anomaly_service_no_data(self):
        """Test anomaly detection with no historical data doesn't crash."""
        plan = self._create_plan()
        stl = self.env['commission.settlement'].create({
            'employee_id': self.employee_1.id,
            'period_id': self.period.id,
            'plan_id': plan.id,
            'state': 'calculated',
        })
        svc = self.env['commission.anomaly.service']
        svc.check_settlement(stl)  # should not raise
