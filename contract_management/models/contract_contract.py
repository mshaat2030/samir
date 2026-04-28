# -*- coding: utf-8 -*-
import base64
import json
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class ContractContract(models.Model):
    """
    Core Contract model.

    Lifecycle:  Draft → Active → Expired | Cancelled
                           ↑_____________|  (reset to Draft)

    Key behaviours:
    - Selecting a template auto-loads its clauses.
    - Fixed clauses are locked; variable clauses are editable.
    - A version snapshot is created on every activation.
    - The contract can be exported as a PDF and attached to a Sale Order.
    - CRM Opportunity and Sale Order links expose smart buttons.
    """
    _name = 'contract.contract'
    _description = 'Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, reference'
    _rec_name = 'name'
    _check_company_auto = True

    # ─────────────────────────────────────────────────────────────────────────
    # Identity
    # ─────────────────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Contract Name',
        required=True,
        tracking=True,
        copy=False,
        help='E.g. "Service Agreement with Acme Corp — Q3 2025"',
    )
    reference = fields.Char(
        string='Reference',
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('New'),
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
        index=True,
    )
    user_id = fields.Many2one(
        comodel_name='res.users',
        string='Responsible',
        default=lambda self: self.env.user,
        tracking=True,
        index=True,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Template & classification (from template, read-only after load)
    # ─────────────────────────────────────────────────────────────────────────
    template_id = fields.Many2one(
        comodel_name='contract.template',
        string='Contract Template',
        required=True,
        tracking=True,
        ondelete='restrict',
        check_company=True,
        help='Selecting a template automatically populates the clause list below.',
    )
    contract_type = fields.Selection(
        related='template_id.contract_type',
        string='Contract Type',
        store=True,
        readonly=True,
    )
    language = fields.Selection(
        selection=[
            ('en', 'English Only'),
            ('bilingual', 'Bilingual (EN + AR)'),
        ],
        related='template_id.language',
        string='Language',
        store=True,
        readonly=True,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Parties
    # ─────────────────────────────────────────────────────────────────────────
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Customer',
        required=True,
        tracking=True,
        ondelete='restrict',
        index=True,
    )
    partner_contact_id = fields.Many2one(
        comodel_name='res.partner',
        string='Customer Contact',
        domain="[('parent_id', '=', partner_id), ('type', 'in', ['contact', 'other'])]",
        tracking=True,
        help='Specific contact person at the customer company.',
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Dates & status
    # ─────────────────────────────────────────────────────────────────────────
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('expired', 'Expired'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        copy=False,
        index=True,
    )
    date_start = fields.Date(
        string='Start Date',
        required=True,
        default=fields.Date.today,
        tracking=True,
    )
    date_end = fields.Date(
        string='End Date',
        tracking=True,
        help='Leave empty for open-ended contracts.',
    )
    signed_date = fields.Date(
        string='Signed Date',
        tracking=True,
    )
    signed_by = fields.Char(
        string='Signed By',
        tracking=True,
        help='Name of the authorised signatory at the customer.',
    )
    is_expired = fields.Boolean(
        compute='_compute_is_expired',
        string='Expired',
        store=True,
        help='Automatically True when End Date has passed and contract is Active.',
    )

    # ─────────────────────────────────────────────────────────────────────────
    # External links
    # ─────────────────────────────────────────────────────────────────────────
    opportunity_id = fields.Many2one(
        comodel_name='crm.lead',
        string='CRM Opportunity',
        tracking=True,
        ondelete='set null',
        domain="[('type', '=', 'opportunity'), ('partner_id', 'child_of', partner_id)]",
        help='Link this contract to an existing CRM opportunity.',
    )
    sale_order_id = fields.Many2one(
        comodel_name='sale.order',
        string='Sales Quotation / Order',
        tracking=True,
        ondelete='set null',
        domain="[('partner_id', 'child_of', partner_id)]",
        help='After confirming, you can export the contract PDF and attach it to this order.',
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Branding
    # ─────────────────────────────────────────────────────────────────────────
    customer_logo = fields.Binary(
        string='Customer Logo',
        attachment=True,
        help='Optional: upload customer logo to display on the cover page alongside the company logo.',
    )
    customer_logo_filename = fields.Char(string='Customer Logo Filename')

    # ─────────────────────────────────────────────────────────────────────────
    # Clauses
    # ─────────────────────────────────────────────────────────────────────────
    clause_ids = fields.One2many(
        comodel_name='contract.clause',
        inverse_name='contract_id',
        string='Contract Clauses',
        copy=True,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Versioning
    # ─────────────────────────────────────────────────────────────────────────
    version_ids = fields.One2many(
        comodel_name='contract.version',
        inverse_name='contract_id',
        string='Version History',
        copy=False,
        readonly=True,
    )
    current_version_number = fields.Integer(
        string='Current Version',
        default=1,
        copy=False,
        readonly=True,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Notes
    # ─────────────────────────────────────────────────────────────────────────
    notes = fields.Html(
        string='Internal Notes',
        sanitize_attributes=False,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Smart-button counts (computed)
    # ─────────────────────────────────────────────────────────────────────────
    clause_count = fields.Integer(compute='_compute_counts', string='Clauses')
    version_count = fields.Integer(compute='_compute_counts', string='Versions')
    attachment_count = fields.Integer(compute='_compute_attachment_count', string='Attachments')

    # ─────────────────────────────────────────────────────────────────────────
    # ORM overrides
    # ─────────────────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('reference', _('New')) == _('New'):
                vals['reference'] = (
                    self.env['ir.sequence'].next_by_code('contract.contract') or _('New')
                )
        return super().create(vals_list)

    # ─────────────────────────────────────────────────────────────────────────
    # onchange
    # ─────────────────────────────────────────────────────────────────────────
    @api.onchange('template_id')
    def _onchange_template_id(self):
        """Auto-populate clauses from the selected template."""
        if not self.template_id:
            return
        self._load_clauses_from_template()

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────
    def _load_clauses_from_template(self):
        """
        Replace all current clauses with fresh copies from the template.
        Called during onchange and can be called programmatically.
        """
        self.ensure_one()
        if not self.template_id:
            return
        # Command 5 = unlink all existing clause lines
        new_lines = [(5, 0, 0)]
        for tc in self.template_id.clause_ids.sorted('sequence'):
            new_lines.append((0, 0, {
                'sequence': tc.sequence,
                'title': tc.title,
                'title_ar': tc.title_ar or '',
                'description': tc.description or '',
                'description_ar': tc.description_ar or '',
                'clause_type': tc.clause_type,
                'template_clause_id': tc.id,
            }))
        self.clause_ids = new_lines

    def _build_clause_snapshot(self):
        """Return a JSON-serialisable list of the current clauses."""
        self.ensure_one()
        snapshot = []
        for clause in self.clause_ids.sorted('sequence'):
            snapshot.append({
                'sequence': clause.sequence,
                'title': clause.title,
                'title_ar': clause.title_ar or '',
                'description': clause.description or '',
                'description_ar': clause.description_ar or '',
                'clause_type': clause.clause_type,
            })
        return json.dumps(snapshot, ensure_ascii=False, indent=2)

    def _create_version_snapshot(self, note=''):
        """Persist a version record with a JSON snapshot of current clauses."""
        self.ensure_one()
        version = self.env['contract.version'].create({
            'contract_id': self.id,
            'version_number': self.current_version_number,
            'notes': note,
            'user_id': self.env.uid,
            'clause_data': self._build_clause_snapshot(),
        })
        self.current_version_number += 1
        return version

    # ─────────────────────────────────────────────────────────────────────────
    # Computed fields
    # ─────────────────────────────────────────────────────────────────────────
    def _compute_counts(self):
        for rec in self:
            rec.clause_count = len(rec.clause_ids)
            rec.version_count = len(rec.version_ids)

    def _compute_attachment_count(self):
        Attach = self.env['ir.attachment']
        for rec in self:
            rec.attachment_count = Attach.search_count([
                ('res_model', '=', self._name),
                ('res_id', '=', rec.id),
            ])

    @api.depends('date_end', 'state')
    def _compute_is_expired(self):
        today = fields.Date.today()
        for rec in self:
            rec.is_expired = bool(
                rec.date_end
                and rec.date_end < today
                and rec.state == 'active'
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Constraints
    # ─────────────────────────────────────────────────────────────────────────
    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_start > rec.date_end:
                raise ValidationError(_('End Date must be after Start Date.'))

    # ─────────────────────────────────────────────────────────────────────────
    # State-transition actions
    # ─────────────────────────────────────────────────────────────────────────
    def action_confirm(self):
        """Draft → Active.  Creates the first version snapshot."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only Draft contracts can be confirmed.'))
            if not rec.clause_ids:
                raise UserError(_('Cannot activate a contract with no clauses.'))
            rec.write({'state': 'active'})
            rec._create_version_snapshot(note=_('Contract activated'))
            rec.message_post(
                body=_('<b>Contract activated</b> and version v1 snapshot saved.')
            )
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == 'cancelled':
                raise UserError(_('This contract is already cancelled.'))
            rec.write({'state': 'cancelled'})
            rec.message_post(body=_('Contract <b>cancelled</b>.'))
        return True

    def action_set_expired(self):
        for rec in self:
            rec.write({'state': 'expired'})
        return True

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ('cancelled', 'expired'):
                raise UserError(_(
                    'Only Cancelled or Expired contracts can be reset to Draft.'
                ))
            rec.write({'state': 'draft'})
            rec.message_post(body=_('Contract reset to <b>Draft</b>.'))
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Manual version snapshot
    # ─────────────────────────────────────────────────────────────────────────
    def action_save_version(self):
        """Manually create a version snapshot at any point."""
        self.ensure_one()
        version = self._create_version_snapshot(note=_('Manual snapshot'))
        self.message_post(
            body=_('Version <b>v%s</b> snapshot saved manually.') % version.version_number
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Version Saved'),
                'message': _('Version v%s has been saved.') % version.version_number,
                'type': 'success',
                'sticky': False,
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Smart-button navigation actions
    # ─────────────────────────────────────────────────────────────────────────
    def action_view_opportunity(self):
        self.ensure_one()
        if not self.opportunity_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Opportunity'),
            'res_model': 'crm.lead',
            'view_mode': 'form',
            'res_id': self.opportunity_id.id,
        }

    def action_view_sale_order(self):
        self.ensure_one()
        if not self.sale_order_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sales Order'),
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.sale_order_id.id,
        }

    def action_view_versions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Version History — %s') % self.reference,
            'res_model': 'contract.version',
            'view_mode': 'list,form',
            'domain': [('contract_id', '=', self.id)],
            'context': {'default_contract_id': self.id},
        }

    def action_view_attachments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Attachments'),
            'res_model': 'ir.attachment',
            'view_mode': 'list,kanban,form',
            'domain': [('res_model', '=', self._name), ('res_id', '=', self.id)],
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # PDF actions
    # ─────────────────────────────────────────────────────────────────────────
    def action_export_pdf(self):
        """Preview / print the contract PDF."""
        self.ensure_one()
        return self.env.ref(
            'contract_management.action_report_contract'
        ).report_action(self)

    def action_attach_to_quotation(self):
        """
        Generate the contract PDF and attach it to the linked Sale Order.
        The PDF is stored as an ir.attachment on the sale.order record.
        """
        self.ensure_one()
        if not self.sale_order_id:
            raise UserError(_(
                'Please link a Sales Quotation or Order to this contract '
                'before attaching the PDF.'
            ))
        report = self.env.ref('contract_management.action_report_contract')
        pdf_bytes, _ = report._render_qweb_pdf(self.ids)
        b64 = base64.b64encode(pdf_bytes)
        filename = '%s_%s.pdf' % (self.reference, self.partner_id.name or 'contract')
        filename = filename.replace('/', '_').replace(' ', '_')

        # Remove any previous attachment with the same name
        old = self.env['ir.attachment'].search([
            ('res_model', '=', 'sale.order'),
            ('res_id', '=', self.sale_order_id.id),
            ('name', '=', filename),
        ])
        old.unlink()

        self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': b64,
            'res_model': 'sale.order',
            'res_id': self.sale_order_id.id,
            'mimetype': 'application/pdf',
            'description': _('Contract PDF attached from %s') % self.reference,
        })

        self.message_post(
            body=_('Contract PDF attached to <a href="#" data-oe-model="sale.order" '
                   'data-oe-id="%d">%s</a>.') % (
                self.sale_order_id.id, self.sale_order_id.name
            )
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('PDF Attached'),
                'message': _('Contract PDF attached to %s.') % self.sale_order_id.name,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_send_by_email(self):
        """Open the send-by-email wizard."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Contract by Email'),
            'res_model': 'contract.send.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_contract_id': self.id},
        }
