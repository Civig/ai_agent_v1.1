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
    const numeric = Number(value);
    return Number.isFinite(numeric) && numeric > 0 ? `${numeric.toFixed(1)} мс` : "Нет данных";
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

export function formatBytesPerSecond(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric < 0) {
        return "Нет данных";
    }
    if (numeric < 1024) {
        return `${numeric.toFixed(0)} B/s`;
    }
    if (numeric < 1024 * 1024) {
        return `${(numeric / 1024).toFixed(1)} KB/s`;
    }
    if (numeric < 1024 * 1024 * 1024) {
        return `${(numeric / (1024 * 1024)).toFixed(1)} MB/s`;
    }
    return `${(numeric / (1024 * 1024 * 1024)).toFixed(2)} GB/s`;
}

function formatMetricValue(value, unit) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
        return "Нет данных";
    }
    if (unit === "percent") {
        return `${numeric.toFixed(1)}%`;
    }
    if (unit === "mb") {
        return `${formatNumber(numeric)} MB`;
    }
    if (unit === "bytes_per_sec") {
        return formatBytesPerSecond(numeric);
    }
    return formatNumber(numeric);
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

function workersSeverity(summary) {
    if (Number(summary.workers_total || 0) <= 0 || Number(summary.workers_working || 0) <= 0) {
        return "critical";
    }
    return "ok";
}

function targetsSeverity(summary) {
    return Number(summary.targets || 0) > 0 ? "ok" : "critical";
}

function hasSchedulerGap(summary) {
    return summary.scheduler_status !== "healthy";
}

function hasRedisGap(summary) {
    return !summary.redis;
}

function hasWorkerGap(summary) {
    return Number(summary.workers_working || 0) <= 0;
}

function hasTargetVisibilityGap(summary) {
    return Number(summary.targets || 0) <= 0;
}

function hasActiveModelVisibilityGap(summary) {
    return !Array.isArray(summary.active_models) || summary.active_models.length <= 0;
}

function queueTotals(summary) {
    return {
        queueDepth: Number(summary.queue_depth || 0),
        activeJobs: Number(summary.active_jobs || 0),
        chatBacklog: Number(summary.chat_backlog || 0),
        parserBacklog: Number(summary.parser_backlog || 0),
    };
}

export function deriveCapacityAssessment(summary) {
    const { queueDepth, activeJobs, chatBacklog } = queueTotals(summary);

    if (hasRedisGap(summary)) {
        return {
            state: "Оценка запаса недоступна",
            severity: "critical",
            reason: "Redis сейчас недоступен, поэтому оценка очередей и admission-state может быть неполной.",
        };
    }

    if (hasSchedulerGap(summary)) {
        return {
            state: "Оценка запаса недоступна",
            severity: "critical",
            reason: "Scheduler heartbeat устарел, поэтому admission-сигнал уже может не отражать реальное состояние мощности.",
        };
    }

    if (hasTargetVisibilityGap(summary)) {
        return {
            state: "Оценка запаса недоступна",
            severity: "warn",
            reason: "Не видно активных вычислительных целей, поэтому честно оценить запас для новых chat-задач нельзя.",
        };
    }

    if (summary.capacity) {
        if (queueDepth <= 0) {
            return {
                state: "Запас есть",
                severity: "ok",
                reason: "Система может принимать новые chat-задачи без ожидания в очереди.",
            };
        }
        return {
            state: "Запас ограничен",
            severity: "warn",
            reason: "Свободная chat capacity ещё reported, но очередь уже не пустая и рост нагрузки нужно наблюдать внимательнее.",
        };
    }

    if (chatBacklog > 0 || queueDepth > 0) {
        return {
            state: "Запас исчерпан",
            severity: "critical",
            reason: "Chat-задачи уже накапливаются в очереди, значит следующая chat-нагрузка почти наверняка будет ждать.",
        };
    }

    if (activeJobs > 0) {
        return {
            state: "Запас ограничен",
            severity: "warn",
            reason: "Текущая chat-мощность занята активной задачей; следующий chat-запрос может ждать освобождения этого слота.",
        };
    }

    if (hasWorkerGap(summary)) {
        return {
            state: "Запас исчерпан",
            severity: "critical",
            reason: "Сейчас нет активных chat workers, которые могли бы взять следующую задачу в обработку.",
        };
    }

    return {
        state: "Запас исчерпан",
        severity: "critical",
        reason: "Scheduler не видит свободной chat capacity для следующей задачи.",
    };
}

export function derivePrimaryBottleneck(summary) {
    const { queueDepth, activeJobs, chatBacklog } = queueTotals(summary);

    if (hasRedisGap(summary)) {
        return {
            title: "Control-plane visibility ограничена",
            detail: "Redis недоступен, поэтому runtime state и очереди могут быть отражены неполно.",
            severity: "critical",
        };
    }

    if (hasSchedulerGap(summary)) {
        return {
            title: "Планировщик публикует устаревший heartbeat",
            detail: "Без свежего scheduler heartbeat admission-state уже может быть неактуален.",
            severity: "critical",
        };
    }

    if (hasWorkerGap(summary)) {
        return {
            title: "Нет активных chat workers",
            detail: "Даже если запрос принят, без working worker он может дольше оставаться до реальной обработки.",
            severity: "critical",
        };
    }

    if (hasTargetVisibilityGap(summary)) {
        return {
            title: "Не видно активных вычислительных целей",
            detail: "Scheduler не может честно оценить запас, если в runtime не reported ни одной живой цели исполнения.",
            severity: "critical",
        };
    }

    if (!summary.capacity && chatBacklog > 0) {
        return {
            title: "Свободная chat capacity уже занята",
            detail: "Chat backlog уже появился, значит спрос на chat path превысил текущий свободный admission-запас.",
            severity: "critical",
        };
    }

    if (!summary.capacity && activeJobs > 0 && queueDepth <= 0) {
        return {
            title: "Текущая chat-мощность занята активной задачей",
            detail: "Очередь пока пустая, но следующий chat-запрос может ждать, пока освободится текущая мощность.",
            severity: "warn",
        };
    }

    if (hasActiveModelVisibilityGap(summary)) {
        return {
            title: "Нет reported active models",
            detail: "Цели видны, но активные модели не опубликованы, поэтому оператору сложнее оценить фактическую готовность target path.",
            severity: "warn",
        };
    }

    if (queueDepth > 0) {
        return {
            title: "Очередь уже формируется",
            detail: "В системе есть pending-задачи, хотя свободная chat capacity ещё reported доступной.",
            severity: "warn",
        };
    }

    return {
        title: "Явных ограничений не видно",
        detail: "По текущим полям не видно признаков bottleneck, который уже мешает новым chat-задачам.",
        severity: "ok",
    };
}

export function deriveScalingHint(summary) {
    const { queueDepth, activeJobs, chatBacklog } = queueTotals(summary);

    if (hasRedisGap(summary) || hasSchedulerGap(summary)) {
        return {
            title: "Недостаточно данных для точной оценки запаса",
            detail: "Сначала восстановите свежий control-plane сигнал, иначе говорить о масштабе роста нагрузки будет не совсем честно.",
            severity: "critical",
        };
    }

    if (hasWorkerGap(summary)) {
        return {
            title: "Сначала восстановите активные chat workers",
            detail: "Пока в системе нет working worker, дополнительная нагрузка будет только накапливаться в ожидании.",
            severity: "critical",
        };
    }

    if (hasTargetVisibilityGap(summary)) {
        return {
            title: "Сначала восстановите visibility по вычислительным целям",
            detail: "Без живых target heartbeat нельзя честно оценить, какой запас мощности остаётся для роста нагрузки.",
            severity: "critical",
        };
    }

    if (summary.capacity && queueDepth <= 0) {
        return {
            title: "Система может принимать новые chat-запросы без ожидания",
            detail: "Очередь пустая, свободная chat capacity есть, поэтому текущий запас выглядит нормальным.",
            severity: "ok",
        };
    }

    if (summary.capacity && queueDepth > 0) {
        return {
            title: "Система пока выдерживает нагрузку, но запас уже не пустой",
            detail: "Новые chat-задачи ещё могут приниматься, однако рост очереди стоит наблюдать до появления устойчивого backlog.",
            severity: "warn",
        };
    }

    if (!summary.capacity && chatBacklog > 0) {
        return {
            title: "Chat capacity уже занята; для роста нагрузки может потребоваться дополнительная вычислительная цель",
            detail: "Backlog уже виден в chat queue, поэтому следующий рост входящих chat-запросов будет увеличивать ожидание.",
            severity: "critical",
        };
    }

    if (!summary.capacity && activeJobs > 0 && queueDepth <= 0) {
        return {
            title: "Следующий chat-запрос вероятно будет ждать освобождения текущей мощности",
            detail: "Система занята полезной работой, но резерв для следующей chat-задачи прямо сейчас не просматривается.",
            severity: "warn",
        };
    }

    return {
        title: "Точный запас оценить нельзя",
        detail: "Текущие поля не позволяют безопасно сказать, выдержит ли система рост chat-нагрузки без ожидания.",
        severity: "warn",
    };
}

