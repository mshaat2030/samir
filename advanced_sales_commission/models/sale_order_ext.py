# -*- coding: utf-8 -*-
"""
Extends sale.order to trigger commission calculation on confirmation/invoicing.
"""
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    commission_line_ids = fields.One2many(
        'asc.commission.line', 'sale_order_id',
        string='Commission Lines',
    )
    commission_count = fields.Integer(
        string='Commissions', compute='_compute_commission_count',
    )
    commission_total = fields.Monetary(
        string='Total Commission',
        compute='_compute_commission_count',
    )

    def _compute_commission_count(self):
        for order in self:
            lines = order.commission_line_ids.filtered(lambda l: not l.is_simulation)
            order.commission_count = len(lines)
            order.commission_total = sum(lines.mapped('net_commission'))

    def action_view_commissions(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Commissions'),
            'res_model': 'asc.commission.line',
            'view_mode': 'list,form',
            'domain': [('sale_order_id', '=', self.id)],
        }

    def action_confirm(self):
        result = super().action_confirm()
        # Auto-calculate if configured
        if self.env['ir.config_parameter'].sudo().get_param('asc.auto_calculate'):
            engine = self.env['asc.commission.engine']
            for order in self:
                try:
                    engine.calculate_for_order(order)
                except Exception as e:
                    _logger.warning('ASC: Commission calculation failed for %s: %s', order.name, e)
        return result


class AccountMove(models.Model):
    _inherit = 'account.move'

    commission_line_ids = fields.One2many(
        'asc.commission.line', 'invoice_id',
        string='Commission Lines',
    )

    def action_post(self):
        result = super().action_post()
        # Trigger commission calculation on invoice posting if auto-calc enabled
        if self.env['ir.config_parameter'].sudo().get_param('asc.auto_calculate'):
            engine = self.env['asc.commission.engine']
            invoices = self.filtered(lambda m: m.move_type in ('out_invoice', 'out_refund'))
            for inv in invoices:
                try:
                    engine.calculate_for_invoice(inv)
                except Exception as e:
                    _logger.warning('ASC: Commission calculation failed for %s: %s', inv.name, e)
        return result
