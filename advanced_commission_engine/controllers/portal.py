# -*- coding: utf-8 -*-
"""Employee commission portal — self-service statements, disputes, rankings."""

import logging
from odoo import http, fields
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError

_logger = logging.getLogger(__name__)

PORTAL_ENABLED_KEY = 'advanced_commission_engine.portal_enabled'


class CommissionPortal(CustomerPortal):
    """Commission self-service portal for employees."""

    # ── Navigation Count ──────────────────────────────────────────────────────

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if request.env['ir.config_parameter'].sudo().get_param(PORTAL_ENABLED_KEY, 'True') == 'True':
            employee = request.env['hr.employee'].sudo().search(
                [('user_id', '=', request.env.user.id)], limit=1
            )
            if employee:
                values['commission_count'] = request.env['commission.settlement'].search_count([
                    ('employee_id', '=', employee.id),
                    ('state', 'not in', ('cancelled',)),
                ])
        return values

    # ── Statement List ────────────────────────────────────────────────────────

    @http.route('/my/commission/settlements', type='http', auth='user', website=True)
    def portal_commission_list(self, page=1, sortby='date', filterby='all', **kw):
        employee = self._get_employee_or_404()
        Settlement = request.env['commission.settlement']

        domain = [('employee_id', '=', employee.id), ('state', 'not in', ('cancelled',))]
        filter_domain = self._get_filter_domain(filterby, domain)

        sort_map = {
            'date': 'period_id desc',
            'amount': 'total_commission desc',
            'state': 'state',
        }
        order = sort_map.get(sortby, 'period_id desc')

        total = Settlement.search_count(filter_domain)
        pager = portal_pager(
            url='/my/commission/settlements',
            total=total,
            page=page,
            step=10,
            url_args={'sortby': sortby, 'filterby': filterby},
        )
        settlements = Settlement.search(filter_domain, order=order,
                                        limit=10, offset=pager['offset'])

        return request.render('advanced_commission_engine.portal_commission_list', {
            'settlements': settlements,
            'page_name': 'commission',
            'pager': pager,
            'sortby': sortby,
            'filterby': filterby,
            'searchbar_sortings': {
                'date': {'label': 'Period', 'order': 'period_id desc'},
                'amount': {'label': 'Amount', 'order': 'total_commission desc'},
                'state': {'label': 'Status', 'order': 'state'},
            },
            'searchbar_filters': {
                'all': {'label': 'All', 'domain': []},
                'paid': {'label': 'Paid', 'domain': [('state', '=', 'paid')]},
                'pending': {'label': 'Pending', 'domain': [('state', 'in', ('submitted', 'approved', 'finance_approved'))]},
            },
        })

    # ── Statement Detail ──────────────────────────────────────────────────────

    @http.route('/my/commission/settlements/<int:settlement_id>', type='http', auth='user', website=True)
    def portal_commission_detail(self, settlement_id, **kw):
        employee = self._get_employee_or_404()
        settlement = self._get_settlement_or_404(settlement_id, employee)

        target = request.env['commission.target'].search([
            ('employee_id', '=', employee.id),
            ('period_id', '=', settlement.period_id.id),
            ('plan_id', '=', settlement.plan_id.id),
        ], limit=1)

        leaderboard = request.env['commission.leaderboard'].search([
            ('employee_id', '=', employee.id),
            ('period_id', '=', settlement.period_id.id),
        ], limit=1)

        return request.render('advanced_commission_engine.portal_commission_detail', {
            'settlement': settlement,
            'target': target,
            'leaderboard': leaderboard,
            'page_name': 'commission',
        })

    # ── Download PDF ──────────────────────────────────────────────────────────

    @http.route('/my/commission/settlements/<int:settlement_id>/pdf', type='http', auth='user', website=True)
    def portal_commission_pdf(self, settlement_id, **kw):
        employee = self._get_employee_or_404()
        settlement = self._get_settlement_or_404(settlement_id, employee)
        pdf, _ = request.env['ir.actions.report'].sudo()._render_qweb_pdf(
            'advanced_commission_engine.action_report_commission_statement',
            [settlement.id],
        )
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', f'attachment; filename="Commission_{settlement.name}.pdf"'),
        ])

    # ── Dispute Submission ────────────────────────────────────────────────────

    @http.route('/my/commission/settlements/<int:settlement_id>/dispute', type='http',
                auth='user', website=True, methods=['GET', 'POST'])
    def portal_submit_dispute(self, settlement_id, **kw):
        employee = self._get_employee_or_404()
        settlement = self._get_settlement_or_404(settlement_id, employee)

        allow_disputes = request.env['ir.config_parameter'].sudo().get_param(
            'advanced_commission_engine.portal_allow_disputes', 'True'
        ) == 'True'
        if not allow_disputes:
            return request.redirect(f'/my/commission/settlements/{settlement_id}')

        error = None
        if request.httprequest.method == 'POST':
            reason = kw.get('reason')
            description = kw.get('description')
            disputed_amount = float(kw.get('disputed_amount', 0.0) or 0.0)
            if not reason or not description:
                error = 'Reason and description are required.'
            else:
                request.env['commission.dispute'].sudo().create({
                    'settlement_id': settlement.id,
                    'reason': reason,
                    'description': description,
                    'disputed_amount': disputed_amount,
                })
                return request.redirect(f'/my/commission/settlements/{settlement_id}?dispute=submitted')

        return request.render('advanced_commission_engine.portal_commission_dispute', {
            'settlement': settlement,
            'error': error,
            'page_name': 'commission',
        })

    # ── Targets ───────────────────────────────────────────────────────────────

    @http.route('/my/commission/targets', type='http', auth='user', website=True)
    def portal_targets(self, **kw):
        employee = self._get_employee_or_404()
        targets = request.env['commission.target'].search([
            ('employee_id', '=', employee.id),
        ], order='period_id desc', limit=12)
        return request.render('advanced_commission_engine.portal_commission_targets', {
            'targets': targets,
            'page_name': 'commission',
        })

    # ── Leaderboard ───────────────────────────────────────────────────────────

    @http.route('/my/commission/leaderboard', type='http', auth='user', website=True)
    def portal_leaderboard(self, period_id=None, **kw):
        public = request.env['ir.config_parameter'].sudo().get_param(
            'advanced_commission_engine.leaderboard_public', 'True'
        ) == 'True'
        if not public:
            return request.redirect('/my/commission/settlements')

        current_period = request.env['commission.period'].search([
            ('state', '=', 'open'),
        ], order='date_start desc', limit=1)

        if period_id:
            period = request.env['commission.period'].browse(int(period_id))
        else:
            period = current_period

        leaders = request.env['commission.leaderboard'].search([
            ('period_id', '=', period.id),
        ], order='rank', limit=20) if period else request.env['commission.leaderboard']

        return request.render('advanced_commission_engine.portal_commission_leaderboard', {
            'leaders': leaders,
            'period': period,
            'periods': request.env['commission.period'].search([], order='date_start desc', limit=12),
            'page_name': 'commission',
        })

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_employee_or_404(self):
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', request.env.user.id)], limit=1
        )
        if not employee:
            return request.redirect('/my')
        return employee

    def _get_settlement_or_404(self, settlement_id, employee):
        settlement = request.env['commission.settlement'].sudo().search([
            ('id', '=', settlement_id),
            ('employee_id', '=', employee.id),
        ], limit=1)
        if not settlement:
            raise MissingError('Settlement not found.')
        return settlement

    def _get_filter_domain(self, filterby, base_domain):
        filter_map = {
            'paid': [('state', '=', 'paid')],
            'pending': [('state', 'in', ('submitted', 'approved', 'finance_approved'))],
            'all': [],
        }
        return base_domain + filter_map.get(filterby, [])
