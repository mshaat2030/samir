# -*- coding: utf-8 -*-
"""Commission Formula model – reusable formula definitions for the dynamic formula engine."""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CommissionFormula(models.Model):
    """Defines reusable Python/expression formulas for commission calculations.

    Formulas are evaluated in a sandboxed context by :class:`services.formula_engine.FormulaEngine`.
    """

    _name = 'commission.formula'
    _description = 'Commission Formula'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _rec_name = 'name'

    name = fields.Char(
        string='Formula Name',
        required=True,
        tracking=True,
    )
    code = fields.Char(
        string='Technical Code',
        required=True,
        copy=False,
        tracking=True,
        help='Unique technical identifier used to reference this formula.',
    )
    sequence_code = fields.Char(
        string='Reference',
        default=lambda self: self.env['ir.sequence'].next_by_code('commission.formula'),
        readonly=True,
        copy=False,
    )
    formula_type = fields.Selection(
        [
            ('python', 'Python Expression'),
            ('simple', 'Simple Expression'),
        ],
        string='Formula Type',
        required=True,
        default='python',
        tracking=True,
    )
    formula_code = fields.Text(
        string='Formula Code',
        required=True,
        help=(
            'Python code evaluated in a sandboxed context.\n'
            'Available variables:\n'
            '  base_amount  – base amount for calculation\n'
            '  rate         – commission rate (from rule)\n'
            '  employee     – employee record (browse)\n'
            '  period       – commission period record\n'
            '  settlement   – settlement record\n'
            '  revenue      – total revenue in period\n'
            '  profit       – total profit in period\n'
            '  margin_pct   – margin percentage\n'
            '  target       – target amount\n'
            '  achieved     – achieved amount\n'
            '  attainment   – achievement rate (0–1)\n'
            '  result       – set this variable to the commission amount'
        ),
    )
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        index=True,
    )


    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        'Formula code must be unique per company.',
    )


    @api.constrains('formula_code')
    def _check_formula_syntax(self):
        """Validate Python syntax of formula code."""
        for rec in self:
            if rec.formula_type == 'python' and rec.formula_code:
                try:
                    compile(rec.formula_code, '<formula>', 'exec')
                except SyntaxError as e:
                    raise ValidationError(
                        f"Formula '{rec.name}' has a syntax error:\n{e}"
                    )

    def action_test_formula(self):
        """Open wizard to test the formula with sample values."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Test Formula: {self.name}',
            'res_model': 'wizard.commission.simulator',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_formula_id': self.id},
        }
