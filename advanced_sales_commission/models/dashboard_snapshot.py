# -*- coding: utf-8 -*-
"""
asc.dashboard.snapshot — Periodic KPI cache for dashboards.
Written by cron jobs to avoid on-the-fly aggregation overhead.
"""
from odoo import models, fields, api
import json


class AscDashboardSnapshot(models.Model):
    _name = 'asc.dashboard.snapshot'
    _description = 'Dashboard KPI Snapshot'
    _order = 'snapshot_date desc'

    name = fields.Char(string='Snapshot Name', required=True)
    snapshot_date = fields.Date(string='Snapshot Date', required=True, default=fields.Date.today, index=True)
    snapshot_type = fields.Selection([
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ], string='Type', required=True, default='daily', index=True)
    role = fields.Selection([
        ('salesperson', 'Salesperson'),
        ('manager', 'Manager'),
        ('finance', 'Finance'),
        ('hr', 'HR'),
        ('executive', 'Executive'),
    ], string='Role', required=True, index=True)

    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    user_id = fields.Many2one(
        'res.users', string='User',
        index=True, help='Null = company-wide snapshot.',
    )

    # ── KPI Data ──────────────────────────────────────────────────────────────
    # Stored as JSON for flexibility
    kpi_data = fields.Text(string='KPI Data (JSON)', default='{}')

    # Quick-access denormalized fields for fast dashboard queries
    total_commission = fields.Float(string='Total Commission', digits=(16, 2))
    total_revenue = fields.Float(string='Total Revenue', digits=(16, 2))
    commission_count = fields.Integer(string='Commission Count')
    pending_approval = fields.Integer(string='Pending Approval')
    achievement_pct = fields.Float(string='Achievement %', digits=(16, 2))
    top_earner = fields.Char(string='Top Earner')

    def get_kpi(self, key, default=None):
        try:
            data = json.loads(self.kpi_data or '{}')
            return data.get(key, default)
        except (json.JSONDecodeError, TypeError):
            return default

    def set_kpi(self, key, value):
        try:
            data = json.loads(self.kpi_data or '{}')
        except (json.JSONDecodeError, TypeError):
            data = {}
        data[key] = value
        self.kpi_data = json.dumps(data)

    @api.model
    def build_snapshot(self, role, snapshot_type='daily', user=None):
        """
        Called by cron — builds and stores a snapshot for the given role.
        Uses read_group for efficiency.
        """
        company = self.env.company
        today = fields.Date.today()
        month = today.month
        year = today.year

        domain = [
            ('company_id', '=', company.id),
            ('period_year', '=', year),
            ('period_month', '=', month),
            ('is_simulation', '=', False),
            ('state', 'not in', ['draft', 'cancelled']),
        ]
        if user:
            domain.append(('salesperson_id', '=', user.id))

        # Single read_group for main KPIs
        result = self.env['asc.commission.line'].read_group(
            domain,
            ['net_commission:sum', 'base_amount:sum', 'id:count'],
            [],
        )
        row = result[0] if result else {}

        pending = self.env['asc.commission.line'].search_count([
            ('company_id', '=', company.id),
            ('state', '=', 'submitted'),
            ('is_simulation', '=', False),
        ])

        # Top earner
        top = self.env['asc.commission.line'].read_group(
            domain + [('state', 'in', ['approved', 'paid'])],
            ['salesperson_id', 'net_commission:sum'],
            ['salesperson_id'],
            orderby='net_commission desc',
            limit=1,
        )
        top_name = top[0]['salesperson_id'][1] if top else ''

        vals = {
            'name': f'{role.title()} Snapshot {today}',
            'snapshot_date': today,
            'snapshot_type': snapshot_type,
            'role': role,
            'company_id': company.id,
            'user_id': user.id if user else False,
            'total_commission': row.get('net_commission', 0.0),
            'total_revenue': row.get('base_amount', 0.0),
            'commission_count': row.get('id_count', 0),
            'pending_approval': pending,
            'top_earner': top_name,
        }
        return self.create(vals)

    def _auto_init(self):
        res = super()._auto_init()
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS asc_dashboard_snapshot_role_date_idx
            ON asc_dashboard_snapshot (role, snapshot_date, company_id);
        """)
        return res
