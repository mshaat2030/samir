# -*- coding: utf-8 -*-
{
    'name': 'Advanced Sales Commission (ASC)',
    'version': '19.0.1.0.0',
    'category': 'Sales/Commission',
    'summary': 'Enterprise Sales Commission Engine with multi-model plans, payroll & accounting integration',
    'description': """
        Advanced Sales Commission Engine for Odoo 19 Enterprise.
        Features: Tiered/Fixed/Percentage/Target/Margin commissions, approval workflows,
        payroll integration, accounting journal entries, role-based dashboards, KPI analytics.
    """,
    'author': 'ASC Enterprise',
    'website': 'https://www.example.com',
    'license': 'OEEL-1',
    'depends': [
        'sale_management',
        'sale_team',
        'account',
        'hr',
        'hr_payroll',
        'product',
        'mail',
        'base_setup',
        'web',
        'report_xlsx',
    ],
    'data': [
        # Security
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        # Data
        'data/sequence_data.xml',
        'data/cron_jobs.xml',
        # Views
        'views/commission_plan_views.xml',
        'views/commission_rule_views.xml',
        'views/commission_line_views.xml',
        'views/commission_settlement_views.xml',
        'views/commission_target_views.xml',
        'views/commission_bonus_views.xml',
        'views/dashboard_views.xml',
        'views/res_config_settings_views.xml',
        'views/menu_views.xml',
        # Wizards
        'wizard/commission_simulate_wizard_views.xml',
        'wizard/commission_batch_wizard_views.xml',
        # Reports
        'report/commission_statement_template.xml',
        'report/commission_report_actions.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'advanced_sales_commission/static/src/scss/asc_dashboard.scss',
            'advanced_sales_commission/static/src/js/asc_dashboard.js',
            'advanced_sales_commission/static/src/xml/asc_dashboard.xml',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': True,
    'sequence': 10,
}
