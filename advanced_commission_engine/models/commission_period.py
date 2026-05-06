# -*- coding: utf-8 -*-
import logging
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class CommissionPeriod(models.Model):
    _name = 'commission.period'
    _description = 'Commission Period'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'commission.mixin']
    _order = 'date_from desc'

    name = fields.Char(string='Period Name', required=True, tracking=True)
    code = fields.Char(string='Period Code', copy=False, index=True)
    period_type = fields.Selection([
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('semi_annual', 'Semi-Annual'),
        ('annual', 'Annual'),
        ('custom', 'Custom'),
    ], string='Period Type', required=True, default='monthly', tracking=True)

    date_from = fields.Date(string='Start Date', required=True, tracking=True)
    date_to = fields.Date(string='End Date', required=True, tracking=True)

    state = fields.Selection([
        ('open', 'Open'),
        ('pending_approval', 'Pending Approval'),
        ('locked', 'Locked'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='open', required=True, tracking=True, index=True)

    plan_ids = fields.Many2many(
        'commission.plan',
        'commission_period_plan_rel',
        'period_id', 'plan_id',
        string='Commission Plans',
    )

    settlement_ids = fields.One2many(
        'commission.settlement', 'period_id',
        string='Settlements',
    )
    settlement_count = fields.Integer(
        string='# Settlements', compute='_compute_settlement_count'
    )
    line_ids = fields.One2many(
        'commission.line', 'period_id', string='Commission Lines'
    )
    line_count = fields.Integer(compute='_compute_line_count')

    total_commission = fields.Monetary(
        string='Total Commission',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_paid = fields.Monetary(
        string='Total Paid',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_pending = fields.Monetary(
        string='Total Pending',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )

    locked_by = fields.Many2one('res.users', string='Locked By', readonly=True)
    locked_date = fields.Datetime(string='Locked On', readonly=True)
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True)
    approved_date = fields.Datetime(string='Approved On', readonly=True)

    note = fields.Text(string='Notes')

    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        'Period code must be unique per company.',
    )

    @api.depends('settlement_ids')
    def _compute_settlement_count(self):
        for period in self:
            period.settlement_count = len(period.settlement_ids)

    @api.depends('line_ids')
    def _compute_line_count(self):
        for period in self:
            period.line_count = len(period.line_ids)

    @api.depends('line_ids.commission_amount', 'line_ids.state')
    def _compute_totals(self):
        for period in self:
            lines = period.line_ids
            period.total_commission = sum(lines.mapped('commission_amount'))
            period.total_paid = sum(
                lines.filtered(lambda l: l.state == 'paid').mapped('commission_amount')
            )
            period.total_pending = sum(
                lines.filtered(lambda l: l.state in ('draft', 'validated')).mapped('commission_amount')
            )

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for period in self:
            if period.date_from > period.date_to:
                raise ValidationError(
                    _('Start Date must be before End Date for period "%s".') % period.name
                )

    def action_lock(self):
        for period in self:
            if period.state != 'open':
                raise UserError(_('Only open periods can be locked.'))
            period.write({
                'state': 'locked',
                'locked_by': self.env.uid,
                'locked_date': fields.Datetime.now(),
            })
            period.message_post(body=_('Period locked by %s.') % self.env.user.name)

    def action_unlock(self):
        self._check_group('advanced_commission_engine.group_commission_finance')
        for period in self:
            if period.state != 'locked':
                raise UserError(_('Only locked periods can be unlocked.'))
            period.write({'state': 'open', 'locked_by': False, 'locked_date': False})
            period.message_post(body=_('Period unlocked by %s.') % self.env.user.name)

    def action_submit_approval(self):
        for period in self:
            period.write({'state': 'pending_approval'})
            period.message_post(body=_('Period submitted for approval.'))

    def action_approve(self):
        self._check_group('advanced_commission_engine.group_commission_finance')
        for period in self:
            period.write({
                'state': 'locked',
                'approved_by': self.env.uid,
                'approved_date': fields.Datetime.now(),
                'locked_by': self.env.uid,
                'locked_date': fields.Datetime.now(),
            })
            period.message_post(body=_('Period approved and locked by %s.') % self.env.user.name)

    def action_cancel(self):
        for period in self:
            if period.settlement_ids.filtered(lambda s: s.state == 'paid'):
                raise UserError(
                    _('Cannot cancel period "%s" with paid settlements.') % period.name
                )
            period.write({'state': 'cancelled'})

    def _check_group(self, group_xml_id):
        if not self.env.user.has_group(group_xml_id):
            raise UserError(_('You do not have permission to perform this action.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code'):
                vals['code'] = self.env['ir.sequence'].next_by_code('commission.period') or '/'
        return super().create(vals_list)

    @api.model
    def generate_periods(self, period_type, year, company_id=None):
        """
        Auto-generate periods for a given year and type.
        Returns created periods.
        """
        company = self.env['res.company'].browse(company_id) if company_id else self.env.company
        periods = []

        if period_type == 'monthly':
            for month in range(1, 13):
                date_from = fields.Date.from_string('%s-%02d-01' % (year, month))
                date_to = date_from + relativedelta(months=1, days=-1)
                name = date_from.strftime('%B %Y')
                periods.append((date_from, date_to, name))
        elif period_type == 'quarterly':
            quarters = [
                (1, 3, 'Q1'), (4, 6, 'Q2'), (7, 9, 'Q3'), (10, 12, 'Q4')
            ]
            for start_month, end_month, q_name in quarters:
                date_from = fields.Date.from_string('%s-%02d-01' % (year, start_month))
                date_to = fields.Date.from_string('%s-%02d-01' % (year, end_month)) + relativedelta(months=1, days=-1)
                name = '%s %s' % (q_name, year)
                periods.append((date_from, date_to, name))
        elif period_type == 'annual':
            date_from = fields.Date.from_string('%s-01-01' % year)
            date_to = fields.Date.from_string('%s-12-31' % year)
            periods.append((date_from, date_to, str(year)))

        created = self.env['commission.period']
        for date_from, date_to, name in periods:
            existing = self.search([
                ('company_id', '=', company.id),
                ('date_from', '=', date_from),
                ('date_to', '=', date_to),
            ])
            if not existing:
                created |= self.create({
                    'name': name,
                    'period_type': period_type,
                    'date_from': date_from,
                    'date_to': date_to,
                    'company_id': company.id,
                })
        return created

    def action_view_settlements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Settlements'),
            'res_model': 'commission.settlement',
            'view_mode': 'list,form',
            'domain': [('period_id', '=', self.id)],
            'context': {'default_period_id': self.id},
        }

    def action_compute_commissions(self):
        """Trigger commission computation for this period."""
        self.ensure_one()
        if self.state == 'locked':
            raise UserError(_('Cannot recompute a locked period.'))
        engine = self.env['commission.engine']
        engine.compute_period(self)

    @api.model
    def cron_auto_generate_periods(self):
        """Called by cron: auto-generate next month period for auto-settle companies."""
        import datetime
        today = datetime.date.today()
        companies = self.env['res.company'].search([
            ('commission_auto_settle', '=', True)
        ])
        for company in companies:
            next_month = (today.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
            self.generate_periods('monthly', next_month.year, company_id=company.id)
