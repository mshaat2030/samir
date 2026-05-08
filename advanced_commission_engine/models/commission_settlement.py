# -*- coding: utf-8 -*-
"""Commission Settlement – the central state machine for commission payout lifecycle."""

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


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
    """A settlement aggregates all commission lines for one employee/plan/period
    and drives the approval and payout lifecycle.

    State machine:
        draft → calculated → submitted → approved → finance_approved
             → payroll_processed → paid
        Any state → cancelled (with reason)
        approved/finance_approved → disputed
    """

    _name = 'commission.settlement'
    _description = 'Commission Settlement'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_id desc, employee_id, id'
    _rec_name = 'name'
    _check_company_auto = True

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Reference',
        required=True,
        default='/',
        copy=False,
        readonly=True,
        tracking=True,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    state = fields.Selection(
        SETTLEMENT_STATES,
        string='State',
        default='draft',
        required=True,
        tracking=True,
        index=True,
        copy=False,
    )

    # ── Core Relations ────────────────────────────────────────────────────────
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        tracking=True,
        index=True,
    )
    plan_id = fields.Many2one(
        'commission.plan',
        string='Commission Plan',
        required=True,
        tracking=True,
        index=True,
    )
    period_id = fields.Many2one(
        'commission.period',
        string='Period',
        required=True,
        tracking=True,
        index=True,
    )

    # ── Lines & Adjustments ───────────────────────────────────────────────────
    line_ids = fields.One2many(
        'commission.line',
        'settlement_id',
        string='Commission Lines',
    )
    adjustment_ids = fields.One2many(
        'commission.adjustment',
        'settlement_id',
        string='Adjustments',
    )
    approval_ids = fields.One2many(
        'commission.approval',
        'settlement_id',
        string='Approvals',
    )
    dispute_ids = fields.One2many(
        'commission.dispute',
        'settlement_id',
        string='Disputes',
    )

    # ── Amounts ───────────────────────────────────────────────────────────────
    gross_amount = fields.Monetary(
        string='Gross Commission',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
    )
    total_adjustment = fields.Monetary(
        string='Total Adjustments',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
    )
    final_amount = fields.Monetary(
        string='Final Amount',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
        tracking=True,
    )
    held_amount = fields.Monetary(
        string='Held Amount',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
    )
    deferred_amount = fields.Monetary(
        string='Deferred Amount',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
    )
    payable_amount = fields.Monetary(
        string='Payable This Period',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
        help='Final amount minus holds and deferred amounts.',
    )

    # ── Statistics ────────────────────────────────────────────────────────────
    line_count = fields.Integer(
        compute='_compute_line_count',
        string='Lines',
    )
    total_base_amount = fields.Monetary(
        string='Total Base Amount',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
    )

    # ── Dates ─────────────────────────────────────────────────────────────────
    calculation_date = fields.Datetime(
        string='Calculated On',
        readonly=True,
        copy=False,
    )
    submitted_date = fields.Datetime(
        string='Submitted On',
        readonly=True,
        copy=False,
    )
    approved_date = fields.Datetime(
        string='Approved On',
        readonly=True,
        copy=False,
    )
    finance_approved_date = fields.Datetime(
        string='Finance Approved On',
        readonly=True,
        copy=False,
    )
    paid_date = fields.Date(
        string='Paid On',
        readonly=True,
        copy=False,
        tracking=True,
    )

    # ── Approvers ─────────────────────────────────────────────────────────────
    approved_by_id = fields.Many2one(
        'res.users',
        string='Approved By',
        readonly=True,
        copy=False,
    )
    finance_approved_by_id = fields.Many2one(
        'res.users',
        string='Finance Approved By',
        readonly=True,
        copy=False,
    )

    # ── Accounting ────────────────────────────────────────────────────────────
    move_id = fields.Many2one(
        'account.move',
        string='Journal Entry',
        readonly=True,
        copy=False,
    )
    payslip_id = fields.Many2one(
        'hr.payslip',
        string='Payslip',
        readonly=True,
        copy=False,
    )

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = fields.Text(string='Internal Notes')
    cancellation_reason = fields.Text(
        string='Cancellation Reason',
        copy=False,
    )

    # ── Payout Split ──────────────────────────────────────────────────────────
    split_payout = fields.Boolean(
        string='Split Payout',
        default=False,
        help='Pay commission in multiple instalments.',
    )
    payout_split_count = fields.Integer(
        string='Number of Instalments',
        default=2,
    )

    # ── Anomaly Flag ──────────────────────────────────────────────────────────
    is_anomaly = fields.Boolean(
        string='Anomaly Detected',
        default=False,
        tracking=True,
    )
    anomaly_notes = fields.Text(string='Anomaly Notes')

    _employee_plan_period_uniq = models.Constraint(
        'UNIQUE(employee_id, plan_id, period_id)',
        'A settlement already exists for this employee/plan/period combination.',
    )

    # ── Computes ──────────────────────────────────────────────────────────────


    @api.depends(
        'line_ids.commission_amount',
        'line_ids.state',
        'adjustment_ids.amount',
        'adjustment_ids.adjustment_type',
        'adjustment_ids.state',
    )
    def _compute_amounts(self):
        for settlement in self:
            active_lines = settlement.line_ids.filtered(
                lambda l: l.state not in ('cancelled',)
            )
            settlement.gross_amount = sum(active_lines.mapped('commission_amount'))
            settlement.total_base_amount = sum(active_lines.mapped('base_amount'))

            adj_lines = settlement.adjustment_ids.filtered(
                lambda a: a.state not in ('cancelled',)
            )
            positive_adj = sum(
                a.amount for a in adj_lines if a.adjustment_type in ('bonus', 'manual')
            )
            negative_adj = sum(
                a.amount for a in adj_lines
                if a.adjustment_type in ('penalty', 'clawback')
            )
            held = sum(
                a.amount for a in adj_lines if a.adjustment_type == 'hold'
            )
            deferred = sum(
                a.amount for a in adj_lines if a.adjustment_type == 'deferred'
            )

            settlement.total_adjustment = positive_adj - negative_adj
            settlement.held_amount = held
            settlement.deferred_amount = deferred
            settlement.final_amount = (
                settlement.gross_amount + settlement.total_adjustment
            )
            settlement.payable_amount = max(
                0, settlement.final_amount - held - deferred
            )

    def _compute_line_count(self):
        data = self.env['commission.line'].read_group(
            [('settlement_id', 'in', self.ids)],
            ['settlement_id'],
            ['settlement_id'],
        )
        mapping = {d['settlement_id'][0]: d['settlement_id_count'] for d in data}
        for s in self:
            s.line_count = mapping.get(s.id, 0)

    # ── ORM Overrides ─────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('commission.settlement') or '/'
        return super().create(vals_list)

    def unlink(self):
        for s in self:
            if s.state not in ('draft', 'cancelled'):
                raise UserError(
                    f"Cannot delete settlement '{s.name}' in state '{s.state}'."
                )
        return super().unlink()

    # ── State Machine Methods ─────────────────────────────────────────────────
    def action_calculate(self):
        """Trigger (re)calculation of commission lines."""
        for settlement in self:
            if settlement.state not in ('draft', 'calculated'):
                raise UserError(
                    f"Cannot recalculate settlement '{settlement.name}' in state '{settlement.state}'."
                )
            if settlement.period_id.state == 'frozen':
                raise UserError('Cannot calculate a settlement in a frozen period.')
            from ..services.calculation_service import CommissionCalculationService
            service = CommissionCalculationService(self.env)
            service.calculate_settlement(settlement)
            settlement.write({
                'state': 'calculated',
                'calculation_date': fields.Datetime.now(),
            })
            settlement.message_post(body='Commission recalculated.')

    def action_submit(self):
        """Submit settlement for manager approval."""
        for settlement in self:
            if settlement.state != 'calculated':
                raise UserError('Settlement must be in Calculated state to submit.')
            if settlement.final_amount <= 0:
                raise UserError('Cannot submit a settlement with zero or negative commission.')

            # Auto-approve if below threshold
            if (
                not settlement.plan_id.approval_required
                or (
                    settlement.plan_id.auto_approve_below > 0
                    and settlement.final_amount <= settlement.plan_id.auto_approve_below
                )
            ):
                settlement.write({
                    'state': 'approved',
                    'submitted_date': fields.Datetime.now(),
                    'approved_date': fields.Datetime.now(),
                    'approved_by_id': self.env.uid,
                })
                settlement.message_post(body='Auto-approved based on plan settings.')
            else:
                settlement.write({
                    'state': 'submitted',
                    'submitted_date': fields.Datetime.now(),
                })
                # Send notification email
                template = self.env.ref(
                    'advanced_commission_engine.mail_template_settlement_submitted',
                    raise_if_not_found=False,
                )
                if template:
                    template.send_mail(settlement.id, force_send=False)
                settlement.message_post(body='Submitted for approval.')

    def action_approve(self):
        """Manager approves the settlement."""
        if not self.env.user.has_group(
            'advanced_commission_engine.group_commission_manager'
        ):
            raise UserError('Only Commission Managers can approve settlements.')
        for settlement in self:
            if settlement.state != 'submitted':
                raise UserError('Settlement must be in Submitted state to approve.')
            settlement.write({
                'state': 'approved',
                'approved_date': fields.Datetime.now(),
                'approved_by_id': self.env.uid,
            })
            # Create approval record
            self.env['commission.approval'].create({
                'settlement_id': settlement.id,
                'approver_id': self.env.uid,
                'level': 'manager',
                'state': 'approved',
                'date': fields.Date.today(),
                'notes': 'Manager approved.',
            })
            # Send email
            template = self.env.ref(
                'advanced_commission_engine.mail_template_settlement_approved',
                raise_if_not_found=False,
            )
            if template:
                template.send_mail(settlement.id, force_send=False)
            settlement.message_post(body=f'Approved by {self.env.user.name}.')

    def action_finance_approve(self):
        """Finance manager gives final financial approval."""
        if not self.env.user.has_group(
            'advanced_commission_engine.group_commission_finance_manager'
        ):
            raise UserError('Only Finance Managers can give financial approval.')
        for settlement in self:
            if settlement.state != 'approved':
                raise UserError('Settlement must be in Approved state for finance approval.')
            settlement.write({
                'state': 'finance_approved',
                'finance_approved_date': fields.Datetime.now(),
                'finance_approved_by_id': self.env.uid,
            })
            self.env['commission.approval'].create({
                'settlement_id': settlement.id,
                'approver_id': self.env.uid,
                'level': 'finance',
                'state': 'approved',
                'date': fields.Date.today(),
                'notes': 'Finance approved.',
            })
            # Create accounting journal entry if plan configured
            if settlement.plan_id.journal_id and settlement.plan_id.expense_account_id:
                settlement._create_accounting_entry()
            settlement.message_post(body=f'Finance approved by {self.env.user.name}.')

    def action_process_payroll(self):
        """Push commission amount to employee payslip."""
        if not self.env.user.has_group(
            'advanced_commission_engine.group_commission_hr_manager'
        ):
            raise UserError('Only HR Managers can process payroll.')
        for settlement in self:
            if settlement.state != 'finance_approved':
                raise UserError('Settlement must be Finance Approved before payroll processing.')
            settlement._inject_payroll_input()
            settlement.write({'state': 'payroll_processed'})
            settlement.message_post(body='Payroll input injected.')

    def action_mark_paid(self):
        """Mark settlement as paid."""
        if not self.env.user.has_group(
            'advanced_commission_engine.group_commission_finance_manager'
        ):
            raise UserError('Only Finance Managers can mark settlements as paid.')
        for settlement in self:
            if settlement.state not in ('payroll_processed', 'finance_approved'):
                raise UserError('Settlement must be Payroll Processed or Finance Approved to mark as paid.')
            settlement.write({
                'state': 'paid',
                'paid_date': fields.Date.today(),
            })
            template = self.env.ref(
                'advanced_commission_engine.mail_template_settlement_paid',
                raise_if_not_found=False,
            )
            if template:
                template.send_mail(settlement.id, force_send=False)
            settlement.message_post(body='Commission payment confirmed.')

    def action_dispute(self):
        """Move settlement to Disputed state."""
        for settlement in self:
            if settlement.state not in ('approved', 'finance_approved'):
                raise UserError('Only approved settlements can be disputed.')
            settlement.write({'state': 'disputed'})
            settlement.message_post(body='Settlement marked as disputed.')

    def action_cancel(self):
        """Cancel the settlement."""
        for settlement in self:
            if settlement.state in ('paid',):
                raise UserError('Cannot cancel a paid settlement.')
            settlement.write({'state': 'cancelled'})
            settlement.message_post(body='Settlement cancelled.')

    def action_reset_draft(self):
        """Reset to draft (admin only)."""
        if not self.env.user.has_group(
            'advanced_commission_engine.group_commission_admin'
        ):
            raise UserError('Only administrators can reset settlements to draft.')
        for settlement in self:
            if settlement.state not in ('cancelled', 'disputed', 'calculated'):
                raise UserError(f"Cannot reset settlement in state '{settlement.state}'.")
            settlement.line_ids.unlink()
            settlement.write({'state': 'draft', 'calculation_date': False})

    # ── Accounting Integration ─────────────────────────────────────────────────
    def _create_accounting_entry(self):
        """Create a journal entry for the approved commission."""
        self.ensure_one()
        plan = self.plan_id
        if not plan.journal_id or not plan.expense_account_id:
            return

        move_vals = {
            'journal_id': plan.journal_id.id,
            'date': fields.Date.today(),
            'ref': f'Commission: {self.name}',
            'company_id': self.company_id.id,
            'line_ids': [
                (0, 0, {
                    'account_id': plan.expense_account_id.id,
                    'name': f'Commission – {self.employee_id.name} – {self.period_id.name}',
                    'debit': self.final_amount,
                    'credit': 0.0,
                    'partner_id': self.employee_id.address_home_id.id or False,
                }),
                (0, 0, {
                    'account_id': (
                        plan.payable_account_id.id
                        or self.company_id.account_journal_payment_credit_account_id.id
                    ),
                    'name': f'Commission Payable – {self.employee_id.name}',
                    'debit': 0.0,
                    'credit': self.final_amount,
                    'partner_id': self.employee_id.address_home_id.id or False,
                }),
            ],
        }
        if plan.analytic_account_id:
            for line in move_vals['line_ids']:
                line[2]['analytic_distribution'] = {
                    str(plan.analytic_account_id.id): 100
                }

        move = self.env['account.move'].create(move_vals)
        move.action_post()
        self.move_id = move

    # ── Payroll Integration ───────────────────────────────────────────────────
    def _inject_payroll_input(self):
        """Inject commission amount into the employee's current payslip input."""
        self.ensure_one()
        if 'hr.payslip' not in self.env:
            return

        input_type = self.plan_id.payroll_input_type_id
        if not input_type:
            input_type = self.env.ref(
                'advanced_commission_engine.payslip_input_commission',
                raise_if_not_found=False,
            )
        if not input_type:
            return

        # Find draft payslip for this employee in the period
        payslip = self.env['hr.payslip'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', 'in', ('draft', 'verify')),
            ('date_from', '<=', self.period_id.date_end),
            ('date_to', '>=', self.period_id.date_start),
        ], limit=1)

        if payslip:
            existing_input = payslip.input_line_ids.filtered(
                lambda i: i.input_type_id == input_type
                and i.name and 'commission' in i.name.lower()
            )
            if existing_input:
                existing_input[0].amount += self.payable_amount
            else:
                payslip.write({
                    'input_line_ids': [(0, 0, {
                        'input_type_id': input_type.id,
                        'name': f'Commission – {self.name}',
                        'amount': self.payable_amount,
                    })]
                })
            self.payslip_id = payslip

    # ── Cron Methods ──────────────────────────────────────────────────────────
    @api.model
    def _cron_calculate_settlements(self):
        """Calculate all draft settlements."""
        drafts = self.search([
            ('state', '=', 'draft'),
            ('period_id.state', '=', 'open'),
        ])
        for settlement in drafts:
            try:
                settlement.action_calculate()
            except Exception as e:
                settlement.message_post(
                    body=f'Auto-calculation failed: {e}',
                    message_type='comment',
                )

    @api.model
    def _cron_detect_anomalies(self):
        """Run anomaly detection on recent settlements."""
        from ..services.anomaly_service import AnomalyService
        service = AnomalyService(self.env)
        recent = self.search([
            ('state', 'in', ('calculated', 'submitted')),
            ('calculation_date', '!=', False),
        ])
        service.detect_anomalies(recent)

    # ── UI Actions ────────────────────────────────────────────────────────────
    def action_view_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Commission Lines',
            'res_model': 'commission.line',
            'view_mode': 'list,form',
            'domain': [('settlement_id', '=', self.id)],
        }

    def action_print_statement(self):
        self.ensure_one()
        return self.env.ref(
            'advanced_commission_engine.action_report_commission_statement'
        ).report_action(self)

    def action_rollback(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Rollback Settlement',
            'res_model': 'wizard.rollback.commission',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_settlement_id': self.id},
        }
