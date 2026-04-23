export const ChatLifecycle = Object.freeze({
    IDLE: "idle",
    SENDING: "sending",
    STREAMING: "streaming",
    DONE: "done",
    ERROR: "error",
    CANCELLED: "cancelled",
});

function createAttachmentRecord(file) {
    return {
        id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`,
        name: file.name,
        size: file.size,
        type: file.type || "application/octet-stream",
        lastModified: file.lastModified,
        file,
    };
}

export class ChatStore {
    constructor(initialState = {}) {
        this.listeners = new Set();
        this.state = {
            status: ChatLifecycle.IDLE,
            currentModel: initialState.currentModel || initialState.currentModelKey || "",
            currentModelKey: initialState.currentModelKey || initialState.currentModel || "",
            currentModelDescription: initialState.currentModelDescription || "Модель по умолчанию",
            authLabel: initialState.authLabel || "Kerberos / Active Directory",
            environmentLabel: initialState.environmentLabel || "corp.local",
            attachments: [],
            uploadingDocuments: false,
            error: null,
            activeJobId: null,
            pendingUserMessageId: null,
            pendingAssistantMessageId: null,
            readonlyThread: false,
        };
    }

    subscribe(listener) {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    getState() {
        return {
            ...this.state,
            attachments: this.state.attachments.map((attachment) => ({ ...attachment })),
        };
    }

    setState(partialState) {
        this.state = {
            ...this.state,
            ...partialState,
        };
        this.emit();
    }

    setStatus(status, extraState = {}) {
        this.setState({
            status,
            ...extraState,
        });
    }

    setModel(model) {
        this.setState({
            currentModel: model.name,
            currentModelKey: model.key,
            currentModelDescription: model.description,
        });
    }

    setReadonlyThread(isReadonly) {
        if (this.state.readonlyThread === isReadonly) {
            return;
        }
        this.setState({ readonlyThread: isReadonly });
    }

    setUploadingDocuments(isUploading) {
        if (this.state.uploadingDocuments === isUploading) {
            return;
        }
        this.setState({ uploadingDocuments: isUploading });
    }

    addAttachments(fileList) {
        const nextAttachments = [...this.state.attachments];

        for (const file of Array.from(fileList || [])) {
            const duplicate = nextAttachments.some(
                (attachment) =>
                    attachment.name === file.name &&
                    attachment.size === file.size &&
                    attachment.lastModified === file.lastModified,
            );
            if (!duplicate) {
                nextAttachments.push(createAttachmentRecord(file));
            }
        }

        this.setState({ attachments: nextAttachments });
    }

    removeAttachment(attachmentId) {
        this.setState({
            attachments: this.state.attachments.filter((attachment) => attachment.id !== attachmentId),
        });
    }

    clearAttachments() {
        if (!this.state.attachments.length) {
            return;
        }
        this.setState({ attachments: [] });
    }

    emit() {
        for (const listener of this.listeners) {
            listener(this.getState());
        }
    }
}
