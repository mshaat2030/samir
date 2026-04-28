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
        translate=False,
        help='Required for English and Bilingual templates.',
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
    @api.constrains('title', 'title_ar', 'template_id')
    def _check_language_titles(self):
        for rec in self:
            lang = rec.template_id.language
            if lang in ('en', 'bilingual') and not rec.title:
                raise ValidationError(_(
                    'An English title is required for English and Bilingual templates. '
                    'Please fill in the Title (EN) field.'
                ))
            if lang in ('ar', 'bilingual') and not rec.title_ar:
                raise ValidationError(_(
                    'An Arabic title is required for Arabic and Bilingual templates. '
                    'Please fill in the Title (AR) field.'
                ))

    # ─────────────────────────────────────────────────────────────────────────
    # Display name
    # ─────────────────────────────────────────────────────────────────────────
    def name_get(self):
        result = []
        for rec in self:
            label = rec.title or rec.title_ar or _('Untitled')
            display = '[%s] %s' % (rec.sequence, label)
            result.append((rec.id, display))
        return result
