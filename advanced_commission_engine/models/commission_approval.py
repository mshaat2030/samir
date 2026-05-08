# -*- coding: utf-8 -*-
"""Commission Approval – audit trail of approval actions on settlements."""

from odoo import fields, models


class CommissionApproval(models.Model):
    """Records each approval step taken on a commission settlement.

    Provides a full audit trail of who approved at which level and when.
    """

    _name = 'commission.approval'
    _description = 'Commission Approval'
    _order = 'settlement_id, date desc'

    settlement_id = fields.Many2one(
        'commission.settlement',
        string='Settlement',
        required=True,
        ondelete='cascade',
        index=True,
    )
    approver_id = fields.Many2one(
        'res.users',
        string='Approver',
        required=True,
        default=lambda self: self.env.user,
    )
    level = fields.Selection(
        [
            ('manager', 'Manager'),
            ('finance', 'Finance'),
            ('hr', 'HR'),
            ('executive', 'Executive'),
        ],
        string='Approval Level',
        required=True,
        default='manager',
        index=True,
    )
    state = fields.Selection(
        [
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('delegated', 'Delegated'),
        ],
        string='Decision',
        required=True,
        default='approved',
    )
    date = fields.Date(
        string='Date',
        default=fields.Date.today,
        required=True,
    )
    notes = fields.Text(string='Notes')

    employee_id = fields.Many2one(
        related='settlement_id.employee_id',
        store=True,
        readonly=True,
        index=True,
    )
    period_id = fields.Many2one(
        related='settlement_id.period_id',
        store=True,
        readonly=True,
        index=True,
    )
