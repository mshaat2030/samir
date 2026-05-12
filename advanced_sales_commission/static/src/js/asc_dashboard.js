/** @odoo-module **/
/**
 * ASC Commission Dashboard — Owl Component
 * Role-aware, lazy-loaded, Chart.js powered.
 */
import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

// ── Helpers ──────────────────────────────────────────────────────────────────
const MONTHS = [
    '', 'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
];

function formatCurrency(amount, symbol = '') {
    if (amount == null) return '—';
    const formatted = new Intl.NumberFormat('en-US', {
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
    }).format(amount);
    return symbol ? `${symbol} ${formatted}` : formatted;
}

// ── Dashboard Component ───────────────────────────────────────────────────────
export class AscDashboard extends Component {
    static template = "asc.Dashboard";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.user = useService("user");

        const today = new Date();
        this.state = useState({
            loading: true,
            month: today.getMonth() + 1,
            year: today.getFullYear(),
            kpi: {
                totalCommission: 0,
                approvedAmount: 0,
                approvedCount: 0,
                pendingCount: 0,
                totalRevenue: 0,
                avgRate: 0,
            },
            rankings: [],
            recentLines: [],
            targets: [],
            trendData: { labels: [], datasets: [] },
            planData: { labels: [], data: [] },
        });

        this.trendChartRef = useRef("trendChart");
        this.planChartRef = useRef("planChart");
        this._trendChart = null;
        this._planChart = null;
        this._currencySymbol = '';

        onMounted(async () => {
            await this._loadChartJs();
            await this.loadData();
        });

