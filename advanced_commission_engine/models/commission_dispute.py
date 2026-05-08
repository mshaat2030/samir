# -*- coding: utf-8 -*-
"""Commission Dispute – employee-raised disputes on settlement amounts."""

from odoo import api, fields, models
from odoo.exceptions import UserError


class CommissionDispute(models.Model):
    """Records a dispute raised by an employee against a settlement.

    Employees can raise disputes from the portal or backend.
    Managers resolve them, optionally creating adjustments.
    """

    _name = 'commission.dispute'
    _description = 'Commission Dispute'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_raised desc'

    name = fields.Char(
        string='Reference',
        default='/',
        copy=False,
        readonly=True,
        index=True,
    )
    settlement_id = fields.Many2one(
        'commission.settlement',
        string='Settlement',
        required=True,
        ondelete='restrict',
        index=True,
    )
    employee_id = fields.Many2one(
        related='settlement_id.employee_id',
        store=True,
        readonly=True,
        index=True,
    )
    currency_id = fields.Many2one(
        related='settlement_id.currency_id',
        readonly=True,
    )
    company_id = fields.Many2one(
        related='settlement_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )

    # ── Dispute Details ───────────────────────────────────────────────────────
    reason = fields.Text(
        string='Dispute Reason',
        required=True,
    )
    dispute_type = fields.Selection(
        [
            ('wrong_amount', 'Wrong Amount'),
            ('missing_line', 'Missing Commission Line'),
            ('wrong_rate', 'Wrong Rate Applied'),
            ('wrong_period', 'Wrong Period'),
            ('duplicate', 'Duplicate Entry'),
            ('other', 'Other'),
        ],
        string='Dispute Type',
        default='wrong_amount',
        required=True,
        index=True,
    )
    current_amount = fields.Monetary(
        string='Current Settlement Amount',
        related='settlement_id.final_amount',
        currency_field='currency_id',
        readonly=True,
    )
    requested_amount = fields.Monetary(
        string='Requested Amount',
        currency_field='currency_id',
    )
    difference = fields.Monetary(
        string='Difference',
        currency_field='currency_id',
        compute='_compute_difference',
    )

    # ── Timeline ──────────────────────────────────────────────────────────────
    date_raised = fields.Date(
        string='Date Raised',
        default=fields.Date.today,
        required=True,
        index=True,
    )
    date_resolved = fields.Date(
        string='Date Resolved',
        readonly=True,
    )
    deadline = fields.Date(
        string='Resolution Deadline',
        compute='_compute_deadline',
        store=True,
    )

    # ── Resolution ────────────────────────────────────────────────────────────
    state = fields.Selection(
        [
            ('open', 'Open'),
            ('under_review', 'Under Review'),
            ('resolved', 'Resolved'),
            ('rejected', 'Rejected'),
            ('withdrawn', 'Withdrawn'),
        ],
        string='State',
        default='open',
        tracking=True,
        index=True,
    )
    resolution = fields.Text(string='Resolution Notes')
    resolved_by_id = fields.Many2one(
        'res.users',
        string='Resolved By',
        readonly=True,
    )
    resolution_action = fields.Selection(
        [
            ('accepted', 'Accepted – Adjustment Created'),
            ('partially_accepted', 'Partially Accepted'),
            ('rejected', 'Rejected'),
            ('no_change', 'No Change Required'),
        ],
        string='Resolution Action',
    )
    adjustment_id = fields.Many2one(
        'commission.adjustment',
        string='Created Adjustment',
        readonly=True,
    )

    # ── Supporting Documents ──────────────────────────────────────────────────
    attachment_count = fields.Integer(
        compute='_compute_attachment_count',
        string='Attachments',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('commission.settlement') or '/'
                ).replace('SET/', 'DIS/')
        return super().create(vals_list)

    @api.depends('current_amount', 'requested_amount')
    def _compute_difference(self):
        for d in self:
            d.difference = (d.requested_amount or 0) - (d.current_amount or 0)

    @api.depends('date_raised')
    def _compute_deadline(self):
        from datetime import timedelta
        for d in self:
            if d.date_raised:
                d.deadline = d.date_raised + timedelta(days=14)
            else:
                d.deadline = False

    def _compute_attachment_count(self):
        attachment_data = self.env['ir.attachment'].read_group(
            [('res_model', '=', self._name), ('res_id', 'in', self.ids)],
            ['res_id'],
            ['res_id'],
        )
        mapping = {d['res_id']: d['res_id_count'] for d in attachment_data}
        for d in self:
            d.attachment_count = mapping.get(d.id, 0)

    def action_review(self):
        self.write({'state': 'under_review'})

    def action_resolve_accept(self):
        """Accept dispute and create an adjustment."""
        if not self.env.user.has_group(
            'advanced_commission_engine.group_commission_manager'
        ):
            raise UserError('Only Commission Managers can resolve disputes.')
        for dispute in self:
            diff = dispute.requested_amount - dispute.current_amount
            if diff:
                adj_type = 'bonus' if diff > 0 else 'penalty'
                adj = self.env['commission.adjustment'].create({
                    'name': f'Dispute Resolution – {dispute.name}',
                    'settlement_id': dispute.settlement_id.id,
                    'adjustment_type': adj_type,
                    'amount': abs(diff),
                    'reason': f'Dispute {dispute.name} accepted: {dispute.reason}',
                    'state': 'approved',
                    'approved_by_id': self.env.uid,
                    'approved_date': fields.Date.today(),
                })
                dispute.adjustment_id = adj
            dispute.write({
                'state': 'resolved',
                'date_resolved': fields.Date.today(),
                'resolved_by_id': self.env.uid,
                'resolution_action': 'accepted',
            })
            # Put settlement back to calculated so it can be re-approved
            if dispute.settlement_id.state == 'disputed':
                dispute.settlement_id.state = 'calculated'

    def action_reject(self):
        if not self.env.user.has_group(
            'advanced_commission_engine.group_commission_manager'
        ):
            raise UserError('Only Commission Managers can reject disputes.')
        for dispute in self:
            dispute.write({
                'state': 'rejected',
                'date_resolved': fields.Date.today(),
                'resolved_by_id': self.env.uid,
                'resolution_action': 'rejected',
            })
            if dispute.settlement_id.state == 'disputed':
                dispute.settlement_id.state = 'approved'

    def action_withdraw(self):
        for dispute in self:
            if dispute.employee_id.user_id != self.env.user:
                if not self.env.user.has_group(
                    'advanced_commission_engine.group_commission_manager'
                ):
                    raise UserError('You can only withdraw your own disputes.')
            dispute.write({'state': 'withdrawn'})
