/** @odoo-module **/
/**
 * Commission Dashboard – OWL component for the main analytics dashboard.
 */

import { Component, useState, onWillStart, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatMonetary } from "@web/core/utils/numbers";

// ── KPI Card ──────────────────────────────────────────────────────────────────

class KPICard extends Component {
    static template = "advanced_commission_engine.KPICard";
    static props = {
        title: String,
        value: { type: [String, Number], optional: true },
        icon: { type: String, optional: true },
        color: { type: String, optional: true },
        subtitle: { type: String, optional: true },
        trend: { type: Number, optional: true },
    };
}

// ── Top Performer Row ─────────────────────────────────────────────────────────

class TopPerformerRow extends Component {
    static template = "advanced_commission_engine.TopPerformerRow";
    static props = {
        rank: Number,
        name: String,
        amount: Number,
        attainment: Number,
        currencySymbol: { type: String, optional: true },
    };
}

// ── Main Dashboard Component ──────────────────────────────────────────────────

class CommissionDashboard extends Component {
    static template = "advanced_commission_engine.CommissionDashboard";
    static components = { KPICard, TopPerformerRow };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");

        this.state = useState({
            loading: true,
            error: null,
            // KPIs
            totalPaidThisMonth: 0,
            totalPendingApproval: 0,
            totalDraft: 0,
            openPeriods: 0,
            totalAnomalies: 0,
            // Period info
            currentPeriodName: "",
            currentPeriodStart: "",
            currentPeriodEnd: "",
            // Leaderboard
            topPerformers: [],
            // Recent settlements
            recentSettlements: [],
            // Chart data
            monthlyTrend: [],
            planDistribution: [],
            // Currency
            currencySymbol: "$",
        });

