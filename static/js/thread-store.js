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
        state: message.state || (role === "assistant" ? "done" : "done"),
    };

    return {
        message: normalized,
        lastUserMessageId: role === "user" ? normalized.id : lastUserMessageId,
    };
}

function buildThreadTitle(messages) {
    const firstUserMessage = messages.find((message) => message.role === "user" && message.content.trim());
    if (!firstUserMessage) {
        return "Новый чат";
    }

    const normalized = firstUserMessage.content.trim().replace(/\s+/g, " ");
    return normalized.length > 48 ? `${normalized.slice(0, 48)}...` : normalized;
}

export class ThreadStore {
    constructor({ initialMessages = [], initialThreadId = DEFAULT_THREAD_ID } = {}) {
        this.listeners = new Set();
        this.threads = [];
        this.activeThreadId = null;
        this.liveThreadId = null;
        this.bootstrap(initialMessages, initialThreadId);
    }

    subscribe(listener) {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    bootstrap(initialMessages, initialThreadId = DEFAULT_THREAD_ID) {
        const normalizedMessages = [];
        let lastUserMessageId = null;

        for (const rawMessage of initialMessages) {
            const normalized = normalizeMessage(rawMessage, lastUserMessageId);
            normalizedMessages.push(normalized.message);
            lastUserMessageId = normalized.lastUserMessageId;
        }

        const initialThread = this.createThreadRecord({
            id: initialThreadId || DEFAULT_THREAD_ID,
            mode: "live",
            messages: normalizedMessages,
        });

        this.threads = [initialThread];
        this.activeThreadId = initialThread.id;
        this.liveThreadId = initialThread.id;
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
        return threadId !== this.liveThreadId;
    }

    setActiveThread(threadId) {
        if (!this.findThread(threadId)) {
            return;
        }
        this.activeThreadId = threadId;
        this.emit();
    }

    startNewThread() {
        const liveThread = this.getLiveThread();
        if (liveThread && liveThread.messages.length === 0) {
            this.activeThreadId = liveThread.id;
            this.emit();
            return liveThread;
        }

        if (liveThread) {
            liveThread.mode = "snapshot";
            liveThread.updatedAt = Date.now();
        }

        const thread = this.createThreadRecord({ mode: "live", messages: [] });
        this.threads.unshift(thread);
        this.activeThreadId = thread.id;
        this.liveThreadId = thread.id;
        this.emit();
        return thread;
    }

    clearLiveThreadMessages() {
        const liveThread = this.getLiveThread();
        if (!liveThread) {
            return;
        }

        liveThread.messages = [];
        liveThread.title = "Новый чат";
        liveThread.updatedAt = Date.now();
        this.activeThreadId = liveThread.id;
        this.emit();
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
        this.activeThreadId = liveThread.id;
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
        this.activeThreadId = liveThread.id;
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
        thread.updatedAt = Date.now();
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

    createThreadRecord({ id = null, mode, messages }) {
        return {
            id: id || createId("thread"),
            title: buildThreadTitle(messages),
            mode,
            createdAt: Date.now(),
            updatedAt: Date.now(),
            messages: [...messages],
        };
    }

    emit() {
        const snapshot = this.getState();
        for (const listener of this.listeners) {
            listener(snapshot);
        }
    }
}
