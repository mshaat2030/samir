# -*- coding: utf-8 -*-
"""Commission Calculation Service – core engine that generates commission lines.

This service handles all commission types, fetches source documents,
applies rules, and populates commission.line records for a settlement.
"""

import logging
from datetime import timedelta

from odoo import fields
from odoo.tools import float_round

_logger = logging.getLogger(__name__)

BATCH_SIZE = 1000


class CommissionCalculationService:
    """Orchestrates commission line generation for a settlement.

    Usage::

        service = CommissionCalculationService(env)
        service.calculate_settlement(settlement)
    """

    def __init__(self, env):
        self.env = env

    # ── Public Entry Point ────────────────────────────────────────────────────

    def calculate_settlement(self, settlement):
        """Recalculate all commission lines for *settlement*.

        Deletes existing draft/confirmed lines, fetches source documents,
        applies rules, and creates new commission.line records.
        """
        _logger.info('Calculating commission for settlement %s', settlement.name)

        # Clear existing lines
        settlement.line_ids.filtered(
            lambda l: l.state != 'cancelled'
        ).unlink()

        plan = settlement.plan_id
        employee = settlement.employee_id
        period = settlement.period_id

        handler = self._get_handler(plan.source_document)
        if not handler:
            _logger.warning(
                'No handler for source_document=%s in plan %s',
                plan.source_document, plan.name,
            )
            return

        source_records = handler(plan, employee, period)
        _logger.info(
            'Found %d source records for %s', len(source_records), settlement.name
        )

        lines_to_create = []
        for record in source_records:
            line_vals = self._build_line_vals(record, settlement, plan, employee)
            if line_vals:
                lines_to_create.append(line_vals)

        # Batch create for performance
        for i in range(0, len(lines_to_create), BATCH_SIZE):
            batch = lines_to_create[i:i + BATCH_SIZE]
            self.env['commission.line'].create(batch)

        _logger.info(
            'Created %d commission lines for settlement %s',
            len(lines_to_create), settlement.name,
        )

    # ── Source Document Handlers ──────────────────────────────────────────────

    def _get_handler(self, source_document):
        handlers = {
            'sale_order': self._get_sale_orders,
            'invoice': self._get_invoices,
            'payment': self._get_payments,
            'pos_order': self._get_pos_orders,
            'project_task': self._get_project_tasks,
            'subscription': self._get_subscriptions,
            'crm_lead': self._get_crm_leads,
        }
        return handlers.get(source_document)

    def _get_invoices(self, plan, employee, period):
        """Fetch customer invoices for commission calculation."""
        domain = [
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('invoice_date', '>=', period.date_start),
            ('invoice_date', '<=', period.date_end),
            ('company_id', '=', plan.company_id.id),
        ]

        trigger = plan.invoice_state_trigger
        if trigger == 'posted':
            domain.append(('state', '=', 'posted'))
        elif trigger == 'paid':
            domain += [
                ('state', '=', 'posted'),
                ('payment_state', 'in', ('paid', 'in_payment')),
            ]
        elif trigger == 'partial':
            domain += [
                ('state', '=', 'posted'),
                ('payment_state', 'in', ('partial', 'paid', 'in_payment')),
            ]

        # Filter by salesperson
        if employee.user_id:
            domain.append(('invoice_user_id', '=', employee.user_id.id))

        # Filter by products if plan restricts
        invoices = self.env['account.move'].search(domain)

        # Apply plan product/category/partner filters
        invoices = self._filter_by_plan_scope(invoices, plan, source_type='invoice')
        return invoices

    def _get_sale_orders(self, plan, employee, period):
        """Fetch confirmed sale orders."""
        domain = [
            ('state', 'in', ('sale', 'done')),
            ('date_order', '>=', fields.Datetime.to_datetime(period.date_start)),
            ('date_order', '<', fields.Datetime.to_datetime(period.date_end) + timedelta(days=1)),
            ('company_id', '=', plan.company_id.id),
        ]
        if employee.user_id:
            domain.append(('user_id', '=', employee.user_id.id))
        orders = self.env['sale.order'].search(domain)
        return self._filter_by_plan_scope(orders, plan, source_type='sale_order')

    def _get_payments(self, plan, employee, period):
        """Fetch customer payments (for collection commissions)."""
        domain = [
            ('payment_type', '=', 'inbound'),
            ('state', '=', 'posted'),
            ('date', '>=', period.date_start),
            ('date', '<=', period.date_end),
            ('company_id', '=', plan.company_id.id),
        ]
        return self.env['account.payment'].search(domain)

    def _get_pos_orders(self, plan, employee, period):
        """Fetch POS orders."""
        if 'pos.order' not in self.env:
            return self.env['account.move'].browse()
        domain = [
            ('state', 'in', ('done', 'invoiced')),
            ('date_order', '>=', fields.Datetime.to_datetime(period.date_start)),
            ('date_order', '<', fields.Datetime.to_datetime(period.date_end) + timedelta(days=1)),
            ('company_id', '=', plan.company_id.id),
        ]
        if employee.user_id:
            domain.append(('user_id', '=', employee.user_id.id))
        return self.env['pos.order'].search(domain)

    def _get_project_tasks(self, plan, employee, period):
        """Fetch completed project tasks (project milestone commissions)."""
        domain = [
            ('stage_id.is_closed', '=', True),
            ('date_deadline', '>=', period.date_start),
            ('date_deadline', '<=', period.date_end),
        ]
        if employee.user_id:
            domain.append(('user_ids', 'in', [employee.user_id.id]))
        return self.env['project.task'].search(domain)

    def _get_subscriptions(self, plan, employee, period):
        """Fetch subscription invoices."""
        if 'sale.order' not in self.env:
            return self.env['account.move'].browse()
        domain = [
            ('move_type', 'in', ('out_invoice',)),
            ('invoice_date', '>=', period.date_start),
            ('invoice_date', '<=', period.date_end),
            ('state', '=', 'posted'),
            ('company_id', '=', plan.company_id.id),
        ]
        # Filter subscription invoices
        try:
            domain.append(('invoice_origin', 'ilike', 'SUB'))
        except Exception:
            pass
        return self.env['account.move'].search(domain)

    def _get_crm_leads(self, plan, employee, period):
        """Fetch won CRM opportunities."""
        domain = [
            ('stage_id.is_won', '=', True),
            ('date_closed', '>=', period.date_start),
            ('date_closed', '<=', period.date_end),
        ]
        if employee.user_id:
            domain.append(('user_id', '=', employee.user_id.id))
        return self.env['crm.lead'].search(domain)

    # ── Line Building ─────────────────────────────────────────────────────────

    def _build_line_vals(self, record, settlement, plan, employee):
        """Build commission.line vals dict for a source record."""
        model_name = record._name
        source_type_map = {
            'account.move': 'invoice',
            'sale.order': 'sale_order',
            'account.payment': 'payment',
            'pos.order': 'pos_order',
            'project.task': 'project_task',
            'crm.lead': 'crm_lead',
        }
        source_type = source_type_map.get(model_name, 'manual')

        base_amount = self._get_base_amount(record, plan)
        if base_amount == 0:
            return None

        margin_pct = self._get_margin_pct(record, plan)
        cost_amount = self._get_cost_amount(record)

        # Find applicable rule
        rule = self._find_applicable_rule(plan, record, base_amount, margin_pct)
        if not rule:
            return None

        # Compute commission
        context_vals = {
            'margin_pct': margin_pct,
            'employee': employee,
            'period': settlement.period_id,
            'settlement': settlement,
            'revenue': base_amount,
            'profit': base_amount * margin_pct / 100.0 if margin_pct else 0,
            'target': 0,
            'achieved': 0,
            'attainment': 0,
            'kpi_score': 80,  # default; overridden for KPI plans
        }

        # Collection delay
        invoice_date = getattr(record, 'invoice_date', None)
        payment_date = getattr(record, 'invoice_date_due', None)
        if hasattr(record, 'invoice_payments_widget'):
            # Try to get actual payment date from payment widget
            pass

        delay_days = 0
        if invoice_date and payment_date:
            from datetime import date
            if isinstance(invoice_date, date) and isinstance(payment_date, date):
                delay_days = max(0, (payment_date - invoice_date).days)
        context_vals['payment_delay_days'] = delay_days

        commission_amount = rule.compute_commission(base_amount, context_vals)
        commission_amount = float_round(commission_amount, precision_digits=2)

        if commission_amount == 0:
            return None

        # Build FK values
        vals = {
            'settlement_id': settlement.id,
            'rule_id': rule.id,
            'source_type': source_type,
            'res_model': model_name,
            'res_id': record.id,
            'date': fields.Date.today(),
            'base_amount': base_amount,
            'commission_rate': rule.rate,
            'commission_amount': commission_amount,
            'margin_pct': margin_pct,
            'cost_amount': cost_amount,
            'margin_amount': base_amount * margin_pct / 100.0 if margin_pct else 0,
            'payment_delay_days': delay_days,
            'state': 'confirmed',
        }

        # Set specific FK fields
        if model_name == 'account.move':
            vals['invoice_id'] = record.id
            vals['date'] = record.invoice_date or fields.Date.today()
            vals['partner_id'] = record.partner_id.id if record.partner_id else False
            vals['salesperson_id'] = record.invoice_user_id.id if record.invoice_user_id else False
        elif model_name == 'sale.order':
            vals['sale_order_id'] = record.id
            from datetime import datetime
            if isinstance(record.date_order, datetime):
                vals['date'] = record.date_order.date()
            vals['partner_id'] = record.partner_id.id if record.partner_id else False
            vals['salesperson_id'] = record.user_id.id if record.user_id else False
        elif model_name == 'pos.order':
            vals['pos_order_id'] = record.id
        elif model_name == 'project.task':
            vals['project_task_id'] = record.id
        elif model_name == 'crm.lead':
            vals['crm_lead_id'] = record.id

        return vals

    # ── Amount Extractors ─────────────────────────────────────────────────────

    def _get_base_amount(self, record, plan):
        """Extract base amount from source document."""
        model = record._name
        include_tax = plan.include_tax

        if model == 'account.move':
            if include_tax:
                return abs(record.amount_total_signed)
            return abs(record.amount_untaxed_signed)

        elif model == 'sale.order':
            if include_tax:
                return record.amount_total
            return record.amount_untaxed

        elif model == 'account.payment':
            return record.amount

        elif model == 'pos.order':
            return record.amount_total

        elif model == 'project.task':
            # Use sale order amount if linked
            if hasattr(record, 'sale_order_id') and record.sale_order_id:
                return record.sale_order_id.amount_untaxed
            return 0.0

        elif model == 'crm.lead':
            return record.expected_revenue or 0.0

        return 0.0

    def _get_margin_pct(self, record, plan):
        """Extract margin percentage from source document."""
        model = record._name
        if model == 'sale.order':
            if hasattr(record, 'margin_percent'):
                return record.margin_percent or 0.0
            if hasattr(record, 'margin') and record.amount_untaxed:
                return (record.margin / record.amount_untaxed) * 100
        elif model == 'account.move':
            # Invoices don't natively have margin; default to plan-level
            pass
        return 0.0

    def _get_cost_amount(self, record):
        """Extract cost amount from source document."""
        model = record._name
        if model == 'sale.order' and hasattr(record, 'margin'):
            return (record.amount_untaxed or 0) - (record.margin or 0)
        return 0.0

    # ── Rule Matching ─────────────────────────────────────────────────────────

    def _find_applicable_rule(self, plan, record, base_amount, margin_pct):
        """Find the first applicable rule for a source document."""
        for rule in plan.rule_ids.sorted('sequence'):
            if not rule.active:
                continue
            if not self._rule_matches(rule, record, base_amount, margin_pct):
                continue
            return rule
        return None

    def _rule_matches(self, rule, record, base_amount, margin_pct):
        """Check if a rule's conditions are satisfied."""
        # Minimum base amount
        if rule.min_base_amount and base_amount < rule.min_base_amount:
            return False

        # Maximum base amount
        if rule.max_base_amount and base_amount > rule.max_base_amount:
            return False

        # Min margin
        if rule.min_margin_pct and margin_pct < rule.min_margin_pct:
            return False

        # Product filter
        if rule.product_ids:
            doc_products = self._get_record_products(record)
            if not (set(doc_products) & set(rule.product_ids.ids)):
                return False

        # Product category filter
        if rule.product_category_ids:
            doc_products = self._get_record_products(record)
            products = self.env['product.product'].browse(doc_products)
            cats = products.mapped('categ_id.id')
            if not (set(cats) & set(rule.product_category_ids.ids)):
                return False

        # Partner filter
        if rule.partner_ids:
            partner_id = getattr(record, 'partner_id', None)
            if partner_id and partner_id.id not in rule.partner_ids.ids:
                return False

        # Country filter
        if rule.country_ids:
            partner = getattr(record, 'partner_id', None)
            if partner and partner.country_id:
                if partner.country_id.id not in rule.country_ids.ids:
                    return False

        return True

    def _get_record_products(self, record):
        """Get product IDs from a source document."""
        model = record._name
        if model == 'account.move':
            return record.invoice_line_ids.mapped('product_id.id')
        elif model == 'sale.order':
            return record.order_line.mapped('product_id.id')
        elif model == 'pos.order':
            return record.lines.mapped('product_id.id')
        return []

    # ── Plan Scope Filters ────────────────────────────────────────────────────

    def _filter_by_plan_scope(self, records, plan, source_type):
        """Apply plan-level product/partner/country filters."""
        if not records:
            return records

        result = records
        if plan.product_ids:
            filtered = self.env[records._name]
            for rec in records:
                prods = self._get_record_products(rec)
                if set(prods) & set(plan.product_ids.ids):
                    filtered |= rec
            result = filtered

        if plan.partner_ids:
            result = result.filtered(
                lambda r: getattr(r, 'partner_id', False)
                and r.partner_id.id in plan.partner_ids.ids
            )

        if plan.country_ids:
            result = result.filtered(
                lambda r: getattr(r, 'partner_id', False)
                and r.partner_id.country_id
                and r.partner_id.country_id.id in plan.country_ids.ids
            )

        return result
