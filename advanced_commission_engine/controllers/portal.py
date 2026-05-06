# -*- coding: utf-8 -*-
import logging
from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

_logger = logging.getLogger(__name__)


class CommissionPortal(CustomerPortal):
    """
    Employee portal for viewing commission statements, settlements, and disputes.
    """

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'commission_count' in counters:
            employee = request.env['hr.employee'].search([
                ('user_id', '=', request.env.user.id)
            ], limit=1)
            if employee:
                values['commission_count'] = request.env['commission.settlement'].search_count([
                    ('employee_id', '=', employee.id),
                ])
            else:
                values['commission_count'] = 0
        return values

    @http.route(
        ['/my/commissions', '/my/commissions/page/<int:page>'],
        type='http',
        auth='user',
        website=True,
    )
    def portal_commission_list(self, page=1, **kw):
        """Display employee commission statement list."""
        employee = request.env['hr.employee'].search([
            ('user_id', '=', request.env.user.id)
        ], limit=1)
        if not employee:
            return request.redirect('/my')

        Settlement = request.env['commission.settlement']
        domain = [('employee_id', '=', employee.id)]
        total = Settlement.search_count(domain)

        pager = portal_pager(
            url='/my/commissions',
            total=total,
            page=page,
            step=10,
        )
        settlements = Settlement.search(
            domain,
            order='date desc',
            limit=10,
            offset=pager['offset'],
        )
        return request.render(
            'advanced_commission_engine.portal_commission_list',
            {
                'employee': employee,
                'settlements': settlements,
                'pager': pager,
                'page_name': 'commissions',
            },
        )

    @http.route(
        '/my/commissions/<int:settlement_id>',
        type='http',
        auth='user',
        website=True,
    )
    def portal_commission_detail(self, settlement_id, **kw):
        """Display a single settlement detail."""
        employee = request.env['hr.employee'].search([
            ('user_id', '=', request.env.user.id)
        ], limit=1)
        settlement = request.env['commission.settlement'].search([
            ('id', '=', settlement_id),
            ('employee_id', '=', employee.id),
        ], limit=1)
        if not settlement:
            return request.redirect('/my/commissions')
        return request.render(
            'advanced_commission_engine.portal_commission_detail',
            {
                'settlement': settlement,
                'employee': employee,
            },
        )

    @http.route(
        '/my/commissions/dispute/new',
        type='http',
        auth='user',
        website=True,
        methods=['GET', 'POST'],
    )
    def portal_create_dispute(self, **kw):
        """Create a dispute from portal."""
        employee = request.env['hr.employee'].search([
            ('user_id', '=', request.env.user.id)
        ], limit=1)
        if not employee:
            return request.redirect('/my')

        if request.httprequest.method == 'POST':
            settlement_id = int(kw.get('settlement_id', 0))
            description = kw.get('description', '')
            claimed_amount = float(kw.get('claimed_amount', 0))
            dispute_type = kw.get('dispute_type', 'amount_incorrect')

            if settlement_id and description:
                settlement = request.env['commission.settlement'].search([
                    ('id', '=', settlement_id),
                    ('employee_id', '=', employee.id),
                ], limit=1)
                if settlement:
                    request.env['commission.dispute'].sudo().create({
                        'employee_id': employee.id,
                        'settlement_id': settlement.id,
                        'description': description,
                        'claimed_amount': claimed_amount,
                        'dispute_type': dispute_type,
                        'company_id': settlement.company_id.id,
                        'currency_id': settlement.currency_id.id,
                    })
                    return request.redirect('/my/commissions?dispute_created=1')

        settlements = request.env['commission.settlement'].search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ('paid', 'approved')),
        ], order='date desc', limit=20)
        return request.render(
            'advanced_commission_engine.portal_create_dispute',
            {
                'employee': employee,
                'settlements': settlements,
                'dispute_types': [
                    ('amount_incorrect', 'Amount Incorrect'),
                    ('missing_commission', 'Missing Commission'),
                    ('wrong_rate', 'Wrong Rate Applied'),
                    ('wrong_period', 'Wrong Period'),
                    ('duplicate', 'Duplicate Entry'),
                    ('clawback_unjustified', 'Unjustified Clawback'),
                    ('other', 'Other'),
                ],
            },
        )
