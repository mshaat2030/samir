# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ContractTemplate(models.Model):
    """
    Contract Template — the master blueprint for generating contracts.
    Each template defines the language, contract type, and an ordered list
    of clauses (fixed or variable) that are copied into new contracts.
    """
    _name = 'contract.template'
    _description = 'Contract Template'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _rec_name = 'name'

    # ── Identity ─────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Template Name',
        required=True,
        tracking=True,
        help='Descriptive name of this template (e.g. NDA, Service Agreement)',
    )
    reference = fields.Char(
        string='Reference',
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('New'),
    )
    active = fields.Boolean(
        default=True,
        tracking=True,
        help='Archived templates are hidden from the selection list.',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    user_id = fields.Many2one(
        comodel_name='res.users',
        string='Responsible',
        default=lambda self: self.env.user,
        tracking=True,
    )

    # ── Classification ────────────────────────────────────────────────────────
    language = fields.Selection(
        selection=[
            ('en', 'English Only'),
            ('bilingual', 'Bilingual (English + Arabic)'),
        ],
        string='Language',
        required=True,
        default='en',
        tracking=True,
        help='Controls how the PDF report renders. '
             'Bilingual templates display English and Arabic side-by-side.',
    )
    contract_type = fields.Selection(
        selection=[
            ('nda', 'Non-Disclosure Agreement (NDA)'),
            ('service', 'Service Agreement'),
            ('implementation', 'Implementation Contract'),
            ('maintenance', 'Maintenance & Support Contract'),
            ('consulting', 'Consulting Agreement'),
            ('partnership', 'Partnership Agreement'),
            ('supply', 'Supply Agreement'),
            ('employment', 'Employment Contract'),
            ('other', 'Other'),
        ],
        string='Contract Type',
        required=True,
        default='other',
        tracking=True,
    )

    # ── Content ───────────────────────────────────────────────────────────────
    description = fields.Html(
        string='Description / Purpose',
        sanitize_attributes=False,
        help="Brief description of this template's intended use.",
    )
    internal_note = fields.Text(
        string='Internal Notes',
        help='Private notes visible only to the contract team.',
    )

    # ── Clauses ───────────────────────────────────────────────────────────────
    clause_ids = fields.One2many(
        comodel_name='contract.template.clause',
        inverse_name='template_id',
        string='Clauses',
        copy=True,
    )

    # ── Computed stats ────────────────────────────────────────────────────────
    clause_count = fields.Integer(
        compute='_compute_clause_count',
        string='Clauses',
    )
    contract_count = fields.Integer(
        compute='_compute_contract_count',
        string='Contracts',
    )
    fixed_clause_count = fields.Integer(
        compute='_compute_clause_count',
        string='Fixed Clauses',
    )
    variable_clause_count = fields.Integer(
        compute='_compute_clause_count',
        string='Variable Clauses',
    )

    # ─────────────────────────────────────────────────────────────────────────
    # ORM overrides
    # ─────────────────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', _('New')) == _('New'):
                vals['reference'] = (
                    self.env['ir.sequence'].next_by_code('contract.template') or _('New')
                )
        return super().create(vals_list)

    # ─────────────────────────────────────────────────────────────────────────
    # Computed fields
    # ─────────────────────────────────────────────────────────────────────────
    def _compute_clause_count(self):
        for rec in self:
            fixed = rec.clause_ids.filtered(lambda c: c.clause_type == 'fixed')
            variable = rec.clause_ids.filtered(lambda c: c.clause_type == 'variable')
            rec.clause_count = len(rec.clause_ids)
            rec.fixed_clause_count = len(fixed)
            rec.variable_clause_count = len(variable)

    def _compute_contract_count(self):
        Contract = self.env['contract.contract']
        for rec in self:
            rec.contract_count = Contract.search_count([('template_id', '=', rec.id)])

    # ─────────────────────────────────────────────────────────────────────────
    # Constraints
    # ─────────────────────────────────────────────────────────────────────────
    @api.constrains('clause_ids', 'language')
    def _check_bilingual_clauses(self):
        for rec in self:
            if rec.language == 'bilingual':
                missing = rec.clause_ids.filtered(lambda c: not c.title_ar)
                if missing:
                    raise ValidationError(_(
                        'Bilingual templates require an Arabic title for every clause. '
                        'Missing Arabic title on: %s'
                    ) % ', '.join(missing.mapped('title')))

    # ─────────────────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────────────────
    def action_view_contracts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contracts — %s') % self.name,
            'res_model': 'contract.contract',
            'view_mode': 'list,form,kanban',
            'domain': [('template_id', '=', self.id)],
            'context': {
                'default_template_id': self.id,
                'search_default_template_id': self.id,
            },
        }

    def action_duplicate_template(self):
        self.ensure_one()
        new = self.copy({'name': _('%s (Copy)') % self.name, 'reference': _('New')})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contract Template'),
            'res_model': 'contract.template',
            'view_mode': 'form',
            'res_id': new.id,
        }

    def action_create_contract(self):
        """Shortcut: open new contract form pre-filled with this template."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Contract'),
            'res_model': 'contract.contract',
            'view_mode': 'form',
            'context': {'default_template_id': self.id},
        }
