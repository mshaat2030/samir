# -*- coding: utf-8 -*-
"""
asc.commission.line — Computed commission record per salesperson per invoice/order line.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class AscCommissionLine(models.Model):
    _name = 'asc.commission.line'
    _description = 'Commission Line'
    _inherit = ['asc.multi.company.mixin', 'asc.state.mixin', 'mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('asc.commission.line'),
    )

    # ── Relations ─────────────────────────────────────────────────────────────
    plan_id = fields.Many2one(
        'asc.commission.plan', string='Commission Plan',
        required=True, index=True, ondelete='restrict',
    )
    rule_id = fields.Many2one(
        'asc.commission.rule', string='Applied Rule',
        index=True, ondelete='set null',
    )
    salesperson_id = fields.Many2one(
        'res.users', string='Salesperson',
        required=True, index=True, ondelete='restrict',
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        compute='_compute_employee_id', store=True, index=True,
    )
    team_id = fields.Many2one('crm.team', string='Sales Team', index=True)

    # ── Source Document ────────────────────────────────────────────────────────
    sale_order_id = fields.Many2one(
        'sale.order', string='Sale Order', index=True, ondelete='set null',
    )
    invoice_id = fields.Many2one(
        'account.move', string='Invoice', index=True, ondelete='set null',
    )
    invoice_line_id = fields.Many2one(
        'account.move.line', string='Invoice Line', index=True, ondelete='set null',
    )
    product_id = fields.Many2one('product.product', string='Product', index=True)

    # ── Amounts ───────────────────────────────────────────────────────────────
    currency_id = fields.Many2one(
        'res.currency', required=True,
        default=lambda self: self.env.company.currency_id,
    )
    company_currency_id = fields.Many2one(
        related='company_id.currency_id', string='Company Currency', readonly=True,
    )
    base_amount = fields.Monetary(
        string='Base Amount', currency_field='currency_id',
        help='The sales amount used as base for calculation.',
    )
    margin_amount = fields.Monetary(
        string='Margin Amount', currency_field='currency_id',
    )
    commission_amount = fields.Monetary(
        string='Commission Amount', currency_field='currency_id',
        tracking=True,
    )
    commission_amount_company = fields.Monetary(
        string='Commission (Company Currency)',
        currency_field='company_currency_id',
        compute='_compute_company_amount', store=True,
    )
    override_amount = fields.Monetary(
        string='Manager Override Amount', currency_field='currency_id',
    )
    bonus_amount = fields.Monetary(
        string='Bonus Amount', currency_field='currency_id',
    )
    clawback_amount = fields.Monetary(
        string='Clawback Amount', currency_field='currency_id',
    )
    net_commission = fields.Monetary(
        string='Net Commission', currency_field='currency_id',
        compute='_compute_net_commission', store=True,
    )

    # ── Rate Info ─────────────────────────────────────────────────────────────
    rate_applied = fields.Float(string='Rate Applied (%)', digits=(16, 4), readonly=True)
    calculation_method = fields.Char(string='Calculation Method', readonly=True)

    # ── Dates ─────────────────────────────────────────────────────────────────
    date = fields.Date(string='Commission Date', required=True, default=fields.Date.today, index=True)
    period_month = fields.Integer(string='Period Month', compute='_compute_period', store=True)
    period_year = fields.Integer(string='Period Year', compute='_compute_period', store=True)

    # ── Settlement ────────────────────────────────────────────────────────────
    settlement_id = fields.Many2one(
        'asc.commission.settlement', string='Settlement',
        index=True, ondelete='set null',
    )
    is_settled = fields.Boolean(
        string='Settled', compute='_compute_is_settled', store=True,
    )

    # ── Simulation ────────────────────────────────────────────────────────────
    is_simulation = fields.Boolean(string='Simulation', default=False, index=True)
    simulation_note = fields.Char(string='Simulation Note')

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = fields.Text(string='Notes')

    # ─────────────────────────────────────────────────────────────────────────
    # Computed Fields
    # ─────────────────────────────────────────────────────────────────────────
    @api.depends('salesperson_id')
    def _compute_employee_id(self):
        # Batch fetch employees for performance
        user_ids = self.mapped('salesperson_id').ids
        employees = self.env['hr.employee'].search_read(
            [('user_id', 'in', user_ids)],
            ['user_id', 'id'],
        )
        user_to_emp = {e['user_id'][0]: e['id'] for e in employees}
        for line in self:
            emp_id = user_to_emp.get(line.salesperson_id.id)
            line.employee_id = emp_id

    @api.depends('commission_amount', 'currency_id', 'company_id', 'date')
    def _compute_company_amount(self):
        for line in self:
            if line.currency_id == line.company_currency_id:
                line.commission_amount_company = line.commission_amount
            else:
                line.commission_amount_company = line.currency_id._convert(
                    line.commission_amount,
                    line.company_currency_id,
                    line.company_id,
                    line.date or fields.Date.today(),
                )

    @api.depends('commission_amount', 'bonus_amount', 'override_amount', 'clawback_amount')
    def _compute_net_commission(self):
        for line in self:
            line.net_commission = (
                line.commission_amount
                + line.bonus_amount
                + line.override_amount
                - line.clawback_amount
            )

    @api.depends('date')
    def _compute_period(self):
        for line in self:
            if line.date:
                line.period_month = line.date.month
                line.period_year = line.date.year
            else:
                line.period_month = 0
                line.period_year = 0

    @api.depends('settlement_id')
    def _compute_is_settled(self):
        for line in self:
            line.is_settled = bool(line.settlement_id)

    # ─────────────────────────────────────────────────────────────────────────
    # State Actions
    # ─────────────────────────────────────────────────────────────────────────
    def _do_calculate(self):
        """Triggered by action_calculate; delegate to engine."""
        engine = self.env['asc.commission.engine']
        engine.recalculate_lines(self)

    def action_apply_clawback(self):
        """Apply clawback to this commission line."""
        for line in self:
            if line.state not in ('approved', 'paid'):
                raise UserError(_('Can only clawback approved or paid commissions.'))
            plan = line.plan_id
            if not plan.has_clawback:
                raise UserError(_('This plan does not support clawbacks.'))
            line.clawback_amount = line.net_commission
            line._compute_net_commission()
            line.message_post(body=_('Clawback applied: %s') % line.clawback_amount)

    # ─────────────────────────────────────────────────────────────────────────
    # Constraints
    # ─────────────────────────────────────────────────────────────────────────
    _name_uniq = models.Constraint(
        'UNIQUE(name)',
        'Commission line reference must be unique.',
    )

    # ─────────────────────────────────────────────────────────────────────────
    # PostgreSQL Indexes (via _auto_init override)
    # ─────────────────────────────────────────────────────────────────────────
    def _auto_init(self):
        res = super()._auto_init()
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS asc_commission_line_period_idx
            ON asc_commission_line (period_year, period_month, salesperson_id);

            CREATE INDEX IF NOT EXISTS asc_commission_line_state_settled_idx
            ON asc_commission_line (state, is_settled, company_id);
        """)
        return res
