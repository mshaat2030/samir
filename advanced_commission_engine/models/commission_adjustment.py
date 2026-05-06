# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class CommissionAdjustment(models.Model):
    _name = 'commission.adjustment'
    _description = 'Commission Adjustment'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'commission.mixin']
    _order = 'date desc'

    name = fields.Char(
        string='Reference', required=True, copy=False,
        default=lambda self: _('New'),
    )
    date = fields.Date(
        string='Adjustment Date', required=True, default=fields.Date.today
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, index=True,
    )
    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan', index=True
    )
    period_id = fields.Many2one(
        'commission.period', string='Period', index=True
    )
    settlement_id = fields.Many2one(
        'commission.settlement', string='Settlement', index=True
    )
    original_line_id = fields.Many2one(
        'commission.line', string='Original Commission Line'
    )

    adjustment_type = fields.Selection([
        ('manual_bonus', 'Manual Bonus'),
        ('retroactive', 'Retroactive Adjustment'),
        ('correction', 'Correction'),
        ('clawback', 'Clawback'),
        ('deduction', 'Deduction'),
        ('advance', 'Commission Advance'),
        ('other', 'Other'),
    ], string='Adjustment Type', required=True, default='manual_bonus', tracking=True)

    amount = fields.Monetary(
        string='Adjustment Amount',
        currency_field='currency_id',
        required=True,
        tracking=True,
    )
    sign = fields.Selection([
        ('positive', 'Positive (+)'),
        ('negative', 'Negative (-)'),
    ], string='Sign', default='positive', required=True)
    effective_amount = fields.Monetary(
        string='Effective Amount',
        currency_field='currency_id',
        compute='_compute_effective_amount',
        store=True,
    )

    reason = fields.Text(string='Reason / Justification', required=True)
    is_retroactive = fields.Boolean(string='Retroactive')
    retroactive_period_id = fields.Many2one(
        'commission.period', string='Affects Period'
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('applied', 'Applied'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', tracking=True, index=True)

    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True)
    approved_date = fields.Datetime(string='Approved On', readonly=True)
    resulting_line_id = fields.Many2one(
        'commission.line', string='Resulting Line', readonly=True
    )

    _name_company_uniq = models.Constraint(
        'UNIQUE(name, company_id)',
        'Adjustment reference must be unique per company.',
    )

    @api.depends('amount', 'sign')
    def _compute_effective_amount(self):
        for adj in self:
            adj.effective_amount = adj.amount if adj.sign == 'positive' else -adj.amount

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'commission.adjustment'
                ) or _('New')
        return super().create(vals_list)

    def action_submit(self):
        for adj in self:
            if adj.state != 'draft':
                raise UserError(_('Only draft adjustments can be submitted.'))
            adj.write({'state': 'submitted'})
            adj.message_post(body=_('Adjustment submitted for approval.'))

    def action_approve(self):
        if not self.env.user.has_group(
            'advanced_commission_engine.group_commission_manager'
        ):
            raise UserError(_('You do not have permission to approve adjustments.'))
        for adj in self:
            if adj.state != 'submitted':
                raise UserError(_('Only submitted adjustments can be approved.'))
            adj.write({
                'state': 'approved',
                'approved_by': self.env.uid,
                'approved_date': fields.Datetime.now(),
            })

    def action_apply(self):
        """Apply adjustment by creating a commission line."""
        for adj in self:
            if adj.state != 'approved':
                raise UserError(_('Only approved adjustments can be applied.'))
            period = adj.period_id or adj.retroactive_period_id
            if not period:
                raise UserError(_('Adjustment "%s" has no period assigned.') % adj.name)
            line = self.env['commission.line'].create({
                'name': _('Adjustment: %s') % adj.name,
                'employee_id': adj.employee_id.id,
                'period_id': period.id,
                'plan_id': adj.plan_id.id if adj.plan_id else False,
                'date': adj.date,
                'line_type': 'adjustment',
                'commission_amount': adj.effective_amount,
                'base_amount': abs(adj.amount),
                'note': adj.reason,
                'company_id': adj.company_id.id,
                'currency_id': adj.currency_id.id,
            })
            adj.write({'state': 'applied', 'resulting_line_id': line.id})
            adj.message_post(body=_('Adjustment applied. Commission line: %s') % line.name)

    def action_reject(self):
        for adj in self:
            adj.write({'state': 'rejected'})

    def action_reset_draft(self):
        for adj in self:
            if adj.state not in ('rejected', 'submitted'):
                raise UserError(_('Can only reset rejected or submitted adjustments.'))
            adj.write({'state': 'draft'})
