# -*- coding: utf-8 -*-
{
    'name': 'Contract Management',
    'version': '19.0.1.0.0',
    'category': 'Sales/Contracts',
    'summary': 'Professional contract lifecycle management with templates, clauses, CRM & Sales integration',
    'description': """
Contract Management
===================
A fully featured contract management module for Odoo 19 Enterprise.

Key Features Samir:
- Contract Templates with reusable clause libraries
- Fixed (read-only) and Variable (editable) clause types
- Bilingual support: English + Arabic (RTL) rendering
- CRM Opportunity & Sales Quotation integration
- Professional QWeb PDF with custom cover page, header & footer
- Company and customer logo on cover
- Contract versioning & history
- Digital signature readiness
- Smart buttons for CRM, Sales, Attachments, Versions
- Role-based access control (User / Manager / Admin)
    """,
    'author': 'Contract Management Module',
    'website': 'https://odoo.sh',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'sale_management',
        'crm',
        'web',
        'account',
    ],
    'data': [
        # Security — always first
        'security/contract_security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/contract_data.xml',
        # Views
        'views/contract_menu.xml',
        'views/contract_template_views.xml',
        'views/contract_views.xml',
        'views/res_partner_views.xml',
        # Reports
        'report/contract_report.xml',
        'report/contract_report_template.xml',
        # Wizards
        'wizard/contract_send_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'contract_management/static/src/scss/contract_style.scss',
        ],
    },
    'images': ['static/description/icon.png'],
    'installable': True,
    'auto_install': False,
    'application': True,
}
