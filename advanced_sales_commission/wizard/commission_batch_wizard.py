# -*- coding: utf-8 -*-
"""Batch recalculation wizard."""
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class AscCommissionBatchWizard(models.TransientModel):
    _name = 'asc.commission.batch.wizard'
    _description = 'Commission Batch Recalculation Wizard'

    month = fields.Selection([
        ('1', 'January'), ('2', 'February'), ('3', 'March'),
        ('4', 'April'), ('5', 'May'), ('6', 'June'),
        ('7', 'July'), ('8', 'August'), ('9', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December'),
    ], string='Month', required=True,
        default=lambda self: str(fields.Date.today().month))
    year = fields.Integer(
        string='Year', required=True,
        default=lambda self: fields.Date.today().year,
    )
    plan_ids = fields.Many2many(
        'asc.commission.plan', string='Limit to Plans',
        help='Leave empty to recalculate all plans.',
    )
    salesperson_ids = fields.Many2many(
        'res.users', string='Limit to Salespersons',
        domain=[('share', '=', False)],
    )
    recalculate_approved = fields.Boolean(
        string='Recalculate Approved Lines',
        default=False,
        help='Warning: This will reset approved lines back to "calculated" state.',
    )

    def action_run(self):
        self.ensure_one()
        domain = [
            ('period_month', '=', int(self.month)),
            ('period_year', '=', self.year),
        ]
        states = ['draft', 'calculated']
        if self.recalculate_approved:
            states.append('approved')
        domain.append(('state', 'in', states))

        if self.plan_ids:
            domain.append(('plan_id', 'in', self.plan_ids.ids))
        if self.salesperson_ids:
            domain.append(('salesperson_id', 'in', self.salesperson_ids.ids))

        engine = self.env['asc.commission.engine']
        engine.batch_recalculate(domain=domain, month=int(self.month), year=self.year)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Batch Recalculation Complete'),
                'message': _('Commission lines for %s/%s have been recalculated.') % (self.month, self.year),
                'type': 'success',
                'sticky': False,
            },
        }
