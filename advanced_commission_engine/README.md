# Advanced Commission Engine — Odoo 19 Enterprise

## Overview
Production-ready, enterprise-grade commission management module for Odoo 19 Enterprise. Handles the full lifecycle from plan design through payment, with gamification, analytics, and AI-ready forecasting services.

## Commission Types
- **Sales** — invoice/sale-order based commissions
- **Collection** — triggered on payment receipt with aging penalties
- **Recurring** — subscription/MRR-based monthly accruals
- **Subscription Renewal** — one-time renewal bonus
- **Project Milestone** — task/milestone completion triggers
- **Referral** — referrer rewards for introduced customers
- **Manager Override** — percentage of team earnings
- **Team** — pool split among team members
- **Recruitment** — HR sourcing bonuses
- **Profit Sharing** — company-profit percentages
- **Territory** — territory-level aggregation
- **KPI Incentive** — weighted score basket

## Calculation Methods
`fixed_percent` · `fixed_amount` · `progressive_slabs` · `tiered` · `margin_based` · `revenue_based` · `profit_based` · `weighted_kpi` · `hybrid` · `dynamic_formula`

## Lifecycle States
`draft` → `calculated` → `submitted` → `approved` → `finance_approved` → `payroll_processed` → `paid` → `cancelled` / `disputed`

## Security Groups
| Group | Description |
|---|---|
| `commission_user` | View own statements, submit disputes |
| `commission_manager` | Manage plans, approve settlements |
| `commission_finance_manager` | Finance approval, journal entries |
| `commission_hr_manager` | Payroll integration, HR approval |
| `commission_executive_viewer` | Read-only executive dashboards |
| `commission_admin` | Full access, configuration |

## Installation
1. Copy module to your Odoo addons path
2. Install dependencies: `report_xlsx`, `sale_subscription`
3. Update apps list and install **Advanced Commission Engine**
4. Configure under **Commission → Configuration → Settings**

## Configuration
Navigate to **Commission → Configuration → Settings** to:
- Set default commission account and journal
- Configure approval workflow steps
- Enable/disable gamification features
- Set anomaly detection thresholds
- Configure payroll integration salary rules

## Performance
- Handles 1M+ commission lines via batch processing
- PostgreSQL indexes on all high-cardinality FK columns
- Async-ready service layer for heavy calculations
- ORM lazy loading and prefetch optimization

## Tests
```bash
python odoo-bin -c odoo.conf -d testdb --test-tags advanced_commission_engine
```
