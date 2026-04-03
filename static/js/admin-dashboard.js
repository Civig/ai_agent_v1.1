import { APIClient, APIError } from "./api-client.js";

function getCsrfToken() {
    const match = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
}

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

function formatNumber(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return "—";
    }
    return new Intl.NumberFormat("ru-RU").format(Number(value));
}

function formatTimestamp(value) {
    if (!value) {
        return "—";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return "—";
    }
    return new Intl.DateTimeFormat("ru-RU", {
        dateStyle: "short",
        timeStyle: "medium",
        timeZone: "UTC",
    }).format(date) + " UTC";
}

function formatLastSeen(seconds) {
    if (seconds === null || seconds === undefined) {
        return "—";
    }
    if (seconds < 60) {
        return `${seconds} сек назад`;
    }
    const minutes = Math.floor(seconds / 60);
    return `${minutes} мин назад`;
}

function formatLatency(value) {
    if (value === null || value === undefined) {
        return "Недоступно";
    }
    return `${formatNumber(value)} ms`;
}

function renderCollection(container, items, renderItem, emptyMessage) {
    if (!container) {
        return;
    }
    if (!Array.isArray(items) || items.length === 0) {
        container.innerHTML = `<div class="empty-state">${emptyMessage}</div>`;
        return;
    }
    container.replaceChildren(...items.map(renderItem));
}

class AdminDashboardApp {
    constructor(bootstrap) {
        this.bootstrap = bootstrap;
        this.apiClient = new APIClient({
            getCsrfToken: () => getCsrfToken(),
            onUnauthorized: () => {
                window.location.href = "/login";
            },
        });
        this.refreshTimer = null;
        this.elements = {
            error: document.getElementById("adminDashboardError"),
            lastRefresh: document.getElementById("adminLastRefresh"),
            overallStatus: document.getElementById("adminOverallStatus"),
            summaryQueueDepth: document.getElementById("summaryQueueDepth"),
            summaryActiveJobs: document.getElementById("summaryActiveJobs"),
            summaryWorkers: document.getElementById("summaryWorkers"),
            summaryTargets: document.getElementById("summaryTargets"),
            summaryFailures: document.getElementById("summaryFailures"),
            chatBacklogValue: document.getElementById("chatBacklogValue"),
            parserBacklogValue: document.getElementById("parserBacklogValue"),
            pendingQueuesList: document.getElementById("pendingQueuesList"),
            healthStatusValue: document.getElementById("healthStatusValue"),
            schedulerStatusValue: document.getElementById("schedulerStatusValue"),
            capacityValue: document.getElementById("capacityValue"),
            avgLatencyValue: document.getElementById("avgLatencyValue"),
            activeModelsList: document.getElementById("activeModelsList"),
            workersMeta: document.getElementById("workersMeta"),
            workersTableBody: document.getElementById("workersTableBody"),
            targetsGrid: document.getElementById("targetsGrid"),
        };
    }

    async init() {
        await this.refresh();
        const interval = Number(this.bootstrap?.refreshIntervalMs || 0);
        if (interval > 0) {
            this.refreshTimer = window.setInterval(() => {
                this.refresh().catch((error) => {
                    console.error("Dashboard refresh failed:", error);
                });
            }, interval);
        }
    }

    async refresh() {
        try {
            const payload = await this.apiClient.requestJSON(this.bootstrap.apiUrl, { method: "GET", timeout: 10000 });
            this.render(payload);
            this.hideError();
        } catch (error) {
            const message = error instanceof APIError ? `${error.message} (HTTP ${error.status})` : "Не удалось обновить dashboard";
            this.showError(message);
        }
    }

