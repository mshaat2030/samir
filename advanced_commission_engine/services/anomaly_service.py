# -*- coding: utf-8 -*-
"""Anomaly Detection Service – flags unusual commission settlements.

AI-ready placeholder: the statistical detection can be replaced
with an ML model (isolation forest, autoencoder, etc.).
"""

import logging
from statistics import mean, stdev

_logger = logging.getLogger(__name__)


class AnomalyService:
    """Detects anomalous commission settlements using statistical methods.

    A settlement is flagged as an anomaly if its amount deviates by more than
    the configured threshold (default 50%) from the employee's rolling average.
    """

    def __init__(self, env):
        self.env = env
        config = env['ir.config_parameter'].sudo()
        self.threshold_pct = float(
            config.get_param('advanced_commission_engine.anomaly_threshold', '50.0')
        )

    def detect_anomalies(self, settlements):
        """Detect anomalies in a recordset of settlements.

        Flags settlements with ``is_anomaly = True`` and populates ``anomaly_notes``.
        """
        for settlement in settlements:
            self._check_settlement(settlement)

    def _check_settlement(self, settlement):
        """Run anomaly checks on one settlement."""
        anomalies = []

        # Check 1: Deviation from historical average
        historical = self._get_historical_amounts(
            settlement.employee_id, settlement.plan_id
        )
        if len(historical) >= 3:
            avg = mean(historical)
            if avg > 0:
                deviation = abs(settlement.final_amount - avg) / avg * 100
                if deviation > self.threshold_pct:
                    direction = 'above' if settlement.final_amount > avg else 'below'
                    anomalies.append(
                        f'Amount {deviation:.1f}% {direction} historical average ({avg:.2f}).'
                    )

        # Check 2: Negative final amount
        if settlement.final_amount < 0:
            anomalies.append('Final amount is negative.')

        # Check 3: Zero lines with positive adjustments
        if not settlement.line_ids and settlement.final_amount > 0:
            anomalies.append('Settlement has no commission lines but positive final amount.')

        # Check 4: Unusually high single-period spike
        if len(historical) >= 2:
            try:
                std = stdev(historical)
                if std > 0 and abs(settlement.final_amount - mean(historical)) > 3 * std:
                    anomalies.append('Settlement amount is a statistical outlier (>3σ).')
            except Exception:
                pass

        if anomalies:
            settlement.write({
                'is_anomaly': True,
                'anomaly_notes': '\n'.join(anomalies),
            })
        else:
            settlement.write({
                'is_anomaly': False,
                'anomaly_notes': False,
            })

    def _get_historical_amounts(self, employee, plan, months=6):
        """Get historical settlement amounts for an employee/plan."""
        self.env.cr.execute("""
            SELECT cs.final_amount
            FROM commission_settlement cs
            WHERE cs.employee_id = %s
              AND cs.plan_id = %s
              AND cs.state IN ('paid', 'payroll_processed', 'finance_approved', 'approved')
            ORDER BY cs.id DESC
            LIMIT %s
        """, (employee.id, plan.id, months))
        rows = self.env.cr.fetchall()
        return [float(r[0]) for r in rows if r[0] is not None]

    def get_anomaly_report(self, company_id, period_id=None):
        """Return a summary of anomalous settlements.

        :return: list of dicts with employee, amount, anomaly_notes
        """
        domain = [
            ('is_anomaly', '=', True),
            ('company_id', '=', company_id),
        ]
        if period_id:
            domain.append(('period_id', '=', period_id))

        anomalous = self.env['commission.settlement'].search(domain)
        return [
            {
                'settlement_id': s.id,
                'settlement_name': s.name,
                'employee_name': s.employee_id.name,
                'final_amount': s.final_amount,
                'anomaly_notes': s.anomaly_notes,
            }
            for s in anomalous
        ]
