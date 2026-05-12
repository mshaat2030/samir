# -*- coding: utf-8 -*-
"""
Reusable mixins for ASC module.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class AscMultiCompanyMixin(models.AbstractModel):
    """Enforces multi-company isolation on all ASC records."""
    _name = 'asc.multi.company.mixin'
    _description = 'ASC Multi-Company Mixin'

    company_id = fields.Many2one(
        'res.company', string='Company',
        required=True, index=True,
        default=lambda self: self.env.company,
    )

    @api.model
    def _company_domain(self):
        return [('company_id', 'in', self.env.companies.ids)]


class AscMailMixin(models.AbstractModel):
    """Adds chatter + activity support to ASC models."""
    _name = 'asc.mail.mixin'
    _description = 'ASC Mail Mixin'
    _inherit = ['mail.thread', 'mail.activity.mixin']


class AscStateMixin(models.AbstractModel):
    """Standard state machine for commission documents."""
    _name = 'asc.state.mixin'
    _description = 'ASC State Mixin'

    state = fields.Selection([
        ('draft', 'Draft'),
        ('calculated', 'Calculated'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True,
        tracking=True, index=True, copy=False)

    def action_calculate(self):
        self._check_state('draft')
        self._do_calculate()
        self.write({'state': 'calculated'})

    def action_submit(self):
        self._check_state('calculated')
        self.write({'state': 'submitted'})

    def action_approve(self):
        self._check_state('submitted')
        if not self.env.user.has_group('advanced_sales_commission.group_asc_manager'):
            raise UserError(_('Only Commission Managers can approve.'))
        self.write({'state': 'approved'})

    def action_cancel(self):
        if self.state == 'paid':
            raise UserError(_('Cannot cancel a paid commission.'))
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self._check_state('cancelled')
        self.write({'state': 'draft'})

    def _check_state(self, expected):
        for rec in self:
            if rec.state != expected:
                raise UserError(
                    _('Action not allowed in state "%s". Expected "%s".') % (rec.state, expected)
                )

    def _do_calculate(self):
        """Override in concrete models."""
        pass


class AscCurrencyMixin(models.AbstractModel):
    """Multi-currency helpers."""
    _name = 'asc.currency.mixin'
    _description = 'ASC Currency Mixin'

    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    def _convert_amount(self, amount, from_currency, to_currency, date=None):
        """Convert amount between currencies efficiently."""
        if from_currency == to_currency:
            return amount
        date = date or fields.Date.today()
        return from_currency._convert(amount, to_currency, self.env.company, date)