export function deriveNextChatExpectation(summary) {
    const { queueDepth, activeJobs, chatBacklog } = queueTotals(summary);

    if (hasRedisGap(summary) || hasSchedulerGap(summary)) {
        return {
            title: "Нельзя честно оценить ожидание",
            detail: "Сначала нужно восстановить надёжный control-plane сигнал по scheduler и очередям.",
            severity: "critical",
        };
    }

    if (hasWorkerGap(summary)) {
        return {
            title: "Следующий chat-запрос под вопросом",
            detail: "Без active chat worker новый запрос может застрять до реальной обработки.",
            severity: "critical",
        };
    }

    if (hasTargetVisibilityGap(summary)) {
        return {
            title: "Ожидание нельзя подтвердить",
            detail: "Не видно живых target heartbeat, поэтому admission-сигнал недостаточно надёжен.",
            severity: "warn",
        };
    }

    if (summary.capacity && queueDepth <= 0) {
        return {
            title: "Примется без ожидания",
            detail: "Свободная chat capacity есть, а очередь не давит на admission.",
            severity: "ok",
        };
    }

    if (summary.capacity && queueDepth > 0) {
        return {
            title: "Вероятно примется, но очередь уже есть",
            detail: "Система ещё reported имеет запас, но ждать подтверждения admission уже может понадобиться.",
            severity: "warn",
        };
    }

    if (!summary.capacity && chatBacklog > 0) {
        return {
            title: "Будет ждать в очереди",
            detail: "Chat backlog уже появился, поэтому новый запрос почти наверняка не стартует сразу.",
            severity: "critical",
        };
    }

    if (!summary.capacity && activeJobs > 0 && queueDepth <= 0) {
        return {
            title: "Вероятно подождёт",
            detail: "Текущая chat-мощность занята активной задачей и свободный слот ещё не виден.",
            severity: "warn",
        };
    }

    return {
        title: "Ожидание не подтверждено",
        detail: "Текущие поля не дают надёжного ответа, примется ли новый chat-запрос сразу.",
        severity: "warn",
    };
}

export function deriveQueuePressure(summary) {
    const { queueDepth, activeJobs, chatBacklog, parserBacklog } = queueTotals(summary);

    if (hasRedisGap(summary)) {
        return {
            state: "Оценка давления неполна",
            detail: "Redis недоступен, поэтому queue pressure и backlog нельзя считать полностью надёжными.",
            severity: "critical",
        };
    }

    if (queueDepth <= 0 && activeJobs <= 0) {
        return {
            state: "Нет давления",
            detail: "Очередь пуста и активных задач сейчас нет: новых запросов в ожидании не видно.",
            severity: "ok",
        };
    }

    if (queueDepth <= 0 && activeJobs > 0 && !summary.capacity) {
        return {
            state: "Система занята",
            detail: "Очередь пустая, потому что задача уже выполняется, но свободной chat-мощности для следующей задачи сейчас нет.",
            severity: "warn",
        };
    }

    if (queueDepth <= 0 && activeJobs > 0 && summary.capacity) {
        return {
            state: "Под контролем",
            detail: "Задачи уже выполняются, но свободная chat capacity ещё видна и явного накопления ожидания нет.",
            severity: "ok",
        };
    }

    if (chatBacklog > 0 && !summary.capacity) {
        return {
            state: "Высокое давление",
            detail: "Chat-задачи уже ждут в очереди: admission или свободная мощность не успевают за входящим спросом.",
            severity: "critical",
        };
    }

    if (queueDepth > 0 && summary.capacity) {
        return {
            state: "Умеренное давление",
            detail: "Очередь уже есть, но система всё ещё reported имеет запас для новых chat-задач.",
            severity: "warn",
        };
    }

    if (parserBacklog > 0 && chatBacklog <= 0) {
        return {
            state: "Локальная очередь parser",
            detail: "Давление сейчас видно в parser/document path, а не в chat path.",
            severity: "warn",
        };
    }

    return {
        state: "Есть давление",
        detail: "В очередях уже есть задачи, поэтому admission и workers стоит наблюдать внимательнее.",
        severity: queueSeverity(summary),
    };
}

export function deriveReadinessView(summary) {
    const { queueDepth, activeJobs, chatBacklog } = queueTotals(summary);

    if (summary.readiness_status === "ready") {
        return {
            value: "Готовность нормальная",
            help: "Новые chat-задачи могут приниматься без явного ожидания по текущему readiness-сигналу.",
            severity: "ok",
        };
    }

    if (hasRedisGap(summary) || hasSchedulerGap(summary)) {
        return {
            value: "Готовность нарушена",
            help: "Нет надёжного control-plane сигнала, поэтому readiness нельзя считать устойчивой.",
            severity: "critical",
        };
    }

    if (hasWorkerGap(summary)) {
        return {
            value: "Готовность нарушена: нет активных chat workers",
            help: "Запросы могут быть приняты, но без active worker реальная обработка новых chat-задач не начнётся штатно.",
            severity: "critical",
        };
    }

    if (!summary.capacity && chatBacklog > 0) {
        return {
            value: "Готовность ограничена: chat-задачи уже ждут",
            help: "Система остаётся живой, но новые chat-задачи уже сталкиваются с ожиданием в очереди.",
            severity: "critical",
        };
    }

    if (!summary.capacity && activeJobs > 0 && queueDepth <= 0) {
        return {
            value: "Готовность ограничена: система занята",
            help: "Очередь ещё не растёт, но свободной chat-мощности для следующей задачи прямо сейчас нет.",
            severity: "warn",
        };
    }

    return {
        value: "Готовность ограничена",
        help: "Сервис отвечает, но не все сигналы подтверждают запас для новых chat-задач.",
        severity: "warn",
    };
}

export function deriveHealthView(summary) {
    if (summary.health_status === "ok") {
        return {
            value: "Базовые компоненты отвечают",
            help: "Health не обещает свободную мощность, но показывает, что control-plane и scheduler сейчас в живом состоянии.",
            severity: "ok",
        };
    }

    if (hasRedisGap(summary) && hasSchedulerGap(summary)) {
        return {
            value: "Проблема в Redis и scheduler",
            help: "И очереди, и admission-сигнал могут быть неполными, поэтому operator-картина уже ненадёжна.",
            severity: "critical",
        };
    }

    if (hasRedisGap(summary)) {
        return {
            value: "Проблема в Redis",
            help: "Control-plane данные по очередям и состоянию runtime могут быть неполными.",
            severity: "critical",
        };
    }

    return {
        value: "Проблема в scheduler heartbeat",
        help: "Без свежего scheduler heartbeat readiness и запас мощности могут быть оценены неточно.",
        severity: "critical",
    };
}

export function deriveOverallState(summary) {
    const { queueDepth, activeJobs, chatBacklog } = queueTotals(summary);

    if (summary.overall_status === "ready" && queueDepth <= 0 && summary.capacity) {
        return {
            severity: "ok",
            title: "Система работает штатно",
            badge: "Норма",
            description: "Система может принимать новые chat-задачи без ожидания, а очередь сейчас не сигнализирует о давлении.",
        };
    }

    if (hasRedisGap(summary)) {
        return {
            severity: "critical",
            title: "Данных недостаточно для точной оценки",
            badge: "Нет сигнала",
            description: "Redis недоступен, поэтому часть control-plane картины по очередям и запасу мощности может быть неполной.",
        };
    }

    if (hasSchedulerGap(summary)) {
        return {
            severity: "critical",
            title: "Данных недостаточно для точной оценки",
            badge: "Heartbeat устарел",
            description: "Scheduler heartbeat устарел, поэтому admission-state и оценка свободной chat capacity уже могут быть неточными.",
        };
    }

    if (hasWorkerGap(summary) || hasTargetVisibilityGap(summary)) {
        return {
            severity: "critical",
            title: "Есть деградация chat capacity",
            badge: "Нужно действие",
            description: "Видимость по worker/target path сейчас неполная или деградировала, поэтому штатная обработка новых chat-задач под вопросом.",
        };
    }

    if (summary.capacity && queueDepth > 0) {
        return {
            severity: "warn",
            title: "Система занята, но работает",
            badge: "Под нагрузкой",
            description: "Очередь уже есть, но по текущим сигналам система ещё может принимать новые chat-задачи без полного исчерпания запаса.",
        };
    }

    if (!summary.capacity && activeJobs > 0 && queueDepth <= 0 && !hasRedisGap(summary) && !hasSchedulerGap(summary) && !hasWorkerGap(summary)) {
        return {
            severity: "warn",
            title: "Система занята, но работает",
            badge: "Занята",
            description: "Очередь пока пустая, потому что задача уже выполняется, но следующая chat-задача может подождать освобождения текущей мощности.",
        };
    }

    if (!summary.capacity && chatBacklog > 0) {
        return {
            severity: "critical",
            title: "Новые chat-задачи будут ждать",
            badge: "Очередь растёт",
            description: "Свободная chat capacity уже закончилась, и backlog подтверждает, что новая chat-нагрузка накапливается в очереди.",
        };
    }

    return {
        severity: "warn",
        title: "Состояние требует наблюдения",
        badge: "Наблюдение",
        description: "Базовые компоненты отвечают, но часть сигналов уже показывает ограничения по мощности или неполную visibility runtime.",
    };
}

