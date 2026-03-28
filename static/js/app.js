import { APIClient, APIError } from "./api-client.js";
import { ChatLifecycle, ChatStore } from "./chat-store.js";
import { ThreadStore } from "./thread-store.js";
import { StreamController } from "./stream-controller.js";
import { ChatRenderer } from "./chat-renderer.js";
import { ModelSelector } from "./model-selector.js";

function parseBootstrapData() {
    const bootstrapElement = document.getElementById("chatBootstrap");
    if (!bootstrapElement) {
        return null;
    }

    try {
        return JSON.parse(bootstrapElement.textContent || "{}");
    } catch (error) {
        console.error("Failed to parse bootstrap data:", error);
        return null;
    }
}

function deriveEnvironmentLabel(hostname) {
    if (!hostname) {
        return "corp.local";
    }

    const segments = hostname.split(".");
    if (segments.length <= 2) {
        return hostname;
    }

    return segments.slice(1).join(".");
}

class CorporateAIApp {
    constructor(bootstrapData) {
        this.bootstrapData = bootstrapData;
        this.elements = {
            appRoot: document.getElementById("appRoot"),
            chatForm: document.getElementById("chatForm"),
            promptInput: document.getElementById("prompt"),
            chatScroll: document.getElementById("chatScroll"),
            chatInner: document.getElementById("chatInner"),
            modelSelect: document.getElementById("modelSelect"),
            logoutBtn: document.getElementById("logoutBtn"),
            sendBtn: document.getElementById("sendBtn"),
            stopBtn: document.getElementById("stopBtn"),
            newChatBtn: document.getElementById("newChatBtn"),
            clearHistoryBtn: document.getElementById("clearHistoryBtn"),
            attachBtn: document.getElementById("attachBtn"),
            attachmentInput: document.getElementById("attachmentInput"),
            attachmentList: document.getElementById("attachmentList"),
            threadList: document.getElementById("threadList"),
            threadCount: document.getElementById("threadCount"),
            threadBanner: document.getElementById("threadBanner"),
            modelStatus: document.getElementById("modelStatus"),
            authStatus: document.getElementById("authStatus"),
            environmentStatus: document.getElementById("environmentStatus"),
            lifecycleStatus: document.getElementById("lifecycleStatus"),
        };

        this.apiClient = new APIClient({
            getCsrfToken: () => this.getCsrfToken(),
            onUnauthorized: () => this.redirectToLogin(),
        });

        this.chatStore = new ChatStore({
            currentModel: bootstrapData.model.name,
            currentModelKey: bootstrapData.model.key,
            currentModelDescription: bootstrapData.model.description,
            authLabel: "Kerberos / Active Directory",
            environmentLabel: deriveEnvironmentLabel(bootstrapData.host),
        });
        this.threadStore = new ThreadStore({ initialMessages: bootstrapData.messages || [] });
        this.streamController = new StreamController(this.apiClient);
        this.renderer = new ChatRenderer(this.elements);
        this.modelSelector = new ModelSelector(this.elements.modelSelect);
        this.availableModels = [
            {
                key: bootstrapData.model.key,
                name: bootstrapData.model.name,
                description: bootstrapData.model.description,
            },
        ];
    }

    async init() {
        if (!this.elements.appRoot || !this.elements.chatForm || !this.elements.promptInput) {
            return;
        }

        this.bindEvents();
        this.renderLayout();
        await this.loadModels();
        this.elements.promptInput.focus();
    }

