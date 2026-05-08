# -*- coding: utf-8 -*-
"""Reusable mixins for all commission models."""

from odoo import api, fields, models


class CommissionCompanyMixin(models.AbstractModel):
    """Adds company isolation and currency helpers to commission models."""

    _name = 'commission.company.mixin'
    _description = 'Commission Company Mixin'

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

    def _get_default_company(self):
        return self.env.company

    @api.model
    def _search_company_ids(self, domain_ids):
        """Return records visible across allowed companies."""
        return self.search([('company_id', 'in', self.env.companies.ids)])


class CommissionAuditMixin(models.AbstractModel):
    """Adds audit log fields to commission models."""

    _name = 'commission.audit.mixin'
    _description = 'Commission Audit Mixin'

    created_by_id = fields.Many2one(
        'res.users',
        string='Created By',
        default=lambda self: self.env.user,
        readonly=True,
        copy=False,
    )
    last_modified_by_id = fields.Many2one(
        'res.users',
        string='Last Modified By',
        readonly=True,
        copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['created_by_id'] = self.env.uid
        records = super().create(vals_list)
        return records

    def write(self, vals):
        vals['last_modified_by_id'] = self.env.uid
        return super().write(vals)


class CommissionStateMixin(models.AbstractModel):
    """State machine helpers for commission lifecycle models."""

    _name = 'commission.state.mixin'
    _description = 'Commission State Mixin'

    LOCKED_STATES = []  # Override in subclass

    def _check_state_locked(self):
        """Raise if record is in a locked state."""
        for rec in self:
            if rec.state in self.LOCKED_STATES:
                raise models.ValidationError(
                    f"Cannot modify record '{rec.display_name}' in state '{rec.state}'."
                )

    def write(self, vals):
        if any(f not in ('state', 'message_ids', 'activity_ids') for f in vals):
            self._check_state_locked()
        return super().write(vals)
