# -*- coding: utf-8 -*-
"""Commission Approval — multi-level approval log per settlement."""

import logging
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

APPROVAL_LEVELS = [
    ('manager', 'Manager'),
    ('finance', 'Finance'),
    ('hr', 'HR'),
    ('executive', 'Executive'),
]

APPROVAL_STATES = [
    ('pending', 'Pending'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('bypassed', 'Auto-Bypassed'),
]


class CommissionApproval(models.Model):
    """Approval step record for a settlement's approval workflow."""

    _name = 'commission.approval'
    _description = 'Commission Approval'
    _inherit = ['mail.thread']
    _order = 'settlement_id, level, create_date'

    # ── Identity ──────────────────────────────────────────────────────────────
    settlement_id = fields.Many2one(
        'commission.settlement', string='Settlement',
        required=True, ondelete='cascade', index=True,
    )
    level = fields.Selection(
        APPROVAL_LEVELS, string='Approval Level',
        required=True, tracking=True,
    )
    state = fields.Selection(
        APPROVAL_STATES, string='Status',
        default='pending', tracking=True, index=True,
    )

    # ── Approver ──────────────────────────────────────────────────────────────
    approver_id = fields.Many2one(
        'res.users', string='Approver',
        required=True, tracking=True,
    )
    acted_at = fields.Datetime(string='Decision At', readonly=True)
    comments = fields.Text(string='Comments / Reason', tracking=True)

    # ── Settlement Summary ────────────────────────────────────────────────────
    employee_id = fields.Many2one(
        'hr.employee', related='settlement_id.employee_id',
        store=True, readonly=True,
    )
    commission_amount = fields.Monetary(
        related='settlement_id.total_commission',
        string='Commission Amount',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency', related='settlement_id.currency_id',
        store=True, readonly=True,
    )

    # ── Deadline ──────────────────────────────────────────────────────────────
    deadline = fields.Date(
        string='Approval Deadline',
        default=lambda self: fields.Date.add(fields.Date.today(), days=5),
    )
    is_overdue = fields.Boolean(
        string='Overdue', compute='_compute_is_overdue',
    )

    # ── Compute ───────────────────────────────────────────────────────────────

    def _compute_is_overdue(self):
        today = fields.Date.today()
        for rec in self:
            rec.is_overdue = (
                rec.state == 'pending'
                and rec.deadline
                and today > rec.deadline
            )

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_approve(self):
        """Approve this level and advance settlement state."""
        for rec in self:
            if rec.state != 'pending':
                raise UserError('This approval step is not pending.')
            if rec.approver_id != self.env.user and not self.env.user.has_group(
                'advanced_commission_engine.group_commission_admin'
            ):
                raise UserError('You are not the designated approver for this step.')
            rec.write({'state': 'approved', 'acted_at': fields.Datetime.now()})
            rec.message_post(body=f'Approved at {rec.level} level by {self.env.user.name}.')

            # Advance settlement based on level
            settlement = rec.settlement_id
            if rec.level == 'manager' and settlement.state == 'submitted':
                settlement.write({'state': 'approved', 'approved_by_id': self.env.user.id,
                                  'approved_at': fields.Datetime.now()})
            elif rec.level == 'finance' and settlement.state == 'approved':
                settlement.write({'state': 'finance_approved',
                                  'finance_approved_by': self.env.user.id,
                                  'finance_approved_at': fields.Datetime.now()})

    def action_reject(self):
        """Reject this approval step and block settlement."""
        for rec in self:
            if rec.state != 'pending':
                raise UserError('This approval step is not pending.')
            if not rec.comments:
                raise UserError('Please add a rejection reason in the Comments field.')
            rec.write({'state': 'rejected', 'acted_at': fields.Datetime.now()})
            rec.settlement_id.write({
                'rejection_reason': rec.comments,
            })
            rec.message_post(body=f'Rejected at {rec.level} level: {rec.comments}')

    def action_delegate(self):
        """Return a form to delegate this approval to another user."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Delegate Approval',
            'res_model': 'commission.approval',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    @api.model
    def create_approval_chain(self, settlement):
        """Create all pending approval records for a settlement's plan workflow."""
        plan = settlement.plan_id
        approvals = []
        manager = settlement.employee_id.parent_id
        if plan.require_manager_approval and manager and manager.user_id:
            approvals.append({
                'settlement_id': settlement.id,
                'level': 'manager',
                'approver_id': manager.user_id.id,
            })
        if plan.require_finance_approval:
            finance_users = self.env.ref(
                'advanced_commission_engine.group_commission_finance_manager'
            ).users
            if finance_users:
                approvals.append({
                    'settlement_id': settlement.id,
                    'level': 'finance',
                    'approver_id': finance_users[0].id,
                })
        if plan.require_hr_approval:
            hr_users = self.env.ref(
                'advanced_commission_engine.group_commission_hr_manager'
            ).users
            if hr_users:
                approvals.append({
                    'settlement_id': settlement.id,
                    'level': 'hr',
                    'approver_id': hr_users[0].id,
                })
        return self.create(approvals)
