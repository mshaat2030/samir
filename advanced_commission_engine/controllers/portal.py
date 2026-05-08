# -*- coding: utf-8 -*-
"""Portal controller – employee self-service for commission statements."""

import logging
from datetime import date

from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

_logger = logging.getLogger(__name__)


class CommissionPortal(CustomerPortal):
    """Extends the customer portal with commission statement access."""

    # ── Portal Home Prepare ───────────────────────────────────────────────────

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'commission_count' in counters:
            employee = self._get_portal_employee()
            if employee:
                values['commission_count'] = request.env['commission.settlement'].search_count([
                    ('employee_id', '=', employee.id),
                    ('state', 'not in', ('cancelled',)),
                ])
            else:
                values['commission_count'] = 0
        return values

    # ── Settlement List ───────────────────────────────────────────────────────

    @http.route([
        '/my/commissions',
        '/my/commissions/page/<int:page>',
    ], type='http', auth='user', website=True)
    def portal_commissions(self, page=1, filterby='all', sortby='date_desc', **kw):
        """Display the employee's commission statements."""
        if not self._check_portal_enabled():
            return request.not_found()

        employee = self._get_portal_employee()
        if not employee:
            return request.render('advanced_commission_engine.portal_no_employee')

        CommissionSettlement = request.env['commission.settlement']
        domain = [
            ('employee_id', '=', employee.id),
            ('state', 'not in', ('cancelled',)),
        ]

        # Filters
        filter_options = {
            'all': {'label': _('All'), 'domain': []},
            'paid': {'label': _('Paid'), 'domain': [('state', '=', 'paid')]},
            'pending': {'label': _('Pending'), 'domain': [('state', 'in', ('submitted', 'approved', 'finance_approved'))]},
            'draft': {'label': _('Draft'), 'domain': [('state', 'in', ('draft', 'calculated'))]},
        }
        if filterby in filter_options:
            domain += filter_options[filterby]['domain']

        # Sort options
        sort_options = {
            'date_desc': 'period_id desc',
            'date_asc': 'period_id asc',
            'amount_desc': 'final_amount desc',
            'amount_asc': 'final_amount asc',
        }
        order = sort_options.get(sortby, 'period_id desc')

        count = CommissionSettlement.search_count(domain)
        pager = portal_pager(
            url='/my/commissions',
            url_args={'filterby': filterby, 'sortby': sortby},
            total=count,
            page=page,
            step=10,
        )
        settlements = CommissionSettlement.search(
            domain, order=order, offset=pager['offset'], limit=10
        )

        # Get current period target
        current_target = None
        today = date.today()
        current_period = request.env['commission.period'].search([
            ('date_start', '<=', today),
            ('date_end', '>=', today),
        ], limit=1)
        if current_period:
            current_target = request.env['commission.target'].search([
                ('employee_id', '=', employee.id),
                ('period_id', '=', current_period.id),
            ], limit=1)

        # Leaderboard position
        leaderboard_entry = None
        if current_period:
            leaderboard_entry = request.env['commission.leaderboard'].search([
                ('employee_id', '=', employee.id),
                ('period_id', '=', current_period.id),
            ], limit=1)

        values = {
            'page_name': 'commissions',
            'settlements': settlements,
            'pager': pager,
            'filterby': filterby,
            'sortby': sortby,
            'filter_options': filter_options,
            'sort_options': {
                'date_desc': _('Newest'),
                'date_asc': _('Oldest'),
                'amount_desc': _('Highest Amount'),
                'amount_asc': _('Lowest Amount'),
            },
            'employee': employee,
            'current_target': current_target,
            'leaderboard_entry': leaderboard_entry,
        }
        return request.render(
            'advanced_commission_engine.portal_commission_list', values
        )

    # ── Settlement Detail ──────────────────────────────────────────────────────

    @http.route(['/my/commissions/<int:settlement_id>'], type='http', auth='user', website=True)
    def portal_commission_detail(self, settlement_id, **kw):
        """Display a single commission statement."""
        if not self._check_portal_enabled():
            return request.not_found()

        employee = self._get_portal_employee()
        if not employee:
            return request.render('advanced_commission_engine.portal_no_employee')

        settlement = request.env['commission.settlement'].browse(settlement_id)
        if not settlement.exists() or settlement.employee_id != employee:
            return request.not_found()

        disputes = request.env['commission.dispute'].search([
            ('settlement_id', '=', settlement.id),
        ])

        values = {
            'page_name': 'commissions',
            'settlement': settlement,
            'employee': employee,
            'disputes': disputes,
        }
        return request.render(
            'advanced_commission_engine.portal_commission_detail', values
        )

    # ── PDF Download ──────────────────────────────────────────────────────────

    @http.route(
        ['/my/commissions/<int:settlement_id>/pdf'],
        type='http', auth='user', website=True,
    )
    def portal_commission_pdf(self, settlement_id, **kw):
        """Download commission statement as PDF."""
        employee = self._get_portal_employee()
        settlement = request.env['commission.settlement'].browse(settlement_id)
        if not settlement.exists() or settlement.employee_id != employee:
            return request.not_found()

        pdf_content, _ = request.env['ir.actions.report']._render_qweb_pdf(
            'advanced_commission_engine.action_report_commission_statement',
            [settlement_id],
        )
        filename = f'commission_{settlement.name.replace("/", "_")}.pdf'
        return request.make_response(
            pdf_content,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', f'attachment; filename="{filename}"'),
            ],
        )

    # ── Submit Dispute ────────────────────────────────────────────────────────

    @http.route(
        ['/my/commissions/<int:settlement_id>/dispute'],
        type='http', auth='user', website=True, methods=['POST'],
    )
    def portal_submit_dispute(self, settlement_id, **kw):
        """Submit a dispute for a commission settlement."""
        employee = self._get_portal_employee()
        settlement = request.env['commission.settlement'].browse(settlement_id)
        if not settlement.exists() or settlement.employee_id != employee:
            return request.not_found()

        if settlement.state not in ('approved', 'finance_approved', 'calculated', 'submitted'):
            return request.redirect(f'/my/commissions/{settlement_id}?error=invalid_state')

        reason = kw.get('reason', '').strip()
        dispute_type = kw.get('dispute_type', 'wrong_amount')
        requested_amount = float(kw.get('requested_amount', 0) or 0)

        if not reason:
            return request.redirect(
                f'/my/commissions/{settlement_id}?error=missing_reason'
            )

        request.env['commission.dispute'].create({
            'settlement_id': settlement.id,
            'reason': reason,
            'dispute_type': dispute_type,
            'requested_amount': requested_amount,
        })

        return request.redirect(
            f'/my/commissions/{settlement_id}?success=dispute_submitted'
        )

    # ── Leaderboard ───────────────────────────────────────────────────────────

    @http.route(['/my/commissions/leaderboard'], type='http', auth='user', website=True)
    def portal_leaderboard(self, **kw):
        """Display the commission leaderboard."""
        if not self._check_portal_leaderboard():
            return request.not_found()

        today = date.today()
        period = request.env['commission.period'].search([
            ('date_start', '<=', today),
            ('date_end', '>=', today),
        ], limit=1)

        leaderboard = request.env['commission.leaderboard'].browse()
        if period:
            leaderboard = request.env['commission.leaderboard'].search([
                ('period_id', '=', period.id),
            ], order='rank asc', limit=20)

        employee = self._get_portal_employee()
        my_entry = None
        if employee and period:
            my_entry = request.env['commission.leaderboard'].search([
                ('employee_id', '=', employee.id),
                ('period_id', '=', period.id),
            ], limit=1)

        values = {
            'page_name': 'commissions',
            'period': period,
            'leaderboard': leaderboard,
            'my_entry': my_entry,
            'employee': employee,
        }
        return request.render(
            'advanced_commission_engine.portal_commission_leaderboard', values
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_portal_employee(self):
        """Get the hr.employee record for the current portal user."""
        user = request.env.user
        employee = request.env['hr.employee'].search([
            ('user_id', '=', user.id),
        ], limit=1)
        return employee

    def _check_portal_enabled(self):
        config = request.env['ir.config_parameter'].sudo()
        return config.get_param(
            'advanced_commission_engine.portal_enabled', 'True'
        ) in ('True', '1', 'true')

    def _check_portal_leaderboard(self):
        config = request.env['ir.config_parameter'].sudo()
        return config.get_param(
            'advanced_commission_engine.portal_show_leaderboard', 'True'
        ) in ('True', '1', 'true')
