# -*- coding: utf-8 -*-
"""Commission module configuration settings."""

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    """Extend res.config.settings with commission module configuration."""

    _inherit = 'res.config.settings'

    # ── General ───────────────────────────────────────────────────────────────
    commission_default_account_id = fields.Many2one(
        'account.account', string='Default Commission Account',
        config_parameter='advanced_commission_engine.default_account_id',
        domain=[('deprecated', '=', False)],
    )
    commission_default_journal_id = fields.Many2one(
        'account.journal', string='Default Commission Journal',
        config_parameter='advanced_commission_engine.default_journal_id',
    )
    commission_default_analytic_id = fields.Many2one(
        'account.analytic.account', string='Default Analytic Account',
        config_parameter='advanced_commission_engine.default_analytic_id',
    )

    # ── Approval Workflow ─────────────────────────────────────────────────────
    commission_require_manager_approval = fields.Boolean(
        string='Require Manager Approval by Default',
        config_parameter='advanced_commission_engine.require_manager_approval',
        default=True,
    )
    commission_require_finance_approval = fields.Boolean(
        string='Require Finance Approval by Default',
        config_parameter='advanced_commission_engine.require_finance_approval',
        default=True,
    )
    commission_auto_approve_threshold = fields.Float(
        string='Auto-Approve Threshold',
        config_parameter='advanced_commission_engine.auto_approve_threshold',
        help='Settlements below this amount are auto-approved.',
    )

    # ── Period Settings ───────────────────────────────────────────────────────
    commission_auto_create_periods = fields.Boolean(
        string='Auto-Create Monthly Periods',
        config_parameter='advanced_commission_engine.auto_create_periods',
        default=True,
    )
    commission_auto_lock_periods = fields.Boolean(
        string='Auto-Lock Past Periods',
        config_parameter='advanced_commission_engine.auto_lock_periods',
        default=True,
    )
    commission_period_lock_delay_days = fields.Integer(
        string='Period Lock Delay (Days After Close)',
        config_parameter='advanced_commission_engine.period_lock_delay_days',
        default=10,
        help='Number of days after period end before auto-locking.',
    )

    # ── Payroll Integration ───────────────────────────────────────────────────
    commission_payroll_integration = fields.Boolean(
        string='Enable Payroll Integration',
        config_parameter='advanced_commission_engine.payroll_integration',
        default=True,
    )

    # ── Clawback ─────────────────────────────────────────────────────────────
    commission_enable_clawback = fields.Boolean(
        string='Enable Clawback by Default',
        config_parameter='advanced_commission_engine.enable_clawback',
        default=False,
    )
    commission_clawback_period_months = fields.Integer(
        string='Default Clawback Period (Months)',
        config_parameter='advanced_commission_engine.clawback_period_months',
        default=3,
    )

    # ── Gamification ──────────────────────────────────────────────────────────
    commission_enable_gamification = fields.Boolean(
        string='Enable Gamification (Badges, Leaderboards)',
        config_parameter='advanced_commission_engine.enable_gamification',
        default=True,
    )
    commission_leaderboard_public = fields.Boolean(
        string='Leaderboard Visible in Employee Portal',
        config_parameter='advanced_commission_engine.leaderboard_public',
        default=True,
    )

    # ── Analytics ─────────────────────────────────────────────────────────────
    commission_anomaly_detection = fields.Boolean(
        string='Enable Anomaly Detection',
        config_parameter='advanced_commission_engine.anomaly_detection',
        default=True,
    )
    commission_anomaly_std_threshold = fields.Float(
        string='Anomaly Detection Threshold (Std Devs)',
        config_parameter='advanced_commission_engine.anomaly_std_threshold',
        default=3.0,
        help='Flag settlements that exceed this many standard deviations from the mean.',
    )
    commission_forecast_enabled = fields.Boolean(
        string='Enable Payout Forecasting',
        config_parameter='advanced_commission_engine.forecast_enabled',
        default=True,
    )

    # ── Portal ────────────────────────────────────────────────────────────────
    commission_portal_enabled = fields.Boolean(
        string='Enable Employee Commission Portal',
        config_parameter='advanced_commission_engine.portal_enabled',
        default=True,
    )
    commission_portal_allow_disputes = fields.Boolean(
        string='Allow Employees to Submit Disputes via Portal',
        config_parameter='advanced_commission_engine.portal_allow_disputes',
        default=True,
    )

    # ── Notification ─────────────────────────────────────────────────────────
    commission_notify_on_approval = fields.Boolean(
        string='Notify Employee on Settlement Approval',
        config_parameter='advanced_commission_engine.notify_on_approval',
        default=True,
    )
    commission_notify_on_payment = fields.Boolean(
        string='Notify Employee on Payment',
        config_parameter='advanced_commission_engine.notify_on_payment',
        default=True,
    )
