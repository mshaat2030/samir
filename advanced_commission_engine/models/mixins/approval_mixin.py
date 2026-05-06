# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ApprovalMixin(models.AbstractModel):
    """
    Mixin providing multi-level approval workflow:
    employee → manager → finance → payroll
    """
    _name = 'commission.approval.mixin'
    _description = 'Commission Approval Mixin'

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('manager_approved', 'Manager Approved'),
        ('finance_approved', 'Finance Approved'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', required=True,
        tracking=True, index=True, copy=False)

    submitted_by = fields.Many2one('res.users', string='Submitted By', readonly=True, copy=False)
    submitted_date = fields.Datetime(string='Submitted On', readonly=True, copy=False)
    manager_approved_by = fields.Many2one('res.users', string='Manager Approved By', readonly=True, copy=False)
    manager_approved_date = fields.Datetime(string='Manager Approved On', readonly=True, copy=False)
    finance_approved_by = fields.Many2one('res.users', string='Finance Approved By', readonly=True, copy=False)
    finance_approved_date = fields.Datetime(string='Finance Approved On', readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', string='Final Approved By', readonly=True, copy=False)
    approved_date = fields.Datetime(string='Final Approved On', readonly=True, copy=False)
    rejection_reason = fields.Text(string='Rejection Reason', readonly=True, copy=False)

    def action_submit(self):
        self._check_state('draft')
        self.write({
            'state': 'submitted',
            'submitted_by': self.env.uid,
            'submitted_date': fields.Datetime.now(),
        })
        self._notify_approver('manager')

    def action_manager_approve(self):
        self._check_state('submitted')
        self._check_group('advanced_commission_engine.group_commission_manager')
        self.write({
            'state': 'manager_approved',
            'manager_approved_by': self.env.uid,
            'manager_approved_date': fields.Datetime.now(),
        })
        self._notify_approver('finance')

    def action_finance_approve(self):
        self._check_state('manager_approved')
        self._check_group('advanced_commission_engine.group_commission_finance')
        self.write({
            'state': 'finance_approved',
            'finance_approved_by': self.env.uid,
            'finance_approved_date': fields.Datetime.now(),
        })
        self._notify_approver('payroll')

    def action_final_approve(self):
        self._check_state('finance_approved')
        self._check_group('advanced_commission_engine.group_commission_finance')
        self.write({
            'state': 'approved',
            'approved_by': self.env.uid,
            'approved_date': fields.Datetime.now(),
        })

    def action_reject(self, reason=''):
        if self.state not in ('submitted', 'manager_approved', 'finance_approved'):
            raise UserError(_('Cannot reject a record in state: %s') % self.state)
        self.write({
            'state': 'rejected',
            'rejection_reason': reason,
        })

    def action_reset_to_draft(self):
        self._check_state('rejected')
        self.write({'state': 'draft', 'rejection_reason': False})

    def _check_state(self, expected):
        for rec in self:
            if rec.state != expected:
                raise UserError(
                    _('Action not allowed in state "%s". Expected "%s".') % (rec.state, expected)
                )

    def _check_group(self, group_xml_id):
        if not self.env.user.has_group(group_xml_id):
            raise UserError(_('You do not have permission to perform this action.'))

    def _notify_approver(self, stage):
        """Override to send notifications to the appropriate approver."""
        pass
