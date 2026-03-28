function createElement(tagName, className, textContent = "") {
    const element = document.createElement(tagName);
    if (className) {
        element.className = className;
    }
    if (textContent) {
        element.textContent = textContent;
    }
    return element;
}

function formatTimestamp(timestamp) {
    return new Intl.DateTimeFormat("ru-RU", {
        hour: "2-digit",
        minute: "2-digit",
    }).format(timestamp);
}

function formatBytes(bytes) {
    if (!bytes) {
        return "0 B";
    }

    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let unitIndex = 0;

    while (value >= 1024 && unitIndex < units.length - 1) {
        value /= 1024;
        unitIndex += 1;
    }

    return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function parseHtmlFragment(html) {
    const parser = new DOMParser();
    const documentFragment = document.createDocumentFragment();
    const parsed = parser.parseFromString(html, "text/html");

    for (const node of Array.from(parsed.body.childNodes)) {
        documentFragment.appendChild(node);
    }

    return documentFragment;
}

export class ChatRenderer {
    constructor(elements) {
        this.elements = elements;
        this.messageElements = new Map();
        this.messageContentElements = new Map();
        this.streamingTextNodes = new Map();
        this.streamBuffers = new Map();
        this.streamFrameId = null;
        this.toastTimer = null;
    }

    renderThreadList(threads, activeThreadId, liveThreadId) {
        if (!this.elements.threadList) {
            return;
        }

        const fragment = document.createDocumentFragment();

        for (const thread of threads) {
            const button = createElement("button", "thread-item");
            button.type = "button";
            button.dataset.threadId = thread.id;
            if (thread.id === activeThreadId) {
                button.classList.add("is-active");
            }
            if (thread.id === liveThreadId) {
                button.classList.add("is-live");
            }

            const title = createElement("span", "thread-title", thread.title);
            const meta = createElement(
                "span",
                "thread-meta",
                thread.id === liveThreadId ? "Активный серверный контекст" : `Снимок • ${formatTimestamp(thread.updatedAt)}`,
            );

            button.append(title, meta);
            fragment.appendChild(button);
        }

        this.elements.threadList.replaceChildren(fragment);

        if (this.elements.threadCount) {
            this.elements.threadCount.textContent = String(threads.length);
        }
    }

    renderThread(thread, options = {}) {
        if (!this.elements.chatInner) {
            return;
        }

        this.messageElements.clear();
        this.messageContentElements.clear();
        this.streamingTextNodes.clear();
        this.streamBuffers.clear();

        const fragment = document.createDocumentFragment();

        if (!thread || thread.messages.length === 0) {
            fragment.appendChild(this.createEmptyState(options.emptyStateDescription || "Модель по умолчанию"));
        } else {
            for (const message of thread.messages) {
                fragment.appendChild(this.createMessageElement(message));
            }
        }

        this.elements.chatInner.replaceChildren(fragment);
        this.scrollToBottom({ force: true });
    }

    appendMessage(message) {
        if (!this.elements.chatInner) {
            return;
        }

        const emptyState = this.elements.chatInner.querySelector(".empty-state");
        if (emptyState) {
            emptyState.remove();
        }

        const messageElement = this.createMessageElement(message);
        this.elements.chatInner.appendChild(messageElement);
        this.scrollToBottom();
    }

    finalizeAssistantMessage(message) {
        const contentElement = this.messageContentElements.get(message.id);
        if (!contentElement) {
            return;
        }

        this.streamingTextNodes.delete(message.id);
        this.streamBuffers.delete(message.id);

        if (message.html) {
            contentElement.replaceChildren(parseHtmlFragment(message.html));
        } else {
            contentElement.replaceChildren(document.createTextNode(message.content));
        }

        const messageElement = this.messageElements.get(message.id);
        if (messageElement) {
            messageElement.dataset.messageState = message.state || "done";
            this.renderMessageActions(messageElement, message);
        }

        this.scrollToBottom();
    }

    markMessageCancelled(message) {
        this.finalizeAssistantMessage(message);
    }

    appendStreamingToken(messageId, token) {
        const currentBuffer = this.streamBuffers.get(messageId) || "";
        this.streamBuffers.set(messageId, currentBuffer + token);

        if (this.streamFrameId) {
            return;
        }

        this.streamFrameId = window.requestAnimationFrame(() => {
            this.flushStreamingBuffers();
        });
    }

    flushStreamingBuffers() {
        this.streamFrameId = null;

        for (const [messageId, buffer] of this.streamBuffers.entries()) {
            if (!buffer) {
                continue;
            }

            const contentElement = this.messageContentElements.get(messageId);
            if (!contentElement) {
                continue;
            }

            let textNode = this.streamingTextNodes.get(messageId);
            if (!textNode) {
                contentElement.replaceChildren();
                textNode = document.createTextNode("");
                contentElement.appendChild(textNode);
                this.streamingTextNodes.set(messageId, textNode);
            }

            textNode.appendData(buffer);
            this.streamBuffers.set(messageId, "");
        }

        this.scrollToBottom();
    }

    setComposerState({ status, readonlyThread }) {
        const isBusy = status === "sending" || status === "streaming";

        if (this.elements.sendBtn) {
            this.elements.sendBtn.disabled = isBusy || readonlyThread;
        }
        if (this.elements.stopBtn) {
            this.elements.stopBtn.hidden = !isBusy;
            this.elements.stopBtn.disabled = !isBusy;
        }
        if (this.elements.promptInput) {
            this.elements.promptInput.disabled = readonlyThread;
            this.elements.promptInput.placeholder = readonlyThread
                ? "Исторический поток открыт только для чтения. Создайте новый чат для продолжения."
                : "Напишите сообщение... (Shift+Enter для новой строки)";
        }
        if (this.elements.attachBtn) {
            this.elements.attachBtn.disabled = isBusy || readonlyThread;
        }
    }

    renderAttachments(attachments) {
        if (!this.elements.attachmentList) {
            return;
        }

        if (!attachments.length) {
            this.elements.attachmentList.replaceChildren();
            this.elements.attachmentList.hidden = true;
            return;
        }

        const fragment = document.createDocumentFragment();
        for (const attachment of attachments) {
            const item = createElement("div", "attachment-chip");
            item.dataset.attachmentId = attachment.id;

            const meta = createElement("div", "attachment-chip-meta");
            const name = createElement("span", "attachment-chip-name", attachment.name);
            const size = createElement("span", "attachment-chip-size", formatBytes(attachment.size));
            meta.append(name, size);

            const removeButton = createElement("button", "attachment-chip-remove", "Удалить");
            removeButton.type = "button";
            removeButton.dataset.action = "remove-attachment";
            removeButton.dataset.attachmentId = attachment.id;

            item.append(meta, removeButton);
            fragment.appendChild(item);
        }

        this.elements.attachmentList.replaceChildren(fragment);
        this.elements.attachmentList.hidden = false;
    }

    renderBanner({ readonlyThread, hasAttachments, uploadingDocuments }) {
        if (!this.elements.threadBanner) {
            return;
        }

        if (readonlyThread) {
            this.elements.threadBanner.hidden = false;
            this.elements.threadBanner.textContent =
                "Открыт сохранённый снимок диалога. Продолжение доступно только в активном серверном чате.";
            return;
        }

        if (uploadingDocuments) {
            this.elements.threadBanner.hidden = false;
            this.elements.threadBanner.textContent =
                "Обрабатываем документы и готовим их для ответа модели...";
            return;
        }

        if (hasAttachments) {
            this.elements.threadBanner.hidden = false;
            this.elements.threadBanner.textContent =
                "Выбраны файлы. Они будут отправлены вместе с сообщением и включены в контекст ответа.";
            return;
        }

        this.elements.threadBanner.hidden = true;
        this.elements.threadBanner.textContent = "";
    }

    updateHeader({ currentModel, authLabel, environmentLabel, status }) {
        if (this.elements.modelStatus) {
            this.elements.modelStatus.textContent = currentModel;
        }
        if (this.elements.authStatus) {
            this.elements.authStatus.textContent = authLabel;
        }
        if (this.elements.environmentStatus) {
            this.elements.environmentStatus.textContent = environmentLabel;
        }
        if (this.elements.lifecycleStatus) {
            this.elements.lifecycleStatus.textContent = status;
            this.elements.lifecycleStatus.dataset.status = status;
        }
    }

    showNotification(message, type = "info") {
        let toast = this.elements.toast;
        if (!toast) {
            toast = createElement("div", "toast");
            document.body.appendChild(toast);
            this.elements.toast = toast;
        }

        toast.textContent = message;
        toast.dataset.type = type;
        toast.classList.add("visible");
        window.clearTimeout(this.toastTimer);
        this.toastTimer = window.setTimeout(() => {
            toast.classList.remove("visible");
        }, 2800);
    }

    scrollToBottom({ force = false } = {}) {
        if (!this.elements.chatScroll) {
            return;
        }

        const { scrollTop, scrollHeight, clientHeight } = this.elements.chatScroll;
        const isNearBottom = scrollHeight - (scrollTop + clientHeight) < 120;
        if (!force && !isNearBottom) {
            return;
        }

        this.elements.chatScroll.scrollTop = this.elements.chatScroll.scrollHeight;
    }

    createMessageElement(message) {
        const messageElement = createElement("article", `message message--${message.role}`);
        messageElement.dataset.messageId = message.id;
        messageElement.dataset.role = message.role;
        messageElement.dataset.messageState = message.state || "done";
        this.messageElements.set(message.id, messageElement);

        const avatar = createElement("div", `message-avatar message-avatar--${message.role}`);
        avatar.setAttribute("aria-hidden", "true");
        avatar.textContent = message.role === "assistant" ? "AI" : "ВЫ";

        const body = createElement("div", "message-body");
        const meta = createElement("div", "message-meta");
        const roleLabel = createElement(
            "span",
            "message-role",
            message.role === "assistant" ? "Assistant" : "Вы",
        );
        meta.appendChild(roleLabel);

        const bubble = createElement("div", "message-bubble");
        const content = createElement("div", "message-content");
        this.messageContentElements.set(message.id, content);

        if (message.role === "assistant" && message.html) {
            content.replaceChildren(parseHtmlFragment(message.html));
        } else if (message.role === "assistant" && message.state === "streaming") {
            content.appendChild(createElement("span", "streaming-placeholder", "Генерация ответа..."));
        } else {
            content.appendChild(document.createTextNode(message.content));
        }

        body.append(meta);

        if (Array.isArray(message.attachments) && message.attachments.length) {
            bubble.appendChild(this.createAttachmentPreview(message.attachments));
        }

        bubble.append(content);
        body.append(bubble);
        body.appendChild(this.createMessageActions(message));
        if (message.role === "assistant") {
            messageElement.append(avatar, body);
        } else {
            messageElement.append(body, avatar);
        }
        return messageElement;
    }

    createAttachmentPreview(attachments) {
        const list = createElement("div", "message-attachments");

        for (const attachment of attachments) {
            const item = createElement("span", "message-attachment");
            const name = createElement("span", "message-attachment-name", attachment.name);
            const size = createElement("span", "message-attachment-size", formatBytes(attachment.size));
            item.append(name, size);
            list.appendChild(item);
        }

        return list;
    }

    createMessageActions(message) {
        const actions = createElement("div", "message-actions");
        if (message.role !== "assistant" || !message.content) {
            return actions;
        }

        const copyButton = createElement("button", "action-btn", "Копировать");
        copyButton.type = "button";
        copyButton.dataset.action = "copy-message";
        copyButton.dataset.messageId = message.id;

        const regenerateButton = createElement("button", "action-btn", "Регенерировать");
        regenerateButton.type = "button";
        regenerateButton.dataset.action = "regenerate-message";
        regenerateButton.dataset.messageId = message.id;

        actions.append(copyButton, regenerateButton);
        return actions;
    }

    renderMessageActions(messageElement, message) {
        const actions = messageElement.querySelector(".message-actions");
        if (!actions) {
            return;
        }

        const nextActions = this.createMessageActions(message);
        actions.replaceWith(nextActions);
    }

    createEmptyState(modelDescription) {
        const wrapper = createElement("div", "empty-state");
        const title = createElement("h1", "empty-state-title", "Корпоративный AI Assistant");
        const description = createElement("p", "empty-state-description", modelDescription);
        wrapper.append(title, description);
        return wrapper;
    }
}
