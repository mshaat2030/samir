# -*- coding: utf-8 -*-
"""Commission Statement Report – Python model for QWeb PDF reports."""

from odoo import api, models


class CommissionStatementReport(models.AbstractModel):
    """Report model for commission statement PDF generation."""

    _name = 'report.advanced_commission_engine.commission_statement_template'
    _description = 'Commission Statement Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        settlements = self.env['commission.settlement'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'commission.settlement',
            'docs': settlements,
            'data': data or {},
        }
