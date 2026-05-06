# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class CommissionRecalculateWizard(models.TransientModel):
    _name = 'commission.recalculate.wizard'
    _description = 'Recalculate Commissions'

    recalc_type = fields.Selection([
        ('period', 'By Period'),
        ('employee', 'By Employee'),
        ('plan', 'By Plan'),
        ('selection', 'Selected Lines'),
    ], string='Recalculate', required=True, default='period')

    period_id = fields.Many2one(
        'commission.period', string='Period',
        domain="[('state', '=', 'open')]",
    )
    employee_ids = fields.Many2many(
        'hr.employee', string='Employees'
    )
    plan_ids = fields.Many2many(
        'commission.plan', string='Plans'
    )
    line_ids = fields.Many2many(
        'commission.line', string='Commission Lines',
        domain="[('state', 'not in', ('paid', 'cancelled'))]",
    )
    create_adjustments = fields.Boolean(
        string='Create Adjustment Entries for Differences',
        default=True,
    )
    reason = fields.Text(string='Reason for Recalculation', required=True)

    def action_recalculate(self):
        self.ensure_one()
        domain = [('state', 'not in', ('paid', 'cancelled'))]

        if self.recalc_type == 'period' and self.period_id:
            domain.append(('period_id', '=', self.period_id.id))
        elif self.recalc_type == 'employee' and self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        elif self.recalc_type == 'plan' and self.plan_ids:
            domain.append(('plan_id', 'in', self.plan_ids.ids))
        elif self.recalc_type == 'selection' and self.line_ids:
            domain.append(('id', 'in', self.line_ids.ids))
        else:
            raise UserError(_('Please provide the recalculation criteria.'))

        lines = self.env['commission.line'].search(domain)
        if not lines:
            raise UserError(_('No commission lines found matching the criteria.'))

        engine = self.env['commission.engine']
        adjusted_lines = engine.recalculate(lines)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': _('%d commission lines recalculated (%d changed).') % (
                    len(lines), len(adjusted_lines)
                ),
                'type': 'success',
                'sticky': False,
            },
        }
