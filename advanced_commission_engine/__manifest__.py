# -*- coding: utf-8 -*-
{
    'name': 'Advanced Commission Engine',
    'version': '19.0.1.0.0',
    'category': 'Sales/Commission',
    'summary': 'Enterprise-grade commission management: plans, rules, settlements, KPI gamification, AI-ready analytics',
    'description': """
Advanced Commission Engine
==========================
A production-ready, fully-featured commission management system for Odoo 19 Enterprise.

Features:
- 12 commission types (sales, collection, recurring, subscription, project, referral, override, team, etc.)
- 10 calculation methods (fixed %, slabs, tiered, margin, profit, KPI, hybrid, formula)
- Full lifecycle: draft → calculated → submitted → approved → finance_approved → payroll_processed → paid
- Payroll integration with hr.payslip inputs
- Accounting integration with journal entries and accruals
- CRM/Sales/POS source document tracking
- KPI gamification: badges, leaderboards, streaks, team competitions
- OWL dashboard with analytics, forecasts, heatmaps
- Employee portal: statements, disputes, PDF download
- AI-ready services: anomaly detection, forecasting, recommendations
- Multi-company, multi-currency, approval workflows
- Performance-optimised for 1M+ commission lines
    """,
    'author': 'Advanced Commission Engine',
    'website': 'https://www.odoo.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'hr',
        'hr_payroll',
        'account',
        'sale',
        'sale_management',
        'crm',
        'analytic',
        'project',
        'gamification',
        'portal',
        'web',
        'board',
        'sale_subscription',
    ],
    'data': [
        # Security
        'security/security.xml',
        'security/record_rules.xml',
        'security/ir.model.access.csv',
        # Data
        'data/sequence.xml',
        'data/commission_data.xml',
        'data/cron.xml',
        'data/mail_templates.xml',
        # Reports
        'report/commission_reports.xml',
        'report/commission_templates.xml',
        # Views
        'views/assets.xml',
        'views/res_config_settings_views.xml',
        'views/commission_plan_views.xml',
        'views/commission_rule_views.xml',
        'views/commission_period_views.xml',
        'views/commission_settlement_views.xml',
        'views/commission_kpi_views.xml',
        'views/commission_target_views.xml',
        'views/commission_simulation_views.xml',
        'views/commission_forecast_views.xml',
        'views/commission_dashboard_views.xml',
        'views/portal_templates.xml',
        'views/menu.xml',
        # Wizards
        'wizard/generate_settlement_views.xml',
        'wizard/commission_simulator_views.xml',
        'wizard/rollback_commission_views.xml',
        'wizard/recalculate_commission_views.xml',
    ],
    'demo': [
        'data/commission_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'advanced_commission_engine/static/src/scss/commission_dashboard.scss',
            'advanced_commission_engine/static/src/js/commission_dashboard.js',
            'advanced_commission_engine/static/src/js/commission_widgets.js',
            'advanced_commission_engine/static/src/xml/commission_dashboard.xml',
        ],
        'web.assets_frontend': [
            'advanced_commission_engine/static/src/scss/portal.scss',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': True,
    'sequence': 10,
}
