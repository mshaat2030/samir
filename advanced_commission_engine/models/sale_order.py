# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    commission_plan_id = fields.Many2one(
        'commission.plan',
        string='Commission Plan',
        domain="[('company_id', '=', company_id), ('trigger_type', 'in', ['sale_confirm', 'invoice_validate', 'payment_collect'])]",
    )
    commission_line_ids = fields.One2many(
        'commission.line', 'sale_order_id',
        string='Commission Lines',
    )
    commission_count = fields.Integer(
        string='Commissions',
        compute='_compute_commission_count',
    )
    commission_amount = fields.Monetary(
        string='Commission Amount',
        compute='_compute_commission_count',
    )

    def _compute_commission_count(self):
        for order in self:
            lines = order.commission_line_ids.filtered(
                lambda l: l.state != 'cancelled'
            )
            order.commission_count = len(lines)
            order.commission_amount = sum(lines.mapped('commission_amount'))

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            plans = self._get_applicable_plans('sale_confirm')
            for plan in plans:
                self._trigger_commission(order, plan, 'sale_confirm')
        return res

    def _get_applicable_plans(self, trigger_type):
        """Return commission plans applicable to this sale order."""
        plans = self.env['commission.plan'].search([
            ('trigger_type', '=', trigger_type),
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
            ('date_from', '<=', fields.Date.today()),
            '|',
            ('date_to', '=', False),
            ('date_to', '>=', fields.Date.today()),
        ])
        if self.commission_plan_id and self.commission_plan_id in plans:
            return self.commission_plan_id
        return plans

    def _trigger_commission(self, order, plan, trigger_type):
        """Create commission lines when a trigger fires."""
        salesperson = order.user_id
        if not salesperson:
            return
        employee = self.env['hr.employee'].search([
            ('user_id', '=', salesperson.id),
            ('company_id', '=', order.company_id.id),
        ], limit=1)
        if not employee or not employee.commission_active:
            return
        eligible_employees = plan._get_eligible_employees()
        if eligible_employees and employee not in eligible_employees:
            return

        # Find current period
        period = self.env['commission.period'].search([
            ('date_from', '<=', order.date_order.date() if order.date_order else fields.Date.today()),
            ('date_to', '>=', order.date_order.date() if order.date_order else fields.Date.today()),
            ('company_id', '=', order.company_id.id),
            ('state', '=', 'open'),
        ], limit=1)
        if not period:
            _logger.warning(
                'No open commission period found for order %s, date %s',
                order.name, order.date_order,
            )
            return

        base_amount = order.amount_untaxed
        ctx = {
            'amount': base_amount,
            'order': order,
            'employee': employee,
        }
        commission = plan.compute_commission(base_amount, employee=employee, context_vals=ctx)
        if commission <= 0:
            return

        self.env['commission.line'].create({
            'name': _('Commission on %s') % order.name,
            'employee_id': employee.id,
            'period_id': period.id,
            'plan_id': plan.id,
            'date': fields.Date.today(),
            'line_type': 'commission',
            'source_type': 'sale_order',
            'sale_order_id': order.id,
            'base_amount': base_amount,
            'rate': plan.fixed_rate,
            'commission_amount': commission,
            'original_currency_id': order.currency_id.id,
            'original_amount': order.amount_untaxed,
            'company_id': order.company_id.id,
            'currency_id': order.company_id.currency_id.id,
            'state': 'draft',
        })

    def action_view_commissions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Commissions'),
            'res_model': 'commission.line',
            'view_mode': 'list,form',
            'domain': [('sale_order_id', '=', self.id)],
        }
