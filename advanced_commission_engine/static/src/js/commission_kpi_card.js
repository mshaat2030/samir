/** @odoo-module **/

import { Component } from "@odoo/owl";

/**
 * KPI Card component for the commission dashboard.
 * Displays a metric with icon, value, trend, and optional click action.
 */
export class CommissionKpiCard extends Component {
    static template = "advanced_commission_engine.CommissionKpiCard";
    static props = {
        title: String,
        value: { type: [String, Number] },
        icon: { type: String, optional: true },
        iconClass: { type: String, optional: true },
        subtitle: { type: String, optional: true },
        trend: { type: String, optional: true },
        trendValue: { type: [String, Number], optional: true },
        color: { type: String, optional: true },
        onClick: { type: Function, optional: true },
        loading: { type: Boolean, optional: true },
        badge: { type: String, optional: true },
        badgeClass: { type: String, optional: true },
    };

    static defaultProps = {
        icon: "fa-chart-bar",
        iconClass: "text-primary",
        color: "primary",
        loading: false,
    };

    get cardClass() {
        return `commission-kpi-card border-start border-${this.props.color} border-4`;
    }

    get iconFullClass() {
        return `fa ${this.props.icon} fa-2x ${this.props.iconClass}`;
    }

    get trendClass() {
        if (!this.props.trend) return "";
        const classes = {
            up: "text-success",
            down: "text-danger",
            neutral: "text-muted",
        };
        return classes[this.props.trend] || "text-muted";
    }

    get trendIcon() {
        if (!this.props.trend) return "";
        const icons = {
            up: "fa-arrow-up",
            down: "fa-arrow-down",
            neutral: "fa-minus",
        };
        return `fa ${icons[this.props.trend] || "fa-minus"}`;
    }

    handleClick() {
        if (this.props.onClick) {
            this.props.onClick();
        }
    }
}
