export class StreamController {
    constructor(apiClient) {
        this.apiClient = apiClient;
        this.abortController = null;
        this.jobId = null;
        this.active = false;
    }

    async start({
        url = "/api/chat",
        prompt,
        model,
        threadId = null,
        body = null,
        headers = {},
        timeout = 300000,
        onOpen,
        onJob,
        onToken,
        onResult,
        onDone,
        onError,
        onCancelled,
    }) {
        if (this.active) {
            await this.stop({ silent: true });
        }

        this.abortController = new AbortController();
        this.jobId = null;
        this.active = true;

        try {
            const requestHeaders = new Headers(headers);
            let requestBody = body;
            if (requestBody === null) {
                requestHeaders.set("Content-Type", "application/json");
                requestBody = JSON.stringify({ prompt, model, thread_id: threadId || undefined });
            }
            if (!requestHeaders.has("Accept")) {
                requestHeaders.set("Accept", "text/event-stream");
            }

            const response = await this.apiClient.requestStream(url, {
                method: "POST",
                headers: requestHeaders,
                body: requestBody,
                signal: this.abortController.signal,
                timeout,
            });

            onOpen?.();

            const reader = response.body?.getReader();
            if (!reader) {
                throw new Error("Streaming response is unavailable");
            }

            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { value, done } = await reader.read();
                if (done) {
                    break;
                }

                buffer += decoder.decode(value, { stream: true });
                const chunks = buffer.split("\n\n");
                buffer = chunks.pop() || "";

                for (const chunk of chunks) {
                    const dataLines = chunk
                        .split("\n")
                        .filter((line) => line.startsWith("data:"))
                        .map((line) => line.replace(/^data:\s*/, ""));

                    if (!dataLines.length) {
                        continue;
                    }

                    const event = JSON.parse(dataLines.join("\n"));

                    if (event.job_id) {
                        this.jobId = event.job_id;
                        onJob?.(event.job_id);
                        continue;
                    }

                    if (event.error) {
                        throw new Error(event.error);
                    }

                    if (event.token) {
                        onToken?.(event.token, event);
                    }

                    if (typeof event.result === "string") {
                        onResult?.(event.result, event);
                    }

                    if (event.done) {
                        onDone?.(event);
                        return;
                    }
                }
            }

            onDone?.({ done: true });
        } catch (error) {
            if (this.isAbortError(error)) {
                onCancelled?.();
                return;
            }

            onError?.(error);
            throw error;
        } finally {
            this.cleanup();
        }
    }

    async stop({ silent = false } = {}) {
        if (!this.active && !this.abortController) {
            return false;
        }

        const controller = this.abortController;
        const jobId = this.jobId;

        this.abortController = null;
        this.jobId = null;
        this.active = false;

        if (controller) {
            controller.abort(new DOMException("Request aborted", "AbortError"));
        }

        if (jobId) {
            try {
                await this.apiClient.requestJSON(`/api/chat/cancel/${encodeURIComponent(jobId)}`, {
                    method: "POST",
                    timeout: 10000,
                    retryOn503: false,
                    autoRefresh: false,
                });
            } catch (error) {
                if (!silent) {
                    console.warn("Cancel request failed:", error);
                }
            }
        }

        return true;
    }

    cleanup() {
        this.abortController = null;
        this.jobId = null;
        this.active = false;
    }

    isAbortError(error) {
        return error?.name === "AbortError";
    }
}
