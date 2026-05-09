# -*- coding: utf-8 -*-
"""Commission Period — time-bounded window for commission accrual."""

import logging
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)

PERIOD_TYPES = [
    ('monthly', 'Monthly'),
    ('weekly', 'Weekly'),
    ('quarterly', 'Quarterly'),
    ('yearly', 'Yearly'),
    ('custom', 'Custom'),
]

PERIOD_STATES = [
    ('draft', 'Draft'),
    ('open', 'Open'),
    ('closed', 'Closed'),
    ('locked', 'Locked'),
]


class CommissionPeriod(models.Model):
    """Commission accrual period with auto-creation and locking support."""

    _name = 'commission.period'
    _description = 'Commission Period'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc'

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(string='Period Name', required=True, tracking=True)
    code = fields.Char(
        string='Code', copy=False,
        default=lambda self: self.env['ir.sequence'].next_by_code('commission.period'),
    )
    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company, index=True,
    )
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', store=True, readonly=True,
    )

    # ── Dates ─────────────────────────────────────────────────────────────────
    period_type = fields.Selection(
        PERIOD_TYPES, string='Period Type',
        required=True, default='monthly', tracking=True,
    )
    date_start = fields.Date(string='Start Date', required=True, tracking=True, index=True)
    date_end = fields.Date(string='End Date', required=True, tracking=True, index=True)
    payment_date = fields.Date(
        string='Payment Date', tracking=True,
        help='Scheduled date for commission payouts.',
    )
    lock_date = fields.Date(
        string='Lock Date',
        help='After this date the period is automatically locked.',
    )

    # ── State ─────────────────────────────────────────────────────────────────
    state = fields.Selection(
        PERIOD_STATES, string='Status',
        default='draft', tracking=True, index=True,
    )

    # ── Plans ─────────────────────────────────────────────────────────────────
    plan_ids = fields.Many2many(
        'commission.plan', 'commission_period_plan_rel',
        'period_id', 'plan_id',
        string='Applicable Plans',
        help='Leave empty to apply all active plans.',
    )

    # ── Settlement Stats ──────────────────────────────────────────────────────
    settlement_count = fields.Integer(compute='_compute_settlement_stats', string='Settlements')
    total_commission = fields.Monetary(
        compute='_compute_settlement_stats',
        currency_field='currency_id',
        string='Total Commission',
    )
    paid_commission = fields.Monetary(
        compute='_compute_settlement_stats',
        currency_field='currency_id',
        string='Paid Commission',
    )

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = fields.Text(string='Notes')

    _sql_constraints = [
        ('code_company_uniq', 'UNIQUE(code, company_id)', 'Period code must be unique per company.'),
    ]

    # ── Compute ───────────────────────────────────────────────────────────────

    def _compute_settlement_stats(self):
        Settlement = self.env['commission.settlement']
        for rec in self:
            settlements = Settlement.search([('period_id', '=', rec.id)])
            rec.settlement_count = len(settlements)
            rec.total_commission = sum(settlements.mapped('total_commission'))
            rec.paid_commission = sum(
                s.total_commission for s in settlements if s.state == 'paid'
            )

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start >= rec.date_end:
                raise ValidationError('End date must be after start date.')

    @api.constrains('date_start', 'date_end', 'company_id')
    def _check_no_overlap(self):
        for rec in self:
            overlap = self.search([
                ('company_id', '=', rec.company_id.id),
                ('id', '!=', rec.id),
                ('date_start', '<', rec.date_end),
                ('date_end', '>', rec.date_start),
                ('state', '!=', 'locked'),
            ])
            if overlap:
                raise ValidationError(
                    f'Period overlaps with existing period: {overlap[0].name}'
                )

    # ── State Transitions ─────────────────────────────────────────────────────

    def action_open(self):
        """Open a draft period for commission calculation."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(f'Period {rec.name} is not in draft state.')
            rec.write({'state': 'open'})
            rec.message_post(body='Period opened for commission calculation.')

    def action_close(self):
        """Close an open period. Settlements can still be edited."""
        for rec in self:
            if rec.state != 'open':
                raise UserError(f'Period {rec.name} is not open.')
            rec.write({'state': 'closed'})
            rec.message_post(body='Period closed.')

    def action_lock(self):
        """Lock a closed period. No further changes allowed."""
        for rec in self:
            if rec.state not in ('closed', 'open'):
                raise UserError(f'Period {rec.name} cannot be locked from its current state.')
            open_settlements = self.env['commission.settlement'].search([
                ('period_id', '=', rec.id),
                ('state', 'not in', ('paid', 'cancelled')),
            ])
            if open_settlements:
                raise UserError(
                    f'Cannot lock period {rec.name}: {len(open_settlements)} settlement(s) are not yet paid or cancelled.'
                )
            rec.write({'state': 'locked'})
            rec.message_post(body='Period locked. No further changes allowed.')

    def action_reopen(self):
        """Reopen a closed/locked period (admin only)."""
        self.env.user.check_groups('advanced_commission_engine.group_commission_admin')
        for rec in self:
            rec.write({'state': 'open'})
            rec.message_post(body=f'Period reopened by {self.env.user.name}.')

    def action_draft(self):
        for rec in self:
            if rec.state != 'open':
                raise UserError('Only open periods can be reverted to draft.')
            rec.write({'state': 'draft'})

    # ── Auto-creation ─────────────────────────────────────────────────────────

    @api.model
    def cron_auto_create_periods(self):
        """Create next period for each company that has auto-creation enabled."""
        companies = self.env['res.company'].search([])
        for company in companies:
            config = self.env['res.config.settings'].sudo()
            self._auto_create_for_company(company)

    @api.model
    def _auto_create_for_company(self, company):
        """Create the next monthly period if it doesn't exist."""
        today = fields.Date.today()
        next_month_start = today.replace(day=1) + relativedelta(months=1)
        next_month_end = next_month_start + relativedelta(months=1) - relativedelta(days=1)

        existing = self.search([
            ('company_id', '=', company.id),
            ('date_start', '=', next_month_start),
        ])
        if existing:
            return

        self.create({
            'name': next_month_start.strftime('%B %Y'),
            'period_type': 'monthly',
            'date_start': next_month_start,
            'date_end': next_month_end,
            'company_id': company.id,
            'state': 'draft',
        })
        _logger.info('Auto-created commission period for %s: %s', company.name, next_month_start.strftime('%B %Y'))

    @api.model
    def cron_auto_lock_periods(self):
        """Auto-lock periods past their lock_date."""
        today = fields.Date.today()
        to_lock = self.search([
            ('state', 'in', ('open', 'closed')),
            ('lock_date', '<=', today),
        ])
        for period in to_lock:
            try:
                period.action_lock()
            except Exception as e:
                _logger.warning('Could not auto-lock period %s: %s', period.name, e)

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_view_settlements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Settlements — {self.name}',
            'res_model': 'commission.settlement',
            'view_mode': 'list,kanban,form',
            'domain': [('period_id', '=', self.id)],
        }

    def action_generate_settlements(self):
        """Launch wizard to generate settlements for this period."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Generate Settlements',
            'res_model': 'wizard.commission.generate.settlement',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_period_id': self.id},
        }

    @api.model
    def get_current_period(self):
        """Return the open period containing today's date."""
        today = fields.Date.today()
        return self.search([
            ('date_start', '<=', today),
            ('date_end', '>=', today),
            ('state', '=', 'open'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
