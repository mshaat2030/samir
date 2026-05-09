# -*- coding: utf-8 -*-
"""Anomaly detection service — flags statistically unusual commission amounts."""

import logging
import statistics
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class CommissionAnomalyService(models.AbstractModel):
    """AI-ready anomaly detection using statistical z-score analysis."""

    _name = 'commission.anomaly.service'
    _description = 'Commission Anomaly Detection Service'

    def detect_all(self):
        """Scan all recent calculated/submitted settlements for anomalies."""
        threshold = float(self.env['ir.config_parameter'].sudo().get_param(
            'advanced_commission_engine.anomaly_std_threshold', '3.0'
        ))
        settlements = self.env['commission.settlement'].search([
            ('state', 'in', ('calculated', 'submitted', 'approved')),
        ])
        for stl in settlements:
            self.check_settlement(stl, threshold)

    def check_settlement(self, settlement, threshold=3.0):
        """Run z-score anomaly check on a single settlement."""
        settlement.ensure_one()
        historical = self._get_historical(settlement)
        if len(historical) < 3:
            return  # not enough data

        try:
            mean = statistics.mean(historical)
            std = statistics.stdev(historical)
        except statistics.StatisticsError:
            return

        if std == 0:
            return

        z_score = abs(settlement.total_commission - mean) / std
        if z_score > threshold:
            reason = (
                f'Commission {settlement.currency_id.symbol}{settlement.total_commission:,.2f} '
                f'is {z_score:.1f} standard deviations from the '
                f'{len(historical)}-period mean of '
                f'{settlement.currency_id.symbol}{mean:,.2f}.'
            )
            settlement.write({'anomaly_flag': True, 'anomaly_reason': reason})
            settlement.activity_schedule(
                'mail.mail_activity_data_warning',
                note=f'Anomaly detected: {reason}',
                user_id=self.env.user.id,
            )
            _logger.warning('Anomaly in settlement %s: %s', settlement.name, reason)
        else:
            if settlement.anomaly_flag:
                settlement.write({'anomaly_flag': False, 'anomaly_reason': False})

    def _get_historical(self, settlement):
        """Return past 12 commission totals for same employee/plan."""
        past = self.env['commission.settlement'].search([
            ('employee_id', '=', settlement.employee_id.id),
            ('plan_id', '=', settlement.plan_id.id),
            ('state', 'in', ('paid', 'payroll_processed', 'finance_approved')),
            ('id', '!=', settlement.id),
        ], order='period_id desc', limit=12)
        return [s.total_commission for s in past]

    def get_anomaly_report(self):
        """Return summary dict of current anomalies for dashboard display."""
        anomalies = self.env['commission.settlement'].search([
            ('anomaly_flag', '=', True),
            ('state', 'not in', ('paid', 'cancelled')),
        ])
        return [{
            'settlement': a.name,
            'employee': a.employee_id.name,
            'period': a.period_id.name,
            'amount': a.total_commission,
            'reason': a.anomaly_reason,
        } for a in anomalies]
