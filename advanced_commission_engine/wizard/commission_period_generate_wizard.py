# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class CommissionPeriodGenerateWizard(models.TransientModel):
    _name = 'commission.period.generate.wizard'
    _description = 'Generate Commission Periods'

    year = fields.Integer(
        string='Year',
        required=True,
        default=lambda self: fields.Date.today().year,
    )
    period_type = fields.Selection([
        ('monthly', 'Monthly (12 periods)'),
        ('quarterly', 'Quarterly (4 periods)'),
        ('semi_annual', 'Semi-Annual (2 periods)'),
        ('annual', 'Annual (1 period)'),
    ], string='Period Type', required=True, default='monthly')
    company_id = fields.Many2one(
        'res.company', string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    plan_ids = fields.Many2many(
        'commission.plan', string='Assign Plans',
        help='Plans to assign to generated periods',
    )

    def action_generate(self):
        self.ensure_one()
        if self.year < 2000 or self.year > 2100:
            raise UserError(_('Please enter a valid year (2000-2100).'))

        created = self.env['commission.period'].generate_periods(
            self.period_type,
            self.year,
            company_id=self.company_id.id,
        )
        if self.plan_ids and created:
            created.write({'plan_ids': [(4, p.id) for p in self.plan_ids]})

        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated Periods'),
            'res_model': 'commission.period',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created.ids)],
        }
