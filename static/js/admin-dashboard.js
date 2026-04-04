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
    const overall = deriveOverallState(summary);
    const capacity = deriveCapacityAssessment(summary);
    const bottleneck = derivePrimaryBottleneck(summary);
    const scaling = deriveScalingHint(summary);

    return [
        {
            label: "Состояние системы",
            value: overall.title,
            detail: overall.description,
            severity: overall.severity,
        },
        {
            label: "Оценка запаса",
            value: capacity.state,
            detail: capacity.reason,
            severity: capacity.severity,
        },
        {
            label: "Что ограничивает систему сейчас",
            value: bottleneck.title,
            detail: bottleneck.detail,
            severity: bottleneck.severity,
        },
        {
            label: "Что это значит для масштабирования",
            value: scaling.title,
            detail: scaling.detail,
            severity: scaling.severity,
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
        const capacity = deriveCapacityAssessment(summary);
        const queuePressure = deriveQueuePressure(summary);
        const readiness = deriveReadinessView(summary);
        const health = deriveHealthView(summary);
        const scaling = deriveScalingHint(summary);
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
            `${capacity.reason} ${scaling.detail}`;
        this.elements.lastRefreshLabel.textContent = formatTimestamp(summary.last_refresh);
        this.elements.readinessStatusValue.textContent = readiness.value;
        this.elements.healthStatusValue.textContent = health.value;
        this.elements.capacityStatusValue.textContent = capacity.state;
        this.elements.queueStatusValue.textContent = queuePressure.state;

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
                                <div class="table-secondary">Статус heartbeat: ${escapeHtml(statusText(worker.status))}</div>
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
                        <td>${escapeHtml(target.target_kind || "Нет данных")}</td>
                        <td><div class="chip-row">${renderChips(target.supports_workloads, { mutedFallback: "Нет данных" })}</div></td>
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
