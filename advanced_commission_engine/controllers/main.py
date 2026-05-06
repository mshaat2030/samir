# -*- coding: utf-8 -*-
import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class CommissionDashboardController(http.Controller):
    """
    Backend JSON API for the Commission Dashboard OWL component.
    """

    @http.route(
        '/commission/dashboard/kpis',
        type='jsonrpc',
        auth='user',
        methods=['POST'],
    )
    def get_dashboard_kpis(self, period_id=None, **kwargs):
        """Return KPI data for the dashboard."""
        try:
            env = request.env
            company = env.company

            domain = [
                ('company_id', '=', company.id),
                ('state', '!=', 'cancelled'),
            ]
            if period_id:
                domain.append(('period_id', '=', int(period_id)))

            lines = env['commission.line'].search(domain)
            commission_lines = lines.filtered(lambda l: l.line_type == 'commission')

            return {
                'total_commission': sum(commission_lines.mapped('commission_amount')),
                'total_paid': sum(
                    commission_lines.filtered(lambda l: l.state == 'paid').mapped('commission_amount')
                ),
                'total_pending': sum(
                    commission_lines.filtered(lambda l: l.state != 'paid').mapped('commission_amount')
                ),
                'employee_count': len(set(commission_lines.mapped('employee_id').ids)),
                'open_disputes': env['commission.dispute'].search_count([
                    ('state', 'in', ('open', 'under_review')),
                    ('company_id', '=', company.id),
                ]),
                'currency_symbol': company.currency_id.symbol,
                'currency_position': company.currency_id.position,
            }
        except Exception as e:
            _logger.error('Dashboard KPI error: %s', str(e))
            return {'error': str(e)}

    @http.route(
        '/commission/leaderboard',
        type='jsonrpc',
        auth='user',
        methods=['POST'],
    )
    def get_leaderboard(self, period_id, limit=10, **kwargs):
        """Return leaderboard data."""
        try:
            data = request.env['commission.leaderboard'].get_dashboard_data(
                int(period_id)
            )
            return data[:limit]
        except Exception as e:
            _logger.error('Leaderboard error: %s', str(e))
            return []
