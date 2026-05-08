# -*- coding: utf-8 -*-
"""Configuration settings for the Advanced Commission Engine."""

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    """Extends res.config.settings to add commission module configuration."""

    _inherit = 'res.config.settings'

    # ── General ───────────────────────────────────────────────────────────────
    commission_auto_approve_threshold = fields.Monetary(
        string='Auto-Approve Settlement Below',
        currency_field='currency_id',
        config_parameter='advanced_commission_engine.auto_approve_threshold',
        help='Settlements below this amount are auto-approved. 0 = disabled.',
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        readonly=True,
    )
    commission_formula_timeout = fields.Integer(
        string='Formula Evaluation Timeout (seconds)',
        default=5,
        config_parameter='advanced_commission_engine.formula_timeout',
    )
    commission_batch_size = fields.Integer(
        string='Batch Processing Size',
        default=1000,
        config_parameter='advanced_commission_engine.batch_size',
        help='Number of commission lines to process per batch.',
    )

    # ── Periods ───────────────────────────────────────────────────────────────
    commission_auto_create_periods = fields.Boolean(
        string='Auto-Create Commission Periods',
        default=True,
        config_parameter='advanced_commission_engine.auto_create_periods',
    )

    # ── Payroll ───────────────────────────────────────────────────────────────
    commission_default_payroll_input_id = fields.Many2one(
        'hr.payslip.input.type',
        string='Default Payroll Input Type',
        config_parameter='advanced_commission_engine.default_payroll_input',
    )

    # ── Notifications ─────────────────────────────────────────────────────────
    commission_notify_on_approval = fields.Boolean(
        string='Notify Employee on Approval',
        default=True,
        config_parameter='advanced_commission_engine.notify_on_approval',
    )
    commission_notify_on_payment = fields.Boolean(
        string='Notify Employee on Payment',
        default=True,
        config_parameter='advanced_commission_engine.notify_on_payment',
    )

    # ── Forecasting ───────────────────────────────────────────────────────────
    commission_forecast_months = fields.Integer(
        string='Forecast Horizon (Months)',
        default=3,
        config_parameter='advanced_commission_engine.forecast_months',
    )
    commission_anomaly_threshold_pct = fields.Float(
        string='Anomaly Detection Threshold (%)',
        default=50.0,
        config_parameter='advanced_commission_engine.anomaly_threshold',
        help='Flag settlements that deviate by more than this % from the employee\'s average.',
    )

    # ── Portal ────────────────────────────────────────────────────────────────
    commission_portal_enabled = fields.Boolean(
        string='Enable Employee Portal',
        default=True,
        config_parameter='advanced_commission_engine.portal_enabled',
    )
    commission_portal_show_leaderboard = fields.Boolean(
        string='Show Leaderboard on Portal',
        default=True,
        config_parameter='advanced_commission_engine.portal_show_leaderboard',
    )
