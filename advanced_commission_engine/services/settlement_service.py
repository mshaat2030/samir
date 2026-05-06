# -*- coding: utf-8 -*-
"""
Settlement service - handles batch processing of commission settlements.
"""
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SettlementService(models.AbstractModel):
    _name = 'commission.settlement.service'
    _description = 'Commission Settlement Service'

    @api.model
    def process_batch(self, settlement_ids=None, period_id=None, company_id=None):
        """
        Process a batch of settlements.
        Either provide settlement_ids or period_id to process all eligible.
        """
        if settlement_ids:
            settlements = self.env['commission.settlement'].browse(settlement_ids)
        elif period_id:
            settlements = self.env['commission.settlement'].search([
                ('period_id', '=', period_id),
                ('state', '=', 'approved'),
            ])
        else:
            raise UserError(_('Provide either settlement IDs or a period ID.'))

        results = {
            'processed': 0,
            'failed': 0,
            'errors': [],
        }
        for settlement in settlements:
            try:
                settlement.action_pay()
                results['processed'] += 1
            except Exception as e:
                results['failed'] += 1
                results['errors'].append({
                    'settlement': settlement.name,
                    'error': str(e),
                })
                _logger.error(
                    'Failed to process settlement %s: %s',
                    settlement.name, str(e)
                )
        return results

    @api.model
    def auto_generate_monthly(self, company=None):
        """
        Called by cron: auto-generate settlements for the current month.
        """
        if not company:
            companies = self.env['res.company'].search([
                ('commission_auto_settle', '=', True)
            ])
        else:
            companies = company

        for comp in companies:
            today = fields.Date.today()
            # Check if today is the settlement day
            if today.day != comp.commission_settlement_day:
                continue
            period = self.env['commission.period'].search([
                ('date_from', '<=', today),
                ('date_to', '>=', today),
                ('company_id', '=', comp.id),
                ('state', '=', 'open'),
            ], limit=1)
            if period:
                engine = self.env['commission.engine']
                engine.generate_settlements(period)
                _logger.info(
                    'Auto-generated settlements for company %s, period %s',
                    comp.name, period.name,
                )

    @api.model
    def compute_deferred_releases(self):
        """
        Release deferred commissions that have passed their release date.
        Called by cron.
        """
        today = fields.Date.today()
        deferred_lines = self.env['commission.line'].search([
            ('is_deferred', '=', True),
            ('deferred_until', '<=', today),
            ('state', '=', 'draft'),
        ])
        if deferred_lines:
            deferred_lines.write({'is_deferred': False, 'deferred_until': False})
            deferred_lines.action_validate()
            _logger.info(
                'Released %d deferred commission lines', len(deferred_lines)
            )

    @api.model
    def process_clawbacks(self):
        """
        Check for refunded/cancelled invoices and create clawback lines.
        Called by cron.
        """
        # Find reversed/cancelled invoices that had commissions
        reversed_moves = self.env['account.move'].search([
            ('move_type', '=', 'out_refund'),
            ('state', '=', 'posted'),
        ])
        for move in reversed_moves:
            original = move.reversed_entry_id
            if not original:
                continue
            original_lines = self.env['commission.line'].search([
                ('invoice_id', '=', original.id),
                ('state', 'in', ('draft', 'validated', 'paid')),
                ('is_clawback', '=', False),
            ])
            for line in original_lines:
                if not line.plan_id.has_clawback:
                    continue
                # Check clawback window
                from_date = fields.Date.today()
                from dateutil.relativedelta import relativedelta
                clawback_from = line.date + relativedelta(
                    days=-line.plan_id.clawback_days
                )
                if from_date < clawback_from:
                    continue
                # Check if clawback already created
                existing_cb = self.env['commission.line'].search([
                    ('original_line_id', '=', line.id),
                    ('is_clawback', '=', True),
                    ('state', '!=', 'cancelled'),
                ], limit=1)
                if existing_cb:
                    continue
                clawback_amount = -(line.commission_amount * line.plan_id.clawback_rate / 100)
                self.env['commission.line'].create({
                    'name': _('Clawback: %s') % line.name,
                    'employee_id': line.employee_id.id,
                    'period_id': line.period_id.id,
                    'plan_id': line.plan_id.id,
                    'date': fields.Date.today(),
                    'line_type': 'clawback',
                    'source_type': 'invoice',
                    'invoice_id': move.id,
                    'base_amount': line.base_amount,
                    'commission_amount': clawback_amount,
                    'is_clawback': True,
                    'original_line_id': line.id,
                    'clawback_reason': _('Invoice %s reversed by %s') % (
                        original.name, move.name
                    ),
                    'company_id': line.company_id.id,
                    'currency_id': line.currency_id.id,
                    'state': 'draft',
                })
