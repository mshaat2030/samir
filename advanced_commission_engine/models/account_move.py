# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    commission_line_ids = fields.One2many(
        'commission.line', 'invoice_id',
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
        for move in self:
            lines = move.commission_line_ids.filtered(
                lambda l: l.state != 'cancelled'
            )
            move.commission_count = len(lines)
            move.commission_amount = sum(lines.mapped('commission_amount'))

    def action_post(self):
        res = super().action_post()
        for move in self.filtered(
            lambda m: m.move_type in ('out_invoice', 'out_refund')
        ):
            move._trigger_invoice_commission()
        return res

    def _trigger_invoice_commission(self):
        """Trigger commission when invoice is validated."""
        plans = self.env['commission.plan'].search([
            ('trigger_type', '=', 'invoice_validate'),
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
            ('date_from', '<=', fields.Date.today()),
            '|',
            ('date_to', '=', False),
            ('date_to', '>=', fields.Date.today()),
        ])
        if not plans:
            return

        salesperson = self.invoice_user_id
        if not salesperson:
            return
        employee = self.env['hr.employee'].search([
            ('user_id', '=', salesperson.id),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not employee or not employee.commission_active:
            return

        period = self.env['commission.period'].search([
            ('date_from', '<=', self.invoice_date or fields.Date.today()),
            ('date_to', '>=', self.invoice_date or fields.Date.today()),
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'open'),
        ], limit=1)
        if not period:
            return

        for plan in plans:
            eligible = plan._get_eligible_employees()
            if eligible and employee not in eligible:
                continue

            # Avoid duplicate commission lines
            existing = self.env['commission.line'].search([
                ('invoice_id', '=', self.id),
                ('plan_id', '=', plan.id),
                ('employee_id', '=', employee.id),
                ('state', '!=', 'cancelled'),
            ], limit=1)
            if existing:
                continue

            # Compute margin if available
            margin = 0.0
            if hasattr(self, 'margin'):
                margin = self.margin

            base_amount = self.amount_untaxed
            if self.move_type == 'out_refund':
                base_amount = -base_amount

            ctx = {
                'amount': base_amount,
                'invoice': self,
                'employee': employee,
                'margin': margin,
                'margin_percent': (margin / base_amount) if base_amount else 0,
            }
            commission = plan.compute_commission(
                base_amount, employee=employee, context_vals=ctx
            )
            if abs(commission) < 0.001:
                continue

            self.env['commission.line'].create({
                'name': _('Commission on %s') % self.name,
                'employee_id': employee.id,
                'period_id': period.id,
                'plan_id': plan.id,
                'date': self.invoice_date or fields.Date.today(),
                'line_type': 'commission',
                'source_type': 'invoice',
                'invoice_id': self.id,
                'base_amount': base_amount,
                'rate': plan.fixed_rate,
                'commission_amount': commission,
                'margin_amount': margin,
                'original_currency_id': self.currency_id.id,
                'original_amount': self.amount_untaxed,
                'company_id': self.company_id.id,
                'currency_id': self.company_id.currency_id.id,
                'state': 'draft',
            })

    def action_view_commissions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Commissions'),
            'res_model': 'commission.line',
            'view_mode': 'list,form',
            'domain': [('invoice_id', '=', self.id)],
        }
