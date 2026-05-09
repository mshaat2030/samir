/** @odoo-module **/
/**
 * Commission OWL widgets — reusable UI components.
 */

import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { formatMonetary } from "@web/views/fields/formatters";

// ── Commission Progress Bar Field Widget ────────────────────────────────────

export class CommissionProgressBarWidget extends Component {
    static template = "commission.ProgressBar";
    static props = {
        label: { type: String, optional: true },
        value: { type: Number },
        height: { type: Number, optional: true },
    };

    get colorClass() {
        const v = this.props.value;
        if (v >= 100) return "bg-success";
        if (v >= 70) return "bg-warning";
        return "bg-danger";
    }
}

// ── KPI Card Component ────────────────────────────────────────────────────

export class CommissionKPICard extends Component {
    static template = "commission.KPICard";
    static props = {
        title: String,
        value: String,
        icon: { type: String, optional: true },
        color: { type: String, optional: true },
        change: { type: Number, optional: true },
        subtext: { type: String, optional: true },
        key: String,
    };
}

// ── Leaderboard Widget ─────────────────────────────────────────────────────

export class CommissionLeaderboardWidget extends Component {
    static template = "commission.LeaderboardWidget";
    static props = {
        entries: { type: Array },
    };
}

// ── Achievement Grid ──────────────────────────────────────────────────────

export class CommissionAchievementGrid extends Component {
    static template = "commission.AchievementGrid";
    static props = {
        data: { type: Array },
    };
}

// ── Pending Approvals List ─────────────────────────────────────────────────

export class CommissionPendingList extends Component {
    static template = "commission.PendingList";
    static props = {
        entries: { type: Array },
    };
}

// ── Trend Chart (Chart.js line chart) ─────────────────────────────────────

export class CommissionTrendChart extends Component {
    static template = "commission.TrendChart";
    static props = {
        data: { type: Object, optional: true },
    };

    setup() {
        this.chartCanvas = useRef("chartCanvas");
        this.chart = null;
        onMounted(() => this._renderChart());
    }

    _renderChart() {
        const canvas = this.chartCanvas.el;
        if (!canvas || !this.props.data) return;

        // Dynamically import Chart.js if available, fallback to static bars
        if (typeof Chart === "undefined") {
            this._renderFallback(canvas);
            return;
        }

        const { labels, datasets } = this.props.data;
        if (this.chart) {
            this.chart.destroy();
        }
        this.chart = new Chart(canvas.getContext("2d"), {
            type: "line",
            data: { labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: true, position: "top" },
                    tooltip: { mode: "index", intersect: false },
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: (v) =>
                                new Intl.NumberFormat("en", {
                                    notation: "compact",
                                    compactDisplay: "short",
                                }).format(v),
                        },
                    },
                },
            },
        });
    }

    _renderFallback(canvas) {
        // Simple SVG-based fallback when Chart.js not available
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#f8f9fa";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = "#6c757d";
        ctx.font = "14px Arial";
        ctx.textAlign = "center";
        ctx.fillText("Chart.js not loaded — install via CDN", canvas.width / 2, canvas.height / 2);
    }

    willUpdateProps(nextProps) {
        if (nextProps.data !== this.props.data) {
            this._renderChart();
        }
    }
}

// ── Register field widgets ─────────────────────────────────────────────────

registry.category("fields").add("commission_progress", {
    component: CommissionProgressBarWidget,
    displayName: "Commission Progress Bar",
    supportedTypes: ["float"],
});
