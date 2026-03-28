export class APIError extends Error {
    constructor(message, options = {}) {
        super(message);
        this.name = "APIError";
        this.status = options.status ?? 0;
        this.payload = options.payload ?? null;
        this.retryAfter = options.retryAfter ?? null;
    }
}

const DEFAULT_TIMEOUT_MS = 30000;
const MAX_503_RETRIES = 2;

function wait(ms) {
    return new Promise((resolve) => {
        window.setTimeout(resolve, ms);
    });
}

function linkAbortSignals(localController, externalSignal) {
    if (!externalSignal) {
        return () => {};
    }

    if (externalSignal.aborted) {
        localController.abort(externalSignal.reason);
        return () => {};
    }

    const handleAbort = () => localController.abort(externalSignal.reason);
    externalSignal.addEventListener("abort", handleAbort, { once: true });
    return () => externalSignal.removeEventListener("abort", handleAbort);
}

async function parseJsonSafely(response) {
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) {
        return null;
    }

    try {
        return await response.json();
    } catch (error) {
        return null;
    }
}

export class APIClient {
    constructor({ getCsrfToken, onUnauthorized } = {}) {
        this.getCsrfToken = typeof getCsrfToken === "function" ? getCsrfToken : () => "";
        this.onUnauthorized = typeof onUnauthorized === "function" ? onUnauthorized : () => {};
        this.refreshPromise = null;
    }

    async requestJSON(url, options = {}) {
        const response = await this.request(url, { ...options, responseType: "json" });
        if (response.status === 204) {
            return null;
        }
        return response.json();
    }

    async requestStream(url, options = {}) {
        return this.request(url, { ...options, responseType: "stream" });
    }

    async request(url, options = {}) {
        const {
            method = "GET",
            headers = {},
            body,
            signal,
            timeout = DEFAULT_TIMEOUT_MS,
            retryOn503 = true,
            autoRefresh = true,
            responseType = "json",
            attempt = 0,
        } = options;

        const upperMethod = method.toUpperCase();
        const localController = new AbortController();
        const unlinkExternal = linkAbortSignals(localController, signal);
        const timeoutId = window.setTimeout(() => {
            localController.abort(new DOMException("Request timed out", "AbortError"));
        }, timeout);

        const requestHeaders = new Headers(headers);
        if (!requestHeaders.has("Accept") && responseType === "json") {
            requestHeaders.set("Accept", "application/json");
        }
        if (["POST", "PUT", "PATCH", "DELETE"].includes(upperMethod) && !requestHeaders.has("X-CSRF-Token")) {
            const csrfToken = this.getCsrfToken();
            if (csrfToken) {
                requestHeaders.set("X-CSRF-Token", csrfToken);
            }
        }

        let response;
        try {
            response = await fetch(url, {
                method: upperMethod,
                headers: requestHeaders,
                body,
                credentials: "same-origin",
                signal: localController.signal,
            });
        } catch (error) {
            unlinkExternal();
            window.clearTimeout(timeoutId);

            if (localController.signal.aborted) {
                throw error;
            }

            throw new APIError("Network request failed", { status: 0 });
        }

        unlinkExternal();
        window.clearTimeout(timeoutId);

        if (response.status === 401 && autoRefresh && !url.endsWith("/api/refresh")) {
            const refreshed = await this.tryRefresh();
            if (refreshed) {
                return this.request(url, {
                    ...options,
                    headers,
                    body,
                    signal,
                    timeout,
                    retryOn503,
                    autoRefresh: false,
                    responseType,
                    attempt,
                });
            }

            this.onUnauthorized();
        }

        if (response.status === 503 && retryOn503 && attempt < MAX_503_RETRIES) {
            const retryAfterMs = await this.readRetryAfter(response);
            if (retryAfterMs > 0) {
                await wait(retryAfterMs);
                return this.request(url, {
                    ...options,
                    headers,
                    body,
                    signal,
                    timeout,
                    retryOn503,
                    autoRefresh,
                    responseType,
                    attempt: attempt + 1,
                });
            }
        }

        if (!response.ok) {
            throw await this.buildApiError(response);
        }

        return response;
    }

    async tryRefresh() {
        if (!this.refreshPromise) {
            this.refreshPromise = this.request("/api/refresh", {
                method: "POST",
                autoRefresh: false,
                retryOn503: false,
                responseType: "json",
                timeout: 10000,
            })
                .then((response) => response.ok)
                .catch(() => false)
                .finally(() => {
                    this.refreshPromise = null;
                });
        }

        return this.refreshPromise;
    }

    async readRetryAfter(response) {
        const headerValue = response.headers.get("retry-after");
        if (headerValue && Number.isFinite(Number(headerValue))) {
            return Number(headerValue) * 1000;
        }

        const payload = await parseJsonSafely(response.clone());
        const retryAfter = Number(payload?.retry_after ?? 0);
        if (Number.isFinite(retryAfter) && retryAfter > 0) {
            return retryAfter * 1000;
        }

        return 0;
    }

    async buildApiError(response) {
        const payload = await parseJsonSafely(response.clone());
        const message =
            payload?.error ||
            payload?.detail ||
            `HTTP ${response.status}`;
        const retryAfter = Number(payload?.retry_after ?? 0) || null;
        return new APIError(message, {
            status: response.status,
            payload,
            retryAfter,
        });
    }
}
