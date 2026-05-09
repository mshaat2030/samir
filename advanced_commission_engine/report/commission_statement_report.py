# -*- coding: utf-8 -*-
"""Commission statement report model — PDF and XLSX."""

import logging
from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CommissionStatementReport(models.AbstractModel):
    """QWeb report model for commission.settlement PDF statement."""

    _name = 'report.advanced_commission_engine.report_commission_statement'
    _description = 'Commission Statement Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['commission.settlement'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'commission.settlement',
            'docs': docs,
            'data': data or {},
        }


class CommissionStatementXlsx(models.AbstractModel):
    """XLSX report model for commission.settlement."""

    _name = 'report.advanced_commission_engine.report_commission_statement_xlsx'
    _description = 'Commission Statement XLSX'
    _inherit = 'report.report_xlsx.abstract'

    def generate_xlsx_report(self, workbook, data, records):
        """Generate XLSX workbook for commission statements."""
        for settlement in records:
            sheet = workbook.add_worksheet(settlement.name[:31])

            # ── Formats ────────────────────────────────────────────────────
            bold = workbook.add_format({'bold': True})
            money_fmt = workbook.add_format({'num_format': '#,##0.00'})
            header_fmt = workbook.add_format({
                'bold': True, 'bg_color': '#2c3e50', 'font_color': 'white',
                'border': 1,
            })
            date_fmt = workbook.add_format({'num_format': 'yyyy-mm-dd'})

            # ── Title ──────────────────────────────────────────────────────
            sheet.merge_range('A1:G1', f'Commission Statement — {settlement.name}', bold)
            sheet.write('A2', 'Employee:', bold)
            sheet.write('B2', settlement.employee_id.name)
            sheet.write('A3', 'Period:', bold)
            sheet.write('B3', settlement.period_id.name)
            sheet.write('A4', 'Plan:', bold)
            sheet.write('B4', settlement.plan_id.name)
            sheet.write('A5', 'Status:', bold)
            sheet.write('B5', dict(settlement._fields['state'].selection).get(settlement.state, ''))

            # ── Headers ────────────────────────────────────────────────────
            row = 7
            headers = ['Date', 'Source', 'Description', 'Partner', 'Base Amount', 'Rate %', 'Commission']
            widths = [12, 15, 35, 25, 15, 10, 15]
            for col, (h, w) in enumerate(zip(headers, widths)):
                sheet.write(row, col, h, header_fmt)
                sheet.set_column(col, col, w)

            # ── Lines ──────────────────────────────────────────────────────
            row += 1
            for line in settlement.line_ids.filtered(lambda l: not l.is_excluded):
                sheet.write(row, 0, str(line.date) if line.date else '', date_fmt)
                sheet.write(row, 1, line.source_type)
                sheet.write(row, 2, line.description or '')
                sheet.write(row, 3, line.partner_id.name if line.partner_id else '')
                sheet.write(row, 4, line.base_amount, money_fmt)
                sheet.write(row, 5, line.rate)
                sheet.write(row, 6, line.commission_amount, money_fmt)
                row += 1

            # ── Adjustments ────────────────────────────────────────────────
            if settlement.adjustment_ids:
                row += 1
                sheet.write(row, 0, 'Adjustments', bold)
                row += 1
                for adj in settlement.adjustment_ids.filtered(lambda a: a.state == 'applied'):
                    sheet.write(row, 2, adj.name)
                    sheet.write(row, 3, dict(adj._fields['adjustment_type'].selection).get(adj.adjustment_type, ''))
                    sheet.write(row, 6, adj.amount, money_fmt)
                    row += 1

            # ── Totals ─────────────────────────────────────────────────────
            row += 1
            total_fmt = workbook.add_format({'bold': True, 'num_format': '#,##0.00', 'top': 2})
            sheet.write(row, 5, 'Gross Commission:', bold)
            sheet.write(row, 6, settlement.gross_commission, total_fmt)
            row += 1
            sheet.write(row, 5, 'Adjustments:', bold)
            sheet.write(row, 6, settlement.total_adjustments, total_fmt)
            row += 1
            sheet.write(row, 5, 'NET COMMISSION:', bold)
            sheet.write(row, 6, settlement.total_commission, total_fmt)


class CommissionPayoutSummaryReport(models.AbstractModel):
    """Aggregated payout summary report for finance team."""

    _name = 'report.advanced_commission_engine.report_payout_summary'
    _description = 'Commission Payout Summary Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        periods = self.env['commission.period'].browse(docids)
        settlements_by_period = {}
        for period in periods:
            settlements = self.env['commission.settlement'].search([
                ('period_id', '=', period.id),
                ('state', 'not in', ('cancelled',)),
            ])
            settlements_by_period[period.id] = {
                'period': period,
                'settlements': settlements,
                'total': sum(settlements.mapped('total_commission')),
                'paid': sum(s.total_commission for s in settlements if s.state == 'paid'),
                'pending': sum(s.total_commission for s in settlements if s.state not in ('paid', 'cancelled')),
            }
        return {
            'doc_ids': docids,
            'doc_model': 'commission.period',
            'docs': periods,
            'data': settlements_by_period,
        }
