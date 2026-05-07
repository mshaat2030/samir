# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class CommissionTarget(models.Model):
    _name = 'commission.target'
    _description = 'Commission Target'
    _inherit = ['mail.thread', 'commission.mixin']
    _order = 'period_id desc, employee_id'

    name = fields.Char(string='Target Name', compute='_compute_name', store=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, index=True,
    )
    period_id = fields.Many2one(
        'commission.period', string='Period',
        required=True, index=True,
    )
    plan_id = fields.Many2one(
        'commission.plan', string='Commission Plan',
        required=True, index=True,
    )
    department_id = fields.Many2one(
        related='employee_id.department_id', store=True
    )

    # ── Target Values ─────────────────────────────────────────────────────────
    target_type = fields.Selection([
        ('revenue', 'Revenue'),
        ('quantity', 'Quantity'),
        ('margin', 'Margin'),
        ('new_customers', 'New Customers'),
        ('renewals', 'Renewals'),
        ('calls', 'Calls Made'),
        ('demos', 'Demos Given'),
        ('custom', 'Custom'),
    ], string='Target Type', required=True, default='revenue')

    target_amount = fields.Monetary(
        string='Target Amount',
        currency_field='currency_id',
    )
    target_quantity = fields.Float(string='Target Quantity', digits=(10, 2))
    achieved_amount = fields.Monetary(
        string='Achieved Amount',
        currency_field='currency_id',
        compute='_compute_achieved',
        store=True,
    )
    achieved_quantity = fields.Float(
        string='Achieved Quantity',
        compute='_compute_achieved',
        store=True,
    )
    achievement_percent = fields.Float(
        string='Achievement %',
        compute='_compute_achievement_percent',
        store=True,
        digits=(5, 2),
    )

    # ── Thresholds ────────────────────────────────────────────────────────────
    threshold_type = fields.Selection([
        ('none', 'No Threshold'),
        ('minimum', 'Minimum (below = no commission)'),
        ('quota', 'Quota-Based'),
    ], default='none', string='Threshold Type')
    minimum_threshold = fields.Float(
        string='Minimum Threshold (%)', default=0.0
    )
    quota_tiers = fields.Text(
        string='Quota Tiers (JSON)',
        help='JSON array: [{"from":0,"to":80,"rate":0.5},{"from":80,"to":100,"rate":1.0},...]',
    )

    # ── Progress ──────────────────────────────────────────────────────────────
    progress_bar_value = fields.Float(
        string='Progress', compute='_compute_achievement_percent', store=True
    )
    color = fields.Integer(string='Color', compute='_compute_color')
    status_label = fields.Char(string='Status Label', compute='_compute_color')

    # ── Notes ─────────────────────────────────────────────────────────────────
    note = fields.Text(string='Notes')

    _employee_period_plan_uniq = models.Constraint(
        'UNIQUE(employee_id, period_id, plan_id, company_id)',
        'A target already exists for this employee/period/plan combination.',
    )

    @api.depends('employee_id', 'period_id', 'target_type')
    def _compute_name(self):
        for t in self:
            employee = t.employee_id.name or ''
            period = t.period_id.name or ''
            target_type = dict(
                t._fields['target_type'].selection
            ).get(t.target_type, '')
            t.name = '%s / %s / %s' % (employee, period, target_type)

    @api.depends('employee_id', 'period_id', 'target_type', 'plan_id')
    def _compute_achieved(self):
        for target in self:
            if not target.employee_id or not target.period_id:
                target.achieved_amount = 0.0
                target.achieved_quantity = 0.0
                continue
            lines = self.env['commission.line'].search([
                ('employee_id', '=', target.employee_id.id),
                ('period_id', '=', target.period_id.id),
                ('plan_id', '=', target.plan_id.id),
                ('state', '!=', 'cancelled'),
                ('line_type', '=', 'commission'),
            ])
            target.achieved_amount = sum(lines.mapped('base_amount'))
            target.achieved_quantity = len(lines)

    @api.depends('target_amount', 'achieved_amount', 'target_quantity', 'achieved_quantity')
    def _compute_achievement_percent(self):
        for t in self:
            if t.target_type in ('revenue', 'margin'):
                if t.target_amount > 0:
                    t.achievement_percent = min(
                        (t.achieved_amount / t.target_amount) * 100, 999.99
                    )
                else:
                    t.achievement_percent = 0.0
            else:
                if t.target_quantity > 0:
                    t.achievement_percent = min(
                        (t.achieved_quantity / t.target_quantity) * 100, 999.99
                    )
                else:
                    t.achievement_percent = 0.0
            t.progress_bar_value = min(t.achievement_percent, 100.0)

    @api.depends('achievement_percent')
    def _compute_color(self):
        for t in self:
            if t.achievement_percent >= 100:
                t.color = 10  # green
                t.status_label = _('Target Met')
            elif t.achievement_percent >= 75:
                t.color = 3   # yellow
                t.status_label = _('On Track')
            elif t.achievement_percent >= 50:
                t.color = 2   # orange
                t.status_label = _('Behind')
            else:
                t.color = 1   # red
                t.status_label = _('At Risk')

    @api.constrains('target_amount', 'target_quantity')
    def _check_target_values(self):
        for t in self:
            if t.target_type in ('revenue', 'margin') and t.target_amount < 0:
                raise ValidationError(_('Target amount cannot be negative.'))
            if t.target_type not in ('revenue', 'margin') and t.target_quantity < 0:
                raise ValidationError(_('Target quantity cannot be negative.'))

    def get_multiplier(self):
        """
        Return commission multiplier based on achievement vs quota tiers.
        Returns 1.0 if no quota configuration.
        """
        self.ensure_one()
        if self.threshold_type == 'minimum':
            if self.achievement_percent < self.minimum_threshold:
                return 0.0
        if self.threshold_type == 'quota' and self.quota_tiers:
            import json
            try:
                tiers = json.loads(self.quota_tiers)
                for tier in tiers:
                    from_pct = tier.get('from', 0)
                    to_pct = tier.get('to', 0)
                    rate = tier.get('rate', 1.0)
                    if from_pct <= self.achievement_percent < (to_pct or float('inf')):
                        return rate
            except (json.JSONDecodeError, KeyError):
                pass
        return 1.0
