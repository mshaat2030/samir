# -*- coding: utf-8 -*-
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    asc_auto_calculate = fields.Boolean(
        string='Auto-Calculate Commissions on Invoice Validation',
        config_parameter='asc.auto_calculate',
    )
    asc_require_approval = fields.Boolean(
        string='Require Manager Approval for Settlements',
        config_parameter='asc.require_approval',
    )
    asc_clawback_enabled = fields.Boolean(
        string='Enable Global Clawback',
        config_parameter='asc.clawback_enabled',
    )
    asc_payroll_integration = fields.Boolean(
        string='Enable Payroll Integration',
        config_parameter='asc.payroll_integration',
    )
    asc_default_plan_id = fields.Many2one(
        'asc.commission.plan',
        string='Default Commission Plan',
        config_parameter='asc.default_plan_id',
    )
