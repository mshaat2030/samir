# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CommissionMixin(models.AbstractModel):
    """
    Mixin providing common commission functionality:
    - currency handling
    - amount computation helpers
    - audit trail
    - company isolation
    """
    _name = 'commission.mixin'
    _description = 'Commission Mixin'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
        store=True,
        readonly=True,
    )
    active = fields.Boolean(default=True, index=True)

    def _get_company_currency(self):
        """Return company currency for conversion."""
        return self.company_id.currency_id or self.env.company.currency_id

    def _convert_amount(self, amount, from_currency, to_currency=None, date=None):
        """
        Convert amount between currencies.
        Falls back to company currency if to_currency not provided.
        """
        if not to_currency:
            to_currency = self._get_company_currency()
        if not from_currency or from_currency == to_currency:
            return amount
        if not date:
            date = fields.Date.today()
        return from_currency._convert(
            amount, to_currency, self.company_id, date
        )

    def _log_commission_event(self, event_type, details=None):
        """Log commission events for audit trail."""
        _logger.info(
            'Commission Event [%s] on %s(%s): %s',
            event_type,
            self._name,
            self.id,
            details or '',
        )

    @api.model
    def _get_active_records(self, domain=None):
        """Return active records respecting multi-company."""
        base_domain = [
            ('active', '=', True),
            ('company_id', 'in', self.env.companies.ids),
        ]
        if domain:
            base_domain.extend(domain)
        return self.search(base_domain)
