# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class CommissionDispute(models.Model):
    _name = 'commission.dispute'
    _description = 'Commission Dispute'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'commission.mixin']
    _order = 'date desc'

    name = fields.Char(
        string='Dispute Reference',
        copy=False,
        readonly=True,
        default='/',
        index=True,
    )
    date = fields.Date(
        string='Dispute Date', required=True, default=fields.Date.today
    )
    deadline = fields.Date(string='Response Deadline')
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, index=True,
    )
    settlement_id = fields.Many2one(
        'commission.settlement', string='Settlement', index=True
    )
    line_id = fields.Many2one(
        'commission.line', string='Commission Line', index=True
    )
    period_id = fields.Many2one(
        'commission.period', string='Period',
        related='settlement_id.period_id', store=True,
    )

    # ── Dispute Details ───────────────────────────────────────────────────────
    dispute_type = fields.Selection([
        ('amount_incorrect', 'Amount Incorrect'),
        ('missing_commission', 'Missing Commission'),
        ('wrong_rate', 'Wrong Rate Applied'),
        ('wrong_period', 'Wrong Period'),
        ('duplicate', 'Duplicate Entry'),
        ('clawback_unjustified', 'Unjustified Clawback'),
        ('other', 'Other'),
    ], string='Dispute Type', required=True, default='amount_incorrect')

    claimed_amount = fields.Monetary(
        string='Claimed Amount',
        currency_field='currency_id',
        help='Amount the employee believes they should receive',
    )
    current_amount = fields.Monetary(
        string='Current Amount',
        currency_field='currency_id',
        related='line_id.commission_amount',
        store=True,
    )
    difference = fields.Monetary(
        string='Difference',
        currency_field='currency_id',
        compute='_compute_difference',
        store=True,
    )

    description = fields.Text(string='Employee Description', required=True)
    supporting_docs = fields.Binary(string='Supporting Document')
    supporting_docs_name = fields.Char(string='Document Name')

    # ── Status ────────────────────────────────────────────────────────────────
    state = fields.Selection([
        ('open', 'Open'),
        ('under_review', 'Under Review'),
        ('resolved_accepted', 'Resolved - Accepted'),
        ('resolved_rejected', 'Resolved - Rejected'),
        ('resolved_partial', 'Resolved - Partial'),
        ('escalated', 'Escalated'),
        ('closed', 'Closed'),
    ], string='Status', default='open', required=True, tracking=True, index=True)

    # ── Resolution ────────────────────────────────────────────────────────────
    reviewer_id = fields.Many2one('res.users', string='Assigned Reviewer')
    reviewed_date = fields.Datetime(string='Reviewed On', readonly=True)
    resolution_notes = fields.Text(string='Resolution Notes')
    resolved_amount = fields.Monetary(
        string='Resolved Amount',
        currency_field='currency_id',
    )
    adjustment_id = fields.Many2one(
        'commission.adjustment', string='Created Adjustment', readonly=True
    )

    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Normal'),
        ('2', 'High'),
        ('3', 'Urgent'),
    ], string='Priority', default='1')

    _name_company_uniq = models.Constraint(
        'UNIQUE(name, company_id)',
        'Dispute reference must be unique per company.',
    )

    @api.depends('claimed_amount', 'current_amount')
    def _compute_difference(self):
        for d in self:
            d.difference = d.claimed_amount - d.current_amount

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'commission.dispute'
                ) or '/'
        return super().create(vals_list)

    def action_start_review(self):
        for dispute in self:
            if dispute.state != 'open':
                raise UserError(_('Only open disputes can be reviewed.'))
            dispute.write({
                'state': 'under_review',
                'reviewer_id': self.env.uid,
            })
            dispute.message_post(
                body=_('Dispute taken under review by %s.') % self.env.user.name
            )

    def action_accept(self):
        for dispute in self:
            if dispute.state not in ('under_review', 'open'):
                raise UserError(_('Dispute cannot be accepted in its current state.'))
            if not dispute.resolution_notes:
                raise UserError(_('Please provide resolution notes before accepting.'))
            dispute.write({
                'state': 'resolved_accepted',
                'reviewed_date': fields.Datetime.now(),
                'resolved_amount': dispute.claimed_amount,
            })
            # Auto-create adjustment
            if dispute.claimed_amount != dispute.current_amount:
                diff = dispute.claimed_amount - dispute.current_amount
                adj = self.env['commission.adjustment'].create({
                    'employee_id': dispute.employee_id.id,
                    'plan_id': dispute.line_id.plan_id.id if dispute.line_id else False,
                    'period_id': dispute.period_id.id,
                    'adjustment_type': 'correction',
                    'amount': abs(diff),
                    'sign': 'positive' if diff > 0 else 'negative',
                    'reason': _('Dispute resolution: %s') % dispute.name,
                    'company_id': dispute.company_id.id,
                    'currency_id': dispute.currency_id.id,
                })
                dispute.adjustment_id = adj
            dispute.message_post(
                body=_('Dispute resolved - Accepted. Adjustment created.')
            )

    def action_reject(self):
        for dispute in self:
            if not dispute.resolution_notes:
                raise UserError(_('Please provide resolution notes before rejecting.'))
            dispute.write({
                'state': 'resolved_rejected',
                'reviewed_date': fields.Datetime.now(),
            })
            dispute.message_post(
                body=_('Dispute resolved - Rejected.')
            )

    def action_partial_accept(self):
        for dispute in self:
            if not dispute.resolved_amount:
                raise UserError(_('Please set the resolved amount for partial acceptance.'))
            dispute.write({
                'state': 'resolved_partial',
                'reviewed_date': fields.Datetime.now(),
            })
            diff = dispute.resolved_amount - dispute.current_amount
            if abs(diff) > 0.01:
                adj = self.env['commission.adjustment'].create({
                    'employee_id': dispute.employee_id.id,
                    'plan_id': dispute.line_id.plan_id.id if dispute.line_id else False,
                    'period_id': dispute.period_id.id,
                    'adjustment_type': 'correction',
                    'amount': abs(diff),
                    'sign': 'positive' if diff > 0 else 'negative',
                    'reason': _('Partial dispute resolution: %s') % dispute.name,
                    'company_id': dispute.company_id.id,
                    'currency_id': dispute.currency_id.id,
                })
                dispute.adjustment_id = adj

    def action_escalate(self):
        for dispute in self:
            dispute.write({'state': 'escalated', 'priority': '3'})
            dispute.message_post(body=_('Dispute escalated.'))

    def action_close(self):
        for dispute in self:
            dispute.write({'state': 'closed'})
