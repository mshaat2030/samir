# -*- coding: utf-8 -*-
from odoo import api, fields, models
from datetime import date, timedelta

try:
    from dateutil.relativedelta import relativedelta
except ImportError:
    from dateutil.relativedelta import relativedelta


class ContractDashboard(models.Model):
    """
    Stateless model used exclusively as an RPC endpoint for the JS dashboard.
    All methods are @api.model and return plain dicts / lists.
    """
    _name = 'contract.dashboard'
    _description = 'Contract Dashboard'

    # ── dummy field so Odoo registers the model ──────────────────────────────
    name = fields.Char(default='dashboard')

    # ─────────────────────────────────────────────────────────────────────────
    # Public RPC entry-point
    # ─────────────────────────────────────────────────────────────────────────
    @api.model
    def get_dashboard_data(self):
        today = date.today()
        Contract = self.env['contract.contract']
        domain_base = []

        # ── Raw counts ───────────────────────────────────────────────────────
        all_recs  = Contract.search(domain_base)
        total     = len(all_recs)
        active    = sum(1 for c in all_recs if c.state == 'active')
        draft     = sum(1 for c in all_recs if c.state == 'draft')
        expired   = sum(1 for c in all_recs if c.state == 'expired')
        cancelled = sum(1 for c in all_recs if c.state == 'cancelled')

        # ── Expiring soon ─────────────────────────────────────────────────────
        d30 = today + timedelta(days=30)
        d60 = today + timedelta(days=60)

        exp30 = Contract.search([
            ('state', '=', 'active'),
            ('date_end', '!=', False),
            ('date_end', '>=', today.strftime('%Y-%m-%d')),
            ('date_end', '<=', d30.strftime('%Y-%m-%d')),
        ])
        exp60 = Contract.search([
            ('state', '=', 'active'),
            ('date_end', '!=', False),
            ('date_end', '>=', today.strftime('%Y-%m-%d')),
            ('date_end', '<=', d60.strftime('%Y-%m-%d')),
        ])

        # ── Type distribution ─────────────────────────────────────────────────
        type_labels = dict(
            Contract.fields_get(['contract_type'])['contract_type']['selection']
        )
        type_counts = {}
        for c in all_recs:
            t = c.contract_type or 'other'
            type_counts[t] = type_counts.get(t, 0) + 1
        type_distribution = [
            {'type': k, 'label': type_labels.get(k, k), 'count': v}
            for k, v in sorted(type_counts.items(), key=lambda x: -x[1])
        ]

        # ── Language distribution ─────────────────────────────────────────────
        lang_labels = {
            'en': 'English Only',
            'ar': 'Arabic Only',
            'bilingual': 'Bilingual EN/AR',
        }
        lang_counts = {}
        for c in all_recs:
            l = c.language or 'en'
            lang_counts[l] = lang_counts.get(l, 0) + 1
        lang_distribution = [
            {'lang': k, 'label': lang_labels.get(k, k), 'count': v}
            for k, v in sorted(lang_counts.items(), key=lambda x: -x[1])
        ]

        # ── Recent contracts ──────────────────────────────────────────────────
        recent_recs = Contract.search(
            [('state', 'in', ['active', 'draft'])],
            order='create_date desc', limit=6
        )
        recent_data = [{
            'id':            c.id,
            'name':          c.name,
            'reference':     c.reference,
            'partner':       c.partner_id.name or '',
            'state':         c.state,
            'date_end':      c.date_end.strftime('%d/%m/%Y') if c.date_end else '—',
            'contract_type': type_labels.get(c.contract_type, c.contract_type or ''),
        } for c in recent_recs]

        # ── Expiring details ──────────────────────────────────────────────────
        expiring_data = sorted([{
            'id':        c.id,
            'name':      c.name,
            'reference': c.reference,
            'partner':   c.partner_id.name or '',
            'date_end':  c.date_end.strftime('%d/%m/%Y') if c.date_end else '—',
            'days_left': (c.date_end - today).days if c.date_end else 0,
        } for c in exp30], key=lambda x: x['days_left'])

        # ── Monthly trend (last 6 months) ──────────────────────────────────────
        monthly_data = []
        for i in range(5, -1, -1):
            m_start = (today.replace(day=1) - relativedelta(months=i))
            m_end   = m_start + relativedelta(months=1) - timedelta(days=1)
            count   = Contract.search_count([
                ('date_start', '>=', m_start.strftime('%Y-%m-%d')),
                ('date_start', '<=', m_end.strftime('%Y-%m-%d')),
            ])
            monthly_data.append({
                'label': m_start.strftime('%b %Y'),
                'count': count,
            })

        # ── AI Insights ────────────────────────────────────────────────────────
        insights = []

        # 1. Portfolio health
        if total > 0:
            health = round(active / total * 100)
            if health >= 70:
                insights.append({
                    'type': 'success', 'icon': '✅',
                    'title': f'Portfolio Health: Excellent ({health}%)',
                    'body': (
                        f'{active} of {total} contracts are active. '
                        'Your portfolio is performing strongly.'
                    ),
                })
            elif health >= 40:
                insights.append({
                    'type': 'warning', 'icon': '⚠️',
                    'title': f'Portfolio Health: Moderate ({health}%)',
                    'body': (
                        f'{active} of {total} contracts are active. '
                        'Consider reviewing drafts and expired contracts.'
                    ),
                })
            else:
                insights.append({
                    'type': 'danger', 'icon': '🔴',
                    'title': f'Portfolio Health: Needs Attention ({health}%)',
                    'body': (
                        f'Only {active} of {total} contracts are active. '
                        'Review your contract pipeline immediately.'
                    ),
                })

        # 2. Expiry risk
        if len(exp30) > 0:
            insights.append({
                'type': 'warning', 'icon': '⏰',
                'title': f'{len(exp30)} Contract(s) Expiring Within 30 Days',
                'body': (
                    'Initiate renewal discussions now to avoid service interruptions '
                    f'for {len(exp30)} active contract(s).'
                ),
            })
        upcoming = len(exp60) - len(exp30)
        if upcoming > 0:
            insights.append({
                'type': 'info', 'icon': '📅',
                'title': f'{upcoming} More Contract(s) Expiring in 31–60 Days',
                'body': (
                    f'Plan ahead: {upcoming} contract(s) expire in the next 31–60 days.'
                ),
            })

        # 3. Draft pipeline
        if draft > 0:
            insights.append({
                'type': 'info', 'icon': '📝',
                'title': f'{draft} Draft Contract(s) Awaiting Activation',
                'body': (
                    f'You have {draft} contract(s) pending activation. '
                    'Review and confirm to build your active portfolio.'
                ),
            })

        # 4. Top contract type
        if type_distribution and total > 0:
            top = type_distribution[0]
            pct = round(top['count'] / total * 100)
            insights.append({
                'type': 'info', 'icon': '📊',
                'title': f'Dominant Type: {top["label"]}',
                'body': (
                    f'{top["label"]} accounts for {pct}% '
                    f'({top["count"]} of {total} contracts).'
                ),
            })

        # 5. Bilingual adoption
        bilingual_count = lang_counts.get('bilingual', 0)
        arabic_count    = lang_counts.get('ar', 0)
        if total > 0 and (bilingual_count + arabic_count) > 0:
            ar_pct = round((bilingual_count + arabic_count) / total * 100)
            insights.append({
                'type': 'info', 'icon': '🌐',
                'title': f'{ar_pct}% of Contracts Include Arabic',
                'body': (
                    f'{bilingual_count} bilingual and {arabic_count} Arabic-only '
                    'contracts support multilingual operations.'
                ),
            })

        # 6. Open-ended contracts
        open_ended = sum(1 for c in all_recs if c.state == 'active' and not c.date_end)
        if open_ended > 0:
            insights.append({
                'type': 'warning', 'icon': '♾️',
                'title': f'{open_ended} Open-Ended Active Contract(s)',
                'body': (
                    f'{open_ended} active contract(s) have no end date. '
                    'Consider setting expiry dates to enable renewal tracking.'
                ),
            })

        return {
            'kpi': {
                'total':       total,
                'active':      active,
                'draft':       draft,
                'expired':     expired,
                'cancelled':   cancelled,
                'expiring_30': len(exp30),
                'expiring_60': len(exp60),
            },
            'type_distribution':  type_distribution,
            'lang_distribution':  lang_distribution,
            'recent_contracts':   recent_data,
            'expiring_contracts': expiring_data,
            'insights':           insights,
            'monthly_trend':      monthly_data,
        }
