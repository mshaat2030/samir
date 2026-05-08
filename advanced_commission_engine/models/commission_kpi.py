# -*- coding: utf-8 -*-
"""Commission KPI – key performance indicator definitions and values."""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CommissionKPI(models.Model):
    """Defines a KPI metric used in weighted KPI commission plans.

    KPIs have a category, weight, and unit. Values are tracked via CommissionKPIValue.
    """

    _name = 'commission.kpi'
    _description = 'Commission KPI'
    _inherit = ['mail.thread']
    _order = 'category, name'

    name = fields.Char(
        string='KPI Name',
        required=True,
        tracking=True,
    )
    code = fields.Char(
        string='Code',
        required=True,
        index=True,
    )
    category = fields.Selection(
        [
            ('sales', 'Sales'),
            ('finance', 'Finance'),
            ('customer', 'Customer'),
            ('operations', 'Operations'),
            ('hr', 'HR'),
            ('other', 'Other'),
        ],
        string='Category',
        default='sales',
        required=True,
        index=True,
    )
    description = fields.Text(string='Description')
    weight = fields.Float(
        string='Weight (%)',
        default=100.0,
        help='Weight of this KPI in the overall score. All KPIs in a plan should sum to 100.',
    )
    unit = fields.Selection(
        [
            ('currency', 'Currency Amount'),
            ('percent', 'Percentage'),
            ('count', 'Count'),
            ('days', 'Days'),
            ('score', 'Score (0-100)'),
        ],
        string='Unit',
        default='currency',
        required=True,
    )
    higher_is_better = fields.Boolean(
        string='Higher is Better',
        default=True,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        index=True,
    )


    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        'KPI code must be unique per company.',
    )


    @api.constrains('weight')
    def _check_weight(self):
        for kpi in self:
            if not (0 <= kpi.weight <= 100):
                raise ValidationError('KPI weight must be between 0 and 100.')


class CommissionKPIValue(models.Model):
    """Stores actual KPI values for an employee in a target period."""

    _name = 'commission.kpi.value'
    _description = 'Commission KPI Value'
    _order = 'target_id, kpi_id'

    target_id = fields.Many2one(
        'commission.target',
        string='Target',
        required=True,
        ondelete='cascade',
        index=True,
    )
    kpi_id = fields.Many2one(
        'commission.kpi',
        string='KPI',
        required=True,
        index=True,
    )
    employee_id = fields.Many2one(
        related='target_id.employee_id',
        store=True,
        readonly=True,
        index=True,
    )
    period_id = fields.Many2one(
        related='target_id.period_id',
        store=True,
        readonly=True,
        index=True,
    )
    currency_id = fields.Many2one(
        related='target_id.currency_id',
        readonly=True,
    )

    # ── Values ────────────────────────────────────────────────────────────────
    target_value = fields.Float(
        string='Target Value',
        digits=(16, 2),
        required=True,
        default=0.0,
    )
    achieved_value = fields.Float(
        string='Achieved Value',
        digits=(16, 2),
        default=0.0,
    )
    weight = fields.Float(
        related='kpi_id.weight',
        readonly=True,
    )

    # ── Score ─────────────────────────────────────────────────────────────────
    attainment_pct = fields.Float(
        string='Attainment %',
        compute='_compute_attainment',
        store=True,
        digits=(16, 1),
    )
    weighted_score = fields.Float(
        string='Weighted Score',
        compute='_compute_attainment',
        store=True,
        digits=(16, 2),
    )

    _target_kpi_uniq = models.Constraint(
        'UNIQUE(target_id, kpi_id)',
        'Duplicate KPI value for this target.',
    )

    @api.depends('target_value', 'achieved_value', 'weight', 'kpi_id.higher_is_better')
    def _compute_attainment(self):
        for val in self:
            if val.target_value:
                raw = (val.achieved_value / val.target_value) * 100.0
                if not val.kpi_id.higher_is_better:
                    raw = 100.0 - raw
                val.attainment_pct = max(0, min(100, raw))
            else:
                val.attainment_pct = 0.0
            val.weighted_score = val.attainment_pct * val.weight / 100.0
