/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class ContractDashboard extends Component {
    static template = "contract_management.Dashboard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading: true,
            data:    null,
            error:   null,
        });

        onWillStart(() => this._loadData());
    }

    // ─── data loading ─────────────────────────────────────────────────────────
    async _loadData() {
        this.state.loading = true;
        this.state.error   = null;
        try {
            const data = await this.orm.call(
                "contract.dashboard",
                "get_dashboard_data",
                []
            );
            this.state.data = data;
        } catch (e) {
            this.state.error = e.message || "Failed to load dashboard data.";
        } finally {
            this.state.loading = false;
        }
    }

    // ─── navigation helpers ───────────────────────────────────────────────────
    openAllContracts()     { this._open([], "All Contracts"); }
    openActive()           { this._open([["state","=","active"]], "Active Contracts"); }
    openDraft()            { this._open([["state","=","draft"]], "Draft Contracts"); }
    openClosedContracts()  { this._open([["state","in",["expired","cancelled"]]], "Expired / Cancelled"); }
    openExpiringSoon()     {
        this._open(
            [["state","=","active"],["date_end","!=",false]],
            "Expiring Contracts"
        );
    }

    _open(domain, name) {
        this.action.doAction({
            type:      "ir.actions.act_window",
            name:      name,
            res_model: "contract.contract",
            view_mode: "list,kanban,form",
            domain:    domain,
        });
    }

    openContract(id) {
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "contract.contract",
            view_mode: "form",
            res_id:    id,
        });
    }

    /** Open new contract form */
    createContract() {
        this.action.doAction({
            type:      "ir.actions.act_window",
            name:      "New Contract",
            res_model: "contract.contract",
            view_mode: "form",
            views:     [[false, "form"]],
        });
    }

    /** Open contract templates list */
    openTemplates() {
        this.action.doAction({
            type:      "ir.actions.act_window",
            name:      "Contract Templates",
            res_model: "contract.template",
            view_mode: "list,kanban,form",
        });
    }

    // ─── chart helpers ─────────────────────────────────────────────────────────
    /** Return bar width % relative to the maximum value in an array of {count}. */
    barPct(count, items) {
        const max = Math.max(...items.map(i => i.count), 1);
        return Math.max(2, Math.round((count / max) * 100));
    }

    /** Colour class cycling for bar charts. */
    barColor(index) {
        const colors = [
            "cm_bar_indigo", "cm_bar_teal", "cm_bar_blue",
            "cm_bar_purple", "cm_bar_orange", "cm_bar_green",
        ];
        return colors[index % colors.length];
    }

    // ─── style helpers ─────────────────────────────────────────────────────────
    daysClass(days) {
        if (days <= 7)  return "cm_days_critical";
        if (days <= 14) return "cm_days_warning";
        return "cm_days_ok";
    }

    stateClass(state) {
        return {
            active:    "cm_badge_active",
            draft:     "cm_badge_draft",
            expired:   "cm_badge_expired",
            cancelled: "cm_badge_cancelled",
        }[state] || "cm_badge_draft";
    }

    insightClass(type) {
        return {
            success: "cm_insight_success",
            warning: "cm_insight_warning",
            danger:  "cm_insight_danger",
            info:    "cm_insight_info",
        }[type] || "cm_insight_info";
    }

    // ─── KPI computed ─────────────────────────────────────────────────────────
    get healthPct() {
        const kpi = this.state.data?.kpi;
        if (!kpi || !kpi.total) return 0;
        return Math.round((kpi.active / kpi.total) * 100);
    }

    get healthLabel() {
        const p = this.healthPct;
        if (p >= 70) return "Excellent";
        if (p >= 40) return "Moderate";
        return "Needs Attention";
    }

    get healthColor() {
        const p = this.healthPct;
        if (p >= 70) return "cm_health_good";
        if (p >= 40) return "cm_health_warn";
        return "cm_health_bad";
    }
}

registry.category("actions").add("contract_management.dashboard", ContractDashboard);
