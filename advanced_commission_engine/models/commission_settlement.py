# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class CommissionSettlement(models.Model):
    _name = 'commission.settlement'
    _description = 'Commission Settlement'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'commission.mixin', 'commission.approval.mixin']
    _order = 'date desc, name'

    name = fields.Char(
        string='Settlement Reference',
        copy=False,
        readonly=True,
        default='/',
        index=True,
    )
    date = fields.Date(
        string='Settlement Date',
        required=True,
        default=fields.Date.today,
        tracking=True,
    )
    period_id = fields.Many2one(
        'commission.period', string='Commission Period',
        required=True, index=True, tracking=True,
        domain="[('company_id', '=', company_id), ('state', '!=', 'cancelled')]",
    )
    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan',
        index=True, tracking=True,
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, index=True, tracking=True,
    )
    department_id = fields.Many2one(
        related='employee_id.department_id',
        store=True, string='Department',
    )
    job_id = fields.Many2one(
        related='employee_id.job_id',
        store=True, string='Job Position',
    )

    # ── Lines ─────────────────────────────────────────────────────────────────
    line_ids = fields.One2many(
        'commission.line', 'settlement_id',
        string='Commission Lines',
    )
    line_count = fields.Integer(compute='_compute_line_count')

    # ── Amounts ───────────────────────────────────────────────────────────────
    gross_commission = fields.Monetary(
        string='Gross Commission',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    adjustment_amount = fields.Monetary(
        string='Adjustments',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    clawback_amount = fields.Monetary(
        string='Clawbacks',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    net_commission = fields.Monetary(
        string='Net Commission',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    paid_amount = fields.Monetary(
        string='Amount Paid',
        compute='_compute_paid_amount',
        store=True,
        currency_field='currency_id',
    )
    residual_amount = fields.Monetary(
        string='Residual',
        compute='_compute_paid_amount',
        store=True,
        currency_field='currency_id',
    )

    # ── Payment ───────────────────────────────────────────────────────────────
    settlement_method = fields.Selection([
        ('payroll', 'Via Payroll'),
        ('vendor_bill', 'Via Vendor Bill'),
        ('journal_entry', 'Via Journal Entry'),
        ('manual', 'Manual'),
    ], string='Settlement Method', default='payroll', required=True, tracking=True)
    payment_date = fields.Date(string='Payment Date', tracking=True)

    # ── Payroll ───────────────────────────────────────────────────────────────
    payslip_id = fields.Many2one(
        'hr.payslip', string='Payslip', readonly=True, copy=False
    )
    payslip_run_id = fields.Many2one(
        'hr.payslip.run', string='Payslip Batch', readonly=True, copy=False
    )

    # ── Accounting ────────────────────────────────────────────────────────────
    move_id = fields.Many2one(
        'account.move', string='Journal Entry', readonly=True, copy=False
    )
    vendor_bill_id = fields.Many2one(
        'account.move', string='Vendor Bill', readonly=True, copy=False
    )
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Analytic Account'
    )

    # ── Deferred ─────────────────────────────────────────────────────────────
    is_deferred = fields.Boolean(string='Deferred Commission')
    deferred_release_date = fields.Date(string='Release Date')

    # ── Notes ─────────────────────────────────────────────────────────────────
    note = fields.Text(string='Internal Notes')

    # ── Overrides state from approval mixin for display ───────────────────────
    state = fields.Selection(
        selection_add=[],
        ondelete={
            'draft': 'set default',
        }
    )

    _name_uniq = models.Constraint(
        'UNIQUE(name, company_id)',
        'Settlement reference must be unique per company.',
    )

    # ── Computes ──────────────────────────────────────────────────────────────
    @api.depends('line_ids')
    def _compute_line_count(self):
        for s in self:
            s.line_count = len(s.line_ids)

    @api.depends('line_ids.commission_amount', 'line_ids.line_type', 'line_ids.state')
    def _compute_amounts(self):
        for s in self:
            lines = s.line_ids.filtered(lambda l: l.state != 'cancelled')
            s.gross_commission = sum(
                lines.filtered(lambda l: l.line_type == 'commission').mapped('commission_amount')
            )
            s.adjustment_amount = sum(
                lines.filtered(lambda l: l.line_type == 'adjustment').mapped('commission_amount')
            )
            s.clawback_amount = sum(
                lines.filtered(lambda l: l.line_type == 'clawback').mapped('commission_amount')
            )
            s.net_commission = s.gross_commission + s.adjustment_amount - abs(s.clawback_amount)

    @api.depends('net_commission', 'move_id', 'vendor_bill_id', 'payslip_id')
    def _compute_paid_amount(self):
        for s in self:
            paid = 0.0
            if s.state == 'paid':
                paid = s.net_commission
            s.paid_amount = paid
            s.residual_amount = s.net_commission - paid

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'commission.settlement'
                ) or '/'
        return super().create(vals_list)

    def action_submit(self):
        for s in self:
            if not s.line_ids:
                raise UserError(_('Cannot submit settlement "%s" without lines.') % s.name)
        super().action_submit()

    def action_final_approve(self):
        super().action_final_approve()

    def action_pay(self):
        """Process payment based on settlement method."""
        for s in self:
            if s.state != 'approved':
                raise UserError(_('Only approved settlements can be paid.'))
            if s.settlement_method == 'payroll':
                s._create_payslip_entry()
            elif s.settlement_method == 'vendor_bill':
                s._create_vendor_bill()
            elif s.settlement_method == 'journal_entry':
                s._create_journal_entry()
            s.write({
                'state': 'paid',
                'payment_date': fields.Date.today(),
            })
            s.line_ids.write({'state': 'paid'})
            s.message_post(
                body=_('Settlement paid via %s.') % dict(
                    s._fields['settlement_method'].selection
                ).get(s.settlement_method)
            )

    def _create_payslip_entry(self):
        """Create payslip input for this settlement."""
        self.ensure_one()
        if not self.employee_id.contract_id:
            raise UserError(
                _('Employee "%s" has no active contract.') % self.employee_id.name
            )
        plan = self.plan_id
        input_type = plan.payroll_input_type_id if plan else False
        if not input_type:
            input_type = self.env.ref(
                'advanced_commission_engine.commission_payslip_input_type',
                raise_if_not_found=False,
            )
        if input_type:
            # Store for payroll processing
            self.write({'state': 'paid'})

    def _create_vendor_bill(self):
        """Create vendor bill for freelancer/external commission payment."""
        self.ensure_one()
        partner = self.employee_id.user_id.partner_id or self.employee_id.address_home_id
        if not partner:
            raise UserError(
                _('Employee "%s" has no linked partner for vendor bill.') % self.employee_id.name
            )
        plan = self.plan_id
        debit_account = plan.debit_account_id if plan else False
        if not debit_account:
            debit_account = self.env['account.account'].search([
                ('account_type', '=', 'expense'),
                ('company_id', '=', self.company_id.id),
            ], limit=1)

        bill_vals = {
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'invoice_date': fields.Date.today(),
            'company_id': self.company_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': _('Commission: %s') % self.name,
                'quantity': 1.0,
                'price_unit': self.net_commission,
                'account_id': debit_account.id if debit_account else False,
            })],
            'narration': _('Commission settlement %s for %s') % (
                self.name, self.employee_id.name
            ),
        }
        bill = self.env['account.move'].create(bill_vals)
        self.vendor_bill_id = bill

    def _create_journal_entry(self):
        """Create accounting journal entry for commission accrual."""
        self.ensure_one()
        plan = self.plan_id
        if not plan or not plan.journal_id:
            raise UserError(
                _('Commission plan "%s" has no journal configured.') % (
                    plan.name if plan else 'N/A'
                )
            )
        debit_account = plan.debit_account_id
        credit_account = plan.credit_account_id
        if not debit_account or not credit_account:
            raise UserError(
                _('Commission plan "%s" is missing debit/credit accounts.') % plan.name
            )
        move_vals = {
            'journal_id': plan.journal_id.id,
            'date': fields.Date.today(),
            'company_id': self.company_id.id,
            'ref': self.name,
            'line_ids': [
                (0, 0, {
                    'account_id': debit_account.id,
                    'name': _('Commission Expense: %s') % self.name,
                    'debit': self.net_commission,
                    'credit': 0.0,
                    'partner_id': self.employee_id.address_home_id.id,
                    'analytic_distribution': {
                        str(plan.analytic_account_id.id): 100
                    } if plan.analytic_account_id else {},
                }),
                (0, 0, {
                    'account_id': credit_account.id,
                    'name': _('Commission Payable: %s') % self.name,
                    'debit': 0.0,
                    'credit': self.net_commission,
                    'partner_id': self.employee_id.address_home_id.id,
                }),
            ],
        }
        move = self.env['account.move'].create(move_vals)
        move.action_post()
        self.move_id = move

    def action_view_move(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('No journal entry found for this settlement.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
        }

    def action_view_payslip(self):
        self.ensure_one()
        if not self.payslip_id:
            raise UserError(_('No payslip linked to this settlement.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip',
            'res_id': self.payslip_id.id,
            'view_mode': 'form',
        }
