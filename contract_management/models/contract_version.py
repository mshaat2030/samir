# -*- coding: utf-8 -*-
import json
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ContractVersion(models.Model):
    """
    Immutable snapshot of a contract's clauses at a given point in time.
    Versions are created automatically on activation and can be created
    manually by managers.  They can be restored (re-applied to the contract)
    only while the contract is in Draft state.
    """
    _name = 'contract.version'
    _description = 'Contract Version'
    _order = 'version_number desc'
    _rec_name = 'display_name'

    # ── Parent ────────────────────────────────────────────────────────────────
    contract_id = fields.Many2one(
        comodel_name='contract.contract',
        string='Contract',
        required=True,
        ondelete='cascade',
        index=True,
        readonly=True,
    )

    # ── Identity ──────────────────────────────────────────────────────────────
    version_number = fields.Integer(
        string='Version #',
        required=True,
        readonly=True,
    )
    display_name = fields.Char(
        compute='_compute_display_name',
        string='Name',
        store=True,
    )

    # ── Audit ─────────────────────────────────────────────────────────────────
    create_date = fields.Datetime(
        string='Created On',
        readonly=True,
    )
    user_id = fields.Many2one(
        comodel_name='res.users',
        string='Created By',
        default=lambda self: self.env.user,
        readonly=True,
    )
    notes = fields.Char(
        string='Version Notes',
        help='What changed in this version.',
    )

    # ── Snapshot data ─────────────────────────────────────────────────────────
    clause_data = fields.Text(
        string='Clause Snapshot (JSON)',
        readonly=True,
        help='A JSON array capturing all clause titles and bodies at this version.',
    )
    clause_count = fields.Integer(
        compute='_compute_clause_count',
        string='Clause Count',
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Computed
    # ─────────────────────────────────────────────────────────────────────────
    @api.depends('contract_id', 'version_number')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = 'v%s — %s' % (rec.version_number, rec.contract_id.reference or '')

    def _compute_clause_count(self):
        for rec in self:
            try:
                data = json.loads(rec.clause_data or '[]')
                rec.clause_count = len(data)
            except (json.JSONDecodeError, TypeError):
                rec.clause_count = 0

    # ─────────────────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────────────────
    def action_restore_version(self):
        """
        Re-apply this version's clause snapshot to the parent contract.
        Only allowed when the contract is in Draft state to prevent accidental
        overwriting of an active, legally-binding contract.
        """
        self.ensure_one()
        contract = self.contract_id
        if contract.state != 'draft':
            raise UserError(_(
                'You can only restore a version while the contract is in Draft. '
                'Please reset "%s" to Draft first.'
            ) % contract.name)

        try:
            clause_data = json.loads(self.clause_data or '[]')
        except (json.JSONDecodeError, TypeError):
            raise UserError(_('Version data is corrupted and cannot be restored.'))

        # Wipe current clauses and rebuild from snapshot
        contract.clause_ids.unlink()
        ClauseModel = self.env['contract.clause']
        for i, clause in enumerate(clause_data, start=1):
            ClauseModel.create({
                'contract_id': contract.id,
                'sequence': clause.get('sequence', i * 10),
                'title': clause.get('title', _('Untitled')),
                'title_ar': clause.get('title_ar', ''),
                'description': clause.get('description', ''),
                'description_ar': clause.get('description_ar', ''),
                'clause_type': clause.get('clause_type', 'fixed'),
            })

        # Log the restore event
        contract.message_post(
            body=_('Contract restored to <b>version %s</b> by %s.') % (
                self.version_number, self.env.user.name
            )
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Version Restored'),
                'message': _('Contract restored to version %s successfully.') % self.version_number,
                'sticky': False,
                'type': 'success',
            },
        }

    def action_preview_version(self):
        """Open a read-only dialog showing the clause snapshot for this version."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Version %s Preview') % self.version_number,
            'res_model': 'contract.version',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
