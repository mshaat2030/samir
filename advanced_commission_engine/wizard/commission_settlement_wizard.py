# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class CommissionSettlementWizard(models.TransientModel):
    _name = 'commission.settlement.wizard'
    _description = 'Generate Commission Settlements'

    period_id = fields.Many2one(
        'commission.period', string='Period',
        required=True,
        domain="[('state', '=', 'open'), ('company_id', '=', company_id)]",
    )
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company
    )
    plan_ids = fields.Many2many(
        'commission.plan', string='Plans',
        help='Leave empty to process all active plans for the period',
    )
    settlement_method = fields.Selection([
        ('payroll', 'Via Payroll'),
        ('vendor_bill', 'Via Vendor Bill'),
        ('journal_entry', 'Via Journal Entry'),
        ('manual', 'Manual'),
    ], string='Settlement Method', default='payroll', required=True)
    include_adjustments = fields.Boolean(
        string='Include Adjustments', default=True
    )
    auto_submit = fields.Boolean(
        string='Auto-Submit for Approval', default=False
    )
    dry_run = fields.Boolean(
        string='Dry Run (Preview Only)', default=False
    )

    # Results
    preview_line_ids = fields.One2many(
        'commission.settlement.wizard.line', 'wizard_id',
        string='Preview',
        readonly=True,
    )
    result_message = fields.Text(string='Result', readonly=True)

    def action_preview(self):
        """Preview what settlements would be generated."""
        self.ensure_one()
        self.preview_line_ids.unlink()
        lines = self.env['commission.line'].search([
            ('period_id', '=', self.period_id.id),
            ('state', '=', 'validated'),
            ('settlement_id', '=', False),
        ])
        if self.plan_ids:
            lines = lines.filtered(lambda l: l.plan_id in self.plan_ids)

        # Group by employee + plan
        groups = {}
        for line in lines:
            key = (line.employee_id.id, line.plan_id.id)
            if key not in groups:
                groups[key] = {'lines': [], 'amount': 0}
            groups[key]['lines'].append(line.id)
            groups[key]['amount'] += line.commission_amount

        preview = []
        for (emp_id, plan_id), data in groups.items():
            emp = self.env['hr.employee'].browse(emp_id)
            plan = self.env['commission.plan'].browse(plan_id)
            preview.append({
                'wizard_id': self.id,
                'employee_id': emp_id,
                'plan_id': plan_id,
                'line_count': len(data['lines']),
                'total_amount': data['amount'],
            })
        if preview:
            self.env['commission.settlement.wizard.line'].create(preview)
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_generate(self):
        """Generate settlements."""
        self.ensure_one()
        if self.dry_run:
            return self.action_preview()

        engine = self.env['commission.engine']
        created = engine.generate_settlements(
            self.period_id,
            method=self.settlement_method,
        )
        if self.auto_submit:
            for s in created:
                try:
                    s.action_submit()
                except Exception:
                    pass
        msg = _('%d settlements generated successfully.') % len(created)
        self.result_message = msg
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': msg,
                'type': 'success',
                'sticky': False,
            },
        }


class CommissionSettlementWizardLine(models.TransientModel):
    _name = 'commission.settlement.wizard.line'
    _description = 'Settlement Wizard Preview Line'

    wizard_id = fields.Many2one('commission.settlement.wizard', ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    plan_id = fields.Many2one('commission.plan', string='Plan')
    line_count = fields.Integer(string='Lines')
    total_amount = fields.Float(string='Total Amount', digits=(16, 2))