        onWillUnmount(() => {
            this._destroyCharts();
        });
    }

    // ── Chart.js lazy load ───────────────────────────────────────────────────
    async _loadChartJs() {
        if (!window.Chart) {
            await loadJS("https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js");
        }
    }

    // ── Data Loading ─────────────────────────────────────────────────────────
    async loadData() {
        this.state.loading = true;
        try {
            await Promise.all([
                this._loadKPIs(),
                this._loadRankings(),
                this._loadRecentLines(),
                this._loadTargets(),
                this._loadTrendData(),
                this._loadPlanData(),
            ]);
        } catch (e) {
            this.notification.add("Failed to load commission data: " + e.message, { type: "danger" });
        } finally {
            this.state.loading = false;
            // Render charts after data loads
            setTimeout(() => this._renderCharts(), 50);
        }
    }

    async _loadKPIs() {
        const domain = this._buildDomain();

        // Total commission stats
        const result = await this.orm.readGroup(
            "asc.commission.line",
            [...domain, ['is_simulation', '=', false], ['state', 'not in', ['cancelled']]],
            ["net_commission:sum", "base_amount:sum", "rate_applied:avg"],
            [],
        );
        const row = result[0] || {};

        // Approved
        const approvedResult = await this.orm.readGroup(
            "asc.commission.line",
            [...domain, ['is_simulation', '=', false], ['state', '=', 'approved']],
            ["net_commission:sum", "id:count"],
            [],
        );
        const appRow = approvedResult[0] || {};

        // Pending
        const pendingCount = await this.orm.searchCount(
            "asc.commission.line",
            [['state', '=', 'submitted'], ['is_simulation', '=', false]],
        );

        this.state.kpi = {
            totalCommission: row["net_commission"] || 0,
            approvedAmount: appRow["net_commission"] || 0,
            approvedCount: appRow["id_count"] || 0,
            pendingCount: pendingCount,
            totalRevenue: row["base_amount"] || 0,
            avgRate: row["rate_applied"] || 0,
        };
    }

    async _loadRankings() {
        const domain = this._buildDomain();
        const result = await this.orm.readGroup(
            "asc.commission.line",
            [...domain, ['is_simulation', '=', false], ['state', 'in', ['approved', 'paid']]],
            ["salesperson_id", "net_commission:sum"],
            ["salesperson_id"],
            { orderby: "net_commission desc", limit: 10 },
        );
        this.state.rankings = result.map(r => ({
            name: r.salesperson_id[1] || 'Unknown',
            amount: r.net_commission || 0,
        }));
    }

    async _loadRecentLines() {
        const lines = await this.orm.searchRead(
            "asc.commission.line",
            [['is_simulation', '=', false], ['state', 'not in', ['cancelled']]],
            ["salesperson_id", "sale_order_id", "invoice_id", "net_commission", "state", "date"],
            { limit: 8, order: "date desc, id desc" },
        );
        this.state.recentLines = lines.map(l => ({
            salesperson: l.salesperson_id ? l.salesperson_id[1] : '—',
            order: l.invoice_id ? l.invoice_id[1] : (l.sale_order_id ? l.sale_order_id[1] : '—'),
            amount: l.net_commission || 0,
            state: l.state,
        }));
    }

    async _loadTargets() {
        const { month, year } = this.state;
        const targets = await this.orm.searchRead(
            "asc.target",
            [
                ['year', '=', year],
                ['month', '=', String(month)],
                ['period_type', '=', 'monthly'],
            ],
            ["salesperson_id", "target_revenue", "achieved_revenue", "achievement_pct"],
            { limit: 9, order: "achievement_pct desc" },
        );
        this.state.targets = targets.map(t => ({
            salesperson: t.salesperson_id ? t.salesperson_id[1] : 'Team',
            target: t.target_revenue || 0,
            achieved: t.achieved_revenue || 0,
            pct: t.achievement_pct || 0,
        }));
    }

    async _loadTrendData() {
        // Last 6 months trend
        const today = new Date();
        const labels = [];
        const amounts = [];

        for (let i = 5; i >= 0; i--) {
            const d = new Date(today.getFullYear(), today.getMonth() - i, 1);
            const m = d.getMonth() + 1;
            const y = d.getFullYear();
            labels.push(`${MONTHS[m].substring(0, 3)} ${y}`);

            const result = await this.orm.readGroup(
                "asc.commission.line",
                [
                    ['period_month', '=', m],
                    ['period_year', '=', y],
                    ['is_simulation', '=', false],
                    ['state', 'not in', ['draft', 'cancelled']],
                ],
                ["net_commission:sum"],
                [],
            );
            amounts.push((result[0] && result[0]["net_commission"]) || 0);
        }

        this.state.trendData = { labels, amounts };
    }

    async _loadPlanData() {
        const domain = this._buildDomain();
        const result = await this.orm.readGroup(
            "asc.commission.line",
            [...domain, ['is_simulation', '=', false]],
            ["plan_id", "net_commission:sum"],
            ["plan_id"],
            { limit: 8 },
        );
        this.state.planData = {
            labels: result.map(r => r.plan_id ? r.plan_id[1] : 'Unknown'),
            data: result.map(r => r.net_commission || 0),
        };
    }

    // ── Chart Rendering ───────────────────────────────────────────────────────
    _renderCharts() {
        if (!window.Chart) return;
        this._destroyCharts();

        const { trendData, planData } = this.state;

        // Trend Chart
        const trendEl = this.trendChartRef.el;
        if (trendEl && trendData.labels.length) {
            this._trendChart = new window.Chart(trendEl, {
                type: 'bar',
                data: {
                    labels: trendData.labels,
                    datasets: [{
                        label: 'Net Commission',
                        data: trendData.amounts,
                        backgroundColor: 'rgba(113, 75, 103, 0.8)',
                        borderColor: '#714B67',
                        borderWidth: 1,
                        borderRadius: 6,
                    }],
                },
                options: {
                    responsive: true,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback: v => this.formatAmount(v),
                            },
                        },
                    },
                },
            });
        }

        // Plan Donut Chart
        const planEl = this.planChartRef.el;
        if (planEl && planData.labels.length) {
            const colors = [
                '#714B67', '#875a7b', '#00b8d9', '#36b37e',
                '#ff5630', '#ffab00', '#6554c0', '#2684ff',
            ];
            this._planChart = new window.Chart(planEl, {
                type: 'doughnut',
                data: {
                    labels: planData.labels,
                    datasets: [{
                        data: planData.data,
                        backgroundColor: colors.slice(0, planData.labels.length),
                        borderWidth: 2,
                    }],
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { position: 'right', labels: { boxWidth: 12 } },
                    },
                    cutout: '65%',
                },
            });
        }
    }

    _destroyCharts() {
        if (this._trendChart) { this._trendChart.destroy(); this._trendChart = null; }
        if (this._planChart)  { this._planChart.destroy();  this._planChart = null;  }
    }

    // ── Domain Builder ────────────────────────────────────────────────────────
    _buildDomain() {
        const { month, year } = this.state;
        const domain = [['period_month', '=', month], ['period_year', '=', year]];
        // If not admin/manager, restrict to own records
        if (!this.env.isAdmin) {
            domain.push(['salesperson_id', '=', this.user.userId]);
        }
        return domain;
    }

    // ── Formatters ────────────────────────────────────────────────────────────
    formatAmount(val) {
        return formatCurrency(val, this._currencySymbol);
    }

    // ── Event Handlers ────────────────────────────────────────────────────────
    onMonthChange(ev) {
        this.state.month = parseInt(ev.target.value);
    }

    onYearChange(ev) {
        this.state.year = parseInt(ev.target.value);
    }

    openLines(state) {
        const domain = this._buildDomain();
        if (state !== 'all') domain.push(['state', '=', state]);
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Commission Lines',
            res_model: 'asc.commission.line',
            view_mode: 'list,form',
            domain,
        });
    }

    openBatchWizard() {
        this.action.doAction('advanced_sales_commission.action_asc_batch_wizard');
    }

    openSimulator() {
        this.action.doAction('advanced_sales_commission.action_asc_simulate_wizard');
    }
}

// ── Client Action Registration ────────────────────────────────────────────────
registry.category("actions").add("asc_dashboard", AscDashboard);
