# -*- coding: utf-8 -*-
from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Commission Engine Settings
    commission_default_plan_id = fields.Many2one(
        'commission.plan',
        string='Default Commission Plan',
        domain="[('company_id', '=', id)]",
    )
    commission_auto_settle = fields.Boolean(
        string='Auto-Generate Settlements',
        default=False,
    )
    commission_settlement_day = fields.Integer(
        string='Settlement Day of Month',
        default=1,
        help='Day of month when automatic settlements are generated',
    )
    commission_require_approval = fields.Boolean(
        string='Require Manager Approval',
        default=True,
    )
    commission_require_finance_approval = fields.Boolean(
        string='Require Finance Approval',
        default=True,
    )
    commission_dispute_deadline_days = fields.Integer(
        string='Dispute Response Deadline (Days)',
        default=15,
    )
    commission_portal_visible = fields.Boolean(
        string='Employee Portal Visible',
        default=True,
        help='Allow employees to see their commissions in the portal',
    )
    commission_clawback_enabled = fields.Boolean(
        string='Enable Global Clawback',
        default=False,
    )
    commission_deferred_days = fields.Integer(
        string='Default Deferred Days',
        default=0,
    )
