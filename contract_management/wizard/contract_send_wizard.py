# -*- coding: utf-8 -*-
import base64
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ContractSendWizard(models.TransientModel):
    """
    Wizard: Send Contract by Email.

    Generates the contract PDF on-the-fly and attaches it to the outgoing
    mail, then sends via Odoo's standard mail queue.
    """
    _name = 'contract.send.wizard'
    _description = 'Send Contract by Email'

    # ── Source contract ───────────────────────────────────────────────────────
    contract_id = fields.Many2one(
        comodel_name='contract.contract',
        string='Contract',
        required=True,
        readonly=True,
        ondelete='cascade',
    )

    # ── Recipients ────────────────────────────────────────────────────────────
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Customer',
        related='contract_id.partner_id',
        readonly=True,
    )
    email_to = fields.Char(
        string='To (Email)',
        required=True,
    )
    email_cc = fields.Char(
        string='CC',
        help='Comma-separated email addresses for CC.',
    )

    # ── Message ───────────────────────────────────────────────────────────────
    subject = fields.Char(
        string='Subject',
        required=True,
    )
    body_html = fields.Html(
        string='Message',
        sanitize_attributes=False,
    )
    include_pdf = fields.Boolean(
        string='Attach Contract PDF',
        default=True,
        help='If checked the contract PDF will be generated and attached.',
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Default values
    # ─────────────────────────────────────────────────────────────────────────
    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        contract_id = self.env.context.get('default_contract_id')
        if not contract_id:
            return defaults
        contract = self.env['contract.contract'].browse(contract_id)
        if not contract.exists():
            return defaults

        defaults['contract_id'] = contract.id
        defaults['email_to'] = (
            contract.partner_contact_id.email
            or contract.partner_id.email
            or ''
        )
        defaults['subject'] = _('Contract — %s [%s]') % (
            contract.name, contract.reference
        )
        defaults['body_html'] = self._default_body(contract)
        return defaults

    def _default_body(self, contract):
        company = contract.company_id
        return _("""
<p>Dear %(partner)s,</p>
<p>Please find attached the contract <strong>%(name)s</strong>
(Reference: %(ref)s) for your review and signature.</p>
<p>Should you have any questions, please do not hesitate to contact us.</p>
<br/>
<p>Kind regards,<br/>
<strong>%(company)s</strong></p>
""") % {
            'partner': contract.partner_id.name,
            'name': contract.name,
            'ref': contract.reference,
            'company': company.name,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────────────────
    def action_send(self):
        """Generate the PDF (if requested) and send the email."""
        self.ensure_one()
        contract = self.contract_id

        if not self.email_to:
            raise UserError(_('Please provide at least one recipient email address.'))

        # Build attachment list
        attachments = []
        if self.include_pdf:
            report = self.env.ref('contract_management.action_report_contract')
            pdf_bytes, _ = report._render_qweb_pdf(contract.ids)
            b64 = base64.b64encode(pdf_bytes).decode()
            filename = '%s_%s.pdf' % (
                contract.reference,
                (contract.partner_id.name or 'contract').replace(' ', '_'),
            )
            attachments = [(filename, b64)]

        # Build mail values
        mail_values = {
            'subject': self.subject,
            'body_html': self.body_html or '',
            'email_to': self.email_to,
            'email_cc': self.email_cc or '',
            'email_from': self.env.user.email_formatted or self.env.company.email or '',
            'author_id': self.env.user.partner_id.id,
            'auto_delete': False,
            'attachment_ids': [],
        }

        # Create attachments as ir.attachment records so they appear in chatter
        attachment_ids = []
        for fname, b64_content in attachments:
            attach = self.env['ir.attachment'].create({
                'name': fname,
                'type': 'binary',
                'datas': b64_content,
                'res_model': 'contract.contract',
                'res_id': contract.id,
                'mimetype': 'application/pdf',
            })
            attachment_ids.append(attach.id)

        mail_values['attachment_ids'] = [(6, 0, attachment_ids)]

        # Send the mail
        mail = self.env['mail.mail'].create(mail_values)
        mail.send()

        # Log in chatter
        contract.message_post(
            body=_('Contract sent by email to <b>%s</b>%s.') % (
                self.email_to,
                (' (CC: %s)' % self.email_cc) if self.email_cc else '',
            ),
            attachment_ids=attachment_ids,
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Email Sent'),
                'message': _('Contract email queued for delivery to %s.') % self.email_to,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}
