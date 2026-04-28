# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ContractClause(models.Model):
    """
    A clause instance attached to a specific Contract.
    Created by copying the parent template's clauses; thereafter the two
    records are independent (editing a contract clause does not change
    the template and vice-versa).

    Fixed clauses expose a computed `is_readonly` flag that the form view
    uses to prevent editing the body fields.
    """
    _name = 'contract.clause'
    _description = 'Contract Clause'
    _order = 'sequence, id'

    # ── Parent link ───────────────────────────────────────────────────────────
    contract_id = fields.Many2one(
        comodel_name='contract.contract',
        string='Contract',
        required=True,
        ondelete='cascade',
        index=True,
    )

    # ── Traceability ──────────────────────────────────────────────────────────
    template_clause_id = fields.Many2one(
        comodel_name='contract.template.clause',
        string='Source Clause',
        ondelete='set null',
        readonly=True,
        help='Original template clause from which this instance was generated.',
    )

    # ── Layout ────────────────────────────────────────────────────────────────
    sequence = fields.Integer(string='Sequence', default=10)

    # ── English content ───────────────────────────────────────────────────────
    title = fields.Char(string='Title (EN)', required=True)
    description = fields.Html(
        string='Body (EN)',
        sanitize_attributes=False,
    )

    # ── Arabic content ────────────────────────────────────────────────────────
    title_ar = fields.Char(string='Title (AR)')
    description_ar = fields.Html(
        string='Body (AR)',
        sanitize_attributes=False,
    )

    # ── Behaviour ─────────────────────────────────────────────────────────────
    clause_type = fields.Selection(
        selection=[
            ('fixed', 'Fixed'),
            ('variable', 'Variable'),
        ],
        string='Clause Type',
        required=True,
        default='fixed',
    )
    is_readonly = fields.Boolean(
        compute='_compute_is_readonly',
        string='Read-Only',
        help='True for Fixed clauses; the form view uses this to lock the body fields.',
    )

    # ── Propagated from contract ───────────────────────────────────────────────
    language = fields.Selection(
        related='contract_id.language',
        string='Language',
        store=True,
        readonly=True,
    )
    contract_state = fields.Selection(
        related='contract_id.state',
        string='Contract State',
        store=True,
        readonly=True,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Computed
    # ─────────────────────────────────────────────────────────────────────────
    @api.depends('clause_type')
    def _compute_is_readonly(self):
        for rec in self:
            rec.is_readonly = rec.clause_type == 'fixed'

    # ─────────────────────────────────────────────────────────────────────────
    # Display name
    # ─────────────────────────────────────────────────────────────────────────
    def name_get(self):
        result = []
        for rec in self:
            display = '[%02d] %s' % (rec.sequence, rec.title)
            result.append((rec.id, display))
        return result