export function buildOperationalSummary(summary) {
    const bottleneck = derivePrimaryBottleneck(summary);
    const nextChat = deriveNextChatExpectation(summary);
    const scaling = deriveScalingHint(summary);

    return [
        {
            label: "Что ограничивает систему сейчас",
            value: bottleneck.title,
            detail: bottleneck.detail,
            severity: bottleneck.severity,
        },
        {
            label: "Следующий chat-запрос",
            value: nextChat.title,
            detail: nextChat.detail,
            severity: nextChat.severity,
        },
        {
            label: "Масштабирование",
            value: scaling.title,
            detail: scaling.detail,
            severity: scaling.severity,
        },
    ];
}

function buildTelemetryCardState(state, fallback) {
    const normalized = String(state || "").toLowerCase();
    if (normalized === "reported") {
        return { label: "reported", severity: "ok" };
    }
    if (normalized === "warming_up") {
        return { label: "прогревается", severity: "warn" };
    }
    if (normalized === "not_configured") {
        return { label: "не настроена", severity: "neutral" };
    }
    if (normalized === "runtime summary") {
        return { label: "runtime summary", severity: "neutral" };
    }
    return { label: fallback, severity: "neutral" };
}

export function buildKpiCards(summary, live = {}) {
    const overall = deriveOverallState(summary);
    const queue = deriveQueuePressure(summary);
    const capacity = deriveCapacityAssessment(summary);
    const cpuValue = Number(live?.cpu_percent);
    const ramUsed = Number(live?.ram_used_mb);
    const ramTotal = Number(live?.ram_total_mb);
    const gpuUtil = Number(live?.gpu_utilization_percent);
    const activeJobs = Number(summary.active_jobs || 0);

    const cpuState = buildTelemetryCardState(live?.cpu_availability, "нет telemetry");
    const ramState = buildTelemetryCardState(live?.ram_availability, "нет telemetry");
    const gpuState = buildTelemetryCardState(live?.gpu_availability, "нет telemetry");
    const ramRatio = Number.isFinite(ramUsed) && Number.isFinite(ramTotal) && ramTotal > 0 ? ramUsed / ramTotal : null;

    return [
        {
            label: "Состояние",
            value: overall.badge,
            help: "Главный operator-сигнал: норма, работа под нагрузкой, очередь или нехватка достоверного сигнала.",
            meta: overall.title,
            severity: overall.severity,
        },
        {
            label: "CPU",
            value: Number.isFinite(cpuValue) ? `${cpuValue.toFixed(1)}%` : "Нет данных",
            help: "Средняя CPU telemetry по online target heartbeat. При отсутствии telemetry панель не подставляет ноль.",
            meta: Number.isFinite(cpuValue) ? `Состояние telemetry: ${cpuState.label}` : "CPU telemetry unavailable",
            severity: Number.isFinite(cpuValue) ? (cpuValue >= 85 ? "warn" : "ok") : cpuState.severity,
        },
        {
            label: "RAM",
            value: Number.isFinite(ramUsed) && Number.isFinite(ramTotal) && ramTotal > 0
                ? `${formatNumber(ramUsed)} / ${formatNumber(ramTotal)} MB`
                : "Нет данных",
            help: "Использованная и общая RAM по live telemetry target path. При отсутствии signal панель показывает honest no-data.",
            meta: Number.isFinite(ramRatio)
                ? `Состояние telemetry: ${ramState.label}`
                : "RAM telemetry unavailable",
            severity: Number.isFinite(ramRatio) ? (ramRatio >= 0.85 ? "warn" : "ok") : ramState.severity,
        },
        {
            label: "GPU",
            value: Number.isFinite(gpuUtil)
                ? `${gpuUtil.toFixed(1)}%`
                : live?.gpu_availability === "not_configured"
                    ? "Не настроена"
                    : "Нет данных",
            help: "GPU utilization показывается только если GPU telemetry реально reported. Если GPU path не настроен, это видно явно.",
            meta: Number.isFinite(Number(live?.vram_free_mb))
                ? `Свободно VRAM: ${formatNumber(live.vram_free_mb)} MB`
                : `Состояние telemetry: ${gpuState.label}`,
            severity: Number.isFinite(gpuUtil)
                ? (gpuUtil >= 90 ? "warn" : "ok")
                : (live?.gpu_availability === "not_configured" ? "neutral" : gpuState.severity),
        },
        {
            label: "Очередь",
            value: formatNumber(summary.queue_depth),
            help: "Общее число pending-задач по очередям. Давление и chat backlog выводятся в подписи без фейковых выводов.",
            meta: queue.state,
            severity: queue.severity,
        },
        {
            label: "Нагрузка",
            value: activeJobs > 0 ? `${formatNumber(activeJobs)} активн.` : "0",
            help: "Сколько задач уже выполняется и есть ли подтверждённый запас для следующей chat-задачи.",
            meta: capacity.state,
            severity: capacity.severity,
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

    if (Number(summary.targets || 0) <= 0) {
        items.push({
            severity: "critical",
            title: "Не видно активных вычислительных целей",
            detail: "Target heartbeat данные отсутствуют, поэтому запас мощности и маршрут admission оцениваются неполно.",
            recommendation: "Проверьте target visibility и убедитесь, что вычислительные цели публикуют heartbeat.",
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

    if (Array.isArray(summary.active_models) && summary.active_models.length <= 0) {
        items.push({
            severity: "warn",
            title: "Нет reported active models",
            detail: "Список активных моделей пуст, поэтому готовность target path видна не полностью.",
            recommendation: "Сверьте target heartbeat и проверьте, публикуются ли loaded models там, где это ожидается.",
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
    const readiness = deriveReadinessView(summary);
    const health = deriveHealthView(summary);
    const capacity = deriveCapacityAssessment(summary);
    const scaling = deriveScalingHint(summary);
    const activeModels = Array.isArray(summary.active_models) && summary.active_models.length
        ? summary.active_models.join(", ")
        : "Нет данных";

    return [
        {
            label: "Готовность системы",
            value: readiness.value,
            help: readiness.help,
            severity: readiness.severity,
        },
        {
            label: "Жизнеспособность",
            value: health.value,
            help: health.help,
            severity: health.severity,
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
            label: "Оценка запаса для chat",
            value: capacity.state,
            help: capacity.reason,
            severity: capacity.severity,
        },
        {
            label: "Подсказка по масштабированию",
            value: scaling.title,
            help: scaling.detail,
            severity: scaling.severity,
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

export function deriveWorkerSnapshotNote(summary, workers) {
    const reportedWorking = Number(summary.workers_working || 0);
    const totalActiveJobs = Number(summary.active_jobs || 0);
    const heartbeatWorking = Array.isArray(workers)
        ? workers.filter((worker) => worker?.status === "working").length
        : 0;

    if (reportedWorking > heartbeatWorking) {
        return `Aggregate summary видит ${formatNumber(reportedWorking)} working worker, но heartbeat snapshot по строкам сейчас показывает ${formatNumber(heartbeatWorking)}. Это может кратковременно отставать от live state.`;
    }

    if (totalActiveJobs > 0 && heartbeatWorking <= 0) {
        return "Есть активные задачи, но heartbeat snapshot ещё не показал working worker. Это может быть кратковременная задержка публикации heartbeat.";
    }

    return "Статус в таблице — это heartbeat snapshot по каждому worker. Он может кратковременно отставать от aggregate summary.";
}

export function buildObservedTargetWorkloads(summary) {
    const observed = new Map();
    for (const worker of Array.isArray(summary.worker_rows) ? summary.worker_rows : []) {
        const targetId = String(worker?.target_id || "").trim();
        if (!targetId) {
            continue;
        }
        const workload = String(worker?.pool || "").trim();
        if (!workload) {
            continue;
        }
        if (!observed.has(targetId)) {
            observed.set(targetId, new Set());
        }
        observed.get(targetId).add(humanizeWorkload(workload));
    }
    return observed;
}

export function buildTargetWorkloadPresentation(summary, target) {
    const observedByTarget = buildObservedTargetWorkloads(summary);
    const targetId = String(target?.target_id || "").trim();
    const observedSet = targetId && observedByTarget.has(targetId) ? observedByTarget.get(targetId) : new Set();
    const reported = Array.isArray(target?.supports_workloads)
        ? target.supports_workloads.map((item) => humanizeWorkload(item))
        : [];
    const observed = Array.from(observedSet);

    return {
        reported,
        observed,
        note: observed.length
            ? "Capabilities показаны отдельно от наблюдаемой нагрузки по worker heartbeat."
            : "Наблюдаемая нагрузка по worker heartbeat сейчас не видна; это не означает, что target не может обслуживать chat.",
    };
}

export function deriveTargetsSectionNote(summary, targets) {
    const visibleTargets = Array.isArray(targets) ? targets.length : 0;
    const observedTargets = buildObservedTargetWorkloads(summary).size;
    if (visibleTargets <= 0) {
        return "";
    }
    if (observedTargets <= 0) {
        return "Capabilities и наблюдаемая нагрузка показаны отдельно. Если наблюдаемая нагрузка пустая, это значит только то, что worker heartbeat её сейчас не reported.";
    }
    return "Capabilities показаны отдельно от наблюдаемой нагрузки, чтобы не путать поддерживаемые workload и фактическое текущее использование.";
}

export function buildQueueOverview(summary) {
    const pressure = deriveQueuePressure(summary);
    return [
        {
            label: "Всего задач в очередях",
            value: formatNumber(summary.queue_depth),
            detail: "Все pending queues по workloads и приоритетам",
            severity: queueSeverity(summary),
        },
        {
            label: "Давление очереди",
            value: pressure.state,
            detail: pressure.detail,
            severity: pressure.severity,
        },
        {
            label: "Ожидающие chat-задачи",
            value: formatNumber(summary.chat_backlog),
            detail: "Сколько chat-задач ждёт admission/start",
            severity: Number(summary.chat_backlog || 0) > 0 ? (summary.capacity ? "warn" : "critical") : "ok",
        },
        {
            label: "Ожидающие parser-задачи",
            value: formatNumber(summary.parser_backlog),
            detail: "Сколько document/parser задач ещё ждёт обработки",
            severity: Number(summary.parser_backlog || 0) > 0 ? "warn" : "ok",
        },
    ];
}

export function buildResourceTelemetryCards(live, summary = {}) {
    const activeModels = Array.isArray(live?.active_models) ? live.active_models.filter(Boolean) : [];
    const cpuValue = Number(live?.cpu_percent);
    const queueDepth = Number(live?.queue_depth || summary.queue_depth || 0);
    const chatBacklog = Number(live?.chat_backlog || summary.chat_backlog || 0);
    const parserBacklog = Number(live?.parser_backlog || summary.parser_backlog || 0);
    const ramUsed = Number(live?.ram_used_mb);
    const ramFree = Number(live?.ram_free_mb);
    const gpuUtil = Number(live?.gpu_utilization_percent);
    const vramFree = Number(live?.vram_free_mb);
    const networkRx = Number(live?.network_rx_bytes_per_sec);
    const networkTx = Number(live?.network_tx_bytes_per_sec);

    return [
        {
            key: "cpu",
            label: "CPU",
            value: Number.isFinite(cpuValue) ? `${cpuValue.toFixed(1)}%` : "Нет данных",
            detail: Number.isFinite(cpuValue)
                ? "Средняя загрузка по online target heartbeat."
                : "CPU telemetry не reported текущим target runtime.",
            severity: Number.isFinite(cpuValue) ? (cpuValue >= 85 ? "warn" : "ok") : "neutral",
            state: live?.cpu_availability || "unavailable",
            fill: Number.isFinite(cpuValue) ? Math.max(6, Math.min(100, cpuValue)) : 0,
        },
        {
            key: "ram",
            label: "RAM",
            value: Number.isFinite(ramUsed) ? `${formatNumber(ramUsed)} MB used` : "Нет данных",
            detail: Number.isFinite(ramFree)
                ? `Свободно ${formatNumber(ramFree)} MB по reported target memory snapshot.`
                : "RAM telemetry не reported текущим target runtime.",
            severity: Number.isFinite(ramUsed) ? "ok" : "neutral",
            state: live?.ram_availability || "unavailable",
            fill: Number.isFinite(ramUsed) && Number.isFinite(Number(live?.ram_total_mb)) && Number(live.ram_total_mb) > 0
                ? Math.max(6, Math.min(100, (ramUsed / Number(live.ram_total_mb)) * 100))
                : 0,
        },
        {
            key: "gpu",
            label: "GPU / VRAM",
            value: Number.isFinite(gpuUtil) ? `${gpuUtil.toFixed(1)}%` : "Нет данных",
            detail: Number.isFinite(vramFree)
                ? `Свободно VRAM: ${formatNumber(vramFree)} MB${Number.isFinite(Number(live?.gpu_temperature_c)) ? ` · ${Number(live.gpu_temperature_c).toFixed(1)}°C` : ""}`
                : "GPU telemetry unavailable или GPU target сейчас не reported.",
            severity: Number.isFinite(gpuUtil) ? (gpuUtil >= 90 ? "warn" : "ok") : "neutral",
            state: live?.gpu_availability || "not_configured",
            fill: Number.isFinite(gpuUtil) ? Math.max(6, Math.min(100, gpuUtil)) : 0,
        },
        {
            key: "network",
            label: "Сеть",
            value: Number.isFinite(networkRx) || Number.isFinite(networkTx)
                ? `${formatBytesPerSecond(networkRx)} / ${formatBytesPerSecond(networkTx)}`
                : "Нет данных",
            detail: Number.isFinite(networkRx) || Number.isFinite(networkTx)
                ? "rx / tx по reported target runtime namespace counters."
                : "Сетевые counters ещё не прогрелись или недоступны в runtime namespace.",
            severity: Number.isFinite(networkRx) || Number.isFinite(networkTx) ? "ok" : "neutral",
            state: live?.network_availability || "unavailable",
            fill: Number.isFinite(networkRx) || Number.isFinite(networkTx) ? 52 : 0,
        },
        {
            key: "queue",
            label: "Очередь",
            value: formatNumber(queueDepth),
            detail: queueDepth > 0
                ? `chat backlog: ${formatNumber(chatBacklog)} · parser backlog: ${formatNumber(parserBacklog)}`
                : "Очередь по текущему runtime summary без признаков давления.",
            severity: queueDepth > 0 ? (summary.capacity ? "warn" : "critical") : "ok",
            state: "runtime summary",
            fill: queueDepth > 0 ? Math.min(100, 24 + queueDepth * 12) : 10,
        },
        {
            key: "models",
            label: "Активные модели",
            value: activeModels.length ? formatNumber(activeModels.length) : "Нет данных",
            detail: activeModels.length
                ? activeModels.join(", ")
                : "Active models ещё не были reported target heartbeat path.",
            severity: activeModels.length ? "ok" : "neutral",
            state: activeModels.length ? "reported" : "unavailable",
            fill: activeModels.length ? Math.min(100, 24 + activeModels.length * 14) : 0,
        },
    ];
}

export function buildResourceSecondaryFacts(live, summary = {}) {
    return [
        {
            label: "Queue pressure",
            detail: "Берётся из текущего runtime summary и admission state.",
            value: deriveQueuePressure(summary).state,
        },
        {
            label: "Sampling cadence",
            detail: "Насколько часто telemetry sampler сохраняет новую точку.",
            value: Number.isFinite(Number(live?.sampling_interval_seconds))
                ? `${formatNumber(live.sampling_interval_seconds)} с`
                : "Нет данных",
        },
        {
            label: "Network",
            detail: "Показывается только после прогрева runtime namespace counters.",
            value: Number.isFinite(Number(live?.network_rx_bytes_per_sec)) || Number.isFinite(Number(live?.network_tx_bytes_per_sec))
                ? `${formatBytesPerSecond(live?.network_rx_bytes_per_sec)} / ${formatBytesPerSecond(live?.network_tx_bytes_per_sec)}`
                : (live?.network_availability === "warming_up" ? "Телеметрия сети прогревается" : "Нет данных"),
        },
        {
            label: "Telemetry scope",
            detail: "Важно не путать target runtime telemetry с гарантированным host-level observability.",
            value: live?.telemetry_scope || "Нет данных",
        },
    ];
}

export function buildHistoryViewModel(historyPayload, range) {
    const labels = {
        "1h": "1 час",
        "6h": "6 часов",
        "24h": "24 часа",
    };
    const normalizedRange = labels[range] ? range : "24h";
    const pointCount = Number(historyPayload?.point_count || 0);
    if (pointCount <= 0) {
        return {
            rangeLabel: labels[normalizedRange],
            note: `Нет сохранённых telemetry samples за диапазон «${labels[normalizedRange]}».`,
            title: "Нет данных за выбранный диапазон",
            detail: "История строится только из реально сохранённых samples. Backend не подставляет synthetic series.",
        };
    }
    return {
        rangeLabel: labels[normalizedRange],
        note: `Загружено ${formatNumber(pointCount)} точек. Bucket: ${formatNumber(historyPayload?.bucket_seconds || 0)} с.`,
        title: "История нагрузки готова",
        detail: "Точки ниже построены из реальных сохранённых telemetry samples и доступны для timeline selection.",
    };
}

export function buildEventLogViewModel(eventsPayload) {
    const events = Array.isArray(eventsPayload?.events) ? eventsPayload.events : [];
    if (!events.length) {
        return {
            title: "Нет событий для отображения",
            detail: "Telemetry sampler ещё не записал transitions или runtime warnings для operator view.",
            meta: "Журнал остаётся честно пустым, пока backend не накопил реальные события.",
        };
    }
    return {
        title: "События доступны",
        detail: `В журнале сейчас ${formatNumber(events.length)} событий(я).`,
        meta: "Список отсортирован от новых к старым и ограничен по размеру.",
    };
}

function metricChartDescriptor(key) {
    const descriptors = {
        cpu_percent: { label: "CPU", unit: "percent", color: "#62c7ff" },
        ram_used_mb: { label: "RAM used", unit: "mb", color: "#54ddb6" },
        gpu_utilization_percent: { label: "GPU", unit: "percent", color: "#ffcb57" },
        queue_depth: { label: "Queue depth", unit: "count", color: "#ff7289" },
    };
    return descriptors[key] || { label: key, unit: "count", color: "#62c7ff" };
}

function buildHistoryPolyline(points, metricKey, color) {
    const values = points
        .map((point) => Number(point?.[metricKey]))
        .filter((value) => Number.isFinite(value));
    if (!values.length) {
        return null;
    }

    const maxValue = Math.max(...values, 1);
    const minValue = Math.min(...values, 0);
    const spread = Math.max(1, maxValue - minValue);
    const width = 960;
    const height = 280;
    const coordinates = points
        .map((point, index) => {
            const value = Number(point?.[metricKey]);
            if (!Number.isFinite(value)) {
                return null;
            }
            const x = points.length <= 1 ? width / 2 : (index / (points.length - 1)) * width;
            const y = height - ((value - minValue) / spread) * (height - 36) - 18;
            return { x, y };
        })
        .filter(Boolean);

    if (!coordinates.length) {
        return null;
    }

    if (coordinates.length === 1) {
        const point = coordinates[0];
        return `
            <svg class="trend-chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="history chart">
                <circle cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="7" fill="${color}"></circle>
            </svg>
        `;
    }

    const polyline = coordinates.map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
    const areaPoints = [`0,${height}`, ...polyline.split(" "), `${width},${height}`].join(" ");
    return `
        <svg class="trend-chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="history chart">
            <polyline fill="rgba(255,255,255,0.03)" stroke="none" points="${areaPoints}"></polyline>
            <polyline fill="none" stroke="${color}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" points="${polyline}"></polyline>
        </svg>
    `;
}

export function buildQueueEntries(summary) {
    return Object.entries(summary.pending || {}).map(([queueKey, count]) => {
        const [workload, priority] = queueKey.split(":");
        const numericCount = Number(count || 0);
        return {
            queueKey,
            title: `${humanizeWorkload(workload)} / ${String(priority || "").toUpperCase()}`,
            value: numericCount,
            help: numericCount > 0 ? "В очереди есть ожидающие задачи." : "Очередь сейчас пуста.",
            severity: numericCount > 0 ? (workload === "chat" && !summary.capacity ? "critical" : "warn") : "ok",
        };
    });
}

export function buildWorkloadEntries(summary) {
    return Object.entries(summary.by_workload || {}).map(([workload, payload]) => {
        const priorities = Object.entries(payload?.by_priority || {})
            .map(([priority, count]) => `${String(priority).toUpperCase()}: ${formatNumber(count)}`)
            .join(" · ");
        return {
            workload: humanizeWorkload(workload),
            total: Number(payload?.total || 0),
            priorities: priorities || "Нет данных по приоритетам",
            severity: Number(payload?.total || 0) > 0 ? (workload === "chat" && !summary.capacity ? "critical" : "warn") : "ok",
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

function buildPrimaryTrendView(historyPayload, metricKey) {
    const descriptor = metricChartDescriptor(metricKey);
    const points = Array.isArray(historyPayload?.points) ? historyPayload.points : [];
    const model = buildHistoryViewModel(historyPayload || {}, historyPayload?.range || "24h");
    if (!points.length) {
        return {
            label: descriptor.label,
            value: "Нет данных",
            detail: "История ещё не накоплена для выбранного диапазона.",
            meta: model.note,
            footnote: "Показываем только реальные telemetry points.",
            html: `
                <div class="trend-empty">
                    <div class="trend-empty-title">${escapeHtml(model.title)}</div>
                    <div class="timeline-detail">${escapeHtml(model.detail)}</div>
                </div>
            `,
        };
    }

    const latestPoint = points[points.length - 1] || {};
    const latestValue = Number(latestPoint?.[metricKey]);
    const svg = buildHistoryPolyline(points, metricKey, descriptor.color);
    if (!svg || !Number.isFinite(latestValue)) {
        return {
            label: descriptor.label,
            value: "Нет данных",
            detail: `${descriptor.label} не reported для выбранного history диапазона.`,
            meta: model.note,
            footnote: "Если series отсутствует, панель не подставляет synthetic line.",
            html: `
                <div class="trend-empty">
                    <div class="trend-empty-title">Нет history series для этой метрики</div>
                    <div class="timeline-detail">Выбранная метрика не была reported в накопленных telemetry samples.</div>
                </div>
            `,
        };
    }

    return {
        label: descriptor.label,
        value: formatMetricValue(latestValue, descriptor.unit),
        detail: `Последняя точка: ${latestPoint?.captured_at_iso ? formatTimestamp(latestPoint.captured_at_iso) : "Нет времени"}.`,
        meta: model.note,
        footnote: "Линия строится только из реально сохранённых points без interpolation.",
        html: svg,
    };
}

function summarizeEventContext(context) {
    if (!context || typeof context !== "object") {
        return "Без дополнительного контекста";
    }

    const entries = Object.entries(context)
        .filter(([, value]) => value !== null && value !== undefined && String(value).trim() !== "")
        .slice(0, 4);
    if (!entries.length) {
        return "Без дополнительного контекста";
    }
    return entries
        .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : String(value)}`)
        .join(" · ");
}

function activeModelsFromPayload(summary, live) {
    const liveModels = Array.isArray(live?.active_models) ? live.active_models.filter(Boolean) : [];
    if (liveModels.length) {
        return liveModels;
    }
    return Array.isArray(summary?.active_models) ? summary.active_models.filter(Boolean) : [];
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
            tabs: Array.from(document.querySelectorAll("[data-dashboard-tab]")),
            views: Array.from(document.querySelectorAll("[data-dashboard-view]")),
            historyRangeButtons: Array.from(document.querySelectorAll("[data-history-range]")),
            trendMetricButtons: Array.from(document.querySelectorAll("[data-trend-metric]")),
            eventFilterButtons: Array.from(document.querySelectorAll("[data-event-filter]")),
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
            overviewTrendMetricLabel: document.getElementById("overviewTrendMetricLabel"),
            overviewTrendValue: document.getElementById("overviewTrendValue"),
            overviewTrendDetail: document.getElementById("overviewTrendDetail"),
            overviewHistoryRangeLabel: document.getElementById("overviewHistoryRangeLabel"),
            overviewTrendUpdatedLabel: document.getElementById("overviewTrendUpdatedLabel"),
            overviewTrendMeta: document.getElementById("overviewTrendMeta"),
            overviewTrendFootnote: document.getElementById("overviewTrendFootnote"),
            overviewTrendChart: document.getElementById("overviewTrendChart"),
            overviewRecentEventsList: document.getElementById("overviewRecentEventsList"),
            queueOverview: document.getElementById("queueOverview"),
            queueBreakdown: document.getElementById("queueBreakdown"),
            workloadBreakdown: document.getElementById("workloadBreakdown"),
            runtimeSummary: document.getElementById("runtimeSummary"),
            workersSectionNote: document.getElementById("workersSectionNote"),
            workersTableBody: document.getElementById("workersTableBody"),
            targetsSectionNote: document.getElementById("targetsSectionNote"),
            targetsTableBody: document.getElementById("targetsTableBody"),
            resourceTelemetryGrid: document.getElementById("resourceTelemetryGrid"),
            resourceSecondaryList: document.getElementById("resourceSecondaryList"),
            resourceNoDataCard: document.getElementById("resourceNoDataCard"),
            resourceLastUpdated: document.getElementById("resourceLastUpdated"),
            resourceUpdatedLabel: document.getElementById("resourceUpdatedLabel"),
            resourceScopeNote: document.getElementById("resourceScopeNote"),
            resourceModelList: document.getElementById("resourceModelList"),
            historyRangeLabel: document.getElementById("historyRangeLabel"),
            historyMetaNote: document.getElementById("historyMetaNote"),
            historyTimelineCard: document.getElementById("historyTimelineCard"),
            historyPointCountLabel: document.getElementById("historyPointCountLabel"),
            historyAvailabilityNote: document.getElementById("historyAvailabilityNote"),
            historyTimelineSlider: document.getElementById("historyTimelineSlider"),
            historySelectedTsLabel: document.getElementById("historySelectedTsLabel"),
            historyBucketLabel: document.getElementById("historyBucketLabel"),
            historySnapshotGrid: document.getElementById("historySnapshotGrid"),
            eventLogList: document.getElementById("eventLogList"),
            eventCountLabel: document.getElementById("eventCountLabel"),
            eventLogUpdatedLabel: document.getElementById("eventLogUpdatedLabel"),
        };
        this.refreshTimer = null;
        this.loading = false;
        this.activeTab = "overview";
        this.historyRange = "24h";
        this.eventFilter = "all";
        this.trendMetric = "queue_depth";
        this.summary = null;
        this.live = null;
        this.history = null;
        this.events = null;
        this.selectedHistoryIndex = 0;
    }

    async init() {
        this.initTabs();
        await this.refresh();
        this.refreshTimer = window.setInterval(() => {
            void this.refresh();
        }, Math.max(5000, Number(this.bootstrap.refreshIntervalMs) || DEFAULT_REFRESH_MS));
    }

    initTabs() {
        for (const button of this.elements.tabs) {
            button.addEventListener("click", () => {
                this.setActiveTab(button.dataset.dashboardTab || "overview");
                void this.refreshDeferredDataForActiveTab();
            });
        }

        for (const button of this.elements.historyRangeButtons) {
            button.addEventListener("click", () => {
                void this.setHistoryRange(button.dataset.historyRange || "24h");
            });
        }

        for (const button of this.elements.trendMetricButtons) {
            button.addEventListener("click", () => {
                this.setTrendMetric(button.dataset.trendMetric || "queue_depth");
            });
        }

        for (const button of this.elements.eventFilterButtons) {
            button.addEventListener("click", () => {
                this.setEventFilter(button.dataset.eventFilter || "all");
            });
        }

        if (this.elements.historyTimelineSlider) {
            this.elements.historyTimelineSlider.addEventListener("input", (event) => {
                const target = event.currentTarget;
                this.selectedHistoryIndex = Number(target?.value || 0);
                this.renderHistorySelection();
            });
        }
    }

    setActiveTab(tabName) {
        this.activeTab = tabName;
        for (const button of this.elements.tabs) {
            button.classList.toggle("is-active", button.dataset.dashboardTab === tabName);
        }
        for (const view of this.elements.views) {
            view.classList.toggle("is-active", view.dataset.dashboardView === tabName);
        }
    }

    async setHistoryRange(range) {
        this.historyRange = range;
        for (const button of this.elements.historyRangeButtons) {
            button.classList.toggle("is-active", button.dataset.historyRange === range);
        }
        await this.refreshHistory({ swallowError: true });
        if (this.summary) {
            this.render(this.summary);
        }
    }

    setTrendMetric(metricKey) {
        this.trendMetric = metricKey;
        for (const button of this.elements.trendMetricButtons) {
            button.classList.toggle("is-active", button.dataset.trendMetric === metricKey);
        }
        this.renderOverviewTrend(this.history);
    }

    setEventFilter(filter) {
        this.eventFilter = filter;
        for (const button of this.elements.eventFilterButtons) {
            button.classList.toggle("is-active", button.dataset.eventFilter === filter);
        }
        this.renderEventLog(this.events);
    }

    async refresh() {
        if (this.loading) {
            return;
        }

        this.loading = true;
        try {
            const [summary, live] = await Promise.all([
                this.apiClient.requestJSON(this.bootstrap.apiUrl, { method: "GET", timeout: 10000 }),
                this.apiClient.requestJSON(this.bootstrap.liveApiUrl, { method: "GET", timeout: 10000 }),
            ]);
            this.summary = summary;
            this.live = live;

            if (this.activeTab === "overview" || this.activeTab === "history") {
                await this.refreshHistory({ swallowError: true });
            }
            if (this.activeTab === "overview" || this.activeTab === "events") {
                await this.refreshEvents({ swallowError: true });
            }

            this.render(summary);
        } catch (error) {
            console.error("Admin dashboard refresh failed:", error);
            this.renderError(error);
        } finally {
            this.loading = false;
        }
    }

    async refreshDeferredDataForActiveTab() {
        if (!this.summary) {
            return;
        }
        if (this.activeTab === "overview" || this.activeTab === "history") {
            await this.refreshHistory({ swallowError: true });
        }
        if (this.activeTab === "overview" || this.activeTab === "events") {
            await this.refreshEvents({ swallowError: true });
        }
        this.render(this.summary);
    }

    async refreshHistory({ swallowError = false } = {}) {
        try {
            const url = new URL(this.bootstrap.historyApiUrl, window.location.origin);
            url.searchParams.set("range", this.historyRange);
            this.history = await this.apiClient.requestJSON(`${url.pathname}${url.search}`, { method: "GET", timeout: 10000 });
            const pointCount = Number(this.history?.point_count || 0);
            this.selectedHistoryIndex = pointCount > 0 ? pointCount - 1 : 0;
        } catch (error) {
            console.error("Dashboard history refresh failed:", error);
            if (!swallowError) {
                throw error;
            }
        }
    }

    async refreshEvents({ swallowError = false } = {}) {
        try {
            this.events = await this.apiClient.requestJSON(this.bootstrap.eventsApiUrl, { method: "GET", timeout: 10000 });
        } catch (error) {
            console.error("Dashboard events refresh failed:", error);
            if (!swallowError) {
                throw error;
            }
        }
    }

    render(summary) {
        const overall = deriveOverallState(summary);
        const capacity = deriveCapacityAssessment(summary);
        const queuePressure = deriveQueuePressure(summary);
        const readiness = deriveReadinessView(summary);
        const health = deriveHealthView(summary);
        const nextChat = deriveNextChatExpectation(summary);
        const schedulerSeverity = summary.scheduler_status === "healthy" ? "ok" : "critical";

        this.elements.heroMeaning.textContent = `${capacity.state}. ${derivePrimaryBottleneck(summary).title}.`;
        this.elements.overallStatusTitle.textContent = overall.title;
        this.elements.overallStatusBadge.className = `status-badge ${severityClass(overall.severity)}`;
        this.elements.overallStatusBadge.textContent = overall.badge;
        this.elements.schedulerHealthBadge.className = `status-badge ${severityClass(schedulerSeverity)}`;
        this.elements.schedulerHealthBadge.textContent =
            summary.scheduler_status === "healthy"
                ? `Планировщик актуален · ${formatAge(summary.scheduler_age_seconds)}`
                : `Планировщик устарел · ${formatAge(summary.scheduler_age_seconds)}`;
        this.elements.statusSupportText.textContent = nextChat.detail;
        this.elements.lastRefreshLabel.textContent = formatTimestamp(summary.last_refresh);
        this.elements.readinessStatusValue.textContent = readiness.value;
        this.elements.healthStatusValue.textContent = health.value;
        this.elements.capacityStatusValue.textContent = capacity.state;
        this.elements.queueStatusValue.textContent = queuePressure.state;

        this.renderSummaryStrip(summary);
        this.renderKpis(summary, this.live);
        this.renderOverviewTrend(this.history);
        this.renderOverviewRecentEvents(this.events);
        this.renderAlerts(summary);
        this.renderQueueOverview(summary);
        this.renderQueueBreakdown(summary);
        this.renderWorkloadBreakdown(summary);
        this.renderRuntimeSummary(summary);
        this.renderWorkers(summary, summary.worker_rows || []);
        this.renderTargets(summary, summary.target_rows || []);
        this.renderResourceTelemetry(this.live, summary);
        this.renderResourceModels(summary, this.live);
        this.renderHistoryView(this.history);
        this.renderEventLog(this.events);
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

    renderKpis(summary, live) {
        this.elements.kpiGrid.innerHTML = buildKpiCards(summary, live || {})
            .map(
                (item) => `
                    <article class="kpi-card ${severityClass(item.severity)}">
                        <div class="kpi-head">
                            <div class="kpi-label">${escapeHtml(item.label)}</div>
                            <span class="info-chip" title="${escapeHtml(item.help)}">i</span>
                        </div>
                        <div class="kpi-value">${escapeHtml(item.value)}</div>
                        <div class="kpi-meta">${escapeHtml(item.meta || "")}</div>
                    </article>
                `,
            )
            .join("");
    }

    renderOverviewTrend(historyPayload = null) {
        const model = buildHistoryViewModel(historyPayload || {}, this.historyRange);
        const trend = buildPrimaryTrendView(historyPayload || {}, this.trendMetric);
        if (this.elements.overviewTrendMetricLabel) {
            this.elements.overviewTrendMetricLabel.textContent = trend.label;
        }
        if (this.elements.overviewTrendValue) {
            this.elements.overviewTrendValue.textContent = trend.value;
        }
        if (this.elements.overviewTrendDetail) {
            this.elements.overviewTrendDetail.textContent = trend.detail;
        }
        if (this.elements.overviewHistoryRangeLabel) {
            this.elements.overviewHistoryRangeLabel.textContent = model.rangeLabel;
        }
        if (this.elements.overviewTrendUpdatedLabel) {
            const latestPoint = Array.isArray(historyPayload?.points) && historyPayload.points.length
                ? historyPayload.points[historyPayload.points.length - 1]
                : null;
            this.elements.overviewTrendUpdatedLabel.textContent = latestPoint?.captured_at_iso
                ? `Последняя точка: ${formatTimestamp(latestPoint.captured_at_iso)}`
                : "История ещё не загружена.";
        }
        if (this.elements.overviewTrendMeta) {
            this.elements.overviewTrendMeta.textContent = trend.meta;
        }
        if (this.elements.overviewTrendFootnote) {
            this.elements.overviewTrendFootnote.textContent = trend.footnote;
        }
        if (this.elements.overviewTrendChart) {
            this.elements.overviewTrendChart.innerHTML = trend.html;
        }
    }

    renderOverviewRecentEvents(eventsPayload = null) {
        const events = Array.isArray(eventsPayload?.events) ? eventsPayload.events : [];
        const recentEvents = events.slice(0, 5);
        if (!recentEvents.length) {
            this.elements.overviewRecentEventsList.innerHTML = `
                <article class="event-card">
                    <div class="event-card-title">Нет событий</div>
                    <div class="event-card-detail">Telemetry sampler ещё не накопил transitions или runtime warnings для overview.</div>
                </article>
            `;
            return;
        }

        this.elements.overviewRecentEventsList.innerHTML = recentEvents
            .map((event) => `
                <article class="event-card ${severityClass(event.severity)}">
                    <div class="event-card-head">
                        <div class="event-card-title">${escapeHtml(event.message || "Событие")}</div>
                        <div class="event-severity-badge ${severityClass(event.severity)}">${escapeHtml(event.severity || "info")}</div>
                    </div>
                    <div class="event-card-detail">${escapeHtml(summarizeEventContext(event.context || {}))}</div>
                    <div class="event-row-meta">${escapeHtml(event.source || "runtime")} · ${escapeHtml(event.timestamp_iso ? formatTimestamp(event.timestamp_iso) : "Нет времени")}</div>
                </article>
            `)
            .join("");
    }

    renderAlerts(summary) {
        this.elements.alertList.innerHTML = buildAlertItems(summary)
            .map(
                (item) => `
                    <article class="summary-card ${severityClass(item.severity)}" title="${escapeHtml(item.recommendation)}">
                        <div class="summary-label">${escapeHtml(item.title)}</div>
                        <div class="summary-value">${escapeHtml(item.severity === "critical" ? "Требует внимания" : item.severity === "warn" ? "Нужно наблюдение" : "Штатно")}</div>
                        <div class="alert-detail">${escapeHtml(item.detail)}</div>
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
                            <div class="summary-value">${formatNumber(item.value)}</div>
                        </div>
                        <div class="summary-detail">${escapeHtml(item.queueKey)}</div>
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
                            <div class="summary-value">${formatNumber(item.total)}</div>
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
                    </article>
                `,
            )
            .join("");
    }

    renderWorkers(summary, workers) {
        if (!Array.isArray(workers) || !workers.length) {
            this.elements.workersSectionNote.textContent = "";
            this.elements.workersTableBody.innerHTML = '<tr><td colspan="7" class="empty-state">Нет активных worker heartbeat данных</td></tr>';
            return;
        }

        this.elements.workersSectionNote.textContent = deriveWorkerSnapshotNote(summary, workers);
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
                                <div class="table-secondary">Heartbeat snapshot: ${escapeHtml(statusText(worker.status))}</div>
                            </div>
                        </td>
                        <td>${escapeHtml(worker.pool || "Нет данных")}</td>
                        <td class="mono">${escapeHtml(worker.target_id || "Нет данных")}</td>
                        <td>${escapeHtml(worker.target_kind || "Нет данных")}</td>
                        <td>${formatNumber(worker.active_jobs)}</td>
                        <td>${formatAge(worker.last_seen_age_seconds)}</td>
                        <td><span class="table-badge ${severityClass(severity)}">${escapeHtml(statusText(worker.status))}</span></td>
                    </tr>
                `;
            })
            .join("");
    }

    renderTargets(summary, targets) {
        if (!Array.isArray(targets) || !targets.length) {
            this.elements.targetsSectionNote.textContent = "";
            this.elements.targetsTableBody.innerHTML = '<tr><td colspan="9" class="empty-state">Нет активных target heartbeat данных</td></tr>';
            return;
        }

        this.elements.targetsSectionNote.textContent = deriveTargetsSectionNote(summary, targets);
        this.elements.targetsTableBody.innerHTML = targets
            .map((target) => {
                const severity = target.status === "online" ? "ok" : "critical";
                const workloadView = buildTargetWorkloadPresentation(summary, target);
                return `
                    <tr>
                        <td>
                            <div class="table-primary">
                                <strong class="mono">${escapeHtml(target.target_id || "-")}</strong>
                                <div class="table-secondary"><span class="table-badge ${severityClass(severity)}">${escapeHtml(statusText(target.status))}</span></div>
                            </div>
                        </td>
                        <td>${escapeHtml(target.target_kind || "Нет данных")}</td>
                        <td>
                            <div class="table-primary">
                                <div class="table-secondary">Reported возможности</div>
                                <div class="chip-row">${renderChips(workloadView.reported, { mutedFallback: "Нет данных" })}</div>
                                <div class="table-secondary">Наблюдаемая нагрузка</div>
                                <div class="chip-row">${renderChips(workloadView.observed, { mutedFallback: "не видно по heartbeat" })}</div>
                                <div class="table-secondary">${escapeHtml(workloadView.note)}</div>
                            </div>
                        </td>
                        <td>${formatNumber(target.base_capacity_tokens)}</td>
                        <td>${Number.isFinite(Number(target.cpu_percent)) ? `${Number(target.cpu_percent).toFixed(1)}%` : "Нет данных"}</td>
                        <td>${Number(target.ram_free_mb || 0) > 0 ? `${formatNumber(target.ram_free_mb)} MB` : "Нет данных"}</td>
                        <td>${Number(target.vram_free_mb || 0) > 0 ? `${formatNumber(target.vram_free_mb)} MB` : "Нет данных"}</td>
                        <td><div class="chip-row">${renderChips(target.loaded_models, { mutedFallback: "Нет reported моделей" })}</div></td>
                        <td>${formatAge(target.last_seen_age_seconds)}</td>
                    </tr>
                `;
            })
            .join("");
    }

    renderResourceTelemetry(live, summary) {
        if (this.elements.resourceTelemetryGrid) {
            this.elements.resourceTelemetryGrid.innerHTML = buildResourceTelemetryCards(live || {}, summary || {})
                .map(
                    (item) => `
                        <article class="resource-card">
                            <div class="resource-card-head">
                                <div class="resource-label">${escapeHtml(item.label)}</div>
                                <span class="resource-state ${severityClass(item.severity)}">${escapeHtml(item.state)}</span>
                            </div>
                            <div class="resource-value">${escapeHtml(item.value)}</div>
                            <div class="resource-detail">${escapeHtml(item.detail)}</div>
                            <div class="resource-visual"><span style="--telemetry-fill:${Number(item.fill || 0)}%"></span></div>
                        </article>
                    `,
                )
                .join("");
        }

        if (this.elements.resourceSecondaryList) {
            this.elements.resourceSecondaryList.innerHTML = buildResourceSecondaryFacts(live || {}, summary || {})
                .map(
                    (item) => `
                        <div class="resource-secondary-row">
                            <div>
                                <div class="resource-secondary-title">${escapeHtml(item.label)}</div>
                                <div class="resource-footnote">${escapeHtml(item.detail)}</div>
                            </div>
                            <div class="resource-secondary-value">${escapeHtml(item.value)}</div>
                        </div>
                    `,
                )
                .join("");
        }

        if (this.elements.resourceNoDataCard) {
            const missingCount = buildResourceTelemetryCards(live || {}, summary || {})
                .filter((item) => item.state !== "reported" && item.state !== "runtime summary").length;
            this.elements.resourceNoDataCard.innerHTML = `
                <div class="resource-label">Текущий статус</div>
                <div class="resource-value">${missingCount > 0 ? "Частичный telemetry mode" : "Runtime summary available"}</div>
                <div class="resource-detail">${
                    missingCount > 0
                        ? "Часть resource cards уже опирается на реальные runtime поля, а недостающие telemetry источники честно помечены как no-data."
                        : "Все видимые resource cards сейчас заполнены реальными runtime полями без поддельных значений."
                }</div>
            `;
        }
        if (this.elements.resourceLastUpdated) {
            this.elements.resourceLastUpdated.textContent = live?.captured_at_iso
                ? formatTimestamp(live.captured_at_iso)
                : "Ожидание live telemetry";
        }
        if (this.elements.resourceUpdatedLabel) {
            this.elements.resourceUpdatedLabel.textContent = live?.captured_at_iso
                ? `Последнее обновление: ${formatTimestamp(live.captured_at_iso)}`
                : "Последнее обновление: нет данных";
        }
        if (this.elements.resourceScopeNote) {
            this.elements.resourceScopeNote.textContent = live?.network_scope
                ? `Scope: ${live.telemetry_scope}. Network: ${live.network_scope}.`
                : "Метрики показываются только там, где их реально сообщает target runtime.";
        }
    }

    renderResourceModels(summary, live) {
        const models = activeModelsFromPayload(summary, live);
        if (!models.length) {
            this.elements.resourceModelList.innerHTML = `
                <article class="summary-card">
                    <div class="summary-label">Модели</div>
                    <div class="summary-value">Нет данных</div>
                    <div class="summary-detail">Loaded models пока не были reported в видимом target heartbeat path.</div>
                </article>
            `;
            return;
        }

        this.elements.resourceModelList.innerHTML = `
            <article class="summary-card">
                <div class="summary-label">Активные модели</div>
                <div class="summary-value">${formatNumber(models.length)}</div>
                <div class="chip-row">${renderChips(models, { mutedFallback: "Нет данных" })}</div>
                <div class="summary-detail">Показываются только модели, которые реально reported target path.</div>
            </article>
        `;
    }

    renderHistoryView(historyPayload = null) {
        const model = buildHistoryViewModel(historyPayload || {}, this.historyRange);
        if (this.elements.historyRangeLabel) {
            this.elements.historyRangeLabel.textContent = model.rangeLabel;
        }
        if (this.elements.historyMetaNote) {
            this.elements.historyMetaNote.textContent = model.note;
        }
        if (this.elements.historyPointCountLabel) {
            this.elements.historyPointCountLabel.textContent = Number(historyPayload?.point_count || 0) > 0
                ? `${formatNumber(historyPayload?.point_count || 0)} telemetry points`
                : "Ожидание samples";
        }
        if (this.elements.historyAvailabilityNote) {
            this.elements.historyAvailabilityNote.textContent = Number(historyPayload?.point_count || 0) > 0
                ? "Charts строятся из сохранённых telemetry samples, без synthetic interpolation."
                : "История появится только после накопления реальных samples.";
        }
        if (this.elements.historyTimelineCard) {
            const points = Array.isArray(historyPayload?.points) ? historyPayload.points : [];
            if (!points.length) {
                this.elements.historyTimelineCard.innerHTML = `
                    <div class="timeline-label">История нагрузки</div>
                    <div class="timeline-title">${escapeHtml(model.title)}</div>
                    <div class="timeline-detail">${escapeHtml(model.detail)}</div>
                `;
            } else {
                const charts = [
                    { key: "cpu_percent" },
                    { key: "ram_used_mb" },
                    { key: "gpu_utilization_percent" },
                    { key: "queue_depth" },
                ].map(({ key }) => {
                    const descriptor = metricChartDescriptor(key);
                    const latestPoint = points[points.length - 1] || {};
                    const svg = buildHistoryPolyline(points, key, descriptor.color);
                    return `
                        <article class="history-chart-card">
                            <div class="history-chart-head">
                                <div class="summary-label">${escapeHtml(descriptor.label)}</div>
                                <div class="summary-value">${escapeHtml(formatMetricValue(latestPoint[key], descriptor.unit))}</div>
                            </div>
                            ${svg || '<div class="trend-empty"><div class="trend-empty-title">Нет series</div><div class="timeline-detail">Метрика не была reported в выбранном диапазоне.</div></div>'}
                        </article>
                    `;
                });
                this.elements.historyTimelineCard.innerHTML = `
                    <div class="timeline-label">История нагрузки</div>
                    <div class="timeline-title">${escapeHtml(model.title)}</div>
                    <div class="timeline-detail">${escapeHtml(model.detail)}</div>
                    <div class="history-chart-grid">${charts.join("")}</div>
                `;
            }
        }

        const points = Array.isArray(historyPayload?.points) ? historyPayload.points : [];
        if (this.elements.historyTimelineSlider) {
            this.elements.historyTimelineSlider.disabled = points.length <= 1;
            this.elements.historyTimelineSlider.max = String(Math.max(0, points.length - 1));
            this.elements.historyTimelineSlider.value = String(Math.min(this.selectedHistoryIndex, Math.max(0, points.length - 1)));
        }
        if (this.elements.historyBucketLabel) {
            this.elements.historyBucketLabel.textContent = Number(historyPayload?.bucket_seconds || 0) > 0
                ? `Bucket: ${formatNumber(historyPayload.bucket_seconds)} с`
                : `Bucket: ${model.rangeLabel}`;
        }
        this.renderHistorySelection();
    }

    renderHistorySelection() {
        const points = Array.isArray(this.history?.points) ? this.history.points : [];
        const selectedPoint = points[Math.min(this.selectedHistoryIndex, Math.max(0, points.length - 1))];
        if (this.elements.historySelectedTsLabel) {
            this.elements.historySelectedTsLabel.textContent = selectedPoint?.captured_at_iso
                ? `Выбранная точка: ${formatTimestamp(selectedPoint.captured_at_iso)}`
                : "Выбранная точка: нет данных";
        }
        if (this.elements.historySnapshotGrid) {
            if (!selectedPoint) {
                this.elements.historySnapshotGrid.innerHTML = `
                    <article class="snapshot-card">
                        <div class="snapshot-label">История</div>
                        <div class="snapshot-value">Нет данных</div>
                        <div class="snapshot-detail">Snapshot появится после загрузки history samples.</div>
                    </article>
                `;
                return;
            }
            const snapshotItems = [
                { label: "CPU", value: formatMetricValue(selectedPoint.cpu_percent, "percent"), detail: "Средняя CPU telemetry по target heartbeat." },
                { label: "RAM used", value: formatMetricValue(selectedPoint.ram_used_mb, "mb"), detail: "Использованная RAM по online targets." },
                { label: "GPU", value: formatMetricValue(selectedPoint.gpu_utilization_percent, "percent"), detail: "GPU utilization reported GPU target path." },
                { label: "VRAM used", value: formatMetricValue(selectedPoint.vram_used_mb, "mb"), detail: "Использованная VRAM, если GPU telemetry доступна." },
                { label: "Network rx/tx", value: `${formatMetricValue(selectedPoint.network_rx_bytes_per_sec, "bytes_per_sec")} / ${formatMetricValue(selectedPoint.network_tx_bytes_per_sec, "bytes_per_sec")}`, detail: "Throughput по target runtime namespace counters." },
                { label: "Queue depth", value: formatNumber(selectedPoint.queue_depth), detail: "Глубина очереди на выбранной telemetry точке." },
                { label: "Active jobs", value: formatNumber(selectedPoint.active_jobs), detail: "Сколько задач выполнялось в момент snapshot." },
                { label: "Workers", value: `${formatNumber(selectedPoint.workers_working)} / ${formatNumber(selectedPoint.workers_total)}`, detail: "working / total workers на выбранной точке." },
            ];
            this.elements.historySnapshotGrid.innerHTML = snapshotItems
                .map(
                    (item) => `
                        <article class="snapshot-card">
                            <div class="snapshot-label">${escapeHtml(item.label)}</div>
                            <div class="snapshot-value">${escapeHtml(item.value)}</div>
                            <div class="snapshot-detail">${escapeHtml(item.detail)}</div>
                        </article>
                    `,
                )
                .join("");
        }
    }

    renderEventLog(eventsPayload) {
        const model = buildEventLogViewModel(eventsPayload || {});
        const events = Array.isArray(eventsPayload?.events) ? eventsPayload.events : [];
        const filteredEvents = this.eventFilter === "all"
            ? events
            : events.filter((event) => String(event?.severity || "").toLowerCase() === this.eventFilter);
        if (this.elements.eventCountLabel) {
            this.elements.eventCountLabel.textContent = `События: ${formatNumber(events.length)}`;
        }
        if (this.elements.eventLogUpdatedLabel) {
            this.elements.eventLogUpdatedLabel.textContent = events[0]?.timestamp_iso
                ? `Последнее событие: ${formatTimestamp(events[0].timestamp_iso)}`
                : "Ожидание event log";
        }
        if (this.elements.eventLogList) {
            if (!filteredEvents.length) {
                this.elements.eventLogList.innerHTML = `
                    <article class="event-row">
                        <div class="event-row-label">Event log</div>
                        <div class="events-empty-title">${escapeHtml(model.title)}</div>
                        <div class="events-empty-text">${escapeHtml(model.detail)}</div>
                        <div class="event-row-meta">${escapeHtml(model.meta)}</div>
                    </article>
                `;
                return;
            }
            this.elements.eventLogList.innerHTML = filteredEvents
                .map(
                    (event) => `
                        <article class="event-row ${severityClass(event.severity)}">
                            <div class="event-row-head">
                                <div class="event-row-label">${escapeHtml(event.source || "runtime")}</div>
                                <div class="event-severity-badge ${severityClass(event.severity)}">${escapeHtml(event.severity || "info")}</div>
                            </div>
                            <div class="events-empty-title">${escapeHtml(event.message || "Событие")}</div>
                            <div class="events-empty-text">${escapeHtml(summarizeEventContext(event.context || {}))}</div>
                            <div class="event-row-meta">${escapeHtml(event.timestamp_iso ? formatTimestamp(event.timestamp_iso) : "Нет времени")}</div>
                        </article>
                    `,
                )
                .join("");
        }
    }

    renderError(error) {
        const message = error instanceof APIError ? error.message : "Не удалось обновить операторскую сводку";
        this.elements.heroMeaning.textContent = "Панель не смогла получить новую сводку. Последние данные могли устареть.";
        this.elements.overallStatusTitle.textContent = "Сводка недоступна";
        this.elements.overallStatusBadge.className = `status-badge ${severityClass("critical")}`;
        this.elements.overallStatusBadge.textContent = "Ошибка";
        this.elements.alertList.innerHTML = `
            <article class="summary-card ${severityClass("critical")}">
                <div class="summary-label">Не удалось обновить dashboard</div>
                <div class="summary-value">Ошибка</div>
                <div class="alert-detail">${escapeHtml(message)}</div>
            </article>
        `;
        if (this.elements.overviewTrendChart) {
            this.elements.overviewTrendChart.innerHTML = `
                <div class="trend-empty">
                    <div class="trend-empty-title">Нет новой history сводки</div>
                    <div class="timeline-detail">Live overview unavailable, пока dashboard API недоступен.</div>
                </div>
            `;
        }
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
