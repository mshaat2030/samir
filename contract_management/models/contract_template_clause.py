# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ContractTemplateClause(models.Model):
    """
    A single clause definition belonging to a Contract Template.
    Clauses are ordered by `sequence` and copied verbatim into new contracts.
    clause_type controls whether the clause body can be edited per-contract:
      - 'fixed'    → body is read-only on the contract instance
      - 'variable' → the contract owner may customise the body
    """
    _name = 'contract.template.clause'
    _description = 'Contract Template Clause'
    _order = 'sequence, id'

    # ── Parent link ───────────────────────────────────────────────────────────
    template_id = fields.Many2one(
        comodel_name='contract.template',
        string='Template',
        required=True,
        ondelete='cascade',
        index=True,
    )

    # ── Layout ────────────────────────────────────────────────────────────────
    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='Lower numbers appear first.',
    )

    # ── English content ───────────────────────────────────────────────────────
    title = fields.Char(
        string='Title (EN)',
        required=True,
        translate=False,
    )
    description = fields.Html(
        string='Body (EN)',
        sanitize_attributes=False,
        translate=False,
    )

    # ── Arabic content (bilingual templates) ─────────────────────────────────
    title_ar = fields.Char(
        string='Title (AR)',
        translate=False,
        help='Required when the template language is set to Bilingual.',
    )
    description_ar = fields.Html(
        string='Body (AR)',
        sanitize_attributes=False,
        translate=False,
        help='Arabic body text; rendered right-to-left in the PDF.',
    )

    # ── Behaviour ─────────────────────────────────────────────────────────────
    clause_type = fields.Selection(
        selection=[
            ('fixed', 'Fixed — read-only on contracts'),
            ('variable', 'Variable — editable on contracts'),
        ],
        string='Clause Type',
        required=True,
        default='fixed',
        help='Fixed clauses protect standard legal language from accidental edits. '
             'Variable clauses can be tailored for each customer.',
    )

    # ── Propagated from template ───────────────────────────────────────────────
    language = fields.Selection(
        related='template_id.language',
        string='Language',
        store=True,
        readonly=True,
    )

    active = fields.Boolean(default=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Constraints
    # ─────────────────────────────────────────────────────────────────────────
    @api.constrains('title_ar', 'template_id')
    def _check_bilingual_arabic(self):
        for rec in self:
            if rec.template_id.language == 'bilingual' and not rec.title_ar:
                raise ValidationError(_(
                    'Clause "%s" is missing an Arabic title. '
                    'All clauses in a bilingual template must have an Arabic title.'
                ) % rec.title)

    # ─────────────────────────────────────────────────────────────────────────
    # Display name
    # ─────────────────────────────────────────────────────────────────────────
    def name_get(self):
        result = []
        for rec in self:
            display = '[%s] %s' % (rec.sequence, rec.title)
            result.append((rec.id, display))
        return result
