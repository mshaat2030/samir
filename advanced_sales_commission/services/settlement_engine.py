# -*- coding: utf-8 -*-
"""
ASC Settlement Engine — Generates journal entries and payroll inputs.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from collections import defaultdict
import logging

_logger = logging.getLogger(__name__)


class AscSettlementEngine(models.AbstractModel):
    _name = 'asc.settlement.engine'
    _description = 'Commission Settlement Engine'

    @api.model
    def generate_monthly_settlement(self, month=None, year=None, company=None):
        """
        Auto-generate a monthly settlement for all approved commission lines
        that haven't been settled yet.
        """
        today = fields.Date.today()
        month = month or today.month
        year = year or today.year
        company = company or self.env.company

        # Check no existing settlement for this period
        existing = self.env['asc.commission.settlement'].search([
            ('month', '=', str(month)),
            ('year', '=', year),
            ('company_id', '=', company.id),
        ])
        if existing:
            _logger.info('ASC: Settlement already exists for %s/%s company %s', month, year, company.name)
            return existing

        # Fetch unsettled lines for the period
        lines = self.env['asc.commission.line'].search([
            ('company_id', '=', company.id),
            ('period_month', '=', month),
            ('period_year', '=', year),
            ('state', '=', 'approved'),
            ('is_settled', '=', False),
            ('is_simulation', '=', False),
        ])

        if not lines:
            _logger.info('ASC: No approved lines to settle for %s/%s', month, year)
            return False

        import calendar
        last_day = calendar.monthrange(year, month)[1]
        date_from = fields.Date.from_string(f'{year}-{month:02d}-01')
        date_to = fields.Date.from_string(f'{year}-{month:02d}-{last_day}')

        settlement = self.env['asc.commission.settlement'].create({
            'month': str(month),
            'year': year,
            'date_from': date_from,
            'date_to': date_to,
            'company_id': company.id,
            'state': 'draft',
        })
        lines.write({'settlement_id': settlement.id})
        settlement.action_calculate()
        _logger.info('ASC: Settlement %s created with %d lines', settlement.name, len(lines))
        return settlement

    @api.model
    def create_journal_entry(self, settlement):
        """
        Generate accounting journal entry for a settlement.
        Groups lines by salesperson → one debit (expense) + one credit (payable) per employee.
        Uses bulk operations.
        """
        company = settlement.company_id
        plan_set = settlement.line_ids.mapped('plan_id')

        # Determine accounts — use plan config or company defaults
        default_expense_account = self.env['account.account'].search([
            ('company_id', '=', company.id),
            ('account_type', '=', 'expense'),
            ('deprecated', '=', False),
        ], limit=1)
        default_payable_account = self.env['account.account'].search([
            ('company_id', '=', company.id),
            ('account_type', '=', 'liability_payable'),
            ('deprecated', '=', False),
        ], limit=1)

        if not default_expense_account or not default_payable_account:
            raise UserError(_('Commission expense or payable account not configured.'))

        # Find journal
        journal = plan_set[:1].journal_id if plan_set[:1].journal_id else \
            self.env['account.journal'].search([
                ('type', '=', 'general'),
                ('company_id', '=', company.id),
            ], limit=1)
        if not journal:
            raise UserError(_('No general journal found for commission entries.'))

        # Group lines by employee/salesperson for batch move line creation
        by_user = defaultdict(lambda: {'net': 0.0, 'expense_acc': None, 'payable_acc': None})
        for line in settlement.line_ids:
            plan = line.plan_id
            uid = line.salesperson_id.id
            by_user[uid]['net'] += line.net_commission
            by_user[uid]['expense_acc'] = plan.commission_account_id or default_expense_account
            by_user[uid]['payable_acc'] = plan.payable_account_id or default_payable_account
            by_user[uid]['salesperson'] = line.salesperson_id

        move_lines = []
        for uid, data in by_user.items():
            if data['net'] <= 0:
                continue
            sp = data['salesperson']
            # Debit: Commission Expense
            move_lines.append((0, 0, {
                'account_id': data['expense_acc'].id,
                'name': _('Commission: %s') % sp.name,
                'debit': data['net'],
                'credit': 0.0,
                'partner_id': sp.partner_id.id,
            }))
            # Credit: Commission Payable
            move_lines.append((0, 0, {
                'account_id': data['payable_acc'].id,
                'name': _('Commission Payable: %s') % sp.name,
                'debit': 0.0,
                'credit': data['net'],
                'partner_id': sp.partner_id.id,
            }))

        if not move_lines:
            raise UserError(_('No positive commission amounts to post.'))

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': settlement.date_to,
            'ref': _('Commission Settlement: %s') % settlement.name,
            'company_id': company.id,
            'line_ids': move_lines,
        })
        move.action_post()
        return move

    @api.model
    def push_to_payroll(self, settlement):
        """
        Create payroll input lines for each employee in the settlement.
        Returns created hr.payslip.input records or payslips.
        """
        company = settlement.company_id
        employee_data = defaultdict(float)
        employee_plan = {}

        # Batch: collect data
        for line in settlement.line_ids:
            emp = line.employee_id
            if not emp:
                continue
            employee_data[emp.id] += line.net_commission
            employee_plan[emp.id] = line.plan_id

        if not employee_data:
            raise UserError(_('No employees found in this settlement (ensure salespersons have linked HR employees).'))

        # Find or create payslips for this period
        import calendar
        year = settlement.year
        month = int(settlement.month)
        date_from = fields.Date.from_string(f'{year}-{month:02d}-01')
        last_day = calendar.monthrange(year, month)[1]
        date_to = fields.Date.from_string(f'{year}-{month:02d}-{last_day}')

        employee_ids = list(employee_data.keys())
        existing_slips = self.env['hr.payslip'].search([
            ('employee_id', 'in', employee_ids),
            ('date_from', '=', date_from),
            ('date_to', '=', date_to),
            ('state', 'not in', ['done', 'cancel']),
            ('company_id', '=', company.id),
        ])
        slip_by_emp = {slip.employee_id.id: slip for slip in existing_slips}

        # Create missing slips in bulk
        to_create_slips = []
        for emp_id in employee_ids:
            if emp_id not in slip_by_emp:
                to_create_slips.append({
                    'employee_id': emp_id,
                    'date_from': date_from,
                    'date_to': date_to,
                    'company_id': company.id,
                })
        if to_create_slips:
            new_slips = self.env['hr.payslip'].create(to_create_slips)
            for slip in new_slips:
                slip_by_emp[slip.employee_id.id] = slip

        # Add payslip input lines in bulk
        to_create_inputs = []
        for emp_id, amount in employee_data.items():
            slip = slip_by_emp.get(emp_id)
            if not slip:
                continue
            plan = employee_plan.get(emp_id)
            input_type = plan.payroll_input_type_id if plan else self.env['hr.payslip.input.type'].search([
                ('code', '=', 'COMMISSION')
            ], limit=1)
            if not input_type:
                _logger.warning('ASC: No payroll input type for commission. Skipping employee %s', emp_id)
                continue
            to_create_inputs.append({
                'payslip_id': slip.id,
                'input_type_id': input_type.id,
                'name': _('Sales Commission - %s') % settlement.name,
                'amount': amount,
            })

        if to_create_inputs:
            self.env['hr.payslip.input'].create(to_create_inputs)

        return self.env['hr.payslip'].browse(list(slip_by_emp.values()))
