# -*- coding: utf-8 -*-
"""Commission Period – time-bound window for commission accumulation."""

import calendar
from datetime import date, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class CommissionPeriod(models.Model):
    """Represents a time window (monthly, quarterly, etc.) for commission accumulation.

    Periods progress through states: open → locked → frozen.
    A locked period cannot receive new commission lines.
    A frozen period is fully closed; only finance managers can reopen.
    """

    _name = 'commission.period'
    _description = 'Commission Period'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, company_id'
    _rec_name = 'name'
    _check_company_auto = True

    name = fields.Char(
        string='Period Name',
        required=True,
        tracking=True,
        index=True,
    )
    code = fields.Char(
        string='Reference',
        default=lambda self: self.env['ir.sequence'].next_by_code('commission.period'),
        readonly=True,
        copy=False,
    )
    period_type = fields.Selection(
        [
            ('weekly', 'Weekly'),
            ('monthly', 'Monthly'),
            ('quarterly', 'Quarterly'),
            ('yearly', 'Yearly'),
            ('custom', 'Custom'),
        ],
        string='Period Type',
        required=True,
        default='monthly',
        tracking=True,
        index=True,
    )
    date_start = fields.Date(
        string='Start Date',
        required=True,
        tracking=True,
        index=True,
    )
    date_end = fields.Date(
        string='End Date',
        required=True,
        tracking=True,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    state = fields.Selection(
        [
            ('open', 'Open'),
            ('locked', 'Locked'),
            ('frozen', 'Frozen'),
        ],
        string='State',
        default='open',
        required=True,
        tracking=True,
        index=True,
    )
    notes = fields.Text(string='Notes')

    # ── Settlements ───────────────────────────────────────────────────────────
    settlement_ids = fields.One2many(
        'commission.settlement',
        'period_id',
        string='Settlements',
    )
    settlement_count = fields.Integer(
        compute='_compute_settlement_count',
        string='Settlements',
    )
    total_commission = fields.Monetary(
        compute='_compute_totals',
        string='Total Commission',
        currency_field='currency_id',
        store=True,
    )
    paid_commission = fields.Monetary(
        compute='_compute_totals',
        string='Total Paid',
        currency_field='currency_id',
        store=True,
    )

    # ── Auto-creation helper ──────────────────────────────────────────────────
    auto_created = fields.Boolean(
        string='Auto-Created',
        default=False,
        readonly=True,
    )


    _dates_consistent = models.Constraint(
        'CHECK(date_start <= date_end)',
        'Period start date must be on or before end date.',
    )


    @api.constrains('date_start', 'date_end', 'company_id', 'period_type')
    def _check_no_overlap(self):
        for period in self:
            domain = [
                ('id', '!=', period.id),
                ('company_id', '=', period.company_id.id),
                ('date_start', '<=', period.date_end),
                ('date_end', '>=', period.date_start),
            ]
            if self.search(domain, limit=1):
                raise ValidationError(
                    f"Period '{period.name}' overlaps with an existing period for the same company."
                )

    # ── Computes ──────────────────────────────────────────────────────────────
    def _compute_settlement_count(self):
        data = self.env['commission.settlement'].read_group(
            [('period_id', 'in', self.ids)],
            ['period_id'],
            ['period_id'],
        )
        mapping = {d['period_id'][0]: d['period_id_count'] for d in data}
        for period in self:
            period.settlement_count = mapping.get(period.id, 0)

    @api.depends('settlement_ids.final_amount', 'settlement_ids.state')
    def _compute_totals(self):
        for period in self:
            settlements = period.settlement_ids
            period.total_commission = sum(settlements.mapped('final_amount'))
            period.paid_commission = sum(
                settlements.filtered(lambda s: s.state == 'paid').mapped('final_amount')
            )

    # ── State Transitions ─────────────────────────────────────────────────────
    def action_lock(self):
        """Lock the period – no new commission lines can be added."""
        for period in self:
            if period.state != 'open':
                raise UserError(f"Period '{period.name}' is not in Open state.")
            period.state = 'locked'

    def action_freeze(self):
        """Freeze the period – fully closed, no changes allowed."""
        for period in self:
            if period.state != 'locked':
                raise UserError(f"Period '{period.name}' must be locked before freezing.")
            period.state = 'frozen'

    def action_reopen(self):
        """Reopen a frozen period (finance manager only)."""
        self._check_finance_rights()
        for period in self:
            if period.state != 'frozen':
                raise UserError(f"Period '{period.name}' is not frozen.")
            period.state = 'open'

    def action_unlock(self):
        """Unlock a locked period back to open."""
        self._check_finance_rights()
        for period in self:
            if period.state != 'locked':
                raise UserError(f"Period '{period.name}' is not locked.")
            period.state = 'open'

    def _check_finance_rights(self):
        if not self.env.user.has_group(
            'advanced_commission_engine.group_commission_finance_manager'
        ):
            raise UserError('Only Finance Managers can reopen/unlock periods.')

    # ── Actions ───────────────────────────────────────────────────────────────
    def action_view_settlements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Settlements – {self.name}',
            'res_model': 'commission.settlement',
            'view_mode': 'list,form',
            'domain': [('period_id', '=', self.id)],
            'context': {'default_period_id': self.id},
        }

    def action_generate_settlements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Generate Settlements',
            'res_model': 'wizard.generate.settlement',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_period_id': self.id},
        }

    # ── Cron: Auto-create periods ─────────────────────────────────────────────
    @api.model
    def _cron_create_periods(self):
        """Auto-create next periods for each company based on open plans."""
        plans = self.env['commission.plan'].search([
            ('state', '=', 'active'),
            ('period_type', '!=', 'custom'),
        ])
        for plan in plans:
            self._ensure_next_period(plan)

    @api.model
    def _ensure_next_period(self, plan):
        """Create the next period for a plan if it doesn't exist yet."""
        today = date.today()
        existing = self.search([
            ('company_id', '=', plan.company_id.id),
            ('period_type', '=', plan.period_type),
            ('date_start', '<=', today),
            ('date_end', '>=', today),
        ], limit=1)
        if not existing:
            self._create_period_for_date(today, plan.period_type, plan.company_id)

    @api.model
    def _create_period_for_date(self, target_date, period_type, company):
        """Create a period containing target_date."""
        if period_type == 'monthly':
            d_start = target_date.replace(day=1)
            last_day = calendar.monthrange(d_start.year, d_start.month)[1]
            d_end = d_start.replace(day=last_day)
            name = d_start.strftime('%B %Y')
        elif period_type == 'weekly':
            d_start = target_date - timedelta(days=target_date.weekday())
            d_end = d_start + timedelta(days=6)
            name = f"Week {d_start.isocalendar()[1]} – {d_start.year}"
        elif period_type == 'quarterly':
            q = (target_date.month - 1) // 3 + 1
            q_start_month = (q - 1) * 3 + 1
            d_start = target_date.replace(month=q_start_month, day=1)
            q_end_month = q_start_month + 2
            last_day = calendar.monthrange(target_date.year, q_end_month)[1]
            d_end = date(target_date.year, q_end_month, last_day)
            name = f"Q{q} {target_date.year}"
        elif period_type == 'yearly':
            d_start = target_date.replace(month=1, day=1)
            d_end = target_date.replace(month=12, day=31)
            name = str(target_date.year)
        else:
            return None

        # Check if an overlapping period already exists for this company / type
        existing = self.search([
            ('company_id', '=', company.id),
            ('period_type', '=', period_type),
            ('date_start', '<=', d_end),
            ('date_end', '>=', d_start),
        ], limit=1)
        if existing:
            return existing

        return self.create({
            'name': name,
            'period_type': period_type,
            'date_start': d_start,
            'date_end': d_end,
            'company_id': company.id,
            'auto_created': True,
        })
