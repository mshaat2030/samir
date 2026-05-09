# -*- coding: utf-8 -*-
"""Commission Settlement — the core aggregation record per employee per period."""

import logging
from odoo import api, fields, models
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)

SETTLEMENT_STATES = [
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


class CommissionSettlement(models.Model):
    """Commission settlement aggregating all lines for an employee in a period."""

    _name = 'commission.settlement'
    _description = 'Commission Settlement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_id desc, employee_id'

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Reference', required=True, copy=False,
        default=lambda self: self.env['ir.sequence'].next_by_code('commission.settlement'),
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company, index=True,
    )
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id',
        store=True, readonly=True,
    )

    # ── Scope ─────────────────────────────────────────────────────────────────
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, tracking=True, index=True,
        ondelete='restrict',
    )
    period_id = fields.Many2one(
        'commission.period', string='Period',
        required=True, tracking=True, index=True,
        ondelete='restrict',
    )
    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan',
        required=True, tracking=True, index=True,
        ondelete='restrict',
    )

    # ── State ─────────────────────────────────────────────────────────────────
    state = fields.Selection(
        SETTLEMENT_STATES, string='Status',
        default='draft', tracking=True, index=True,
    )

    # ── Lines ─────────────────────────────────────────────────────────────────
    line_ids = fields.One2many(
        'commission.line', 'settlement_id', string='Commission Lines',
    )
    adjustment_ids = fields.One2many(
        'commission.adjustment', 'settlement_id', string='Adjustments',
    )
    dispute_ids = fields.One2many(
        'commission.dispute', 'settlement_id', string='Disputes',
    )
    approval_ids = fields.One2many(
        'commission.approval', 'settlement_id', string='Approvals',
    )

    # ── Amounts ───────────────────────────────────────────────────────────────
    gross_commission = fields.Monetary(
        compute='_compute_amounts', store=True,
        currency_field='currency_id',
        string='Gross Commission',
    )
    total_adjustments = fields.Monetary(
        compute='_compute_amounts', store=True,
        currency_field='currency_id',
        string='Total Adjustments',
    )
    total_commission = fields.Monetary(
        compute='_compute_amounts', store=True,
        currency_field='currency_id',
        string='Net Commission',
        tracking=True,
    )
    deferred_amount = fields.Monetary(
        compute='_compute_amounts', store=True,
        currency_field='currency_id',
        string='Deferred Amount',
    )
    clawback_amount = fields.Monetary(
        currency_field='currency_id',
        string='Clawback Amount', tracking=True,
    )
    hold_amount = fields.Monetary(
        currency_field='currency_id',
        string='On Hold Amount', tracking=True,
    )

    # ── Payout ────────────────────────────────────────────────────────────────
    payment_date = fields.Date(string='Payment Date', tracking=True)
    payslip_id = fields.Many2one(
        'hr.payslip', string='Payslip',
        readonly=True, tracking=True,
    )
    move_id = fields.Many2one(
        'account.move', string='Journal Entry',
        readonly=True, tracking=True,
    )
    is_deferred = fields.Boolean(string='Deferred Payout', tracking=True)
    split_payout = fields.Boolean(string='Split Payout', tracking=True)
    split_count = fields.Integer(string='Split Installments', default=1)

    # ── Approval ──────────────────────────────────────────────────────────────
    submitted_by = fields.Many2one('res.users', string='Submitted By', readonly=True)
    submitted_at = fields.Datetime(string='Submitted At', readonly=True)
    approved_by_id = fields.Many2one('res.users', string='Manager Approved By', readonly=True)
    approved_at = fields.Datetime(string='Manager Approved At', readonly=True)
    finance_approved_by = fields.Many2one('res.users', string='Finance Approved By', readonly=True)
    finance_approved_at = fields.Datetime(string='Finance Approved At', readonly=True)
    rejection_reason = fields.Text(string='Rejection Reason')

    # ── Anomaly Detection ─────────────────────────────────────────────────────
    anomaly_flag = fields.Boolean(string='Anomaly Detected', tracking=True)
    anomaly_reason = fields.Text(string='Anomaly Reason')

    # ── Stats ─────────────────────────────────────────────────────────────────
    line_count = fields.Integer(compute='_compute_line_count', string='Lines')
    dispute_count = fields.Integer(compute='_compute_dispute_count', string='Disputes')

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = fields.Text(string='Notes')
    manager_notes = fields.Text(string='Manager Notes')

    _sql_constraints = [
        ('unique_employee_period_plan', 'UNIQUE(employee_id, period_id, plan_id)',
         'A settlement already exists for this employee/period/plan combination.'),
    ]

    # ── Compute ───────────────────────────────────────────────────────────────

    @api.depends('line_ids.commission_amount', 'adjustment_ids.amount', 'adjustment_ids.adjustment_type')
    def _compute_amounts(self):
        for rec in self:
            gross = sum(rec.line_ids.mapped('commission_amount'))
            adjustments = 0.0
            deferred = 0.0
            for adj in rec.adjustment_ids:
                if adj.adjustment_type == 'deferred':
                    deferred += adj.amount
                elif adj.adjustment_type in ('clawback', 'penalty', 'negative'):
                    adjustments -= adj.amount
                else:
                    adjustments += adj.amount
            rec.gross_commission = gross
            rec.total_adjustments = adjustments
            rec.total_commission = gross + adjustments
            rec.deferred_amount = deferred

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.depends('dispute_ids')
    def _compute_dispute_count(self):
        for rec in self:
            rec.dispute_count = len(rec.dispute_ids)

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('period_id', 'state')
    def _check_period_state(self):
        for rec in self:
            if rec.state not in ('cancelled',) and rec.period_id.state == 'locked':
                raise ValidationError('Cannot modify a settlement in a locked period.')

    # ── State Transitions ─────────────────────────────────────────────────────

    def action_calculate(self):
        """Calculate commission from source documents."""
        for rec in self:
            if rec.state not in ('draft',):
                raise UserError(f'Settlement {rec.name} cannot be recalculated from its current state.')
            if rec.period_id.state == 'locked':
                raise UserError('Cannot calculate in a locked period.')
            svc = self.env['commission.calculation.service']
            svc.calculate_settlement(rec)
            rec.write({'state': 'calculated'})
            rec.message_post(body=f'Commission calculated. Net: {rec.currency_id.symbol}{rec.total_commission:,.2f}')

    def action_submit(self):
        """Submit for manager approval."""
        for rec in self:
            if rec.state != 'calculated':
                raise UserError('Only calculated settlements can be submitted.')
            rec.write({
                'state': 'submitted',
                'submitted_by': self.env.user.id,
                'submitted_at': fields.Datetime.now(),
            })
            # Auto-approve if below threshold
            if rec.plan_id.auto_approve_threshold and rec.total_commission <= rec.plan_id.auto_approve_threshold:
                rec.action_approve()
                return
            rec._notify_manager()
            rec.message_post(body='Settlement submitted for approval.')

    def action_approve(self):
        """Manager approval."""
        for rec in self:
            if rec.state != 'submitted':
                raise UserError('Only submitted settlements can be approved.')
            if not self.env.user.has_group('advanced_commission_engine.group_commission_manager'):
                raise UserError('Only commission managers can approve settlements.')
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approved_at': fields.Datetime.now(),
            })
            if rec.plan_id.require_finance_approval:
                rec._notify_finance()
            else:
                rec.write({'state': 'finance_approved'})
            rec.message_post(body=f'Approved by {self.env.user.name}.')
            template = self.env.ref('advanced_commission_engine.mail_template_settlement_approved', False)
            if template:
                template.send_mail(rec.id, force_send=True)

    def action_finance_approve(self):
        """Finance approval."""
        for rec in self:
            if rec.state != 'approved':
                raise UserError('Settlement must be manager-approved first.')
            if not self.env.user.has_group('advanced_commission_engine.group_commission_finance_manager'):
                raise UserError('Only finance managers can give finance approval.')
            rec.write({
                'state': 'finance_approved',
                'finance_approved_by': self.env.user.id,
                'finance_approved_at': fields.Datetime.now(),
            })
            rec.message_post(body=f'Finance approved by {self.env.user.name}.')

    def action_process_payroll(self):
        """Link to payroll and mark as payroll_processed."""
        for rec in self:
            if rec.state != 'finance_approved':
                raise UserError('Settlement must be finance-approved before payroll processing.')
            rec._create_payroll_input()
            rec.write({'state': 'payroll_processed'})
            rec.message_post(body='Payroll input created.')

    def action_mark_paid(self):
        """Mark as paid and create accounting entry."""
        for rec in self:
            if rec.state != 'payroll_processed':
                raise UserError('Settlement must be payroll-processed before marking as paid.')
            rec._create_accounting_entry()
            rec.write({'state': 'paid', 'payment_date': fields.Date.today()})
            rec.message_post(body=f'Commission paid: {rec.currency_id.symbol}{rec.total_commission:,.2f}')
            template = self.env.ref('advanced_commission_engine.mail_template_settlement_paid', False)
            if template:
                template.send_mail(rec.id, force_send=True)

    def action_cancel(self):
        """Cancel settlement."""
        for rec in self:
            if rec.state in ('paid',):
                raise UserError('Paid settlements cannot be cancelled directly. Use rollback.')
            rec.write({'state': 'cancelled'})
            rec.message_post(body=f'Cancelled by {self.env.user.name}.')

    def action_reset_draft(self):
        """Reset to draft for recalculation."""
        for rec in self:
            if rec.state in ('paid', 'payroll_processed'):
                raise UserError('Cannot reset a paid or payroll-processed settlement to draft.')
            rec.line_ids.unlink()
            rec.write({'state': 'draft'})
            rec.message_post(body='Reset to draft for recalculation.')

    def action_dispute(self):
        """Move to disputed state."""
        for rec in self:
            rec.write({'state': 'disputed'})
            rec.message_post(body='Settlement under dispute.')

    # ── Internal Helpers ──────────────────────────────────────────────────────

    def _notify_manager(self):
        """Notify employee's manager that a settlement needs approval."""
        self.ensure_one()
        manager = self.employee_id.parent_id
        if manager and manager.user_id:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=manager.user_id.id,
                note=f'Commission settlement {self.name} awaiting your approval.',
            )

    def _notify_finance(self):
        """Notify finance managers for second-level approval."""
        self.ensure_one()
        finance_group = self.env.ref('advanced_commission_engine.group_commission_finance_manager')
        for user in finance_group.users:
            self.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=user.id,
                note=f'Commission settlement {self.name} awaiting finance approval.',
            )

    def _create_payroll_input(self):
        """Create payslip input for this settlement."""
        self.ensure_one()
        if not self.plan_id.payroll_salary_rule_id:
            return
        # Find current payslip for the employee
        payslip = self.env['hr.payslip'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', 'in', ('draft', 'verify')),
            ('date_from', '>=', self.period_id.date_start),
            ('date_to', '<=', self.period_id.date_end),
        ], limit=1)
        if not payslip:
            return
        self.env['hr.payslip.input'].create({
            'payslip_id': payslip.id,
            'input_type_id': self.plan_id.payroll_salary_rule_id.id,
            'amount': self.total_commission,
            'name': f'Commission — {self.name}',
        })
        self.write({'payslip_id': payslip.id})

    def _create_accounting_entry(self):
        """Create journal entry for commission payout."""
        self.ensure_one()
        account = self.plan_id.account_id or self.env.company.account_journal_payment_debit_account_id
        journal = self.plan_id.journal_id
        if not account or not journal:
            return
        move_vals = {
            'journal_id': journal.id,
            'date': fields.Date.today(),
            'ref': f'Commission {self.name}',
            'move_type': 'entry',
            'line_ids': [
                (0, 0, {
                    'account_id': account.id,
                    'name': f'Commission {self.name} — {self.employee_id.name}',
                    'debit': self.total_commission,
                    'credit': 0.0,
                    'analytic_distribution': (
                        {str(self.plan_id.analytic_account_id.id): 100}
                        if self.plan_id.analytic_account_id else {}
                    ),
                }),
                (0, 0, {
                    'account_id': self.env.company.account_journal_payment_credit_account_id.id,
                    'name': f'Commission Payable {self.name}',
                    'debit': 0.0,
                    'credit': self.total_commission,
                }),
            ],
        }
        move = self.env['account.move'].create(move_vals)
        move.action_post()
        self.write({'move_id': move.id})

    # ── Cron Jobs ─────────────────────────────────────────────────────────────

    @api.model
    def cron_auto_calculate(self):
        """Auto-calculate settlements for all open periods."""
        open_periods = self.env['commission.period'].search([
            ('state', '=', 'open'),
            ('company_id', 'in', self.env.user.company_ids.ids),
        ])
        for period in open_periods:
            self.env['commission.calculation.service'].auto_calculate_period(period)

    @api.model
    def cron_detect_anomalies(self):
        """Run anomaly detection on recent settlements."""
        self.env['commission.anomaly.service'].detect_all()

    # ── Portal ────────────────────────────────────────────────────────────────

    def get_portal_url(self, suffix=None, report_type=None, download=None, query_string=None, anchor=None):
        """Return the portal URL for this settlement."""
        self.ensure_one()
        url = f'/my/commission/settlements/{self.id}'
        return url

    # ── Smart Buttons ─────────────────────────────────────────────────────────

    def action_view_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Commission Lines',
            'res_model': 'commission.line',
            'view_mode': 'list,form',
            'domain': [('settlement_id', '=', self.id)],
        }

    def action_view_adjustments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Adjustments',
            'res_model': 'commission.adjustment',
            'view_mode': 'list,form',
            'domain': [('settlement_id', '=', self.id)],
            'context': {'default_settlement_id': self.id},
        }

    def action_view_disputes(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Disputes',
            'res_model': 'commission.dispute',
            'view_mode': 'list,form',
            'domain': [('settlement_id', '=', self.id)],
            'context': {'default_settlement_id': self.id},
        }

    def action_print_statement(self):
        return self.env.ref('advanced_commission_engine.action_report_commission_statement').report_action(self)

    def action_download_xlsx(self):
        return self.env.ref('advanced_commission_engine.action_report_commission_statement_xlsx').report_action(self)
