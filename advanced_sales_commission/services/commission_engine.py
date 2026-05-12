# -*- coding: utf-8 -*-
"""
ASC Commission Engine — Central calculation service.

Design principles:
  - Single source of truth for all commission calculations
  - Batch operations: prefetch related data, then process in Python
  - No ORM queries inside loops
  - Simulation mode: calculate without persisting
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from collections import defaultdict
import logging

_logger = logging.getLogger(__name__)


class AscCommissionEngine(models.AbstractModel):
    _name = 'asc.commission.engine'
    _description = 'Commission Calculation Engine'

    # ─────────────────────────────────────────────────────────────────────────
    # Public Entry Points
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def calculate_for_order(self, order, simulate=False):
        """
        Calculate commissions for a single sale order.
        Returns list of (salesperson, amount, plan, rule) tuples if simulate=True,
        otherwise creates/updates asc.commission.line records.
        """
        plan = self._find_plan_for_user(order.user_id, order.date_order.date())
        if not plan:
            return []
        results = self._calculate_order_commissions(order, plan, simulate=simulate)
        if not simulate:
            self._persist_order_commissions(order, results)
        return results

    @api.model
    def calculate_for_invoice(self, invoice, simulate=False):
        """
        Calculate commissions for an account.move (invoice).
        """
        if invoice.move_type not in ('out_invoice', 'out_refund'):
            return []
        salesperson = invoice.invoice_user_id or invoice.user_id
        if not salesperson:
            return []
        invoice_date = invoice.invoice_date or fields.Date.today()
        plan = self._find_plan_for_user(salesperson, invoice_date)
        if not plan:
            return []
        results = self._calculate_invoice_commissions(invoice, plan, simulate=simulate)
        if not simulate:
            self._persist_invoice_commissions(invoice, results)
        return results

    @api.model
    def batch_recalculate(self, domain=None, month=None, year=None):
        """
        Batch recalculate commissions. Called by cron.
        Processes in chunks to avoid memory issues.
        """
        CHUNK_SIZE = 200
        today = fields.Date.today()
        month = month or today.month
        year = year or today.year

        base_domain = [
            ('period_month', '=', month),
            ('period_year', '=', year),
            ('state', 'in', ['draft', 'calculated']),
            ('is_simulation', '=', False),
        ]
        if domain:
            base_domain += domain

        all_lines = self.env['asc.commission.line'].search(base_domain)
        total = len(all_lines)
        _logger.info('ASC Batch recalculate: %d lines for %s/%s', total, month, year)

        for i in range(0, total, CHUNK_SIZE):
            chunk = all_lines[i:i + CHUNK_SIZE]
            self.recalculate_lines(chunk)
            self.env.cr.commit()

    @api.model
    def recalculate_lines(self, lines):
        """Recalculate specific commission lines."""
        if not lines:
            return
        # Group by source document for efficiency
        order_lines = lines.filtered(lambda l: l.sale_order_id and not l.invoice_id)
        invoice_lines = lines.filtered(lambda l: l.invoice_id)

        # Bulk prefetch
        order_lines.mapped('plan_id')
        order_lines.mapped('sale_order_id.order_line.product_id')
        invoice_lines.mapped('invoice_id.invoice_line_ids.product_id')

        for line in order_lines:
            results = self._calculate_order_commissions(line.sale_order_id, line.plan_id)
            # Update this specific line if found in results
            for r in results:
                if r['salesperson_id'] == line.salesperson_id.id:
                    line.write({
                        'commission_amount': r['commission_amount'],
                        'bonus_amount': r['bonus_amount'],
                        'rate_applied': r['rate_applied'],
                        'calculation_method': r['calculation_method'],
                        'state': 'calculated',
                    })

        for line in invoice_lines:
            results = self._calculate_invoice_commissions(line.invoice_id, line.plan_id)
            for r in results:
                if r['salesperson_id'] == line.salesperson_id.id:
                    line.write({
                        'commission_amount': r['commission_amount'],
                        'bonus_amount': r['bonus_amount'],
                        'rate_applied': r['rate_applied'],
                        'calculation_method': r['calculation_method'],
                        'state': 'calculated',
                    })

    # ─────────────────────────────────────────────────────────────────────────
    # Plan Resolution
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def _find_plan_for_user(self, user, date):
        """
        Find the best matching commission plan for a user on a date.
        Priority: explicit user assignment > team assignment > default.
        Single query with prefetch.
        """
        if not user:
            return None
        plans = self.env['asc.commission.plan'].search([
            ('active', '=', True),
            ('date_from', '<=', date),
            '|', ('date_to', '=', False), ('date_to', '>=', date),
            ('company_id', 'in', self.env.companies.ids),
        ], order='sequence, id')

        # User-specific plan
        for plan in plans:
            if user in plan.user_ids:
                return plan
        # Team plan
        user_team_ids = user.sale_team_id.ids if hasattr(user, 'sale_team_id') else []
        for plan in plans:
            if plan.team_ids and set(plan.team_ids.ids).intersection(user_team_ids):
                return plan
        # Default (first active plan)
        return plans[:1] or None

    # ─────────────────────────────────────────────────────────────────────────
    # Calculation Core
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def _calculate_order_commissions(self, order, plan, simulate=False):
        """
        Calculate commissions for a sale order against a plan.
        Returns list of result dicts.
        """
        salesperson = order.user_id
        if not salesperson:
            return []

        date = order.date_order.date() if order.date_order else fields.Date.today()
        base_amount = sum(order.order_line.mapped('price_subtotal'))
        margin_amount = sum(
            (line.price_subtotal - line.product_id.standard_price * line.product_uom_qty)
            for line in order.order_line
            if line.product_id
        )

        return self._apply_plan(
            plan=plan,
            salesperson=salesperson,
            date=date,
            base_amount=base_amount,
            margin_amount=margin_amount,
            source_lines=order.order_line,
            context_label=f'order:{order.name}',
        )

    @api.model
    def _calculate_invoice_commissions(self, invoice, plan, simulate=False):
        """
        Calculate commissions for an invoice against a plan.
        Handles credit notes (negative amounts → clawback).
        """
        salesperson = invoice.invoice_user_id or invoice.user_id
        if not salesperson:
            return []

        date = invoice.invoice_date or fields.Date.today()
        sign = -1 if invoice.move_type == 'out_refund' else 1
        base_amount = sign * invoice.amount_untaxed
        margin_amount = sign * sum(
            (line.price_subtotal - line.product_id.standard_price * line.quantity)
            for line in invoice.invoice_line_ids
            if line.product_id and line.display_type == 'product'
        )

        return self._apply_plan(
            plan=plan,
            salesperson=salesperson,
            date=date,
            base_amount=base_amount,
            margin_amount=margin_amount,
            source_lines=invoice.invoice_line_ids.filtered(
                lambda l: l.display_type == 'product'
            ),
            context_label=f'invoice:{invoice.name}',
        )

    @api.model
    def _apply_plan(self, plan, salesperson, date, base_amount, margin_amount, source_lines, context_label=''):
        """
        Core plan application logic.
        Evaluates all active rules in priority order.
        Returns a list of result dicts.
        """
        results = []
        commission_amount = 0.0
        bonus_amount = 0.0
        rate_applied = 0.0
        method_parts = []
        exclusive_triggered = False

        # Get active rules sorted by priority (ascending = higher priority first)
        active_rules = plan.rule_ids.filtered(lambda r: r.active).sorted('priority')

        # Prefetch rule data to avoid per-rule queries
        active_rules.mapped('tier_ids')
        active_rules.mapped('product_ids')
        active_rules.mapped('product_category_ids')

        # Determine base for calculation
        calc_base = base_amount if plan.calculation_base in ('invoiced', 'ordered') else base_amount

        for rule in active_rules:
            if exclusive_triggered:
                break
            if not self._rule_applies(rule, date):
                continue

            rule_amount = self._evaluate_rule(rule, calc_base, margin_amount, source_lines)
            if rule_amount is None:
                continue

            commission_amount += rule_amount
            rate_applied = rule.rate or rate_applied
            method_parts.append(f'{rule.name}({rule.rule_type})')

            if rule.is_exclusive:
                exclusive_triggered = True
                break

        # Plan-level fixed / percentage if no rules matched
        if not method_parts:
            commission_amount, rate_applied = self._apply_plan_base(plan, calc_base, margin_amount)
            method_parts.append(f'plan_base({plan.plan_type})')

        # Bonus evaluation
        bonus_amount = self._evaluate_bonuses(plan, salesperson, date, base_amount, commission_amount)

        # Manager override (fetch from context if any)
        override_amount = 0.0

        # Apply cap
        if commission_amount and plan.rule_ids.filtered(lambda r: r.apply_cap and r.max_amount):
            cap = min(r.max_amount for r in plan.rule_ids if r.apply_cap and r.max_amount)
            commission_amount = min(commission_amount, cap)

        results.append({
            'salesperson_id': salesperson.id,
            'plan_id': plan.id,
            'commission_amount': max(0.0, commission_amount),
            'bonus_amount': max(0.0, bonus_amount),
            'override_amount': override_amount,
            'base_amount': base_amount,
            'margin_amount': margin_amount,
            'rate_applied': rate_applied,
            'calculation_method': ' | '.join(method_parts),
            'currency_id': plan.currency_id.id,
            'date': date,
        })

        return results

    def _rule_applies(self, rule, date):
        """Check if rule is effective on a given date."""
        if rule.date_from and date < rule.date_from:
            return False
        if rule.date_to and date > rule.date_to:
            return False
        return True

    def _evaluate_rule(self, rule, base_amount, margin_amount, source_lines):
        """Evaluate a single rule and return the commission amount."""
        rtype = rule.rule_type

        if rtype == 'fixed':
            return rule.fixed_amount

        elif rtype == 'percentage':
            amount = margin_amount if rule.rate_on == 'margin' else base_amount
            return (rule.rate / 100.0) * amount

        elif rtype == 'tiered':
            return self._evaluate_tiered(rule, base_amount)

        elif rtype == 'bonus':
            return None  # Handled separately in _evaluate_bonuses

        elif rtype == 'clawback':
            return -(rule.rate / 100.0) * base_amount if base_amount < 0 else None

        elif rtype == 'override':
            return None  # Manager override applied separately

        return None

    def _evaluate_tiered(self, rule, base_amount):
        """
        Progressive tiered calculation.
        Supports both progressive (amount in each bracket) and flat-rate (rate for total).
        """
        tiers = rule.tier_ids.sorted('amount_from')
        if not tiers:
            return 0.0

        total = 0.0
        remaining = base_amount

        for tier in tiers:
            if remaining <= 0:
                break
            from_amt = tier.amount_from
            to_amt = tier.amount_to or float('inf')

            if base_amount < from_amt:
                break

            bracket_amount = min(remaining, to_amt - from_amt) if to_amt != float('inf') else remaining
            bracket_amount = max(0.0, min(bracket_amount, base_amount - from_amt))

            if tier.tier_method == 'rate':
                total += (tier.rate / 100.0) * bracket_amount
            else:
                total += tier.fixed_amount

            remaining -= bracket_amount

        return total

    def _apply_plan_base(self, plan, base_amount, margin_amount):
        """Apply plan-level commission when no rules match."""
        ptype = plan.plan_type
        if ptype == 'fixed':
            return plan.fixed_amount, 0.0
        elif ptype == 'percentage':
            rate = plan.commission_rate
            return (rate / 100.0) * base_amount, rate
        elif ptype == 'margin_based':
            rate = plan.margin_rate
            if plan.min_margin_pct:
                margin_pct = (margin_amount / base_amount * 100) if base_amount else 0
                if margin_pct < plan.min_margin_pct:
                    return 0.0, 0.0
            return (rate / 100.0) * margin_amount, rate
        elif ptype == 'tiered':
            # Use first tiered rule if exists
            tiered_rule = plan.rule_ids.filtered(lambda r: r.rule_type == 'tiered')[:1]
            if tiered_rule:
                return self._evaluate_tiered(tiered_rule, base_amount), tiered_rule.rate
        return 0.0, 0.0

    def _evaluate_bonuses(self, plan, salesperson, date, base_amount, commission_amount):
        """
        Evaluate active bonuses and accelerators.
        Returns total bonus amount.
        """
        total_bonus = 0.0
        bonuses = self.env['asc.bonus'].search([
            ('state', '=', 'approved'),
            ('date_from', '<=', date),
            ('date_to', '>=', date),
            ('company_id', '=', plan.company_id.id),
        ])

        for bonus in bonuses:
            if not bonus.is_applicable(salesperson, date):
                continue
            if bonus.amount_type == 'fixed':
                total_bonus += bonus.amount
            elif bonus.amount_type == 'percentage':
                total_bonus += (bonus.percentage / 100.0) * commission_amount
            elif bonus.amount_type == 'per_unit':
                pass  # Requires unit count — handled in product-level calculation

        return total_bonus

    # ─────────────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def _persist_order_commissions(self, order, results):
        """Bulk create/update commission lines for an order."""
        if not results:
            return
        CommLine = self.env['asc.commission.line']
        existing = CommLine.search([
            ('sale_order_id', '=', order.id),
            ('is_simulation', '=', False),
        ])
        existing_by_user = {l.salesperson_id.id: l for l in existing}

        to_create = []
        to_update = []
        for r in results:
            vals = self._result_to_line_vals(r, order=order)
            uid = r['salesperson_id']
            if uid in existing_by_user:
                to_update.append((existing_by_user[uid], vals))
            else:
                to_create.append(vals)

        if to_create:
            CommLine.create(to_create)
        for line, vals in to_update:
            line.write(vals)

    @api.model
    def _persist_invoice_commissions(self, invoice, results):
        """Bulk create/update commission lines for an invoice."""
        if not results:
            return
        CommLine = self.env['asc.commission.line']
        existing = CommLine.search([
            ('invoice_id', '=', invoice.id),
            ('is_simulation', '=', False),
        ])
        existing_by_user = {l.salesperson_id.id: l for l in existing}

        to_create = []
        to_update = []
        for r in results:
            vals = self._result_to_line_vals(r, invoice=invoice)
            uid = r['salesperson_id']
            if uid in existing_by_user:
                to_update.append((existing_by_user[uid], vals))
            else:
                to_create.append(vals)

        if to_create:
            CommLine.create(to_create)
        for line, vals in to_update:
            line.write(vals)

    def _result_to_line_vals(self, result, order=None, invoice=None):
        """Convert a calculation result dict to asc.commission.line field values."""
        salesperson = self.env['res.users'].browse(result['salesperson_id'])
        vals = {
            'plan_id': result['plan_id'],
            'salesperson_id': result['salesperson_id'],
            'team_id': salesperson.sale_team_id.id if hasattr(salesperson, 'sale_team_id') else False,
            'commission_amount': result['commission_amount'],
            'bonus_amount': result['bonus_amount'],
            'override_amount': result.get('override_amount', 0.0),
            'base_amount': result['base_amount'],
            'margin_amount': result.get('margin_amount', 0.0),
            'rate_applied': result['rate_applied'],
            'calculation_method': result['calculation_method'],
            'currency_id': result['currency_id'],
            'date': result['date'],
            'state': 'calculated',
            'company_id': self.env.company.id,
        }
        if order:
            vals['sale_order_id'] = order.id
        if invoice:
            vals['invoice_id'] = invoice.id
            vals['sale_order_id'] = invoice.invoice_origin and self.env['sale.order'].search(
                [('name', '=', invoice.invoice_origin)], limit=1
            ).id or False
        return vals
