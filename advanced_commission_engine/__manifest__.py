# -*- coding: utf-8 -*-
{
    'name': 'Advanced Commission Engine',
    'version': '19.0.1.0.0',
    'category': 'Sales/Commission',
    'summary': 'Enterprise-grade commission management with AI-ready analytics, gamification, and full payroll integration',
    'description': """
Advanced Commission Engine
==========================
Production-ready, scalable commission management for Odoo 19 Enterprise.

Key Features:
- 12 commission types: sales, collection, recurring, subscription renewal, project milestone,
  referral, manager override, team, recruitment, profit-sharing, territory, KPI incentive
- 10 calculation methods: fixed %, fixed amount, progressive slabs, tiered, margin-based,
  revenue-based, profit-based, weighted KPI score, hybrid, dynamic formula engine
- Full lifecycle: draft → calculated → submitted → approved → finance_approved →
  payroll_processed → paid → cancelled → disputed
- Payroll, accounting, CRM/Sales integrations
- KPI gamification: leaderboards, badges, streaks, campaigns
- AI-ready services: anomaly detection, forecasting, recommendations
- Employee portal with PDF statements, dispute submission, progress tracking
- OWL dashboards, pivot/graph/cohort analytics
- Multi-company, multi-currency, full audit trail
    """,
    'author': 'Advanced Commission Engine',
    'website': 'https://github.com/advanced-commission-engine',
    'license': 'OEEL-1',
    'depends': [
        'base',
        'base_setup',
        'mail',
        'hr',
        'hr_payroll',
        'account',
        'account_accountant',
        'analytic',
        'sale',
        'sale_management',
        'crm',
        'sale_subscription',
        'project',
        'portal',
        'web',
        'gamification',
        'board',
        'report_xlsx',
    ],
    'data': [
        # Security - must be first
        'security/security.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        # Data
        'data/sequence.xml',
        'data/commission_data.xml',
        'data/mail_templates.xml',
        'data/cron.xml',
        # Wizard views
        'wizard/generate_settlement_views.xml',
        'wizard/commission_simulator_views.xml',
        'wizard/rollback_commission_views.xml',
        'wizard/recalculate_commission_views.xml',
        # Views
        'views/commission_plan_views.xml',
        'views/commission_rule_views.xml',
        'views/commission_period_views.xml',
        'views/commission_settlement_views.xml',
        'views/commission_kpi_views.xml',
        'views/commission_target_views.xml',
        'views/commission_simulation_views.xml',
        'views/commission_forecast_views.xml',
        'views/commission_dashboard_views.xml',
        'views/res_config_settings_views.xml',
        'views/portal_templates.xml',
        'views/menu.xml',
        # Reports
        'report/commission_reports.xml',
        'report/commission_templates.xml',
    ],
    'demo': [
        'data/commission_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'advanced_commission_engine/static/src/scss/commission.scss',
            'advanced_commission_engine/static/src/xml/commission_dashboard.xml',
            'advanced_commission_engine/static/src/js/commission_widgets.js',
            'advanced_commission_engine/static/src/js/commission_dashboard.js',
        ],
        'web.assets_frontend': [
            'advanced_commission_engine/static/src/scss/commission.scss',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': True,
    'sequence': 10,
}
