import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const styles = readFileSync(new URL("../static/styles.css", import.meta.url), "utf8");

test("delete action is rendered as compact overlay control instead of separate strip button", () => {
    assert.match(styles, /\.thread-item \{[\s\S]*display: grid;/);
    assert.match(styles, /\.thread-item \{[\s\S]*grid-template-columns: minmax\(0, 1fr\) auto;/);
    assert.match(styles, /\.thread-item \{[\s\S]*padding: 0\.78rem 0\.88rem;/);
    assert.match(styles, /\.thread-delete-btn \{[\s\S]*width: 1\.8rem;/);
    assert.match(styles, /\.thread-delete-btn \{[\s\S]*height: 1\.8rem;/);
    assert.match(styles, /\.thread-delete-btn::before \{[\s\S]*mask:/);
});

test("delete action stays secondary until hover or focus", () => {
    assert.match(styles, /\.thread-delete-btn \{[\s\S]*opacity: 0;/);
    assert.match(styles, /\.thread-delete-btn \{[\s\S]*pointer-events: none;/);
    assert.match(styles, /\.thread-item:hover \.thread-delete-btn,[\s\S]*opacity: 1;/);
    assert.match(styles, /\.thread-item:focus-within \.thread-delete-btn[\s\S]*pointer-events: auto;/);
});

test("touch fallback keeps delete action accessible without changing backend semantics", () => {
    assert.match(styles, /@media \(hover: none\)/);
    assert.match(styles, /@media \(hover: none\) \{[\s\S]*\.thread-delete-btn \{[\s\S]*opacity: 0\.72;/);
    assert.match(styles, /@media \(hover: none\) \{[\s\S]*\.thread-delete-btn \{[\s\S]*pointer-events: auto;/);
});