        onWillStart(async () => {
            await this._loadDashboardData();
        });
    }

    // ── Data Loading ──────────────────────────────────────────────────────────

    async _loadDashboardData() {
        try {
            this.state.loading = true;
            await Promise.all([
                this._loadKPIs(),
                this._loadLeaderboard(),
                this._loadRecentSettlements(),
                this._loadTrend(),
            ]);
        } catch (e) {
            this.state.error = e.message || "Failed to load dashboard data.";
            console.error("Commission Dashboard Error:", e);
        } finally {
            this.state.loading = false;
        }
    }

    async _loadKPIs() {
        // Total paid this month
        const today = new Date();
        const firstDayMonth = new Date(today.getFullYear(), today.getMonth(), 1)
            .toISOString()
            .split("T")[0];

        const [paid] = await this.orm.readGroup(
            "commission.settlement",
            [["state", "=", "paid"], ["paid_date", ">=", firstDayMonth]],
            ["final_amount:sum"],
            []
        );
        this.state.totalPaidThisMonth = paid.final_amount || 0;

        const [pending] = await this.orm.readGroup(
            "commission.settlement",
            [["state", "in", ["submitted", "approved"]]],
            ["final_amount:sum"],
            []
        );
        this.state.totalPendingApproval = pending.final_amount || 0;

        const draftCount = await this.orm.searchCount("commission.settlement", [
            ["state", "=", "draft"],
        ]);
        this.state.totalDraft = draftCount;

        const openPeriods = await this.orm.searchCount("commission.period", [
            ["state", "=", "open"],
        ]);
        this.state.openPeriods = openPeriods;

        const anomalies = await this.orm.searchCount("commission.settlement", [
            ["is_anomaly", "=", true],
            ["state", "not in", ["cancelled", "paid"]],
        ]);
        this.state.totalAnomalies = anomalies;

        // Current period
        const periods = await this.orm.search("commission.period", [
            ["state", "=", "open"],
        ], { limit: 1, order: "date_start desc" });
        if (periods.length) {
            const period = await this.orm.read("commission.period", periods, [
                "name", "date_start", "date_end",
            ]);
            this.state.currentPeriodName = period[0].name;
            this.state.currentPeriodStart = period[0].date_start;
            this.state.currentPeriodEnd = period[0].date_end;
        }

        // Currency
        const companies = await this.orm.read("res.company", [1], ["currency_id"]);
        if (companies.length && companies[0].currency_id) {
            const currency = await this.orm.read(
                "res.currency", [companies[0].currency_id[0]], ["symbol"]
            );
            if (currency.length) {
                this.state.currencySymbol = currency[0].symbol;
            }
        }
    }

    async _loadLeaderboard() {
        // Get current open period leaderboard
        const periods = await this.orm.search("commission.period", [
            ["state", "=", "open"],
        ], { limit: 1, order: "date_start desc" });

        if (!periods.length) return;

        const entries = await this.orm.searchRead(
            "commission.leaderboard",
            [["period_id", "=", periods[0]]],
            ["rank", "employee_id", "total_commission", "target_attainment", "rank_change_icon"],
            { limit: 10, order: "rank asc" }
        );

        this.state.topPerformers = entries.map((e) => ({
            rank: e.rank,
            name: e.employee_id[1],
            amount: e.total_commission,
            attainment: e.target_attainment,
            change: e.rank_change_icon,
        }));
    }

    async _loadRecentSettlements() {
        const settlements = await this.orm.searchRead(
            "commission.settlement",
            [["state", "not in", ["cancelled"]]],
            ["name", "employee_id", "period_id", "final_amount", "state"],
            { limit: 8, order: "id desc" }
        );
        this.state.recentSettlements = settlements;
    }

    async _loadTrend() {
        // Last 6 months trend data
        const data = await this.orm.readGroup(
            "commission.settlement",
            [["state", "in", ["paid", "payroll_processed", "finance_approved"]]],
            ["period_id", "final_amount:sum"],
            ["period_id"],
            { limit: 6, orderby: "period_id desc" }
        );
        this.state.monthlyTrend = data.reverse().map((d) => ({
            label: d.period_id ? d.period_id[1] : "Unknown",
            value: d.final_amount || 0,
        }));
    }

    // ── Formatting ────────────────────────────────────────────────────────────

    formatAmount(value) {
        return `${this.state.currencySymbol} ${Number(value || 0).toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        })}`;
    }

    stateLabel(state) {
        const labels = {
            draft: "Draft",
            calculated: "Calculated",
            submitted: "Pending",
            approved: "Approved",
            finance_approved: "Fin. Approved",
            payroll_processed: "Payroll",
            paid: "Paid",
            cancelled: "Cancelled",
            disputed: "Disputed",
        };
        return labels[state] || state;
    }

    stateBadgeClass(state) {
        const classes = {
            draft: "bg-secondary",
            calculated: "bg-info",
            submitted: "bg-warning text-dark",
            approved: "bg-primary",
            finance_approved: "bg-primary",
            payroll_processed: "bg-success",
            paid: "bg-success",
            cancelled: "bg-danger",
            disputed: "bg-warning text-dark",
        };
        return `badge ${classes[state] || "bg-secondary"}`;
    }

    // ── Actions ───────────────────────────────────────────────────────────────

    openSettlements() {
        this.action.doAction("advanced_commission_engine.action_commission_settlement_all");
    }

    openPeriods() {
        this.action.doAction("advanced_commission_engine.action_commission_period");
    }

    openAnomalies() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Anomalous Settlements",
            res_model: "commission.settlement",
            view_mode: "list,form",
            domain: [["is_anomaly", "=", true]],
        });
    }

    openGenerateWizard() {
        this.action.doAction(
            "advanced_commission_engine.action_wizard_generate_settlement"
        );
    }

    async refreshDashboard() {
        await this._loadDashboardData();
        this.notification.add("Dashboard refreshed.", { type: "info" });
    }
}

registry.category("actions").add("commission_dashboard", CommissionDashboard);
