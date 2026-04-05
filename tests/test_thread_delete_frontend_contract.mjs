import test from "node:test";
import assert from "node:assert/strict";

class FakeClassList {
    constructor() {
        this.values = new Set();
    }

    add(...classNames) {
        for (const className of classNames) {
            this.values.add(className);
        }
    }
}

class FakeElement {
    constructor(tagName) {
        this.tagName = tagName.toUpperCase();
        this.children = [];
        this.dataset = {};
        this.className = "";
        this.classList = new FakeClassList();
        this.textContent = "";
        this.type = "";
        this.title = "";
        this.attributes = new Map();
    }

    append(...nodes) {
        this.children.push(...nodes);
    }

    appendChild(node) {
        this.children.push(node);
        return node;
    }

    replaceChildren(...nodes) {
        this.children = [...nodes];
    }

    setAttribute(name, value) {
        this.attributes.set(name, value);
    }
}

global.document = {
    createElement(tagName) {
        return new FakeElement(tagName);
    },
    createDocumentFragment() {
        return new FakeElement("#fragment");
    },
};

const { ChatRenderer } = await import("../static/js/chat-renderer.js");
const { ThreadStore } = await import("../static/js/thread-store.js");

test("thread list render adds dedicated delete action", () => {
    const threadList = new FakeElement("div");
    const renderer = new ChatRenderer({ threadList, threadCount: new FakeElement("span") });

    renderer.renderThreadList(
        [
            { id: "thread-a", title: "Первый", updatedAt: 10_000, messageCount: 1 },
            { id: "thread-b", title: "Второй", updatedAt: 9_000, messageCount: 0 },
        ],
        "thread-a",
        "thread-a",
    );

    const fragment = threadList.children[0];
    const firstRow = fragment.children[0];
    const deleteButton = firstRow.children[1];

    assert.equal(deleteButton.dataset.action, "delete-thread");
    assert.equal(deleteButton.dataset.threadId, "thread-a");
    assert.equal(deleteButton.textContent, "");
    assert.equal(deleteButton.attributes.get("aria-label"), "Удалить диалог Первый");
});

test("thread store keeps active thread when deleting inactive thread via server truth", () => {
    const store = new ThreadStore({
        initialThreads: [
            { id: "thread-a", title: "Первый", updatedAt: 20_000, messageCount: 1 },
            { id: "thread-b", title: "Второй", updatedAt: 10_000, messageCount: 1 },
        ],
        initialThreadId: "thread-a",
    });

    store.replaceThreads(
        [{ id: "thread-a", title: "Первый", updatedAt: 20_000, messageCount: 1 }],
        "thread-a",
    );

    assert.equal(store.getState().activeThreadId, "thread-a");
    assert.deepEqual(store.getThreads().map((thread) => thread.id), ["thread-a"]);
});

test("thread store switches to fallback thread when active thread is deleted", () => {
    const store = new ThreadStore({
        initialThreads: [
            { id: "thread-a", title: "Первый", updatedAt: 20_000, messageCount: 1 },
            { id: "thread-b", title: "Второй", updatedAt: 10_000, messageCount: 1 },
        ],
        initialThreadId: "thread-a",
    });

    store.replaceThreads(
        [{ id: "thread-b", title: "Второй", updatedAt: 10_000, messageCount: 1 }],
        "thread-b",
    );

    assert.equal(store.getState().activeThreadId, "thread-b");
    assert.deepEqual(store.getThreads().map((thread) => thread.id), ["thread-b"]);
});
