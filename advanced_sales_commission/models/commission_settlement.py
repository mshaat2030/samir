# -*- coding: utf-8 -*-
"""
asc.commission.settlement — Monthly settlement batch.
Generates payroll inputs and accounting journal entries.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class AscCommissionSettlement(models.Model):
    _name = 'asc.commission.settlement'
    _description = 'Commission Settlement'
    _inherit = ['asc.multi.company.mixin', 'asc.state.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'year desc, month desc, id desc'

    name = fields.Char(
        string='Settlement Reference', required=True, copy=False, readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('asc.commission.settlement'),
    )

    # ── Period ────────────────────────────────────────────────────────────────
    month = fields.Selection([
        ('1', 'January'), ('2', 'February'), ('3', 'March'),
        ('4', 'April'), ('5', 'May'), ('6', 'June'),
        ('7', 'July'), ('8', 'August'), ('9', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December'),
    ], string='Month', required=True)
    year = fields.Integer(string='Year', required=True, default=lambda self: fields.Date.today().year)
    date_from = fields.Date(string='Period From', required=True)
    date_to = fields.Date(string='Period To', required=True)

    # ── Commission Lines ───────────────────────────────────────────────────────
    line_ids = fields.One2many(
        'asc.commission.line', 'settlement_id',
        string='Commission Lines',
    )
    line_count = fields.Integer(compute='_compute_totals', store=True)

    # ── Salesperson Breakdown ─────────────────────────────────────────────────
    salesperson_ids = fields.Many2many(
        'res.users', 'asc_settlement_user_rel', 'settlement_id', 'user_id',
        string='Salespersons', compute='_compute_salesperson_ids', store=True,
    )

    # ── Amounts ───────────────────────────────────────────────────────────────
    currency_id = fields.Many2one(
        related='company_id.currency_id', string='Currency', readonly=True,
    )
    total_base_amount = fields.Monetary(
        string='Total Base Amount', currency_field='currency_id',
        compute='_compute_totals', store=True,
    )
    total_commission = fields.Monetary(
        string='Total Commission', currency_field='currency_id',
        compute='_compute_totals', store=True,
    )
    total_bonus = fields.Monetary(
        string='Total Bonus', currency_field='currency_id',
        compute='_compute_totals', store=True,
    )
    total_clawback = fields.Monetary(
        string='Total Clawback', currency_field='currency_id',
        compute='_compute_totals', store=True,
    )
    net_payable = fields.Monetary(
        string='Net Payable', currency_field='currency_id',
        compute='_compute_totals', store=True,
    )

    # ── Accounting ────────────────────────────────────────────────────────────
    move_id = fields.Many2one(
        'account.move', string='Journal Entry',
        copy=False, readonly=True,
    )
    payroll_slip_ids = fields.Many2many(
        'hr.payslip', 'asc_settlement_slip_rel', 'settlement_id', 'slip_id',
        string='Payroll Slips', copy=False,
    )
    payroll_slip_count = fields.Integer(
        compute='_compute_payroll_slip_count',
    )

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = fields.Text(string='Notes')

    # ─────────────────────────────────────────────────────────────────────────
    # Computed
    # ─────────────────────────────────────────────────────────────────────────
    @api.depends('line_ids', 'line_ids.base_amount', 'line_ids.commission_amount_company',
                 'line_ids.bonus_amount', 'line_ids.clawback_amount', 'line_ids.net_commission')
    def _compute_totals(self):
        for settlement in self:
            lines = settlement.line_ids
            settlement.line_count = len(lines)
            settlement.total_base_amount = sum(lines.mapped('base_amount'))
            settlement.total_commission = sum(lines.mapped('commission_amount_company'))
            settlement.total_bonus = sum(lines.mapped('bonus_amount'))
            settlement.total_clawback = sum(lines.mapped('clawback_amount'))
            settlement.net_payable = sum(lines.mapped('net_commission'))

    @api.depends('line_ids.salesperson_id')
    def _compute_salesperson_ids(self):
        for settlement in self:
            settlement.salesperson_ids = settlement.line_ids.mapped('salesperson_id')

    def _compute_payroll_slip_count(self):
        for settlement in self:
            settlement.payroll_slip_count = len(settlement.payroll_slip_ids)

    # ─────────────────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────────────────
    def action_generate_journal_entry(self):
        """Delegate to settlement engine."""
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_('Settlement must be approved before posting journal entries.'))
        engine = self.env['asc.settlement.engine']
        move = engine.create_journal_entry(self)
        self.move_id = move
        self.message_post(body=_('Journal entry %s created.') % move.name)

    def action_push_to_payroll(self):
        """Create payslip inputs for all employees in this settlement."""
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_('Settlement must be approved before pushing to payroll.'))
        engine = self.env['asc.settlement.engine']
        slips = engine.push_to_payroll(self)
        self.payroll_slip_ids = [(4, s.id) for s in slips]
        self.message_post(
            body=_('%d payslip input(s) created.') % len(slips)
        )

    def action_mark_paid(self):
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_('Settlement must be approved before marking as paid.'))
        self.line_ids.write({'state': 'paid'})
        self.write({'state': 'paid'})

    def action_view_journal_entry(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('No journal entry generated yet.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
        }

    def action_view_payroll_slips(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Payroll Slips'),
            'res_model': 'hr.payslip',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.payroll_slip_ids.ids)],
        }

    # ─────────────────────────────────────────────────────────────────────────
    # SQL Constraints
    # ─────────────────────────────────────────────────────────────────────────
    _sql_constraints = [
        ('period_company_uniq', 'UNIQUE(month, year, company_id)',
         'A settlement already exists for this month/year/company.'),
        ('name_uniq', 'UNIQUE(name)', 'Settlement reference must be unique.'),
    ]

    def _auto_init(self):
        res = super()._auto_init()
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS asc_commission_settlement_period_idx
            ON asc_commission_settlement (year, month, company_id, state);
        """)
        return res
