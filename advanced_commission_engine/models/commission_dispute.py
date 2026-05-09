# -*- coding: utf-8 -*-
"""Commission Dispute — employee-raised challenge against a settlement."""

import logging
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DISPUTE_STATES = [
    ('draft', 'Submitted'),
    ('under_review', 'Under Review'),
    ('resolved_accepted', 'Resolved — Accepted'),
    ('resolved_rejected', 'Resolved — Rejected'),
    ('escalated', 'Escalated'),
    ('closed', 'Closed'),
]

DISPUTE_REASONS = [
    ('calculation_error', 'Calculation Error'),
    ('missing_transactions', 'Missing Transactions'),
    ('wrong_rate', 'Wrong Rate Applied'),
    ('period_error', 'Wrong Period'),
    ('clawback_dispute', 'Clawback Dispute'),
    ('target_error', 'Target / Quota Error'),
    ('other', 'Other'),
]


class CommissionDispute(models.Model):
    """Employee-submitted dispute for review by commission managers."""

    _name = 'commission.dispute'
    _description = 'Commission Dispute'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Dispute Reference', required=True, copy=False,
        default=lambda self: self.env['ir.sequence'].next_by_code('commission.dispute'),
    )
    settlement_id = fields.Many2one(
        'commission.settlement', string='Settlement',
        required=True, ondelete='cascade', index=True,
    )
    employee_id = fields.Many2one(
        'hr.employee', related='settlement_id.employee_id',
        store=True, readonly=True, index=True,
    )
    period_id = fields.Many2one(
        'commission.period', related='settlement_id.period_id',
        store=True, readonly=True,
    )
    company_id = fields.Many2one(
        'res.company', related='settlement_id.company_id',
        store=True, readonly=True,
    )

    # ── Dispute Details ───────────────────────────────────────────────────────
    reason = fields.Selection(
        DISPUTE_REASONS, string='Dispute Reason',
        required=True, tracking=True,
    )
    description = fields.Text(
        string='Detailed Description', required=True, tracking=True,
    )
    disputed_amount = fields.Monetary(
        string='Disputed Amount',
        currency_field='currency_id',
        tracking=True,
        help='Amount the employee believes should be different.',
    )
    currency_id = fields.Many2one(
        'res.currency', related='settlement_id.currency_id',
        store=True, readonly=True,
    )

    # ── State ─────────────────────────────────────────────────────────────────
    state = fields.Selection(
        DISPUTE_STATES, string='Status',
        default='draft', tracking=True, index=True,
    )
    priority = fields.Selection([
        ('0', 'Normal'),
        ('1', 'Important'),
        ('2', 'Urgent'),
    ], string='Priority', default='0')

    # ── Resolution ────────────────────────────────────────────────────────────
    assigned_to = fields.Many2one(
        'res.users', string='Assigned To', tracking=True,
    )
    resolution_notes = fields.Text(string='Resolution Notes', tracking=True)
    resolution_date = fields.Date(string='Resolution Date', readonly=True)
    adjusted_amount = fields.Monetary(
        string='Adjusted Amount Awarded',
        currency_field='currency_id',
        tracking=True,
    )
    resulting_adjustment_id = fields.Many2one(
        'commission.adjustment', string='Resulting Adjustment',
        readonly=True,
    )

    # ── Evidence ──────────────────────────────────────────────────────────────
    attachment_ids = fields.Many2many(
        'ir.attachment', 'commission_dispute_attachment_rel',
        'dispute_id', 'attachment_id',
        string='Evidence / Attachments',
    )

    # ── Deadline ──────────────────────────────────────────────────────────────
    deadline = fields.Date(
        string='Response Deadline',
        default=lambda self: fields.Date.add(fields.Date.today(), days=14),
    )

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('disputed_amount')
    def _check_disputed_amount(self):
        for rec in self:
            if rec.disputed_amount and rec.disputed_amount < 0:
                raise UserError('Disputed amount must be positive.')

    # ── State Transitions ─────────────────────────────────────────────────────

    def action_start_review(self):
        """Assign to reviewer and begin review."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError('Only submitted disputes can be started.')
            rec.write({
                'state': 'under_review',
                'assigned_to': self.env.user.id,
            })
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=self.env.user.id,
                note=f'Review dispute {rec.name} — deadline {rec.deadline}',
            )
            rec.message_post(body=f'Dispute review started by {self.env.user.name}.')

    def action_accept(self):
        """Accept dispute and create compensating adjustment."""
        for rec in self:
            if rec.state != 'under_review':
                raise UserError('Only under-review disputes can be accepted.')
            if not rec.resolution_notes:
                raise UserError('Resolution notes are required when accepting a dispute.')

            adj = None
            if rec.adjusted_amount:
                adj = self.env['commission.adjustment'].create({
                    'settlement_id': rec.settlement_id.id,
                    'adjustment_type': 'correction',
                    'amount': rec.adjusted_amount,
                    'reason': f'Dispute {rec.name} accepted: {rec.resolution_notes}',
                    'date': fields.Date.today(),
                    'state': 'confirmed',
                })
                adj.action_apply()

            rec.write({
                'state': 'resolved_accepted',
                'resolution_date': fields.Date.today(),
                'resulting_adjustment_id': adj.id if adj else False,
            })
            rec.settlement_id.write({'state': 'calculated'})
            rec.message_post(body=f'Dispute accepted. Adjustment: {rec.adjusted_amount}')

    def action_reject(self):
        """Reject dispute with explanation."""
        for rec in self:
            if rec.state != 'under_review':
                raise UserError('Only under-review disputes can be rejected.')
            if not rec.resolution_notes:
                raise UserError('Resolution notes are required when rejecting a dispute.')
            rec.write({
                'state': 'resolved_rejected',
                'resolution_date': fields.Date.today(),
            })
            rec.message_post(body=f'Dispute rejected: {rec.resolution_notes}')

    def action_escalate(self):
        """Escalate to senior management."""
        for rec in self:
            rec.write({'state': 'escalated', 'priority': '2'})
            rec.message_post(body=f'Dispute escalated by {self.env.user.name}.')

    def action_close(self):
        """Close an accepted or rejected dispute."""
        for rec in self:
            if rec.state not in ('resolved_accepted', 'resolved_rejected', 'escalated'):
                raise UserError('Only resolved or escalated disputes can be closed.')
            rec.write({'state': 'closed'})
