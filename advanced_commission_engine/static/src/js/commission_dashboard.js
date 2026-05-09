/** @odoo-module **/
/**
 * Commission Dashboard — OWL client action component.
 * Registered as the `commission_dashboard` client action tag.
 */

import { Component, useState, onMounted, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import {
    CommissionKPICard,
    CommissionTrendChart,
    CommissionLeaderboardWidget,
    CommissionAchievementGrid,
    CommissionPendingList,
} from "./commission_widgets";

class CommissionDashboard extends Component {
    static template = "commission.Dashboard";
    static components = {
        CommissionKPICard,
        CommissionTrendChart,
        CommissionLeaderboardWidget,
        CommissionAchievementGrid,
        CommissionPendingList,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            periods: [],
            activePeriodId: null,
            currentPeriodName: "Loading...",
            trendMode: "6m",
            kpiCards: [],
            trendData: null,
            topPerformers: [],
            achievementData: [],
            pendingApprovals: [],
            pendingCount: 0,
            anomalies: [],
        });

        onWillStart(async () => {
            await this._loadPeriods();
        });

        onMounted(async () => {
            if (this.state.activePeriodId) {
                await this._loadDashboardData();
            }
        });
    }

    // ── Data Loading ───────────────────────────────────────────────────────

    async _loadPeriods() {
        const periods = await this.orm.searchRead(
            "commission.period",
            [["state", "in", ["open", "closed"]]],
            ["id", "name", "date_start", "date_end", "state"],
            { order: "date_start desc", limit: 24 }
        );
        this.state.periods = periods;
        if (periods.length) {
            const open = periods.find((p) => p.state === "open") || periods[0];
            this.state.activePeriodId = open.id;
            this.state.currentPeriodName = open.name;
        }
    }

    async _loadDashboardData() {
        this.state.loading = true;
        try {
            await Promise.all([
                this._loadKPICards(),
                this._loadTrendData(),
                this._loadLeaderboard(),
                this._loadAchievements(),
                this._loadPendingApprovals(),
                this._loadAnomalies(),
            ]);
        } catch (error) {
            console.error("Commission dashboard load error:", error);
            this.notification.add("Failed to load dashboard data.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async _loadKPICards() {
        const periodId = this.state.activePeriodId;
        if (!periodId) return;

        // Fetch settlements for current period
        const settlements = await this.orm.searchRead(
            "commission.settlement",
            [["period_id", "=", periodId], ["state", "not in", ["cancelled"]]],
            ["total_commission", "state", "gross_commission", "total_adjustments", "employee_id", "currency_id"]
        );

        const total = settlements.reduce((s, r) => s + (r.total_commission || 0), 0);
        const paid = settlements
            .filter((r) => r.state === "paid")
            .reduce((s, r) => s + (r.total_commission || 0), 0);
        const pending = settlements
            .filter((r) => ["submitted", "approved", "finance_approved"].includes(r.state))
            .reduce((s, r) => s + (r.total_commission || 0), 0);
        const employees = new Set(settlements.map((r) => r.employee_id && r.employee_id[0])).size;

        // Format currency
        const fmt = (n) => new Intl.NumberFormat("en", { style: "decimal", maximumFractionDigits: 0 }).format(n);

        this.state.kpiCards = [
            {
                key: "total",
                title: "Total Commission",
                value: fmt(total),
                icon: "money",
                color: "primary",
                subtext: `${settlements.length} settlement(s)`,
            },
            {
                key: "paid",
                title: "Paid",
                value: fmt(paid),
                icon: "check-circle",
                color: "success",
                subtext: `${settlements.filter((r) => r.state === "paid").length} settlement(s)`,
            },
            {
                key: "pending",
                title: "Pending Payout",
                value: fmt(pending),
                icon: "clock-o",
                color: "warning",
                subtext: `${settlements.filter((r) => ["submitted", "approved", "finance_approved"].includes(r.state)).length} awaiting approval`,
            },
            {
                key: "employees",
                title: "Employees",
                value: employees.toString(),
                icon: "users",
                color: "info",
                subtext: "with active settlements",
            },
        ];
    }

    async _loadTrendData() {
        const n = this.state.trendMode === "ytd" ? 12 : parseInt(this.state.trendMode);
        const periods = await this.orm.searchRead(
            "commission.period",
            [["state", "in", ["open", "closed", "locked"]]],
            ["id", "name", "total_commission", "paid_commission"],
            { order: "date_start desc", limit: n }
        );
        const sorted = periods.reverse();
        this.state.trendData = {
            labels: sorted.map((p) => p.name),
            datasets: [
                {
                    label: "Total Commission",
                    data: sorted.map((p) => p.total_commission || 0),
                    borderColor: "#3498db",
                    backgroundColor: "rgba(52,152,219,0.1)",
                    tension: 0.4,
                    fill: true,
                },
                {
                    label: "Paid",
                    data: sorted.map((p) => p.paid_commission || 0),
                    borderColor: "#2ecc71",
                    backgroundColor: "rgba(46,204,113,0.1)",
                    tension: 0.4,
                    fill: true,
                },
            ],
        };
    }

    async _loadLeaderboard() {
        const periodId = this.state.activePeriodId;
        if (!periodId) return;
        const entries = await this.orm.searchRead(
            "commission.leaderboard",
            [["period_id", "=", periodId]],
            ["rank", "employee_id", "total_commission", "currency_id", "streak_badge", "rank_change_icon"],
            { order: "rank", limit: 10 }
        );
        this.state.topPerformers = entries.map((e) => ({
            rank: e.rank,
            employee: e.employee_id ? e.employee_id[1] : "Unknown",
            commission_formatted: new Intl.NumberFormat("en", {
                style: "decimal",
                maximumFractionDigits: 0,
            }).format(e.total_commission || 0),
            streak_badge: e.streak_badge || "",
            change_icon: e.rank_change_icon || "",
        }));
    }

    async _loadAchievements() {
        const periodId = this.state.activePeriodId;
        if (!periodId) return;
        const targets = await this.orm.searchRead(
            "commission.target",
            [["period_id", "=", periodId]],
            ["employee_id", "achievement_pct"],
            { order: "achievement_pct desc", limit: 15 }
        );
        this.state.achievementData = targets.map((t) => ({
            employee_id: t.employee_id ? t.employee_id[0] : 0,
            employee: t.employee_id ? t.employee_id[1] : "Unknown",
            pct: t.achievement_pct || 0,
        }));
    }

    async _loadPendingApprovals() {
        const pending = await this.orm.searchRead(
            "commission.settlement",
            [["state", "in", ["submitted", "approved"]]],
            ["name", "employee_id", "total_commission", "state", "currency_id"],
            { order: "write_date desc", limit: 10 }
        );
        this.state.pendingCount = pending.length;
        this.state.pendingApprovals = pending.map((s) => ({
            id: s.id,
            name: s.name,
            employee: s.employee_id ? s.employee_id[1] : "Unknown",
            amount_formatted: new Intl.NumberFormat("en", {
                style: "decimal",
                maximumFractionDigits: 0,
            }).format(s.total_commission || 0),
            state: s.state,
        }));
    }

    async _loadAnomalies() {
        const anomalous = await this.orm.searchRead(
            "commission.settlement",
            [["anomaly_flag", "=", true], ["state", "not in", ["paid", "cancelled"]]],
            ["name", "employee_id", "anomaly_reason"],
            { limit: 5 }
        );
        this.state.anomalies = anomalous.map((s) => ({
            id: s.id,
            employee: s.employee_id ? s.employee_id[1] : "Unknown",
            reason: s.anomaly_reason || "Unusual amount detected",
        }));
    }

    // ── Event Handlers ─────────────────────────────────────────────────────

    async onPeriodChange(ev) {
        const periodId = parseInt(ev.target.value);
        const period = this.state.periods.find((p) => p.id === periodId);
        this.state.activePeriodId = periodId;
        this.state.currentPeriodName = period ? period.name : "";
        await this._loadDashboardData();
    }

    async onRefresh() {
        await this._loadDashboardData();
        this.notification.add("Dashboard refreshed.", { type: "success" });
    }

    async setTrendMode(mode) {
        this.state.trendMode = mode;
        await this._loadTrendData();
    }

    openSimulator() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "wizard.commission.simulator",
            view_mode: "form",
            target: "new",
        });
    }
}

// Register as client action
registry.category("actions").add("commission_dashboard", CommissionDashboard);
