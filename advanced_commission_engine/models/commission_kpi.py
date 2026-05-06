# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class CommissionKpi(models.Model):
    _name = 'commission.kpi'
    _description = 'Commission KPI'
    _inherit = ['commission.mixin']
    _order = 'sequence, name'

    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan',
        required=True, ondelete='cascade', index=True,
    )
    name = fields.Char(string='KPI Name', required=True)
    code = fields.Char(string='KPI Code', required=True)
    sequence = fields.Integer(default=10)
    description = fields.Text(string='Description')

    kpi_type = fields.Selection([
        ('revenue', 'Revenue Achievement'),
        ('quantity', 'Units Sold'),
        ('new_customers', 'New Customers Acquired'),
        ('retention', 'Customer Retention Rate'),
        ('satisfaction', 'Customer Satisfaction (CSAT)'),
        ('activity', 'Activity Count (Calls/Meetings)'),
        ('margin', 'Margin Achievement'),
        ('cross_sell', 'Cross-Sell/Upsell Rate'),
        ('custom', 'Custom Metric'),
    ], string='KPI Type', required=True, default='revenue')

    weight = fields.Float(
        string='Weight (%)',
        default=100.0,
        digits=(5, 2),
        help='Weight in weighted average KPI aggregation',
    )

    # ── Target Values ─────────────────────────────────────────────────────────
    target_value = fields.Float(string='Target Value', required=True, default=100.0)
    min_value = fields.Float(
        string='Minimum Value',
        help='Below this value, KPI contributes 0%',
    )
    max_value = fields.Float(
        string='Maximum Value (Cap)',
        help='Achievement capped at this value',
    )
    unit = fields.Char(string='Unit', default='%')

    # ── Measurement ───────────────────────────────────────────────────────────
    measurement_method = fields.Selection([
        ('automatic', 'Automatic (from Odoo data)'),
        ('manual', 'Manual Entry'),
        ('formula', 'Formula'),
    ], string='Measurement Method', default='automatic')

    auto_source = fields.Selection([
        ('sale_orders', 'Confirmed Sale Orders'),
        ('invoices', 'Validated Invoices'),
        ('payments', 'Collected Payments'),
        ('crm_leads', 'CRM Leads Won'),
        ('crm_activities', 'CRM Activities'),
        ('pos_orders', 'POS Orders'),
    ], string='Auto Source', default='invoices')

    formula = fields.Text(
        string='Measurement Formula',
        help='Python expression returning numeric achievement. Variables: employee, period, env',
    )

    # ── Scale/Scoring ─────────────────────────────────────────────────────────
    scale_type = fields.Selection([
        ('linear', 'Linear'),
        ('stepped', 'Stepped'),
        ('binary', 'Binary (met/not met)'),
    ], string='Scoring Scale', default='linear')

    payout_cap = fields.Float(
        string='Maximum Payout (%)',
        default=150.0,
        help='Maximum KPI achievement % that earns commission (150% = overachievement capped)',
    )

    _code_plan_uniq = models.Constraint(
        'UNIQUE(code, plan_id)',
        'KPI code must be unique within a plan.',
    )

    @api.constrains('weight')
    def _check_weight(self):
        for kpi in self:
            if not (0 <= kpi.weight <= 100):
                raise ValidationError(
                    _('KPI weight must be between 0 and 100.')
                )

    def get_achievement(self, employee):
        """
        Return achievement % for this KPI for a given employee.
        Measured against the current period.
        """
        self.ensure_one()
        if self.measurement_method == 'manual':
            # Manual entries tracked via commission.target
            target = self.env['commission.target'].search([
                ('employee_id', '=', employee.id),
                ('plan_id', '=', self.plan_id.id),
            ], limit=1)
            if target:
                return min(target.achievement_percent, self.payout_cap)
            return 0.0
        elif self.measurement_method == 'formula' and self.formula:
            from ..services.formula_engine import FormulaEngine
            engine = FormulaEngine(self.env)
            try:
                result = engine.evaluate(self.formula, {
                    'employee': employee,
                    'env': self.env,
                })
                return min(float(result), self.payout_cap)
            except Exception as e:
                _logger.error('KPI formula error: %s', e)
                return 0.0
        elif self.measurement_method == 'automatic':
            return self._auto_measure(employee)
        return 0.0

    def _auto_measure(self, employee):
        """Auto-measure KPI based on configured source."""
        self.ensure_one()
        # Default: return 100% if no specific logic
        if self.auto_source == 'invoices':
            domain = [
                ('invoice_user_id', '=', employee.user_id.id),
                ('move_type', 'in', ['out_invoice', 'out_refund']),
                ('state', '=', 'posted'),
                ('company_id', '=', self.company_id.id),
            ]
            total = sum(
                self.env['account.move'].search(domain).mapped('amount_untaxed')
            )
            if self.target_value > 0:
                return min((total / self.target_value) * 100, self.payout_cap)
        elif self.auto_source == 'sale_orders':
            domain = [
                ('user_id', '=', employee.user_id.id),
                ('state', 'in', ['sale', 'done']),
                ('company_id', '=', self.company_id.id),
            ]
            total = sum(
                self.env['sale.order'].search(domain).mapped('amount_untaxed')
            )
            if self.target_value > 0:
                return min((total / self.target_value) * 100, self.payout_cap)
        return 0.0