    bindEvents() {
        this.elements.chatForm.addEventListener("submit", (event) => {
            event.preventDefault();
            this.handleSendMessage();
        });

        this.elements.promptInput.addEventListener("input", () => {
            this.autoResize();
        });

        this.elements.promptInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                this.handleSendMessage();
            }
        });

        this.elements.newChatBtn?.addEventListener("click", () => {
            this.handleNewChat();
        });

        this.elements.clearHistoryBtn?.addEventListener("click", () => {
            this.handleClearActiveThread();
        });

        this.elements.stopBtn?.addEventListener("click", () => {
            this.handleStopGeneration();
        });

        this.elements.logoutBtn?.addEventListener("click", () => {
            this.handleLogout();
        });

        this.elements.modelSelect?.addEventListener("change", (event) => {
            this.handleModelSwitch(event.target.value);
        });

        this.elements.threadList?.addEventListener("click", (event) => {
            const target = event.target.closest("[data-thread-id]");
            if (!target) {
                return;
            }
            if ([ChatLifecycle.SENDING, ChatLifecycle.STREAMING].includes(this.chatStore.getState().status)) {
                this.renderer.showNotification("Во время генерации поток нельзя переключить. Сначала остановите ответ или дождитесь завершения.", "warning");
                return;
            }
            this.threadStore.setActiveThread(target.dataset.threadId);
            this.renderLayout();
        });

        this.elements.chatInner?.addEventListener("click", (event) => {
            const target = event.target.closest("[data-action]");
            if (!target) {
                return;
            }

            const action = target.dataset.action;
            if (action === "copy-message") {
                this.handleCopyMessage(target.dataset.messageId);
            }
            if (action === "regenerate-message") {
                this.handleRegenerateMessage(target.dataset.messageId);
            }
        });

        this.elements.attachBtn?.addEventListener("click", () => {
            this.elements.attachmentInput?.click();
        });

        this.elements.attachmentInput?.addEventListener("change", (event) => {
            this.chatStore.addAttachments(event.target.files);
            event.target.value = "";
            this.renderChrome();
        });

        this.elements.attachmentList?.addEventListener("click", (event) => {
            const target = event.target.closest("[data-action='remove-attachment']");
            if (!target) {
                return;
            }
            this.chatStore.removeAttachment(target.dataset.attachmentId);
            this.renderChrome();
        });
    }

    async loadModels() {
        try {
            const models = await this.apiClient.requestJSON("/api/models", {
                method: "GET",
                timeout: 10000,
            });
            this.availableModels = Array.isArray(models) ? models : [];
        } catch (error) {
            console.warn("Could not load models:", error);
            this.renderer.showNotification("Не удалось обновить каталог моделей", "warning");
        } finally {
            this.modelSelector.render(this.availableModels, this.chatStore.getState().currentModelKey);
            this.renderChrome();
        }
    }

    async handleSendMessage(promptOverride = null) {
        const chatState = this.chatStore.getState();
        const activeThread = this.threadStore.getActiveThread();
        const prompt = (promptOverride ?? this.elements.promptInput.value).trim();
        const selectedModel = chatState.currentModelKey || chatState.currentModel || null;

        if (!prompt || !activeThread || chatState.readonlyThread) {
            if (chatState.readonlyThread) {
                this.renderer.showNotification("Снимок диалога открыт только для чтения. Создайте новый чат для продолжения.", "warning");
            }
            return;
        }

        if ([ChatLifecycle.SENDING, ChatLifecycle.STREAMING].includes(chatState.status)) {
            return;
        }

        const attachments = promptOverride === null ? chatState.attachments : [];
        const hasAttachments = attachments.length > 0;
        const targetThreadId = this.threadStore.liveThreadId;
        const userMessage = this.threadStore.appendUserMessage(prompt, attachments);
        const assistantMessage = this.threadStore.appendAssistantPlaceholder(userMessage.id);

        this.renderer.appendMessage(userMessage);
        this.renderer.appendMessage(assistantMessage);

        this.chatStore.clearAttachments();
        this.chatStore.setUploadingDocuments(hasAttachments);
        this.chatStore.setStatus(ChatLifecycle.SENDING, {
            error: null,
            activeJobId: null,
            pendingUserMessageId: userMessage.id,
            pendingAssistantMessageId: assistantMessage.id,
        });

        this.elements.promptInput.value = "";
        this.autoResize();
        this.renderThreads();
        this.renderChrome();

        let fullText = "";

        try {
            if (hasAttachments) {
                await this.sendMessageWithFiles({
                    prompt,
                    model: selectedModel,
                    attachments,
                    onJob: (jobId) => {
                        this.chatStore.setStatus(ChatLifecycle.STREAMING, {
                            activeJobId: jobId,
                        });
                        this.renderChrome();
                    },
                    onToken: (token) => {
                        fullText += token;
                        if (this.chatStore.getState().status !== ChatLifecycle.STREAMING) {
                            this.chatStore.setStatus(ChatLifecycle.STREAMING);
                            this.renderChrome();
                        }
                        this.renderer.appendStreamingToken(assistantMessage.id, token);
                    },
                    onResult: (result) => {
                        fullText = result || fullText;
                    },
                    onDone: async () => {
                        const html = await this.renderMarkdown(fullText);
                        const finalized = this.threadStore.finalizeAssistantMessage(assistantMessage.id, {
                            content: fullText,
                            html,
                            state: "done",
                        }, targetThreadId);

                        if (finalized) {
                            this.renderer.finalizeAssistantMessage(finalized);
                        }

                        this.chatStore.setStatus(ChatLifecycle.DONE, {
                            activeJobId: null,
                            pendingUserMessageId: null,
                            pendingAssistantMessageId: null,
                        });
                        this.chatStore.setUploadingDocuments(false);
                        this.renderThreads();
                        this.renderChrome();
                    },
                    onCancelled: () => {
                        const finalText = fullText || "Генерация остановлена пользователем.";
                        const cancelled = this.threadStore.markAssistantCancelled(assistantMessage.id, finalText, targetThreadId);
                        if (cancelled) {
                            this.renderer.markMessageCancelled(cancelled);
                        }

                        this.chatStore.setStatus(ChatLifecycle.CANCELLED, {
                            activeJobId: null,
                            pendingUserMessageId: null,
                            pendingAssistantMessageId: null,
                        });
                        this.chatStore.setUploadingDocuments(false);
                        this.renderThreads();
                        this.renderChrome();
                    },
                    onError: (error) => {
                        throw error;
                    },
                });
                return;
            }

            await this.streamController.start({
                prompt,
                model: selectedModel,
                onJob: (jobId) => {
                    this.chatStore.setStatus(ChatLifecycle.STREAMING, {
                        activeJobId: jobId,
                    });
                    this.renderChrome();
                },
                onToken: (token) => {
                    fullText += token;
                    if (this.chatStore.getState().status !== ChatLifecycle.STREAMING) {
                        this.chatStore.setStatus(ChatLifecycle.STREAMING);
                        this.renderChrome();
                    }
                    this.renderer.appendStreamingToken(assistantMessage.id, token);
                },
                onDone: async () => {
                    const html = await this.renderMarkdown(fullText);
                    const finalized = this.threadStore.finalizeAssistantMessage(assistantMessage.id, {
                        content: fullText,
                        html,
                        state: "done",
                    }, targetThreadId);

                    if (finalized) {
                        this.renderer.finalizeAssistantMessage(finalized);
                    }

                    this.chatStore.setStatus(ChatLifecycle.DONE, {
                        activeJobId: null,
                        pendingUserMessageId: null,
                        pendingAssistantMessageId: null,
                    });
                    this.chatStore.setUploadingDocuments(false);
                    this.renderThreads();
                    this.renderChrome();
                },
                onCancelled: () => {
                    const finalText = fullText || "Генерация остановлена пользователем.";
                    const cancelled = this.threadStore.markAssistantCancelled(assistantMessage.id, finalText, targetThreadId);
                    if (cancelled) {
                        this.renderer.markMessageCancelled(cancelled);
                    }

                    this.chatStore.setStatus(ChatLifecycle.CANCELLED, {
                        activeJobId: null,
                        pendingUserMessageId: null,
                        pendingAssistantMessageId: null,
                    });
                    this.chatStore.setUploadingDocuments(false);
                    this.renderThreads();
                    this.renderChrome();
                },
                onError: (error) => {
                    throw error;
                },
            });
        } catch (error) {
            const message = error instanceof APIError ? error.message : "Не удалось отправить сообщение";
            const failed = this.threadStore.finalizeAssistantMessage(assistantMessage.id, {
                content: `Ошибка: ${message}`,
                html: "",
                state: "error",
            }, targetThreadId);

            if (failed) {
                this.renderer.finalizeAssistantMessage(failed);
            }

            this.chatStore.setStatus(ChatLifecycle.ERROR, {
                error: message,
                activeJobId: null,
                pendingUserMessageId: null,
                pendingAssistantMessageId: null,
            });
            this.chatStore.setUploadingDocuments(false);
            this.renderer.showNotification(message, "error");
            this.renderThreads();
            this.renderChrome();
        }
    }

    async sendMessageWithFiles({ prompt, model, attachments, onJob, onToken, onResult, onDone, onError, onCancelled }) {
        const formData = new FormData();
        formData.append("message", prompt);
        if (model) {
            formData.append("model", model);
        }

        for (const attachment of attachments) {
            if (attachment?.file instanceof File) {
                formData.append("files", attachment.file, attachment.name);
            }
        }

        return this.streamController.start({
            url: "/api/chat_with_files",
            body: formData,
            headers: {
                Accept: "text/event-stream",
            },
            timeout: 300000,
            onJob,
            onToken,
            onResult,
            onDone,
            onError,
            onCancelled,
        });
    }

    async handleNewChat() {
        if ([ChatLifecycle.SENDING, ChatLifecycle.STREAMING].includes(this.chatStore.getState().status)) {
            await this.handleStopGeneration({ silent: true });
        }

        try {
            await this.apiClient.requestJSON("/api/chat/clear", {
                method: "POST",
                timeout: 15000,
            });
            this.threadStore.startNewThread();
            this.chatStore.clearAttachments();
            this.chatStore.setUploadingDocuments(false);
            this.chatStore.setStatus(ChatLifecycle.IDLE, {
                error: null,
                activeJobId: null,
                pendingUserMessageId: null,
                pendingAssistantMessageId: null,
            });
            this.elements.promptInput.value = "";
            this.autoResize();
            this.renderLayout();
            this.renderer.showNotification("Создан новый чат. Серверный контекст сброшен.", "info");
        } catch (error) {
            const message = error instanceof APIError ? error.message : "Не удалось создать новый чат";
            this.renderer.showNotification(message, "error");
        }
    }

    async handleClearActiveThread() {
        if (this.threadStore.isReadonlyThread()) {
            this.renderer.showNotification("Сохранённый снимок нельзя очистить на сервере. Переключитесь на активный чат.", "warning");
            return;
        }

        try {
            await this.apiClient.requestJSON("/api/chat/clear", {
                method: "POST",
                timeout: 15000,
            });
            this.threadStore.clearLiveThreadMessages();
            this.chatStore.clearAttachments();
            this.chatStore.setUploadingDocuments(false);
            this.chatStore.setStatus(ChatLifecycle.IDLE, {
                error: null,
                activeJobId: null,
                pendingUserMessageId: null,
                pendingAssistantMessageId: null,
            });
            this.elements.promptInput.value = "";
            this.autoResize();
            this.renderLayout();
            this.renderer.showNotification("Активный чат очищен и серверный контекст сброшен.", "info");
        } catch (error) {
            const message = error instanceof APIError ? error.message : "Не удалось очистить активный чат";
            this.renderer.showNotification(message, "error");
        }
    }

    async handleStopGeneration({ silent = false } = {}) {
        if (![ChatLifecycle.SENDING, ChatLifecycle.STREAMING].includes(this.chatStore.getState().status)) {
            return;
        }

        await this.streamController.stop({ silent: true });

        if (!silent) {
            this.renderer.showNotification("Генерация остановлена", "info");
        }
    }

    async handleModelSwitch(modelKey) {
        const previousModelKey = this.chatStore.getState().currentModelKey;
        this.modelSelector.setDisabled(true);

        try {
            const payload = await this.apiClient.requestJSON("/api/switch-model", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ model: modelKey }),
                timeout: 15000,
            });

            this.chatStore.setModel(payload);
            this.renderer.showNotification(`Модель переключена: ${payload.name}`, "info");
        } catch (error) {
            const message = error instanceof APIError ? error.message : "Не удалось переключить модель";
            this.renderer.showNotification(message, "error");
            this.modelSelector.render(this.availableModels, previousModelKey);
        } finally {
            this.modelSelector.setDisabled(false);
            this.renderChrome();
        }
    }

    async handleLogout() {
        try {
            await this.apiClient.requestJSON("/logout", {
                method: "POST",
                timeout: 15000,
                autoRefresh: false,
            });
        } catch (error) {
            console.warn("Logout failed:", error);
        } finally {
            this.redirectToLogin();
        }
    }

    async handleCopyMessage(messageId) {
        const message = this.threadStore.findMessage(this.threadStore.activeThreadId, messageId);
        if (!message) {
            return;
        }

        try {
            await navigator.clipboard.writeText(message.content);
            this.renderer.showNotification("Ответ скопирован", "info");
        } catch (error) {
            this.renderer.showNotification("Не удалось скопировать текст", "error");
        }
    }

    async handleRegenerateMessage(messageId) {
        if (this.threadStore.isReadonlyThread()) {
            this.renderer.showNotification("Регенерация доступна только в активном серверном чате.", "warning");
            return;
        }

        const activeThread = this.threadStore.getActiveThread();
        const assistantMessage = activeThread?.messages.find((message) => message.id === messageId);
        const sourceUserMessageId = assistantMessage?.sourceUserMessageId;
        const sourceUserMessage = sourceUserMessageId
            ? activeThread.messages.find((message) => message.id === sourceUserMessageId)
            : null;

        if (!sourceUserMessage?.content) {
            this.renderer.showNotification("Не удалось определить исходный запрос для регенерации.", "warning");
            return;
        }

        await this.handleSendMessage(sourceUserMessage.content);
    }

    async renderMarkdown(text) {
        if (!text) {
            return "";
        }

        const payload = await this.apiClient.requestJSON("/api/render-markdown", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ text }),
            timeout: 15000,
        });

        return payload?.html || "";
    }

    renderLayout() {
        this.renderThreads();
        this.renderActiveThread();
        this.renderChrome();
    }

    renderThreads() {
        const threadState = this.threadStore.getState();
        this.renderer.renderThreadList(threadState.threads, threadState.activeThreadId, threadState.liveThreadId);
    }

    renderActiveThread() {
        this.renderer.renderThread(this.threadStore.getActiveThread(), {
            emptyStateDescription: this.chatStore.getState().currentModelDescription,
        });
    }

    renderChrome() {
        const readonlyThread = this.threadStore.isReadonlyThread();
        this.chatStore.setReadonlyThread(readonlyThread);
        const chatState = this.chatStore.getState();

        this.renderer.renderAttachments(chatState.attachments);
        this.renderer.renderBanner({
            readonlyThread,
            hasAttachments: chatState.attachments.length > 0,
            uploadingDocuments: chatState.uploadingDocuments,
        });
        this.renderer.updateHeader({
            currentModel: chatState.currentModel,
            authLabel: chatState.authLabel,
            environmentLabel: chatState.environmentLabel,
            status: chatState.status,
        });
        this.renderer.setComposerState({
            status: chatState.status,
            readonlyThread,
        });
        const isBusy = [ChatLifecycle.SENDING, ChatLifecycle.STREAMING].includes(chatState.status);
        if (this.elements.newChatBtn) {
            this.elements.newChatBtn.disabled = isBusy;
        }
        if (this.elements.clearHistoryBtn) {
            this.elements.clearHistoryBtn.disabled = isBusy || readonlyThread;
        }
        this.modelSelector.setDisabled(isBusy);
        this.modelSelector.render(this.availableModels, chatState.currentModelKey);
    }

    autoResize() {
        const textarea = this.elements.promptInput;
        if (!textarea) {
            return;
        }

        textarea.style.height = "auto";
        textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
    }

    getCsrfToken() {
        const match = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    redirectToLogin() {
        window.location.href = "/login";
    }
}

document.addEventListener("DOMContentLoaded", async () => {
    const bootstrapData = parseBootstrapData();
    if (!bootstrapData) {
        return;
    }

    const app = new CorporateAIApp(bootstrapData);
    window.corporateAIApp = app;
    await app.init();
});
