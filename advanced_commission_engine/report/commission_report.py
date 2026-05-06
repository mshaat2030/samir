# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class CommissionSettlementReport(models.AbstractModel):
    _name = 'report.advanced_commission_engine.report_settlement'
    _description = 'Commission Settlement Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        settlements = self.env['commission.settlement'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'commission.settlement',
            'docs': settlements,
            'data': data,
        }


class CommissionStatementReport(models.AbstractModel):
    _name = 'report.advanced_commission_engine.report_commission_statement'
    _description = 'Commission Statement Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        employees = self.env['hr.employee'].browse(docids)
        period_id = data.get('period_id') if data else False
        results = []
        for emp in employees:
            domain = [
                ('employee_id', '=', emp.id),
                ('state', '!=', 'cancelled'),
                ('line_type', '=', 'commission'),
            ]
            if period_id:
                domain.append(('period_id', '=', period_id))
            lines = self.env['commission.line'].search(domain, order='date')
            results.append({
                'employee': emp,
                'lines': lines,
                'total': sum(lines.mapped('commission_amount')),
                'paid': sum(lines.filtered(lambda l: l.state == 'paid').mapped('commission_amount')),
                'pending': sum(lines.filtered(lambda l: l.state != 'paid').mapped('commission_amount')),
            })
        return {
            'doc_ids': docids,
            'doc_model': 'hr.employee',
            'docs': employees,
            'results': results,
            'data': data,
        }
