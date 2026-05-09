# -*- coding: utf-8 -*-
"""Reusable mixins shared across commission models."""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CommissionAmountMixin(models.AbstractModel):
    """Provides currency-aware amount fields and formatting helpers."""

    _name = 'commission.amount.mixin'
    _description = 'Commission Amount Mixin'

    company_id = fields.Many2one(
        'res.company', string='Company',
        required=True, default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        related='company_id.currency_id', store=True, readonly=True,
    )

    def _format_amount(self, amount):
        """Return human-readable currency string."""
        self.ensure_one()
        return self.currency_id.symbol + ' {:,.2f}'.format(amount)


class CommissionStateMixin(models.AbstractModel):
    """Provides standard state field and transition helpers."""

    _name = 'commission.state.mixin'
    _description = 'Commission State Mixin'

    STATES = [
        ('draft', 'Draft'),
        ('calculated', 'Calculated'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('finance_approved', 'Finance Approved'),
        ('payroll_processed', 'Payroll Processed'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
        ('disputed', 'Disputed'),
    ]

    state = fields.Selection(STATES, string='Status', default='draft', tracking=True, index=True)

    def action_draft(self):
        self._check_state_transition('draft')
        self.write({'state': 'draft'})

    def action_submit(self):
        self._check_state_transition('submitted')
        self.write({'state': 'submitted'})

    def action_approve(self):
        self._check_state_transition('approved')
        self.write({'state': 'approved'})

    def action_finance_approve(self):
        self._check_state_transition('finance_approved')
        self.write({'state': 'finance_approved'})

    def action_cancel(self):
        self._check_state_transition('cancelled')
        self.write({'state': 'cancelled'})

    def _check_state_transition(self, target_state):
        """Override in subclasses to enforce transition rules."""
        pass

    def _get_state_color(self):
        """Return Bootstrap color class for current state."""
        colors = {
            'draft': 'secondary',
            'calculated': 'info',
            'submitted': 'primary',
            'approved': 'success',
            'finance_approved': 'success',
            'payroll_processed': 'warning',
            'paid': 'success',
            'cancelled': 'danger',
            'disputed': 'warning',
        }
        return colors.get(self.state, 'secondary')


class CommissionAuditMixin(models.AbstractModel):
    """Provides audit logging fields."""

    _name = 'commission.audit.mixin'
    _description = 'Commission Audit Mixin'

    calculated_at = fields.Datetime(string='Calculated At', readonly=True)
    calculated_by = fields.Many2one('res.users', string='Calculated By', readonly=True)
    approved_at = fields.Datetime(string='Approved At', readonly=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    paid_at = fields.Datetime(string='Paid At', readonly=True)
    audit_notes = fields.Text(string='Audit Notes')

    def _stamp_calculated(self):
        self.write({
            'calculated_at': fields.Datetime.now(),
            'calculated_by': self.env.user.id,
        })

    def _stamp_approved(self):
        self.write({
            'approved_at': fields.Datetime.now(),
            'approved_by_id': self.env.user.id,
        })

    def _stamp_paid(self):
        self.write({'paid_at': fields.Datetime.now()})
