# -*- coding: utf-8 -*-
"""Core commission calculation service — orchestrates rule matching and line creation."""

import logging
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BATCH_SIZE = 500


class CommissionCalculationService(models.AbstractModel):
    """Stateless service model for all commission calculation logic."""

    _name = 'commission.calculation.service'
    _description = 'Commission Calculation Service'

    # ── Public API ────────────────────────────────────────────────────────────

    def calculate_settlement(self, settlement):
        """Full recalculation of a single settlement.

        Deletes existing lines then recomputes from source documents.
        """
        settlement.ensure_one()
        _logger.info('Calculating settlement %s for %s / %s',
                     settlement.name, settlement.employee_id.name, settlement.period_id.name)

        # Delete existing lines
        settlement.line_ids.unlink()

        plan = settlement.plan_id
        period = settlement.period_id
        employee = settlement.employee_id

        dispatch = {
            'invoice': self._calc_from_invoices,
            'payment': self._calc_from_payments,
            'sale_order': self._calc_from_sale_orders,
            'subscription': self._calc_from_subscriptions,
            'project_task': self._calc_from_project_tasks,
            'crm_lead': self._calc_from_crm_leads,
            'kpi': self._calc_from_kpi,
            'custom': self._calc_custom,
        }

        handler = dispatch.get(plan.base_on)
        if not handler:
            raise UserError(f'No calculation handler for base_on={plan.base_on}')

        handler(settlement, plan, period, employee)

        # Apply collection delay penalties at settlement level
        self._apply_collection_penalties(settlement, plan)

        # Award badges if gamification enabled
        if plan.enable_gamification:
            self.env['commission.badge'].check_and_award_badges(settlement)

        settlement._stamp_calculated()

    def auto_calculate_period(self, period):
        """Calculate commissions for all employees/plans in an open period."""
        _logger.info('Auto-calculating commissions for period %s', period.name)
        plans = period.plan_ids or self.env['commission.plan'].search([
            ('active', '=', True),
            ('company_id', 'in', [period.company_id.id, False]),
        ])
        for plan in plans:
            employees = plan.employee_ids or self.env['hr.employee'].search([
                ('company_id', '=', period.company_id.id),
                ('active', '=', True),
            ])
            for employee in employees:
                try:
                    self._ensure_and_calculate(period, plan, employee)
                except Exception as e:
                    _logger.error(
                        'Failed to calculate commission for %s/%s/%s: %s',
                        employee.name, period.name, plan.name, e,
                    )

    def _ensure_and_calculate(self, period, plan, employee):
        """Create or reuse a settlement and calculate it."""
        settlement = self.env['commission.settlement'].search([
            ('employee_id', '=', employee.id),
            ('period_id', '=', period.id),
            ('plan_id', '=', plan.id),
        ], limit=1)
        if not settlement:
            settlement = self.env['commission.settlement'].create({
                'employee_id': employee.id,
                'period_id': period.id,
                'plan_id': plan.id,
            })
        if settlement.state in ('draft', 'calculated'):
            self.calculate_settlement(settlement)

    # ── Source Handlers ───────────────────────────────────────────────────────

    def _calc_from_invoices(self, settlement, plan, period, employee):
        """Generate commission lines from customer invoices."""
        domain = [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('invoice_date', '>=', period.date_start),
            ('invoice_date', '<=', period.date_end),
            ('invoice_user_id', '=', employee.user_id.id),
        ]
        if plan.min_base_amount:
            domain.append(('amount_untaxed', '>=', plan.min_base_amount))

        invoices = self.env['account.move'].search(domain)
        _logger.debug('Found %d invoices for %s', len(invoices), employee.name)

        for invoice in invoices:
            margin = self._compute_invoice_margin(invoice)
            base = invoice.amount_untaxed

            rules = plan.get_applicable_rules(employee=employee, invoice=invoice)
            for rule in rules:
                # Check amount bounds on rule
                if rule.min_amount and base < rule.min_amount:
                    continue
                if rule.max_amount and base > rule.max_amount:
                    base = rule.max_amount

                ctx = {
                    'base_amount': base,
                    'margin_amount': margin,
                    'revenue_amount': base,
                    'profit_amount': margin,
                    'achievement_pct': self._get_achievement_pct(employee, period, plan),
                }
                commission = rule.calculate_commission(base, ctx)
                commission = plan.apply_commission_cap(commission)

                # Collection delay penalty
                penalty = 0.0
                days_overdue = 0
                if rule.collection_delay_penalty_rate:
                    today = fields.Date.today()
                    age = (today - invoice.invoice_date).days
                    if age > 0:
                        months = age / 30.0
                        penalty = commission * rule.collection_delay_penalty_rate / 100.0 * months
                        commission = max(0, commission - penalty)
                        days_overdue = age

                if not rule.is_additive:
                    settlement.line_ids.unlink()

                self.env['commission.line'].create({
                    'settlement_id': settlement.id,
                    'rule_id': rule.id,
                    'invoice_id': invoice.id,
                    'source_type': 'invoice',
                    'date': invoice.invoice_date,
                    'partner_id': invoice.partner_id.id,
                    'salesperson_id': invoice.invoice_user_id.id,
                    'base_amount': base,
                    'margin_amount': margin,
                    'rate': rule.rate,
                    'commission_amount': commission,
                    'collection_penalty': penalty,
                    'invoice_date': invoice.invoice_date,
                    'days_overdue': days_overdue,
                    'description': f'Invoice {invoice.name}',
                })
                if rule.stop_further_rules:
                    break

    def _calc_from_payments(self, settlement, plan, period, employee):
        """Generate commission lines from customer payments."""
        domain = [
            ('payment_type', '=', 'inbound'),
            ('state', '=', 'posted'),
            ('date', '>=', period.date_start),
            ('date', '<=', period.date_end),
            ('journal_id.type', 'in', ('bank', 'cash')),
        ]
        payments = self.env['account.payment'].search(domain)

        for payment in payments:
            # Filter to employee's customers
            if payment.partner_id not in self._get_employee_customers(employee):
                continue

            base = payment.amount
            rules = plan.get_applicable_rules(employee=employee)
            for rule in rules:
                commission = rule.calculate_commission(base)
                commission = plan.apply_commission_cap(commission)
                self.env['commission.line'].create({
                    'settlement_id': settlement.id,
                    'rule_id': rule.id,
                    'payment_id': payment.id,
                    'source_type': 'payment',
                    'date': payment.date,
                    'partner_id': payment.partner_id.id,
                    'base_amount': base,
                    'rate': rule.rate,
                    'commission_amount': commission,
                    'payment_date': payment.date,
                    'description': f'Payment {payment.name}',
                })
                if rule.stop_further_rules:
                    break

    def _calc_from_sale_orders(self, settlement, plan, period, employee):
        """Generate commission lines from confirmed sale orders."""
        domain = [
            ('state', 'in', ('sale', 'done')),
            ('date_order', '>=', str(period.date_start)),
            ('date_order', '<=', str(period.date_end)),
            ('user_id', '=', employee.user_id.id),
        ]
        orders = self.env['sale.order'].search(domain)
        for order in orders:
            base = order.amount_untaxed
            margin = sum(
                (l.price_subtotal - l.product_id.standard_price * l.product_uom_qty)
                for l in order.order_line if l.product_id
            )
            rules = plan.get_applicable_rules(employee=employee, sale_order=order)
            for rule in rules:
                ctx = {'base_amount': base, 'margin_amount': margin}
                commission = rule.calculate_commission(base, ctx)
                commission = plan.apply_commission_cap(commission)
                self.env['commission.line'].create({
                    'settlement_id': settlement.id,
                    'rule_id': rule.id,
                    'sale_order_id': order.id,
                    'source_type': 'sale_order',
                    'date': order.date_order.date() if order.date_order else period.date_start,
                    'partner_id': order.partner_id.id,
                    'salesperson_id': order.user_id.id,
                    'base_amount': base,
                    'margin_amount': margin,
                    'rate': rule.rate,
                    'commission_amount': commission,
                    'description': f'Sale Order {order.name}',
                })
                if rule.stop_further_rules:
                    break

    def _calc_from_subscriptions(self, settlement, plan, period, employee):
        """Generate commission lines from active subscriptions (MRR)."""
        domain = [
            ('stage_id.is_won', '=', True),
            ('user_id', '=', employee.user_id.id),
        ]
        subscriptions = self.env['sale.order'].search(domain)
        for sub in subscriptions:
            base = sub.recurring_monthly or 0.0
            rules = plan.get_applicable_rules(employee=employee)
            for rule in rules:
                commission = rule.calculate_commission(base)
                commission = plan.apply_commission_cap(commission)
                self.env['commission.line'].create({
                    'settlement_id': settlement.id,
                    'rule_id': rule.id,
                    'subscription_id': sub.id,
                    'source_type': 'subscription',
                    'date': period.date_start,
                    'partner_id': sub.partner_id.id,
                    'base_amount': base,
                    'rate': rule.rate,
                    'commission_amount': commission,
                    'description': f'Subscription {sub.name} MRR',
                })
                if rule.stop_further_rules:
                    break

    def _calc_from_project_tasks(self, settlement, plan, period, employee):
        """Generate commission lines from completed project milestones."""
        domain = [
            ('user_ids', 'in', [employee.user_id.id]),
            ('date_deadline', '>=', str(period.date_start)),
            ('date_deadline', '<=', str(period.date_end)),
            ('stage_id.is_closed', '=', True),
        ]
        tasks = self.env['project.task'].search(domain)
        for task in tasks:
            base = task.planned_hours * (task.project_id.partner_id.property_product_pricelist.currency_id.rate if task.project_id.partner_id else 1.0)
            rules = plan.get_applicable_rules(employee=employee)
            for rule in rules:
                commission = rule.calculate_commission(base or plan.min_base_amount or 0)
                commission = plan.apply_commission_cap(commission)
                self.env['commission.line'].create({
                    'settlement_id': settlement.id,
                    'rule_id': rule.id,
                    'project_task_id': task.id,
                    'source_type': 'project_task',
                    'date': task.date_deadline or period.date_start,
                    'base_amount': base,
                    'rate': rule.rate,
                    'commission_amount': commission,
                    'description': f'Task Milestone: {task.name}',
                })
                if rule.stop_further_rules:
                    break

    def _calc_from_crm_leads(self, settlement, plan, period, employee):
        """Generate commission lines from won CRM leads (referral)."""
        domain = [
            ('user_id', '=', employee.user_id.id),
            ('date_closed', '>=', str(period.date_start)),
            ('date_closed', '<=', str(period.date_end)),
            ('stage_id.is_won', '=', True),
        ]
        leads = self.env['crm.lead'].search(domain)
        for lead in leads:
            base = lead.expected_revenue or 0.0
            rules = plan.get_applicable_rules(employee=employee)
            for rule in rules:
                commission = rule.calculate_commission(base)
                commission = plan.apply_commission_cap(commission)
                self.env['commission.line'].create({
                    'settlement_id': settlement.id,
                    'rule_id': rule.id,
                    'crm_lead_id': lead.id,
                    'source_type': 'crm_lead',
                    'date': lead.date_closed or period.date_start,
                    'partner_id': lead.partner_id.id if lead.partner_id else False,
                    'base_amount': base,
                    'rate': rule.rate,
                    'commission_amount': commission,
                    'description': f'Lead: {lead.name}',
                })
                if rule.stop_further_rules:
                    break

    def _calc_from_kpi(self, settlement, plan, period, employee):
        """Generate commission line from aggregated KPI weighted score."""
        kpis = self.env['commission.kpi'].search([
            ('employee_id', '=', employee.id),
            ('period_id', '=', period.id),
            ('plan_id', '=', plan.id),
        ])
        if not kpis:
            return

        # Auto-compute any auto-compute KPIs
        kpis.filtered('auto_compute').compute_achieved_value()

        total_score = sum(kpis.mapped('weighted_score'))
        base_pool = plan.max_commission or 10000.0
        rules = plan.get_applicable_rules(employee=employee)
        for rule in rules:
            commission = rule.calculate_commission(base_pool, {'kpi_score': total_score, 'base_pool': base_pool})
            commission = plan.apply_commission_cap(commission)
            self.env['commission.line'].create({
                'settlement_id': settlement.id,
                'rule_id': rule.id,
                'source_type': 'kpi',
                'date': period.date_end,
                'base_amount': base_pool,
                'kpi_score': total_score,
                'rate': rule.rate,
                'commission_amount': commission,
                'description': f'KPI Score: {total_score:.1f}%',
            })
            if rule.stop_further_rules:
                break

    def _calc_custom(self, settlement, plan, period, employee):
        """Placeholder for custom commission types using dynamic formula."""
        if plan.formula_id:
            ctx = {'base_amount': plan.min_base_amount or 0}
            commission = plan.formula_id.evaluate(ctx)
            self.env['commission.line'].create({
                'settlement_id': settlement.id,
                'source_type': 'manual',
                'date': period.date_end,
                'base_amount': plan.min_base_amount or 0,
                'commission_amount': commission,
                'description': f'Custom Formula: {plan.formula_id.name}',
            })

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _compute_invoice_margin(self, invoice):
        """Compute gross margin on an invoice."""
        margin = 0.0
        for line in invoice.invoice_line_ids:
            if line.product_id and not line.display_type:
                cost = line.product_id.standard_price * line.quantity
                margin += line.price_subtotal - cost
        return margin

    def _get_employee_customers(self, employee):
        """Return partners where this employee is the assigned salesperson."""
        return self.env['res.partner'].search([
            ('user_id', '=', employee.user_id.id),
            ('is_company', '=', True),
        ])

    def _get_achievement_pct(self, employee, period, plan):
        """Return current achievement % from target record."""
        target = self.env['commission.target'].search([
            ('employee_id', '=', employee.id),
            ('period_id', '=', period.id),
            ('plan_id', '=', plan.id),
        ], limit=1)
        return target.achievement_pct if target else 0.0

    def _apply_collection_penalties(self, settlement, plan):
        """Post-process: reduce commission amounts by collection delay penalty."""
        if not plan.collection_delay_penalty:
            return
        for line in settlement.line_ids:
            if line.days_overdue and not line.collection_penalty:
                months = line.days_overdue / 30.0
                penalty = line.commission_amount * plan.collection_delay_penalty / 100.0 * months
                new_amount = max(0, line.commission_amount - penalty)
                line.write({'collection_penalty': penalty, 'commission_amount': new_amount})

    # ── Batch Processing ──────────────────────────────────────────────────────

    def recalculate_batch(self, settlement_ids):
        """Recalculate a batch of settlements efficiently."""
        settlements = self.env['commission.settlement'].browse(settlement_ids)
        for chunk_start in range(0, len(settlements), BATCH_SIZE):
            chunk = settlements[chunk_start:chunk_start + BATCH_SIZE]
            for stl in chunk:
                try:
                    stl.action_reset_draft()
                    self.calculate_settlement(stl)
                except Exception as e:
                    _logger.error('Batch recalc failed for %s: %s', stl.name, e)
            self.env.cr.commit()
            _logger.info('Recalculated batch %d-%d', chunk_start, chunk_start + len(chunk))