    render(payload) {
        const summary = payload.summary || {};
        const queues = payload.queues || {};
        const metrics = payload.metrics || {};
        const health = payload.health || {};

        this.elements.lastRefresh.textContent = formatTimestamp(payload.last_refresh);
        this.elements.overallStatus.textContent = this.describeStatus(payload.overall_status);
        this.elements.overallStatus.dataset.status = payload.overall_status || "degraded";

        this.elements.summaryQueueDepth.textContent = formatNumber(summary.queue_depth);
        this.elements.summaryActiveJobs.textContent = formatNumber(summary.active_jobs);
        this.elements.summaryWorkers.textContent = `${formatNumber(summary.workers_working)} / ${formatNumber(summary.workers_total)}`;
        this.elements.summaryTargets.textContent = formatNumber(summary.targets);
        this.elements.summaryFailures.textContent = `${formatNumber(summary.failed_jobs)} / ${formatNumber(summary.rejected_jobs)}`;

        this.elements.chatBacklogValue.textContent = formatNumber(queues.chat_backlog);
        this.elements.parserBacklogValue.textContent = formatNumber(queues.parser_backlog);

        this.elements.healthStatusValue.textContent = health.status || "—";
        this.elements.schedulerStatusValue.textContent = this.describeScheduler(health.scheduler, health.scheduler_age_seconds);
        this.elements.capacityValue.textContent = health.capacity ? "Available" : "Constrained";
        this.elements.avgLatencyValue.textContent = formatLatency(metrics.avg_latency_ms);
        this.elements.workersMeta.textContent = `${formatNumber(summary.workers_working)} активных worker(-ов) на ${formatNumber(summary.targets)} target(-ах)`;

        renderCollection(
            this.elements.pendingQueuesList,
            Object.entries(queues.pending || {}),
            ([queueName, count]) => {
                const row = document.createElement("div");
                row.className = "queue-row";
                row.innerHTML = `
                    <span class="queue-row-label">${queueName}</span>
                    <span class="queue-row-value">${formatNumber(count)}</span>
                `;
                return row;
            },
            "Pending queues пока не reported.",
        );

        renderCollection(
            this.elements.activeModelsList,
            metrics.active_models || [],
            (modelName) => {
                const row = document.createElement("div");
                row.className = "metric-row";
                row.innerHTML = `
                    <span class="metric-row-label">${modelName}</span>
                    <span class="metric-row-value">reported by targets</span>
                `;
                return row;
            },
            "Нет данных о загруженных моделях.",
        );

        this.renderWorkers(payload.workers || []);
        renderCollection(
            this.elements.targetsGrid,
            payload.targets || [],
            (target) => {
                const card = document.createElement("article");
                card.className = "target-card";
                card.innerHTML = `
                    <div class="target-card-title">${target.target_id}</div>
                    <div class="target-card-subtitle">${target.target_kind} / ${target.runtime_label}</div>
                    <div class="target-card-metrics">
                        <div>Capacity tokens: ${formatNumber(target.base_capacity_tokens)}</div>
                        <div>Supports: ${(target.supports_workloads || []).join(", ") || "—"}</div>
                        <div>Loaded models: ${(target.loaded_models || []).join(", ") || "Нет данных"}</div>
                        <div>CPU: ${formatNumber(target.cpu_percent)}%</div>
                        <div>RAM free: ${formatNumber(target.ram_free_mb)} MB</div>
                        <div>VRAM free: ${formatNumber(target.vram_free_mb)} MB</div>
                        <div>Last seen: ${formatLastSeen(target.last_seen_age_seconds)}</div>
                    </div>
                `;
                return card;
            },
            "Активные targets сейчас не reported.",
        );
    }

    renderWorkers(workers) {
        const tbody = this.elements.workersTableBody;
        if (!tbody) {
            return;
        }
        if (!Array.isArray(workers) || workers.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state">Активные workers сейчас не reported.</div></td></tr>`;
            return;
        }
        const rows = workers.map((worker) => {
            const row = document.createElement("tr");
            row.innerHTML = `
                <td>${worker.worker_id}</td>
                <td>${worker.worker_pool}</td>
                <td><span class="worker-status" data-status="${worker.status}">${worker.status}</span></td>
                <td>${worker.target_id || "—"}</td>
                <td>${worker.target_kind}</td>
                <td>${formatNumber(worker.active_jobs)}</td>
                <td>${formatLastSeen(worker.last_seen_age_seconds)}</td>
            `;
            return row;
        });
        tbody.replaceChildren(...rows);
    }

    describeStatus(status) {
        if (status === "ready") {
            return "Готов к приёму нагрузки";
        }
        if (status === "not_ready") {
            return "Не готов";
        }
        return "Деградирован, но жив";
    }

    describeScheduler(status, ageSeconds) {
        if (status === "healthy") {
            return ageSeconds === null || ageSeconds === undefined
                ? "healthy"
                : `healthy • ${formatLastSeen(ageSeconds)}`;
        }
        return ageSeconds === null || ageSeconds === undefined
            ? "stale"
            : `stale • ${formatLastSeen(ageSeconds)}`;
    }

    showError(message) {
        if (!this.elements.error) {
            return;
        }
        this.elements.error.hidden = false;
        this.elements.error.textContent = message;
    }

    hideError() {
        if (!this.elements.error) {
            return;
        }
        this.elements.error.hidden = true;
        this.elements.error.textContent = "";
    }
}

document.addEventListener("DOMContentLoaded", async () => {
    const bootstrap = parseBootstrap();
    if (!bootstrap?.apiUrl) {
        return;
    }

    const app = new AdminDashboardApp(bootstrap);
    await app.init();
});
