/** @odoo-module **/
/**
 * Commission custom widgets and field renderers.
 */

import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Progress bar widget for attainment fields.
 * Renders a colored progress bar based on percentage value.
 */
class CommissionProgressBar extends Component {
    static template = "advanced_commission_engine.CommissionProgressBar";
    static props = {
        ...standardFieldProps,
        maxValue: { type: Number, optional: true },
    };

    get value() {
        return this.props.record.data[this.props.name] || 0;
    }

    get percentage() {
        const max = this.props.maxValue || 100;
        return Math.min(100, Math.max(0, (this.value / max) * 100));
    }

    get colorClass() {
        const pct = this.percentage;
        if (pct >= 100) return "bg-success";
        if (pct >= 75) return "bg-info";
        if (pct >= 50) return "bg-warning";
        return "bg-danger";
    }
}

registry.category("fields").add("commission_progress", CommissionProgressBar);

/**
 * Commission state badge widget with color coding.
 */
class CommissionStateBadge extends Component {
    static template = "advanced_commission_engine.CommissionStateBadge";
    static props = { ...standardFieldProps };

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    get label() {
        const field = this.props.record.fields[this.props.name];
        if (!field || !field.selection) return this.value;
        const option = field.selection.find(([v]) => v === this.value);
        return option ? option[1] : this.value;
    }

    get badgeClass() {
        const classes = {
            draft: "badge text-bg-secondary",
            calculated: "badge text-bg-info",
            submitted: "badge text-bg-warning",
            approved: "badge text-bg-primary",
            finance_approved: "badge text-bg-primary",
            payroll_processed: "badge text-bg-success",
            paid: "badge text-bg-success",
            cancelled: "badge text-bg-danger",
            disputed: "badge text-bg-warning",
        };
        return classes[this.value] || "badge text-bg-secondary";
    }
}

registry.category("fields").add("commission_state_badge", CommissionStateBadge);
