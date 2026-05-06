/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onMounted, onWillStart } from "@odoo/owl";
import { CommissionKpiCard } from "./commission_kpi_card";
import { formatMonetary } from "@web/views/fields/formatters";

const { DateTime } = luxon;

/**
 * Advanced Commission Dashboard
 * OWL Component providing a real-time commission management overview.
 */
export class CommissionDashboard extends Component {
    static template = "advanced_commission_engine.CommissionDashboard";
    static components = { CommissionKpiCard };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            period: null,
            periods: [],
            selectedPeriodId: null,
            kpis: {
                totalCommission: 0,
                totalPaid: 0,
                totalPending: 0,
                settlementsCount: 0,
                employeesCount: 0,
                openDisputes: 0,
                achievementRate: 0,
            },
            topPerformers: [],
            recentSettlements: [],
            periodProgress: 0,
            chartData: [],
            currency: { symbol: "", position: "before" },
            companyId: null,
        });
    }

    async willStart() {
        await this._loadInitialData();
    }

    async _loadInitialData() {
        try {
            // Get company currency
            const companies = await this.orm.call(
                "res.company",
                "search_read",
                [[["id", "=", 1]]],
                { fields: ["currency_id", "name"], limit: 1 }
            );
            if (companies.length) {
                this.state.companyId = companies[0].id;
            }

            // Load periods
            const periods = await this.orm.call(
                "commission.period",
                "search_read",
                [[["state", "!=", "cancelled"]]],
                {
                    fields: ["id", "name", "date_from", "date_to", "state", "total_commission"],
                    order: "date_from desc",
                    limit: 12,
                }
            );
            this.state.periods = periods;

            // Select current open period
            const openPeriod = periods.find(p => p.state === "open");
            if (openPeriod) {
                this.state.selectedPeriodId = openPeriod.id;
                this.state.period = openPeriod;
            } else if (periods.length) {
                this.state.selectedPeriodId = periods[0].id;
                this.state.period = periods[0];
            }

            if (this.state.selectedPeriodId) {
                await this._loadPeriodData(this.state.selectedPeriodId);
            }
        } catch (e) {
            console.error("Commission Dashboard load error:", e);
            this.notification.add("Failed to load dashboard data.", {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }

    async _loadPeriodData(periodId) {
        this.state.loading = true;
        try {
            // KPI aggregates
            const lineStats = await this.orm.call(
                "commission.line",
                "read_group",
                [
                    [
                        ["period_id", "=", periodId],
                        ["state", "!=", "cancelled"],
                    ],
                ],
                {
                    fields: [
                        "commission_amount:sum",
                        "line_type",
                        "state",
                    ],
                    groupby: ["line_type", "state"],
                }
            );

            let totalCommission = 0;
            let totalPaid = 0;
            let totalPending = 0;

            for (const group of lineStats) {
                if (group.line_type === "commission") {
                    totalCommission += group.commission_amount;
                    if (group.state === "paid") {
                        totalPaid += group.commission_amount;
                    } else if (group.state !== "cancelled") {
                        totalPending += group.commission_amount;
                    }
                }
            }

            this.state.kpis.totalCommission = totalCommission;
            this.state.kpis.totalPaid = totalPaid;
            this.state.kpis.totalPending = totalPending;

            // Settlements count
            const settlements = await this.orm.call(
                "commission.settlement",
                "search_count",
                [[["period_id", "=", periodId]]]
            );
            this.state.kpis.settlementsCount = settlements;

            // Distinct employees
            const employees = await this.orm.call(
                "commission.line",
                "read_group",
                [[["period_id", "=", periodId], ["state", "!=", "cancelled"]]],
                { fields: ["employee_id"], groupby: ["employee_id"] }
            );
            this.state.kpis.employeesCount = employees.length;

            // Open disputes
            const disputes = await this.orm.call(
                "commission.dispute",
                "search_count",
                [[["state", "in", ["open", "under_review"]]]]
            );
            this.state.kpis.openDisputes = disputes;

            // Achievement rate
            const targets = await this.orm.call(
                "commission.target",
                "search_read",
                [[["period_id", "=", periodId]]],
                { fields: ["achievement_percent"], limit: 100 }
            );
            if (targets.length) {
                const avgAchievement =
                    targets.reduce((s, t) => s + t.achievement_percent, 0) /
                    targets.length;
                this.state.kpis.achievementRate = Math.round(avgAchievement * 10) / 10;
            }

            // Top performers from leaderboard
            const leaderboard = await this.orm.call(
                "commission.leaderboard",
                "get_dashboard_data",
                [periodId]
            );
            this.state.topPerformers = leaderboard.slice(0, 5);

            // Recent settlements
            const recentSettlements = await this.orm.call(
                "commission.settlement",
                "search_read",
                [[["period_id", "=", periodId]]],
                {
                    fields: [
                        "name",
                        "employee_id",
                        "net_commission",
                        "state",
                        "date",
                        "settlement_method",
                    ],
                    order: "date desc",
                    limit: 5,
                }
            );
            this.state.recentSettlements = recentSettlements;

            // Monthly chart data
            await this._loadChartData();

            // Period progress
            const period = this.state.period;
            if (period) {
                const from = DateTime.fromISO(period.date_from);
                const to = DateTime.fromISO(period.date_to);
                const now = DateTime.now();
                const total = to.diff(from, "days").days;
                const elapsed = now.diff(from, "days").days;
                this.state.periodProgress = Math.min(
                    100,
                    Math.max(0, Math.round((elapsed / total) * 100))
                );
            }
        } catch (e) {
            console.error("Period data load error:", e);
        } finally {
            this.state.loading = false;
        }
    }

    async _loadChartData() {
        try {
            const monthlyData = await this.orm.call(
                "commission.line",
                "read_group",
                [
                    [
                        ["state", "=", "paid"],
                        ["line_type", "=", "commission"],
                    ],
                ],
                {
                    fields: ["commission_amount:sum", "date:month"],
                    groupby: ["date:month"],
                    orderby: "date:month asc",
                    limit: 12,
                }
            );
            this.state.chartData = monthlyData.map(d => ({
                label: d["date:month"],
                value: d.commission_amount,
            }));
        } catch (e) {
            this.state.chartData = [];
        }
    }

    async onPeriodChange(ev) {
        const periodId = parseInt(ev.target.value);
        const period = this.state.periods.find(p => p.id === periodId);
        this.state.selectedPeriodId = periodId;
        this.state.period = period;
        await this._loadPeriodData(periodId);
    }

    formatAmount(amount) {
        return new Intl.NumberFormat(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }).format(amount || 0);
    }

    getStateClass(state) {
        const classes = {
            draft: "text-bg-secondary",
            submitted: "text-bg-warning",
            manager_approved: "text-bg-info",
            finance_approved: "text-bg-primary",
            approved: "text-bg-success",
            paid: "text-bg-success",
            cancelled: "text-bg-danger",
            rejected: "text-bg-danger",
        };
        return classes[state] || "text-bg-secondary";
    }

    getTrendIcon(trend) {
        const icons = {
            up: "fa-arrow-up text-success",
            down: "fa-arrow-down text-danger",
            same: "fa-minus text-muted",
            new: "fa-star text-warning",
        };
        return icons[trend] || "fa-minus";
    }

    // ── Navigation Actions ────────────────────────────────────────────────

    openPlans() {
        this.action.doAction("advanced_commission_engine.action_commission_plan");
    }

    openPeriods() {
        this.action.doAction("advanced_commission_engine.action_commission_period");
    }

    openSettlements() {
        this.action.doAction("advanced_commission_engine.action_commission_settlement");
    }

    openLines() {
        this.action.doAction("advanced_commission_engine.action_commission_line");
    }

    openDisputes() {
        this.action.doAction("advanced_commission_engine.action_commission_dispute");
    }

    openLeaderboard() {
        this.action.doAction("advanced_commission_engine.action_commission_leaderboard");
    }

    openAnalytics() {
        this.action.doAction("advanced_commission_engine.action_commission_analytics");
    }

    openSettlementWizard() {
        this.action.doAction("advanced_commission_engine.action_commission_settlement_wizard");
    }

    openSimulationWizard() {
        this.action.doAction("advanced_commission_engine.action_commission_simulation_wizard");
    }

    async refreshDashboard() {
        this.notification.add("Refreshing dashboard...", { type: "info" });
        await this._loadInitialData();
        this.notification.add("Dashboard refreshed.", { type: "success" });
    }
}

registry.category("actions").add("commission_dashboard", CommissionDashboard);
