function createId(prefix) {
    return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

const DEFAULT_THREAD_ID = "default";

function normalizeAttachment(attachment) {
    return {
        id: attachment.id || createId("attachment"),
        name: attachment.name || "attachment",
        size: Number(attachment.size || 0),
        type: attachment.type || "application/octet-stream",
        lastModified: Number(attachment.lastModified || Date.now()),
    };
}

function normalizeMessage(message, lastUserMessageId = null) {
    const role = message.role === "assistant" ? "assistant" : "user";
    const normalized = {
        id: message.id ? String(message.id) : createId("msg"),
        role,
        content: String(message.content || ""),
        html: typeof message.html === "string" ? message.html : "",
        sourceUserMessageId:
            message.sourceUserMessageId ||
            (role === "assistant" ? lastUserMessageId : null),
        attachments: Array.isArray(message.attachments)
            ? message.attachments.map(normalizeAttachment)
            : [],
        state: message.state || "done",
    };

    return {
        message: normalized,
        lastUserMessageId: role === "user" ? normalized.id : lastUserMessageId,
    };
}

function normalizeMessages(messages) {
    const normalizedMessages = [];
    let lastUserMessageId = null;

    for (const rawMessage of messages || []) {
        const normalized = normalizeMessage(rawMessage, lastUserMessageId);
        normalizedMessages.push(normalized.message);
        lastUserMessageId = normalized.lastUserMessageId;
    }

    return normalizedMessages;
}

function buildThreadTitle(messages) {
    const firstUserMessage = messages.find((message) => message.role === "user" && message.content.trim());
    if (!firstUserMessage) {
        return "Новый чат";
    }

    const normalized = firstUserMessage.content.trim().replace(/\s+/g, " ");
    return normalized.length > 48 ? `${normalized.slice(0, 48)}...` : normalized;
}

function normalizeThreadSummary(thread) {
    const normalizedId = String(thread?.id || DEFAULT_THREAD_ID).trim() || DEFAULT_THREAD_ID;
    const normalizedUpdatedAt = Number(thread?.updatedAt || Date.now());
    return {
        id: normalizedId,
        title: String(thread?.title || "Новый чат").trim() || "Новый чат",
        updatedAt: Number.isFinite(normalizedUpdatedAt) && normalizedUpdatedAt > 0
            ? normalizedUpdatedAt
            : Date.now(),
        messageCount: Math.max(0, Number(thread?.messageCount || 0)),
    };
}

export class ThreadStore {
    constructor({ initialThreads = [], initialMessages = [], initialThreadId = DEFAULT_THREAD_ID } = {}) {
        this.listeners = new Set();
        this.threads = [];
        this.activeThreadId = null;
        this.liveThreadId = null;
        this.bootstrap(initialThreads, initialMessages, initialThreadId);
    }

    subscribe(listener) {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    bootstrap(initialThreads = [], initialMessages = [], initialThreadId = DEFAULT_THREAD_ID) {
        const normalizedThreads = Array.isArray(initialThreads) && initialThreads.length
            ? initialThreads.map((thread) => this.createThreadRecord(thread))
            : [this.createThreadRecord({ id: initialThreadId || DEFAULT_THREAD_ID })];
        const resolvedThreadId = this.resolveThreadId(initialThreadId, normalizedThreads);
        const resolvedMessages = normalizeMessages(initialMessages);

        this.threads = normalizedThreads;
        this.setThreadMessages(resolvedThreadId, resolvedMessages, { emit: false });
        this.activeThreadId = resolvedThreadId;
        this.liveThreadId = resolvedThreadId;
        this.sortThreads();
    }

    getState() {
        return {
            threads: this.threads.map((thread) => ({
                ...thread,
                messages: thread.messages.map((message) => ({
                    ...message,
                    attachments: message.attachments.map((attachment) => ({ ...attachment })),
                })),
            })),
            activeThreadId: this.activeThreadId,
            liveThreadId: this.liveThreadId,
        };
    }

    getThreads() {
        return this.threads;
    }

    getActiveThread() {
        return this.findThread(this.activeThreadId);
    }

    getLiveThread() {
        return this.findThread(this.liveThreadId);
    }

    isReadonlyThread(threadId = this.activeThreadId) {
        return !Boolean(this.findThread(threadId));
    }

    setActiveThread(threadId) {
        const resolvedThreadId = this.resolveThreadId(threadId, this.threads);
        if (!this.findThread(resolvedThreadId)) {
            return;
        }
        this.activeThreadId = resolvedThreadId;
        this.liveThreadId = resolvedThreadId;
        this.emit();
    }

    replaceThreads(threads, activeThreadId = this.activeThreadId) {
        const existingById = new Map(this.threads.map((thread) => [thread.id, thread]));
        this.threads = (threads || []).map((threadSummary) => {
            const normalized = normalizeThreadSummary(threadSummary);
            const existing = existingById.get(normalized.id);
            return this.createThreadRecord({
                ...normalized,
                messages: existing?.messages || [],
            });
        });
        if (!this.threads.length) {
            this.threads = [this.createThreadRecord({ id: DEFAULT_THREAD_ID })];
        }
        const resolvedThreadId = this.resolveThreadId(activeThreadId, this.threads);
        this.activeThreadId = resolvedThreadId;
        this.liveThreadId = resolvedThreadId;
        this.sortThreads();
        this.emit();
    }

    attachServerThread(threadSummary, messages = null) {
        const normalized = normalizeThreadSummary(threadSummary);
        const hasServerMessages = Array.isArray(messages);
        const normalizedMessages = hasServerMessages ? normalizeMessages(messages) : [];
        const existing = this.findThread(normalized.id);

        if (existing) {
            existing.title = normalized.title;
            existing.updatedAt = normalized.updatedAt;
            existing.messageCount = normalized.messageCount;
            if (hasServerMessages) {
                existing.messages = normalizedMessages;
            }
        } else {
            this.threads.unshift(this.createThreadRecord({
                ...normalized,
                messages: hasServerMessages ? normalizedMessages : [],
            }));
        }

        this.activeThreadId = normalized.id;
        this.liveThreadId = normalized.id;
        this.sortThreads();
        this.emit();
        return this.findThread(normalized.id);
    }

    clearLiveThreadMessages() {
        const liveThread = this.getLiveThread();
        if (!liveThread) {
            return;
        }

        liveThread.messages = [];
        liveThread.title = "Новый чат";
        liveThread.updatedAt = Date.now();
        liveThread.messageCount = 0;
        this.activeThreadId = liveThread.id;
        this.liveThreadId = liveThread.id;
        this.sortThreads();
        this.emit();
    }

    setThreadMessages(threadId, messages, { emit = true } = {}) {
        const thread = this.findThread(threadId);
        if (!thread) {
            return null;
        }

        thread.messages = normalizeMessages(messages);
        thread.title = buildThreadTitle(thread.messages);
        thread.messageCount = thread.messages.length;
        thread.updatedAt = Date.now();
        if (emit) {
            this.sortThreads();
            this.emit();
        }
        return thread;
    }

    appendUserMessage(content, attachments = []) {
        const liveThread = this.getLiveThread();
        if (!liveThread) {
            throw new Error("Live thread is not initialized");
        }

        const message = {
            id: createId("msg"),
            role: "user",
            content,
            html: "",
            sourceUserMessageId: null,
            attachments: attachments.map(normalizeAttachment),
            state: "done",
        };

        liveThread.messages.push(message);
        liveThread.title = buildThreadTitle(liveThread.messages);
        liveThread.updatedAt = Date.now();
        liveThread.messageCount = liveThread.messages.length;
        this.activeThreadId = liveThread.id;
        this.liveThreadId = liveThread.id;
        this.sortThreads();
        this.emit();
        return message;
    }

    appendAssistantPlaceholder(sourceUserMessageId) {
        const liveThread = this.getLiveThread();
        if (!liveThread) {
            throw new Error("Live thread is not initialized");
        }

        const message = {
            id: createId("msg"),
            role: "assistant",
            content: "",
            html: "",
            sourceUserMessageId,
            attachments: [],
            state: "streaming",
        };

        liveThread.messages.push(message);
        liveThread.updatedAt = Date.now();
        liveThread.messageCount = liveThread.messages.length;
        this.activeThreadId = liveThread.id;
        this.liveThreadId = liveThread.id;
        this.sortThreads();
        this.emit();
        return message;
    }

    finalizeAssistantMessage(messageId, payload, threadId = null) {
        const thread = threadId ? this.findThread(threadId) : this.findThreadByMessage(messageId);
        const message = thread?.messages.find((item) => item.id === messageId);
        if (!message) {
            return null;
        }

        message.content = payload.content || "";
        message.html = payload.html || "";
        message.state = payload.state || "done";
        thread.title = buildThreadTitle(thread.messages);
        thread.updatedAt = Date.now();
        thread.messageCount = thread.messages.length;
        this.sortThreads();
        this.emit();
        return message;
    }

    markAssistantCancelled(messageId, fallbackContent, threadId = null) {
        return this.finalizeAssistantMessage(messageId, {
            content: fallbackContent,
            html: "",
            state: "cancelled",
        }, threadId);
    }

    findMessage(threadId, messageId) {
        const thread = this.findThread(threadId);
        return thread?.messages.find((message) => message.id === messageId) || null;
    }

    findThread(threadId) {
        return this.threads.find((thread) => thread.id === threadId) || null;
    }

    findThreadByMessage(messageId) {
        return this.threads.find((thread) =>
            thread.messages.some((message) => message.id === messageId),
        ) || null;
    }

    createThreadRecord(thread) {
        const normalized = normalizeThreadSummary(thread);
        const messages = normalizeMessages(thread?.messages || []);
        return {
            id: normalized.id,
            title: messages.length ? buildThreadTitle(messages) : normalized.title,
            createdAt: Number(thread?.createdAt || normalized.updatedAt || Date.now()),
            updatedAt: normalized.updatedAt,
            messageCount: messages.length || normalized.messageCount,
            messages,
        };
    }

    resolveThreadId(threadId, threads = this.threads) {
        const normalizedThreadId = String(threadId || DEFAULT_THREAD_ID).trim() || DEFAULT_THREAD_ID;
        if (threads.some((thread) => thread.id === normalizedThreadId)) {
            return normalizedThreadId;
        }
        if (threads.length) {
            return threads[0].id;
        }
        return DEFAULT_THREAD_ID;
    }

    sortThreads() {
        this.threads.sort((left, right) => {
            if (right.updatedAt !== left.updatedAt) {
                return right.updatedAt - left.updatedAt;
            }
            return left.id.localeCompare(right.id);
        });
    }

    emit() {
        const snapshot = this.getState();
        for (const listener of this.listeners) {
            listener(snapshot);
        }
    }
}
