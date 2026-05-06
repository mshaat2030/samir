# -*- coding: utf-8 -*-
"""
Core Commission Engine service.
Handles computation, recalculation, and rollback of commissions.
"""
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CommissionEngine(models.AbstractModel):
    """
    Service model for commission computation.
    Acts as the central orchestrator for all commission calculations.
    """
    _name = 'commission.engine'
    _description = 'Commission Engine'

    @api.model
    def compute_period(self, period):
        """
        Compute all commissions for a period.
        Called by cron or manual trigger.
        """
        _logger.info('Commission Engine: Computing period %s', period.name)
        plans = period.plan_ids or self.env['commission.plan'].search([
            ('company_id', '=', period.company_id.id),
            ('active', '=', True),
        ])
        for plan in plans:
            self._compute_plan_for_period(plan, period)
        period.message_post(
            body=_('Commission computation completed by %s.') % self.env.user.name
        )

    @api.model
    def _compute_plan_for_period(self, plan, period):
        """Compute commissions for a specific plan and period."""
        employees = plan._get_eligible_employees()
        for employee in employees:
            self._compute_employee_commission(employee, plan, period)

    @api.model
    def _compute_employee_commission(self, employee, plan, period):
        """
        Compute and create/update commission lines for one employee.
        """
        # Get source records for the trigger type
        source_records = self._get_source_records(employee, plan, period)
        for record in source_records:
            self._process_source_record(record, employee, plan, period)

    @api.model
    def _get_source_records(self, employee, plan, period):
        """Return source records based on trigger type."""
        trigger = plan.trigger_type
        domain_base = [
            ('company_id', '=', plan.company_id.id),
        ]
        if trigger == 'invoice_validate':
            user = employee.user_id
            if not user:
                return []
            return self.env['account.move'].search(
                domain_base + [
                    ('invoice_user_id', '=', user.id),
                    ('move_type', 'in', ['out_invoice', 'out_refund']),
                    ('state', '=', 'posted'),
                    ('invoice_date', '>=', period.date_from),
                    ('invoice_date', '<=', period.date_to),
                ]
            )
        elif trigger == 'sale_confirm':
            user = employee.user_id
            if not user:
                return []
            return self.env['sale.order'].search(
                domain_base + [
                    ('user_id', '=', user.id),
                    ('state', 'in', ['sale', 'done']),
                    ('date_order', '>=', fields.Datetime.from_string(
                        '%s 00:00:00' % period.date_from
                    )),
                    ('date_order', '<=', fields.Datetime.from_string(
                        '%s 23:59:59' % period.date_to
                    )),
                ]
            )
        return []

    @api.model
    def _process_source_record(self, record, employee, plan, period):
        """
        Process a single source record and create commission line if needed.
        """
        model_name = record._name
        field_map = {
            'account.move': ('invoice_id', 'invoice'),
            'sale.order': ('sale_order_id', 'sale_order'),
        }
        line_field, source_type = field_map.get(model_name, ('invoice_id', 'invoice'))

        # Check for existing line
        existing = self.env['commission.line'].search([
            (line_field, '=', record.id),
            ('plan_id', '=', plan.id),
            ('employee_id', '=', employee.id),
            ('state', '!=', 'cancelled'),
        ], limit=1)
        if existing:
            return

        # Compute base amount
        if model_name == 'account.move':
            base_amount = record.amount_untaxed
            if record.move_type == 'out_refund':
                base_amount = -base_amount
            margin = getattr(record, 'margin', 0) or 0
            record_date = record.invoice_date or fields.Date.today()
            original_currency = record.currency_id
        elif model_name == 'sale.order':
            base_amount = record.amount_untaxed
            margin = getattr(record, 'margin', 0) or 0
            record_date = record.date_order.date() if record.date_order else fields.Date.today()
            original_currency = record.currency_id
        else:
            return

        ctx = {
            'amount': base_amount,
            'margin': margin,
            'margin_percent': (margin / base_amount) if base_amount else 0,
            'employee': employee,
        }
        commission = plan.compute_commission(
            base_amount, employee=employee, context_vals=ctx
        )
        if abs(commission) < 0.001:
            return

        line_vals = {
            'name': _('Commission: %s') % record.display_name,
            'employee_id': employee.id,
            'period_id': period.id,
            'plan_id': plan.id,
            'date': record_date,
            'line_type': 'commission',
            'source_type': source_type,
            line_field: record.id,
            'base_amount': base_amount,
            'rate': plan.fixed_rate,
            'commission_amount': commission,
            'margin_amount': margin,
            'original_currency_id': original_currency.id,
            'original_amount': base_amount,
            'company_id': plan.company_id.id,
            'currency_id': plan.company_id.currency_id.id,
            'state': 'draft',
        }
        self.env['commission.line'].create(line_vals)

    @api.model
    def recalculate(self, lines):
        """
        Recalculate commission for given lines.
        Creates adjustment entries for differences.
        """
        adjusted = self.env['commission.line']
        for line in lines.filtered(lambda l: l.state not in ('paid', 'cancelled')):
            plan = line.plan_id
            if not plan:
                continue
            ctx = {'amount': line.base_amount, 'employee': line.employee_id}
            new_commission = plan.compute_commission(
                line.base_amount, employee=line.employee_id, context_vals=ctx
            )
            if abs(new_commission - line.commission_amount) > 0.001:
                line.write({'commission_amount': new_commission})
                adjusted |= line
        return adjusted

    @api.model
    def rollback_period(self, period):
        """
        Rollback all draft/validated commission lines for a period.
        Paid lines are not rolled back.
        """
        lines = self.env['commission.line'].search([
            ('period_id', '=', period.id),
            ('state', 'in', ('draft', 'validated')),
        ])
        count = len(lines)
        lines.write({'state': 'cancelled'})
        _logger.info('Rolled back %d commission lines for period %s', count, period.name)
        return count

    @api.model
    def create_retroactive_adjustment(self, employee, plan, period, amount, reason):
        """Create a retroactive adjustment entry."""
        adj = self.env['commission.adjustment'].create({
            'employee_id': employee.id,
            'plan_id': plan.id,
            'period_id': period.id,
            'adjustment_type': 'retroactive',
            'amount': abs(amount),
            'sign': 'positive' if amount >= 0 else 'negative',
            'reason': reason,
            'is_retroactive': True,
            'retroactive_period_id': period.id,
            'company_id': plan.company_id.id,
            'currency_id': plan.company_id.currency_id.id,
            'state': 'draft',
        })
        return adj

    @api.model
    def generate_settlements(self, period, method='payroll'):
        """
        Auto-generate settlements for all employees with commission lines in a period.
        """
        lines = self.env['commission.line'].search([
            ('period_id', '=', period.id),
            ('state', '=', 'validated'),
            ('settlement_id', '=', False),
        ])
        # Group by employee + plan
        settlements = {}
        for line in lines:
            key = (line.employee_id.id, line.plan_id.id)
            if key not in settlements:
                settlements[key] = self.env['commission.line']
            settlements[key] |= line

        created = self.env['commission.settlement']
        for (emp_id, plan_id), settlement_lines in settlements.items():
            employee = self.env['hr.employee'].browse(emp_id)
            plan = self.env['commission.plan'].browse(plan_id)
            settlement = self.env['commission.settlement'].create({
                'period_id': period.id,
                'plan_id': plan.id,
                'employee_id': emp_id,
                'settlement_method': plan.settlement_method or method,
                'company_id': period.company_id.id,
                'currency_id': period.company_id.currency_id.id,
                'state': 'draft',
            })
            settlement_lines.write({'settlement_id': settlement.id})
            created |= settlement
        _logger.info(
            'Generated %d settlements for period %s', len(created), period.name
        )
        return created
