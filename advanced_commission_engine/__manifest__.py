# -*- coding: utf-8 -*-
{
    'name': 'Advanced Commission Engine',
    'version': '19.0.1.0.0',
    'category': 'Sales/Commission',
    'summary': 'Enterprise-grade commission management with AI-ready architecture',
    'description': """
Advanced Commission Engine
==========================
Complete enterprise commission management system featuring:
- Multi-company, multi-currency support
- Flexible commission plans (fixed, tiered, slabs, formula-based, KPI-based)
- Automated settlement with payroll and accounting integration
- Real-time OWL dashboard and analytics
- Employee portal with dispute management
- AI-ready hooks for prediction and anomaly detection
    """,
    'author': 'Odoo Enterprise',
    'website': 'https://www.odoo.com',
    'license': 'OEEL-1',
    'depends': [
        'base',
        'mail',
        'hr',
        'hr_payroll',
        'sale_management',
        'account',
        'crm',
        'project',
        'web',
        'portal',
        'gamification',
    ],
    'data': [
        # Security
        'security/commission_security.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        # Data
        'data/commission_sequences.xml',
        'data/commission_cron.xml',
        'data/commission_mail_templates.xml',
        'data/hr_payroll_data.xml',
        # Views
        'views/commission_plan_views.xml',
        'views/commission_rule_views.xml',
        'views/commission_period_views.xml',
        'views/commission_settlement_views.xml',
        'views/commission_line_views.xml',
        'views/commission_target_views.xml',
        'views/commission_kpi_views.xml',
        'views/commission_adjustment_views.xml',
        'views/commission_simulation_views.xml',
        'views/commission_forecast_views.xml',
        'views/commission_dispute_views.xml',
        'views/commission_leaderboard_views.xml',
        'views/commission_dashboard_views.xml',
        'views/wizard_views.xml',
        'views/menu_views.xml',
        # Reports
        'report/commission_report_templates.xml',
        'report/commission_statement_template.xml',
        # Wizards
    ],
    'demo': [
        'data/demo/commission_demo.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'advanced_commission_engine/static/src/scss/commission_dashboard.scss',
            'advanced_commission_engine/static/src/js/commission_dashboard.js',
            'advanced_commission_engine/static/src/js/commission_kpi_card.js',
            'advanced_commission_engine/static/src/xml/commission_dashboard.xml',
            'advanced_commission_engine/static/src/xml/commission_kpi_card.xml',
        ],
        'web.assets_frontend': [
            'advanced_commission_engine/static/src/scss/commission_dashboard.scss',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': True,
    'sequence': 10,
}
