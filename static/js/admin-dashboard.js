import { APIClient, APIError } from "./api-client.js";

const DEFAULT_REFRESH_MS = 8000;

const STATUS_TEXT = {
    ready: "Норма",
    degraded: "Внимание",
    not_ready: "Не готова",
    ok: "Базовые компоненты отвечают",
    healthy: "Актуален",
    stale: "Устарел",
    working: "Работает",
    idle: "Ожидает задачи",
    online: "Доступна",
};

const WORKLOAD_LABELS = {
    chat: "chat",
    parse: "parser",
    siem: "siem",
    batch: "batch",
};

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

export function formatNumber(value, fallback = "Нет данных") {
    return Number.isFinite(Number(value)) ? new Intl.NumberFormat("ru-RU").format(Number(value)) : fallback;
}

export function formatLatency(value) {
    return Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)} мс` : "Нет данных";
}

export function formatAge(value) {
    if (!Number.isFinite(Number(value))) {
        return "Нет данных";
    }

    const seconds = Math.max(0, Math.floor(Number(value)));
    if (seconds < 60) {
        return `${seconds} с`;
    }

    const minutes = Math.floor(seconds / 60);
    const restSeconds = seconds % 60;
    if (minutes < 60) {
        return restSeconds ? `${minutes} мин ${restSeconds} с` : `${minutes} мин`;
    }

    const hours = Math.floor(minutes / 60);
    const restMinutes = minutes % 60;
    return restMinutes ? `${hours} ч ${restMinutes} мин` : `${hours} ч`;
}

export function formatTimestamp(value) {
    if (!value) {
        return "Нет данных";
    }
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return String(value);
    }
    return parsed.toLocaleString("ru-RU", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
    });
}

export function severityClass(level) {
    const normalized = String(level || "neutral").toLowerCase();
    if (normalized === "ok") {
        return "severity-ok";
    }
    if (normalized === "warn") {
        return "severity-warn";
    }
    if (normalized === "critical") {
        return "severity-critical";
    }
    return "severity-neutral";
}

export function humanizeWorkload(workload) {
    return WORKLOAD_LABELS[String(workload || "").toLowerCase()] || String(workload || "unknown");
}

function statusText(status) {
    return STATUS_TEXT[String(status || "").toLowerCase()] || String(status || "Нет данных");
}

function queueSeverity(summary) {
    const queueDepth = Number(summary.queue_depth || 0);
    if (queueDepth <= 0) {
        return "ok";
    }
    return summary.capacity ? "warn" : "critical";
}

function capacitySeverity(summary) {
    return summary.capacity ? "ok" : "critical";
}

function workersSeverity(summary) {
    if (Number(summary.workers_total || 0) <= 0 || Number(summary.workers_working || 0) <= 0) {
        return "critical";
    }
    return "ok";
}

function targetsSeverity(summary) {
    return Number(summary.targets || 0) > 0 ? "ok" : "critical";
}

function counterSeverity(value) {
    return Number(value || 0) > 0 ? "warn" : "ok";
}

export function deriveOverallState(summary) {
    if (summary.overall_status === "ready") {
        return {
            severity: "ok",
            title: "Система готова",
            badge: "Норма",
            description:
                Number(summary.queue_depth || 0) > 0
                    ? "Система принимает chat-задачи и уже обрабатывает часть очереди."
                    : "Система готова принимать новые chat-задачи, очередь сейчас не накапливается.",
        };
    }

    if (!summary.redis || summary.scheduler_status !== "healthy" || Number(summary.workers_working || 0) <= 0) {
        return {
            severity: "critical",
            title: "Требует немедленного внимания",
            badge: "Проблема",
            description: "Есть проблема в базовых компонентах или worker-path, которая может мешать штатной обработке chat-задач.",
        };
    }

    if (!summary.capacity) {
        return {
            severity: Number(summary.chat_backlog || 0) > 0 ? "critical" : "warn",
            title: "Есть ограничения по мощности",
            badge: "Внимание",
            description: "Сервис отвечает, но новые chat-задачи могут ждать в очереди из-за нехватки свободной мощности.",
        };
    }

    return {
        severity: "warn",
        title: "Состояние требует наблюдения",
        badge: "Внимание",
        description: "Базовые компоненты отвечают, но часть сигналов указывает, что системе нужно внимание оператора.",
    };
}

export function buildOperationalSummary(summary) {
    const queueDepth = Number(summary.queue_depth || 0);
    const chatBacklog = Number(summary.chat_backlog || 0);
    const parserBacklog = Number(summary.parser_backlog || 0);
    return [
        {
            label: "Что происходит сейчас",
            value: deriveOverallState(summary).title,
            detail: deriveOverallState(summary).description,
            severity: deriveOverallState(summary).severity,
        },
        {
            label: "Очереди",
            value: queueDepth > 0 ? `${formatNumber(queueDepth)} задач` : "Очереди пусты",
            detail:
                queueDepth > 0
                    ? `chat: ${formatNumber(chatBacklog)} · parser: ${formatNumber(parserBacklog)}`
                    : "Новых задач в ожидании нет",
            severity: queueSeverity(summary),
        },
        {
            label: "Свободная мощность",
            value: summary.capacity ? "Есть запас" : "Запас исчерпан",
            detail: summary.capacity ? "Новые chat-задачи могут приниматься штатно" : "Новые chat-задачи могут ждать admission",
            severity: capacitySeverity(summary),
        },
        {
            label: "Воркеры и цели",
            value: `${formatNumber(summary.workers_working)} / ${formatNumber(summary.workers_total)} воркеров · ${formatNumber(summary.targets)} целей`,
            detail: "Показывает, есть ли живые исполнители и доступные цели для admission",
            severity: workersSeverity(summary) === "critical" || targetsSeverity(summary) === "critical" ? "critical" : "ok",
        },
    ];
}

export function buildKpiCards(summary) {
    return [
        {
            label: "Всего задач в очередях",
            value: formatNumber(summary.queue_depth),
            help: "Сколько задач ещё ждут admission/start и не начали выполняться.",
            severity: queueSeverity(summary),
        },
        {
            label: "Задач в обработке",
            value: formatNumber(summary.active_jobs),
            help: "Сколько задач уже находятся в active runtime state.",
            severity: Number(summary.active_jobs || 0) > 0 ? "ok" : "neutral",
        },
        {
            label: "Активно работают / всего воркеров",
            value: `${formatNumber(summary.workers_working)} / ${formatNumber(summary.workers_total)}`,
            help: "Worker — процесс, который забирает задачу из dispatch и выполняет её.",
            severity: workersSeverity(summary),
        },
        {
            label: "Доступные вычислительные цели",
            value: formatNumber(summary.targets),
            help: "Target — цель исполнения, на которую scheduler может допустить задачу.",
            severity: targetsSeverity(summary),
        },
        {
            label: "Ошибки обработки",
            value: formatNumber(summary.failures),
            help: "Накопительный счётчик завершений с ошибкой в текущем runtime.",
            severity: counterSeverity(summary.failures),
        },
        {
            label: "Отклонённые запросы",
            value: formatNumber(summary.rejected),
            help: "Сколько задач было отклонено admission-логикой.",
            severity: counterSeverity(summary.rejected),
        },
        {
            label: "Среднее время обработки",
            value: formatLatency(summary.avg_latency_ms),
            help: "Считается только если реально есть latency counters; иначе показываем 'Нет данных'.",
            severity: Number.isFinite(Number(summary.avg_latency_ms)) ? "neutral" : "warn",
        },
        {
            label: "Свободная мощность для chat",
            value: summary.capacity ? "Есть" : "Нет",
            help: "Показывает, может ли система сейчас принять новые chat-задачи без ожидания.",
            severity: capacitySeverity(summary),
        },
    ];
}

export function buildAlertItems(summary) {
    const items = [];

    if (!summary.redis) {
        items.push({
            severity: "critical",
            title: "Redis недоступен",
            detail: "Control-plane состояние и очереди могут быть недоступны или неполными.",
            recommendation: "Проверьте состояние Redis и сетевую доступность приложения к нему.",
        });
    }

    if (summary.scheduler_status !== "healthy") {
        items.push({
            severity: "critical",
            title: "Данные scheduler устарели",
            detail: `Последний heartbeat планировщика: ${formatAge(summary.scheduler_age_seconds)} назад.`,
            recommendation: "Проверьте heartbeat и логи scheduler: без актуального scheduler admission может быть непредсказуем.",
        });
    }

    if (Number(summary.workers_working || 0) <= 0) {
        items.push({
            severity: "critical",
            title: "Нет активных chat workers",
            detail: "Даже если сервис отвечает, новые chat-задачи могут застрять до этапа реальной обработки.",
            recommendation: "Проверьте chat worker heartbeat, binding к target и его runtime-состояние.",
        });
    }

    if (!summary.capacity) {
        items.push({
            severity: Number(summary.chat_backlog || 0) > 0 ? "critical" : "warn",
            title: "Свободная мощность для chat сейчас недоступна",
            detail: "Новые chat-задачи сейчас могут ждать admission и дольше оставаться в очереди.",
            recommendation: "Сверьте backlog, количество working workers и доступные targets.",
        });
    }

    if (Number(summary.chat_backlog || 0) > 0) {
        items.push({
            severity: summary.capacity ? "warn" : "critical",
            title: `Есть ожидающие chat-задачи: ${formatNumber(summary.chat_backlog)}`,
            detail: "Часть пользовательских chat-запросов ещё не начала выполняться.",
            recommendation: "Следите за ростом очереди и проверьте, есть ли свободная мощность для новых задач.",
        });
    }

    if (Number(summary.parser_backlog || 0) > 0) {
        items.push({
            severity: "warn",
            title: `Есть parser backlog: ${formatNumber(summary.parser_backlog)}`,
            detail: "Задачи разбора документов ожидают своего выполнения.",
            recommendation: "Если backlog растёт, проверьте parser pool и текущую загрузку document path.",
        });
    }

    if (Number(summary.failures || 0) > 0) {
        items.push({
            severity: "warn",
            title: `Есть ошибки обработки: ${formatNumber(summary.failures)}`,
            detail: "Runtime уже зафиксировал завершения с ошибкой.",
            recommendation: "Проверьте свежие ошибки в assistant / worker / scheduler логах и сравните с queue state.",
        });
    }

    if (Number(summary.rejected || 0) > 0) {
        items.push({
            severity: "warn",
            title: `Есть отклонённые запросы: ${formatNumber(summary.rejected)}`,
            detail: "Admission logic уже отклоняла часть задач.",
            recommendation: "Сопоставьте объём очереди с доступной мощностью и admission pressure.",
        });
    }

    if (!items.length) {
        items.push({
            severity: "ok",
            title: "Критических предупреждений нет",
            detail: "По текущим runtime-полям система выглядит штатно: базовые компоненты отвечают, а очередь не сигнализирует о проблеме.",
            recommendation: "Продолжайте наблюдать за queue depth, capacity и heartbeat, но срочных действий не требуется.",
        });
    }

    return items;
}

export function buildRuntimeRows(summary) {
    const activeModels = Array.isArray(summary.active_models) && summary.active_models.length
        ? summary.active_models.join(", ")
        : "Нет данных";

    return [
        {
            label: "Готовность системы",
            value: summary.readiness_status === "ready" ? "Готова принимать chat-задачи" : "Сейчас не готова принимать новые chat-задачи",
            help: "Readiness учитывает Redis, scheduler, активные chat workers и свободную мощность.",
            severity: summary.readiness_status === "ready" ? "ok" : "critical",
        },
        {
            label: "Жизнеспособность",
            value: summary.health_status === "ok" ? "Базовые компоненты отвечают" : "Есть проблема в базовых компонентах",
            help: "Health показывает базовую доступность runtime даже если мощности для новых задач может не хватать.",
            severity: summary.health_status === "ok" ? "ok" : "critical",
        },
        {
            label: "Планировщик",
            value: summary.scheduler_status === "healthy" ? "Heartbeat актуален" : "Heartbeat устарел",
            help: "Scheduler управляет admission и dispatch, поэтому stale heartbeat требует отдельной проверки.",
            severity: summary.scheduler_status === "healthy" ? "ok" : "critical",
        },
        {
            label: "Возраст heartbeat планировщика",
            value: formatAge(summary.scheduler_age_seconds),
            help: "Чем больше возраст, тем выше риск, что информация scheduler уже неактуальна.",
            severity: summary.scheduler_status === "healthy" ? "neutral" : "warn",
        },
        {
            label: "Свободная мощность",
            value: summary.capacity ? "Есть запас для новых chat-задач" : "Новые chat-задачи могут ждать admission",
            help: "Capacity относится только к chat workload и не означает отсутствие других очередей.",
            severity: capacitySeverity(summary),
        },
        {
            label: "Активные модели",
            value: activeModels,
            help: "Показываются только модели, которые реально reported активными целями. Если данных нет, мы это не скрываем.",
            severity: activeModels === "Нет данных" ? "warn" : "neutral",
        },
        {
            label: "Последнее обновление панели",
            value: formatTimestamp(summary.last_refresh),
            help: "Панель автоматически обновляется и всегда показывает только последнее полученное состояние.",
            severity: "neutral",
        },
    ];
}

export function buildQueueOverview(summary) {
    return [
        {
            label: "Всего в очередях",
            value: formatNumber(summary.queue_depth),
            detail: "Все pending queues по workloads и приоритетам",
            severity: queueSeverity(summary),
        },
        {
            label: "Chat backlog",
            value: formatNumber(summary.chat_backlog),
            detail: "Сколько chat-задач ждёт admission/start",
            severity: Number(summary.chat_backlog || 0) > 0 ? (summary.capacity ? "warn" : "critical") : "ok",
        },
        {
            label: "Parser backlog",
            value: formatNumber(summary.parser_backlog),
            detail: "Сколько document/parser задач ещё ждёт обработки",
            severity: Number(summary.parser_backlog || 0) > 0 ? "warn" : "ok",
        },
    ];
}

export function buildQueueEntries(summary) {
    return Object.entries(summary.pending || {}).map(([queueKey, count]) => {
        const [workload, priority = ""] = queueKey.split(":");
        const numericCount = Number(count || 0);
        return {
            queueKey,
            title: `${humanizeWorkload(workload)} · приоритет ${priority || "n/a"}`,
            value: numericCount,
            help: numericCount > 0 ? "В этой очереди есть ожидающие задачи." : "Ожидающих задач сейчас нет.",
            severity: numericCount > 0 ? (workload === "chat" && !summary.capacity ? "critical" : "warn") : "ok",
        };
    });
}

export function buildWorkloadEntries(summary) {
    return Object.entries(summary.by_workload || {}).map(([workload, payload]) => {
        const priorities = Object.entries(payload.by_priority || {})
            .map(([priority, count]) => `${priority}: ${formatNumber(count)}`)
            .join(" · ");
        return {
            workload: humanizeWorkload(workload),
            total: Number(payload.total || 0),
            priorities: priorities || "Нет разбивки по приоритетам",
            severity: Number(payload.total || 0) > 0 ? (workload === "chat" && !summary.capacity ? "critical" : "warn") : "ok",
        };
    });
}

function renderChips(items, { mutedFallback = "Нет данных" } = {}) {
    const values = Array.isArray(items) ? items.filter((item) => String(item || "").trim()) : [];
    if (!values.length) {
        return `<span class="chip chip--muted">${escapeHtml(mutedFallback)}</span>`;
    }
    return values.map((item) => `<span class="chip">${escapeHtml(item)}</span>`).join("");
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
            heroMeaning: document.getElementById("heroMeaning"),
            overallStatusTitle: document.getElementById("overallStatusTitle"),
            overallStatusBadge: document.getElementById("overallStatusBadge"),
            schedulerHealthBadge: document.getElementById("schedulerHealthBadge"),
            statusSupportText: document.getElementById("statusSupportText"),
            lastRefreshLabel: document.getElementById("lastRefreshLabel"),
            readinessStatusValue: document.getElementById("readinessStatusValue"),
            healthStatusValue: document.getElementById("healthStatusValue"),
            capacityStatusValue: document.getElementById("capacityStatusValue"),
            queueStatusValue: document.getElementById("queueStatusValue"),
            operatorSummaryStrip: document.getElementById("operatorSummaryStrip"),
            kpiGrid: document.getElementById("kpiGrid"),
            alertList: document.getElementById("alertList"),
            queueOverview: document.getElementById("queueOverview"),
            queueBreakdown: document.getElementById("queueBreakdown"),
            workloadBreakdown: document.getElementById("workloadBreakdown"),
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
        }, Math.max(5000, Number(this.bootstrap.refreshIntervalMs) || DEFAULT_REFRESH_MS));
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
        const overall = deriveOverallState(summary);
        const schedulerSeverity = summary.scheduler_status === "healthy" ? "ok" : "critical";
        this.elements.heroMeaning.textContent = overall.description;
        this.elements.overallStatusTitle.textContent = overall.title;
        this.elements.overallStatusBadge.className = `status-badge ${severityClass(overall.severity)}`;
        this.elements.overallStatusBadge.textContent = overall.badge;
        this.elements.schedulerHealthBadge.className = `status-badge ${severityClass(schedulerSeverity)}`;
        this.elements.schedulerHealthBadge.textContent =
            summary.scheduler_status === "healthy"
                ? `Планировщик актуален · ${formatAge(summary.scheduler_age_seconds)}`
                : `Планировщик устарел · ${formatAge(summary.scheduler_age_seconds)}`;
        this.elements.statusSupportText.textContent =
            summary.overall_status === "ready"
                ? "Система выглядит готовой к приёму новых chat-задач. Ниже можно быстро понять, где есть очередь и какой запас мощности остаётся."
                : "Ниже показано, что именно мешает штатной работе: очередь, мощность, воркеры, цели или свежесть scheduler heartbeat.";
        this.elements.lastRefreshLabel.textContent = formatTimestamp(summary.last_refresh);
        this.elements.readinessStatusValue.textContent =
            summary.readiness_status === "ready" ? "Готова" : "Не готова";
        this.elements.healthStatusValue.textContent =
            summary.health_status === "ok" ? "Базовые компоненты отвечают" : "Есть проблемы";
        this.elements.capacityStatusValue.textContent =
            summary.capacity ? "Есть запас" : "Запас исчерпан";
        this.elements.queueStatusValue.textContent =
            Number(summary.queue_depth || 0) > 0
                ? `${formatNumber(summary.queue_depth)} в ожидании`
                : "Очереди пусты";

        this.renderSummaryStrip(summary);
        this.renderKpis(summary);
        this.renderAlerts(summary);
        this.renderQueueOverview(summary);
        this.renderQueueBreakdown(summary);
        this.renderWorkloadBreakdown(summary);
        this.renderRuntimeSummary(summary);
        this.renderWorkers(summary.worker_rows || []);
        this.renderTargets(summary.target_rows || []);
    }

    renderSummaryStrip(summary) {
        this.elements.operatorSummaryStrip.innerHTML = buildOperationalSummary(summary)
            .map(
                (item) => `
                    <article class="summary-card ${severityClass(item.severity)}">
                        <div class="summary-label">${escapeHtml(item.label)}</div>
                        <div class="summary-value">${escapeHtml(item.value)}</div>
                        <div class="summary-detail">${escapeHtml(item.detail)}</div>
                    </article>
                `,
            )
            .join("");
    }

    renderKpis(summary) {
        this.elements.kpiGrid.innerHTML = buildKpiCards(summary)
            .map(
                (item) => `
                    <article class="kpi-card ${severityClass(item.severity)}">
                        <div class="kpi-label">${escapeHtml(item.label)}</div>
                        <div class="kpi-value">${escapeHtml(item.value)}</div>
                        <div class="kpi-help">${escapeHtml(item.help)}</div>
                    </article>
                `,
            )
            .join("");
    }

    renderAlerts(summary) {
        this.elements.alertList.innerHTML = buildAlertItems(summary)
            .map(
                (item) => `
                    <article class="alert-card ${severityClass(item.severity)}">
                        <div class="alert-title">
                            <span class="alert-title-dot"></span>
                            ${escapeHtml(item.title)}
                        </div>
                        <div class="alert-detail">${escapeHtml(item.detail)}</div>
                        <div class="alert-recommendation">${escapeHtml(item.recommendation)}</div>
                    </article>
                `,
            )
            .join("");
    }

    renderQueueOverview(summary) {
        this.elements.queueOverview.innerHTML = buildQueueOverview(summary)
            .map(
                (item) => `
                    <article class="summary-card ${severityClass(item.severity)}">
                        <div class="summary-label">${escapeHtml(item.label)}</div>
                        <div class="summary-value">${escapeHtml(item.value)}</div>
                        <div class="summary-detail">${escapeHtml(item.detail)}</div>
                    </article>
                `,
            )
            .join("");
    }

    renderQueueBreakdown(summary) {
        const items = buildQueueEntries(summary);
        if (!items.length) {
            this.elements.queueBreakdown.innerHTML = '<div class="empty-state">Нет данных по очередям</div>';
            return;
        }

        this.elements.queueBreakdown.innerHTML = items
            .map(
                (item) => `
                    <article class="queue-card ${severityClass(item.severity)}">
                        <div class="queue-card-head">
                            <div class="queue-key">${escapeHtml(item.title)}</div>
                            <div class="queue-value">${formatNumber(item.value)}</div>
                        </div>
                        <div class="queue-raw">${escapeHtml(item.queueKey)}</div>
                        <div class="queue-help">${escapeHtml(item.help)}</div>
                    </article>
                `,
            )
            .join("");
    }

    renderWorkloadBreakdown(summary) {
        const items = buildWorkloadEntries(summary);
        if (!items.length) {
            this.elements.workloadBreakdown.innerHTML = '<div class="empty-state">Нет breakdown по workload</div>';
            return;
        }

        this.elements.workloadBreakdown.innerHTML = items
            .map(
                (item) => `
                    <article class="queue-card ${severityClass(item.severity)}">
                        <div class="queue-card-head">
                            <div class="queue-key">${escapeHtml(item.workload)}</div>
                            <div class="queue-value">${formatNumber(item.total)}</div>
                        </div>
                        <div class="queue-help">${escapeHtml(item.priorities)}</div>
                    </article>
                `,
            )
            .join("");
    }

    renderRuntimeSummary(summary) {
        this.elements.runtimeSummary.innerHTML = buildRuntimeRows(summary)
            .map(
                (item) => `
                    <article class="runtime-card ${severityClass(item.severity)}">
                        <div class="runtime-card-head">
                            <div class="runtime-key">${escapeHtml(item.label)}</div>
                            <div class="runtime-value">${escapeHtml(item.value)}</div>
                        </div>
                        <div class="runtime-help">${escapeHtml(item.help)}</div>
                    </article>
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
            .map((worker) => {
                const severity =
                    worker.status === "working"
                        ? "ok"
                        : worker.status === "idle"
                            ? "warn"
                            : "critical";
                return `
                    <tr>
                        <td>
                            <div class="table-primary">
                                <strong class="mono">${escapeHtml(worker.worker_id || "-")}</strong>
                            </div>
                        </td>
                        <td>${escapeHtml(worker.pool || "-")}</td>
                        <td class="mono">${escapeHtml(worker.target_id || "-")}</td>
                        <td>${escapeHtml(worker.target_kind || "-")}</td>
                        <td>${formatNumber(worker.active_jobs)}</td>
                        <td>${formatAge(worker.last_seen_age_seconds)}</td>
                        <td><span class="table-badge ${severityClass(severity)}">${escapeHtml(statusText(worker.status))}</span></td>
                    </tr>
                `;
            })
            .join("");
    }

    renderTargets(targets) {
        if (!Array.isArray(targets) || !targets.length) {
            this.elements.targetsTableBody.innerHTML = '<tr><td colspan="9" class="empty-state">Нет активных target heartbeat данных</td></tr>';
            return;
        }

        this.elements.targetsTableBody.innerHTML = targets
            .map((target) => {
                const severity = target.status === "online" ? "ok" : "critical";
                return `
                    <tr>
                        <td>
                            <div class="table-primary">
                                <strong class="mono">${escapeHtml(target.target_id || "-")}</strong>
                                <div class="table-secondary"><span class="table-badge ${severityClass(severity)}">${escapeHtml(statusText(target.status))}</span></div>
                            </div>
                        </td>
                        <td>${escapeHtml(target.target_kind || "-")}</td>
                        <td><div class="chip-row">${renderChips(target.supports_workloads, { mutedFallback: "Нет данных" })}</div></td>
                        <td>${formatNumber(target.base_capacity_tokens)}</td>
                        <td>${Number.isFinite(Number(target.cpu_percent)) ? `${Number(target.cpu_percent).toFixed(1)}%` : "Нет данных"}</td>
                        <td>${Number(target.ram_free_mb || 0) > 0 ? `${formatNumber(target.ram_free_mb)} MB` : "Нет данных"}</td>
                        <td>${Number(target.vram_free_mb || 0) > 0 ? `${formatNumber(target.vram_free_mb)} MB` : "Нет данных"}</td>
                        <td><div class="chip-row">${renderChips(target.loaded_models, { mutedFallback: "Нет данных" })}</div></td>
                        <td>${formatAge(target.last_seen_age_seconds)}</td>
                    </tr>
                `;
            })
            .join("");
    }

    renderError(error) {
        const message = error instanceof APIError ? error.message : "Не удалось обновить операторскую сводку";
        this.elements.heroMeaning.textContent = "Панель не смогла получить новую сводку. Последние данные могли устареть.";
        this.elements.overallStatusTitle.textContent = "Сводка недоступна";
        this.elements.overallStatusBadge.className = `status-badge ${severityClass("critical")}`;
        this.elements.overallStatusBadge.textContent = "Ошибка";
        this.elements.alertList.innerHTML = `
            <article class="alert-card ${severityClass("critical")}">
                <div class="alert-title">
                    <span class="alert-title-dot"></span>
                    Не удалось обновить dashboard
                </div>
                <div class="alert-detail">${escapeHtml(message)}</div>
                <div class="alert-recommendation">Проверьте доступность dashboard API и состояние runtime.</div>
            </article>
        `;
    }
}

if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", () => {
        const bootstrap = parseBootstrap();
        if (!bootstrap) {
            return;
        }
        const app = new AdminDashboardApp(bootstrap);
        void app.init();
    });
}
