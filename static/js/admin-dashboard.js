import { APIClient, APIError } from "./api-client.js";

function parseBootstrap() {
    const bootstrapElement = document.getElementById("adminDashboardBootstrap");
    if (!bootstrapElement) {
        return null;
    }

    try {
        return JSON.parse(bootstrapElement.textContent || "{}");
    } catch (error) {
        console.error("Failed to parse admin dashboard bootstrap:", error);
        return null;
    }
}

function getCsrfToken() {
    const match = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function formatNumber(value) {
    return Number.isFinite(Number(value)) ? new Intl.NumberFormat("ru-RU").format(Number(value)) : "unavailable";
}

function formatLatency(value) {
    return Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)} ms` : "unavailable";
}

function formatAge(value) {
    return Number.isFinite(Number(value)) ? `${Math.max(0, Number(value))} s` : "unavailable";
}

function formatMegabytes(value) {
    return Number.isFinite(Number(value)) ? `${formatNumber(value)} MB` : "unavailable";
}

function statusClass(status) {
    if (status === "ready" || status === "healthy" || status === "online" || status === "working") {
        return "status-ready";
    }
    if (status === "degraded" || status === "stale") {
        return "status-degraded";
    }
    return "status-stale";
}

class AdminDashboardApp {
    constructor(bootstrap) {
        this.bootstrap = bootstrap;
        this.apiClient = new APIClient({
            getCsrfToken,
            onUnauthorized: () => {
                window.location.href = "/login";
            },
        });
        this.elements = {
            overallStatusBadge: document.getElementById("overallStatusBadge"),
            lastRefreshLabel: document.getElementById("lastRefreshLabel"),
            lastRefreshValue: document.getElementById("lastRefreshValue"),
            schedulerHealthValue: document.getElementById("schedulerHealthValue"),
            warningStrip: document.getElementById("warningStrip"),
            kpiGrid: document.getElementById("kpiGrid"),
            queueBreakdown: document.getElementById("queueBreakdown"),
            workloadBreakdown: document.getElementById("workloadBreakdown"),
            backlogSummary: document.getElementById("backlogSummary"),
            runtimeSummary: document.getElementById("runtimeSummary"),
            workersTableBody: document.getElementById("workersTableBody"),
            targetsTableBody: document.getElementById("targetsTableBody"),
        };
        this.refreshTimer = null;
        this.loading = false;
    }

    async init() {
        await this.refresh();
        this.refreshTimer = window.setInterval(() => {
            void this.refresh();
        }, Math.max(5000, Number(this.bootstrap.refreshIntervalMs) || 8000));
    }

    async refresh() {
        if (this.loading) {
            return;
        }

        this.loading = true;
        try {
            const summary = await this.apiClient.requestJSON(this.bootstrap.apiUrl, { method: "GET", timeout: 10000 });
            this.render(summary);
        } catch (error) {
            console.error("Admin dashboard refresh failed:", error);
            this.renderError(error);
        } finally {
            this.loading = false;
        }
    }

    render(summary) {
        const overallStatus = String(summary.overall_status || "degraded");
        const schedulerStatus = String(summary.scheduler_status || "stale");
        this.elements.overallStatusBadge.className = `status-badge ${statusClass(overallStatus)}`;
        this.elements.overallStatusBadge.textContent = overallStatus === "ready" ? "Ready" : "Degraded";
        this.elements.lastRefreshLabel.textContent = summary.last_refresh || "unavailable";
        this.elements.lastRefreshValue.textContent = summary.last_refresh || "unavailable";
        this.elements.schedulerHealthValue.textContent =
            schedulerStatus === "healthy"
                ? `healthy · age ${formatAge(summary.scheduler_age_seconds)}`
                : `stale · age ${formatAge(summary.scheduler_age_seconds)}`;

        this.renderWarnings(summary);
        this.renderKpis(summary);
        this.renderQueueBreakdown(summary);
        this.renderWorkloadBreakdown(summary);
        this.renderBacklog(summary);
        this.renderRuntimeSummary(summary);
        this.renderWorkers(summary.worker_rows || []);
        this.renderTargets(summary.target_rows || []);
    }

    renderWarnings(summary) {
        const warnings = Array.isArray(summary.warnings) ? summary.warnings : [];
        if (!warnings.length) {
            this.elements.warningStrip.innerHTML = '<div class="warning-pill warning-pill--ok">Runtime ready: критических предупреждений нет</div>';
            return;
        }
        this.elements.warningStrip.innerHTML = warnings
            .map((message) => `<div class="warning-pill">${escapeHtml(message)}</div>`)
            .join("");
    }

    renderKpis(summary) {
        const cards = [
            ["Queue Depth", formatNumber(summary.queue_depth), "Все pending queues"],
            ["Active Jobs", formatNumber(summary.active_jobs), "Jobs в active runtime state"],
            ["Workers", `${formatNumber(summary.workers_working)} / ${formatNumber(summary.workers_total)}`, "working / total"],
            ["Targets", formatNumber(summary.targets), "Active target heartbeats"],
            ["Failures", formatNumber(summary.failures), "Accumulated failed jobs"],
            ["Rejected", formatNumber(summary.rejected), "Admission rejects"],
            ["Avg Latency", formatLatency(summary.avg_latency_ms), "Из job_latency_total_ms / count"],
            ["Capacity", summary.capacity ? "Available" : "Unavailable", `Scope: ${escapeHtml(summary.capacity_scope || "unavailable")}`],
        ];

        this.elements.kpiGrid.innerHTML = cards
            .map(
                ([label, value, footnote]) => `
                    <article class="panel-card metric-card">
                        <div class="metric-label">${escapeHtml(label)}</div>
                        <div class="metric-value">${escapeHtml(value)}</div>
                        <div class="metric-footnote">${escapeHtml(footnote)}</div>
                    </article>
                `,
            )
            .join("");
    }

    renderQueueBreakdown(summary) {
        const pending = summary.pending || {};
        const entries = Object.entries(pending);
        if (!entries.length) {
            this.elements.queueBreakdown.innerHTML = '<div class="empty-state">Нет данных по очередям</div>';
            return;
        }

        this.elements.queueBreakdown.innerHTML = entries
            .map(
                ([queueKey, value]) => `
                    <div class="stack-item">
                        <span class="stack-key mono">${escapeHtml(queueKey)}</span>
                        <span class="stack-value">${formatNumber(value)}</span>
                    </div>
                `,
            )
            .join("");
    }

    renderWorkloadBreakdown(summary) {
        const byWorkload = summary.by_workload || {};
        const entries = Object.entries(byWorkload);
        if (!entries.length) {
            this.elements.workloadBreakdown.innerHTML = '<div class="empty-state">Нет workload breakdown</div>';
            return;
        }

        this.elements.workloadBreakdown.innerHTML = entries
            .map(([workload, payload]) => {
                const priorities = Object.entries(payload.by_priority || {})
                    .map(([priority, count]) => `${priority}: ${formatNumber(count)}`)
                    .join(" · ");
                return `
                    <div class="tag-pill">
                        <strong>${escapeHtml(workload)}</strong>
                        <div>${formatNumber(payload.total)} pending</div>
                        <div class="metric-footnote">${escapeHtml(priorities || "Нет priority details")}</div>
                    </div>
                `;
            })
            .join("");
    }

    renderBacklog(summary) {
        const items = [
            ["Chat backlog", formatNumber(summary.chat_backlog)],
            ["Parser backlog", formatNumber(summary.parser_backlog)],
            ["Queue depth", formatNumber(summary.queue_depth)],
            ["Active models", Array.isArray(summary.active_models) && summary.active_models.length ? summary.active_models.join(", ") : "unavailable"],
        ];
        this.elements.backlogSummary.innerHTML = items
            .map(
                ([label, value]) => `
                    <div class="stat-item">
                        <span class="stat-key">${escapeHtml(label)}</span>
                        <span class="stat-value">${escapeHtml(value)}</span>
                    </div>
                `,
            )
            .join("");
    }

    renderRuntimeSummary(summary) {
        const items = [
            ["Readiness", summary.readiness_status || "unavailable"],
            ["Health", summary.health_status || "unavailable"],
            ["Scheduler", summary.scheduler_status || "unavailable"],
            ["Scheduler age", formatAge(summary.scheduler_age_seconds)],
            ["Capacity", summary.capacity ? "true" : "false"],
            ["Last refresh", summary.last_refresh || "unavailable"],
        ];
        this.elements.runtimeSummary.innerHTML = items
            .map(
                ([label, value]) => `
                    <div class="stat-item">
                        <span class="stat-key">${escapeHtml(label)}</span>
                        <span class="stat-value">${escapeHtml(value)}</span>
                    </div>
                `,
            )
            .join("");
    }

    renderWorkers(workers) {
        if (!Array.isArray(workers) || !workers.length) {
            this.elements.workersTableBody.innerHTML = '<tr><td colspan="7" class="empty-state">Нет активных worker heartbeat данных</td></tr>';
            return;
        }

        this.elements.workersTableBody.innerHTML = workers
            .map(
                (worker) => `
                    <tr>
                        <td class="mono">${escapeHtml(worker.worker_id || "-")}</td>
                        <td>${escapeHtml(worker.pool || "-")}</td>
                        <td class="mono">${escapeHtml(worker.target_id || "-")}</td>
                        <td>${escapeHtml(worker.target_kind || "-")}</td>
                        <td>${formatNumber(worker.active_jobs)}</td>
                        <td>${formatAge(worker.last_seen_age_seconds)}</td>
                        <td><span class="table-status ${statusClass(worker.status)}">${escapeHtml(worker.status || "unknown")}</span></td>
                    </tr>
                `,
            )
            .join("");
    }

    renderTargets(targets) {
        if (!Array.isArray(targets) || !targets.length) {
            this.elements.targetsTableBody.innerHTML = '<tr><td colspan="9" class="empty-state">Нет активных target heartbeat данных</td></tr>';
            return;
        }

        this.elements.targetsTableBody.innerHTML = targets
            .map(
                (target) => `
                    <tr>
                        <td class="mono">${escapeHtml(target.target_id || "-")}</td>
                        <td>${escapeHtml(target.target_kind || "-")}</td>
                        <td>${escapeHtml((target.supports_workloads || []).join(", ") || "-")}</td>
                        <td>${formatNumber(target.base_capacity_tokens)}</td>
                        <td>${Number.isFinite(Number(target.cpu_percent)) ? `${Number(target.cpu_percent).toFixed(1)}%` : "unavailable"}</td>
                        <td>${formatMegabytes(target.ram_free_mb)}</td>
                        <td>${target.vram_free_mb > 0 ? formatMegabytes(target.vram_free_mb) : "unavailable"}</td>
                        <td>${escapeHtml((target.loaded_models || []).join(", ") || "unavailable")}</td>
                        <td>${formatAge(target.last_seen_age_seconds)}</td>
                    </tr>
                `,
            )
            .join("");
    }

    renderError(error) {
        const message = error instanceof APIError ? error.message : "Dashboard data unavailable";
        this.elements.warningStrip.innerHTML = `<div class="warning-pill">${escapeHtml(message)}</div>`;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const bootstrap = parseBootstrap();
    if (!bootstrap) {
        return;
    }
    const app = new AdminDashboardApp(bootstrap);
    void app.init();
});
