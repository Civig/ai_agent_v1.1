"""Internal helpers for future document comparison normalization.

This module intentionally does not call an LLM, expose API surface, run file
uploads, use storage, or affect the existing file-chat runtime path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_PARSER_VERSION = "parser-v1"
MAX_NORMALIZED_BLOCK_TEXT_CHARS = 8000

DOCX_SECTION_LABELS = {
    "DOCX Body": "body",
    "DOCX Header": "header",
    "DOCX Footer": "footer",
    "DOCX Comments": "comments",
    "Tracked changes": "tracked_changes",
    "Embedded images": "embedded_images",
}

METADATA_PREFIXES = (
    "Formula:",
    "Merged cells:",
    "Hidden sheet:",
    "Hidden row:",
    "Hidden rows:",
    "Hidden column:",
    "Hidden columns:",
    "Embedded images",
)

PDF_OCR_PAGE_RE = re.compile(r"^PDF OCR Page\s+(\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class BlockSource:
    filename: str
    section: str = ""
    page: int | None = None
    sheet: str = ""
    row_index: int | None = None
    column: str = ""
    raw_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "section": self.section,
            "page": self.page,
            "sheet": self.sheet,
            "row_index": self.row_index,
            "column": self.column,
            "raw_label": self.raw_label,
        }


@dataclass(frozen=True)
class NormalizedBlock:
    block_id: str
    type: str
    order_index: int
    text: str
    normalized_text: str
    hash: str
    source: BlockSource
    cells: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "type": self.type,
            "order_index": self.order_index,
            "text": self.text,
            "normalized_text": self.normalized_text,
            "hash": self.hash,
            "source": self.source.to_dict(),
            "cells": list(self.cells),
        }


@dataclass(frozen=True)
class NormalizedDocument:
    document_id: str
    filename: str
    format: str
    parser_version: str
    blocks: tuple[NormalizedBlock, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "format": self.format,
            "parser_version": self.parser_version,
            "blocks": [block.to_dict() for block in self.blocks],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class ComparisonChange:
    change_id: str
    change_type: str
    block_type: str
    source_a: BlockSource | None = None
    source_b: BlockSource | None = None
    text_a: str = ""
    text_b: str = ""
    hash_a: str = ""
    hash_b: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "change_type": self.change_type,
            "block_type": self.block_type,
            "source_a": self.source_a.to_dict() if self.source_a else None,
            "source_b": self.source_b.to_dict() if self.source_b else None,
            "text_a": self.text_a,
            "text_b": self.text_b,
            "hash_a": self.hash_a,
            "hash_b": self.hash_b,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ComparisonResult:
    document_a_id: str
    document_b_id: str
    added: tuple[ComparisonChange, ...]
    removed: tuple[ComparisonChange, ...]
    changed: tuple[ComparisonChange, ...]
    unchanged_count: int
    summary: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_a_id": self.document_a_id,
            "document_b_id": self.document_b_id,
            "added": [change.to_dict() for change in self.added],
            "removed": [change.to_dict() for change in self.removed],
            "changed": [change.to_dict() for change in self.changed],
            "unchanged_count": self.unchanged_count,
            "summary": dict(self.summary),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class _Section:
    label: str
    text: str


def normalize_text_for_compare(text: str) -> str:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.casefold()


def normalize_extracted_document(
    *,
    filename: str,
    file_format: str,
    content: str,
    parser_version: str = DEFAULT_PARSER_VERSION,
) -> NormalizedDocument:
    normalized_filename = _normalize_filename(filename)
    normalized_format = _normalize_file_format(file_format, normalized_filename)
    parser_version = (parser_version or DEFAULT_PARSER_VERSION).strip() or DEFAULT_PARSER_VERSION
    sections = _split_labeled_sections(content or "")
    blocks: list[NormalizedBlock] = []

    if normalized_format == "docx":
        _normalize_docx_sections(blocks, normalized_format, normalized_filename, sections)
    elif normalized_format in {"csv", "xlsx"}:
        _normalize_spreadsheet_sections(blocks, normalized_format, normalized_filename, sections)
    elif normalized_format == "pdf":
        _normalize_pdf_sections(blocks, normalized_format, normalized_filename, sections)
    else:
        _normalize_generic_sections(blocks, normalized_format, normalized_filename, sections)

    document_hash = _short_hash(
        "\n".join(
            [
                normalized_format,
                normalized_filename,
                parser_version,
                normalize_text_for_compare(content or ""),
            ]
        ),
        length=16,
    )
    return NormalizedDocument(
        document_id=f"{normalized_format}:{document_hash}",
        filename=normalized_filename,
        format=normalized_format,
        parser_version=parser_version,
        blocks=tuple(blocks),
    )


def compare_normalized_documents(doc_a: NormalizedDocument, doc_b: NormalizedDocument) -> ComparisonResult:
    if not isinstance(doc_a, NormalizedDocument) or not isinstance(doc_b, NormalizedDocument):
        raise ValueError("compare_normalized_documents expects NormalizedDocument inputs")

    blocks_a = tuple(doc_a.blocks)
    blocks_b = tuple(doc_b.blocks)
    unmatched_a = set(range(len(blocks_a)))
    unmatched_b = set(range(len(blocks_b)))
    matched_pairs: list[tuple[int, int, str]] = []

    _match_by_exact_hash(blocks_a, blocks_b, unmatched_a, unmatched_b, matched_pairs)
    _match_by_source_key(blocks_a, blocks_b, unmatched_a, unmatched_b, matched_pairs)
    _match_by_type_order(blocks_a, blocks_b, unmatched_a, unmatched_b, matched_pairs)

    unchanged_count = 0
    changed: list[ComparisonChange] = []
    for index_a, index_b, reason in sorted(matched_pairs, key=lambda pair: (pair[0], pair[1], pair[2])):
        block_a = blocks_a[index_a]
        block_b = blocks_b[index_b]
        if block_a.hash == block_b.hash:
            unchanged_count += 1
            continue
        changed.append(_make_changed_change(doc_a, doc_b, block_a, block_b, reason))

    removed = tuple(
        _make_removed_change(doc_a, doc_b, blocks_a[index])
        for index in sorted(unmatched_a, key=lambda item: _block_sort_key(blocks_a[item]))
    )
    added = tuple(
        _make_added_change(doc_a, doc_b, blocks_b[index])
        for index in sorted(unmatched_b, key=lambda item: _block_sort_key(blocks_b[item]))
    )
    changed_tuple = tuple(changed)
    summary = {
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed_tuple),
        "unchanged_count": unchanged_count,
        "total_a_blocks": len(blocks_a),
        "total_b_blocks": len(blocks_b),
    }
    return ComparisonResult(
        document_a_id=doc_a.document_id,
        document_b_id=doc_b.document_id,
        added=added,
        removed=removed,
        changed=changed_tuple,
        unchanged_count=unchanged_count,
        summary=summary,
    )


def _normalize_filename(filename: str) -> str:
    normalized = Path((filename or "document").strip() or "document").name
    return normalized or "document"


def _normalize_file_format(file_format: str, filename: str) -> str:
    normalized = (file_format or "").strip().lower().lstrip(".")
    if not normalized:
        normalized = Path(filename).suffix.lower().lstrip(".")
    return normalized or "unknown"


def _split_labeled_sections(content: str) -> list[_Section]:
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections: list[_Section] = []
    current_label = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        if current_label or any(line.strip() for line in current_lines):
            sections.append(_Section(label=current_label, text="\n".join(current_lines).strip()))
        current_lines = []

    for line in lines:
        label = _canonical_section_label(line.strip())
        if label:
            flush()
            current_label = label
            continue
        current_lines.append(line)

    flush()
    return sections


def _canonical_section_label(line: str) -> str:
    if not line:
        return ""
    if line in DOCX_SECTION_LABELS:
        return line
    if line.startswith("CSV:"):
        return line
    if line.startswith("Sheet:"):
        return line
    if line.startswith("Sheet metadata:"):
        return line
    if PDF_OCR_PAGE_RE.match(line):
        return line
    return ""


def _normalize_docx_sections(
    blocks: list[NormalizedBlock],
    file_format: str,
    filename: str,
    sections: list[_Section],
) -> None:
    for section in sections:
        section_name = DOCX_SECTION_LABELS.get(section.label, "body" if not section.label else section.label.casefold())
        if section_name == "body":
            _add_text_blocks(
                blocks,
                file_format,
                filename,
                section.text,
                section="body",
                raw_label=section.label,
                table_block_type="table_row",
            )
        else:
            _add_metadata_blocks(
                blocks,
                file_format,
                filename,
                section.text or section.label,
                section=section_name,
                raw_label=section.label,
            )


def _normalize_spreadsheet_sections(
    blocks: list[NormalizedBlock],
    file_format: str,
    filename: str,
    sections: list[_Section],
) -> None:
    for section in sections:
        label = section.label
        if label.startswith("CSV:"):
            _add_table_lines(
                blocks,
                file_format,
                filename,
                section.text,
                block_type="table_row",
                section="csv",
                raw_label=label,
            )
            continue

        if label.startswith("Sheet metadata:"):
            sheet_name = label.split(":", 1)[1].strip()
            _add_metadata_blocks(
                blocks,
                file_format,
                filename,
                section.text,
                section="sheet_metadata",
                sheet=sheet_name,
                raw_label=label,
            )
            continue

        if label.startswith("Sheet:"):
            sheet_name = label.split(":", 1)[1].strip()
            _add_sheet_lines(blocks, file_format, filename, section.text, sheet=sheet_name, raw_label=label)
            continue

        if file_format == "csv":
            _add_table_lines(
                blocks,
                file_format,
                filename,
                section.text,
                block_type="table_row",
                section="csv",
                raw_label=label,
            )
        else:
            _add_sheet_lines(blocks, file_format, filename, section.text, sheet="", raw_label=label)


def _normalize_pdf_sections(
    blocks: list[NormalizedBlock],
    file_format: str,
    filename: str,
    sections: list[_Section],
) -> None:
    for section in sections:
        page_match = PDF_OCR_PAGE_RE.match(section.label)
        if page_match:
            _add_block(
                blocks,
                file_format,
                "ocr_page",
                section.text,
                BlockSource(
                    filename=filename,
                    section="ocr_page",
                    page=int(page_match.group(1)),
                    raw_label=section.label,
                ),
            )
        else:
            _add_text_blocks(
                blocks,
                file_format,
                filename,
                section.text,
                section="text",
                raw_label=section.label,
                table_block_type="table_row",
            )


def _normalize_generic_sections(
    blocks: list[NormalizedBlock],
    file_format: str,
    filename: str,
    sections: list[_Section],
) -> None:
    for section in sections:
        _add_text_blocks(
            blocks,
            file_format,
            filename,
            section.text,
            section="text",
            raw_label=section.label,
            table_block_type="table_row",
        )


def _add_text_blocks(
    blocks: list[NormalizedBlock],
    file_format: str,
    filename: str,
    text: str,
    *,
    section: str,
    raw_label: str,
    table_block_type: str,
) -> None:
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        paragraph_text = "\n".join(paragraph_lines).strip()
        if paragraph_text:
            _add_block(
                blocks,
                file_format,
                "paragraph",
                paragraph_text,
                BlockSource(filename=filename, section=section, raw_label=raw_label),
            )
        paragraph_lines = []

    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            continue

        if _line_is_table_row(stripped):
            flush_paragraph()
            _add_table_row_block(
                blocks,
                file_format,
                filename,
                stripped,
                block_type=table_block_type,
                section=section,
                raw_label=raw_label,
            )
            continue

        if _line_is_metadata(stripped):
            flush_paragraph()
            _add_block(
                blocks,
                file_format,
                "metadata",
                stripped,
                BlockSource(filename=filename, section=section, raw_label=raw_label),
            )
            continue

        paragraph_lines.append(stripped)

    flush_paragraph()


def _add_sheet_lines(
    blocks: list[NormalizedBlock],
    file_format: str,
    filename: str,
    text: str,
    *,
    sheet: str,
    raw_label: str,
) -> None:
    row_index = 0
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        paragraph_text = "\n".join(paragraph_lines).strip()
        if paragraph_text:
            _add_block(
                blocks,
                file_format,
                "paragraph",
                paragraph_text,
                BlockSource(filename=filename, section="sheet", sheet=sheet, raw_label=raw_label),
            )
        paragraph_lines = []

    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            continue
        if _line_is_metadata(stripped):
            flush_paragraph()
            _add_block(
                blocks,
                file_format,
                "metadata",
                stripped,
                BlockSource(filename=filename, section="sheet_metadata", sheet=sheet, raw_label=raw_label),
            )
            continue
        if _line_is_table_row(stripped):
            flush_paragraph()
            row_index += 1
            _add_table_row_block(
                blocks,
                file_format,
                filename,
                stripped,
                block_type="sheet_row",
                section="sheet",
                sheet=sheet,
                row_index=row_index,
                raw_label=raw_label,
            )
            continue
        paragraph_lines.append(stripped)

    flush_paragraph()


def _add_table_lines(
    blocks: list[NormalizedBlock],
    file_format: str,
    filename: str,
    text: str,
    *,
    block_type: str,
    section: str,
    raw_label: str,
) -> None:
    row_index = 0
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _line_is_metadata(stripped):
            _add_block(
                blocks,
                file_format,
                "metadata",
                stripped,
                BlockSource(filename=filename, section=section, raw_label=raw_label),
            )
            continue
        row_index += 1
        _add_table_row_block(
            blocks,
            file_format,
            filename,
            stripped,
            block_type=block_type if _line_is_table_row(stripped) else "paragraph",
            section=section,
            row_index=row_index,
            raw_label=raw_label,
        )


def _add_metadata_blocks(
    blocks: list[NormalizedBlock],
    file_format: str,
    filename: str,
    text: str,
    *,
    section: str,
    raw_label: str,
    sheet: str = "",
) -> None:
    paragraphs = [chunk.strip() for chunk in re.split(r"\n\s*\n+", text or "") if chunk.strip()]
    for paragraph in paragraphs:
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        if not lines:
            continue
        if len(lines) == 1:
            _add_block(
                blocks,
                file_format,
                "metadata",
                lines[0],
                BlockSource(filename=filename, section=section, sheet=sheet, raw_label=raw_label),
            )
            continue
        for line in lines:
            _add_block(
                blocks,
                file_format,
                "metadata",
                line,
                BlockSource(filename=filename, section=section, sheet=sheet, raw_label=raw_label),
            )


def _add_table_row_block(
    blocks: list[NormalizedBlock],
    file_format: str,
    filename: str,
    text: str,
    *,
    block_type: str,
    section: str,
    raw_label: str,
    sheet: str = "",
    row_index: int | None = None,
) -> None:
    cells = tuple(cell.strip() for cell in text.split("|"))
    _add_block(
        blocks,
        file_format,
        block_type,
        text,
        BlockSource(
            filename=filename,
            section=section,
            sheet=sheet,
            row_index=row_index,
            raw_label=raw_label,
        ),
        cells=cells,
    )


def _add_block(
    blocks: list[NormalizedBlock],
    file_format: str,
    block_type: str,
    text: str,
    source: BlockSource,
    *,
    cells: tuple[str, ...] = (),
) -> None:
    clean_text = _bound_block_text(text)
    normalized_text = normalize_text_for_compare(clean_text)
    if not normalized_text:
        return

    digest = _hash_text(normalized_text)
    order_index = len(blocks)
    block_id = f"{file_format}:{order_index}:{digest[:12]}"
    blocks.append(
        NormalizedBlock(
            block_id=block_id,
            type=block_type,
            order_index=order_index,
            text=clean_text,
            normalized_text=normalized_text,
            hash=digest,
            source=source,
            cells=tuple(cell for cell in cells if cell),
        )
    )


def _bound_block_text(text: str) -> str:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) <= MAX_NORMALIZED_BLOCK_TEXT_CHARS:
        return normalized
    return normalized[:MAX_NORMALIZED_BLOCK_TEXT_CHARS].rstrip()


def _line_is_table_row(line: str) -> bool:
    if "|" not in line:
        return False
    cells = [cell.strip() for cell in line.split("|")]
    return sum(1 for cell in cells if cell) >= 2


def _line_is_metadata(line: str) -> bool:
    return line.startswith(METADATA_PREFIXES)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _short_hash(text: str, *, length: int) -> str:
    return _hash_text(text)[:length]


def _match_by_exact_hash(
    blocks_a: tuple[NormalizedBlock, ...],
    blocks_b: tuple[NormalizedBlock, ...],
    unmatched_a: set[int],
    unmatched_b: set[int],
    matched_pairs: list[tuple[int, int, str]],
) -> None:
    candidates_by_key = _build_unmatched_index(blocks_b, unmatched_b, _exact_match_key)
    for index_a in sorted(list(unmatched_a), key=lambda item: _block_sort_key(blocks_a[item])):
        candidate = _take_candidate(candidates_by_key.get(_exact_match_key(blocks_a[index_a]), []), unmatched_b)
        if candidate is None:
            continue
        unmatched_a.remove(index_a)
        unmatched_b.remove(candidate)
        matched_pairs.append((index_a, candidate, "exact_hash"))


def _match_by_source_key(
    blocks_a: tuple[NormalizedBlock, ...],
    blocks_b: tuple[NormalizedBlock, ...],
    unmatched_a: set[int],
    unmatched_b: set[int],
    matched_pairs: list[tuple[int, int, str]],
) -> None:
    candidates_by_key = _build_unmatched_index(blocks_b, unmatched_b, _source_match_key)
    for index_a in sorted(list(unmatched_a), key=lambda item: _block_sort_key(blocks_a[item])):
        key = _source_match_key(blocks_a[index_a])
        if key is None:
            continue
        candidate = _take_candidate(candidates_by_key.get(key, []), unmatched_b)
        if candidate is None:
            continue
        unmatched_a.remove(index_a)
        unmatched_b.remove(candidate)
        matched_pairs.append((index_a, candidate, "source_key"))


def _match_by_type_order(
    blocks_a: tuple[NormalizedBlock, ...],
    blocks_b: tuple[NormalizedBlock, ...],
    unmatched_a: set[int],
    unmatched_b: set[int],
    matched_pairs: list[tuple[int, int, str]],
) -> None:
    candidates_by_key = _build_unmatched_index(blocks_b, unmatched_b, lambda block: block.type)
    for index_a in sorted(list(unmatched_a), key=lambda item: _block_sort_key(blocks_a[item])):
        candidate = _take_candidate(candidates_by_key.get(blocks_a[index_a].type, []), unmatched_b)
        if candidate is None:
            continue
        unmatched_a.remove(index_a)
        unmatched_b.remove(candidate)
        matched_pairs.append((index_a, candidate, "type_order"))


def _build_unmatched_index(
    blocks: tuple[NormalizedBlock, ...],
    unmatched: set[int],
    key_fn: Any,
) -> dict[Any, list[int]]:
    indexed: dict[Any, list[int]] = {}
    for index in sorted(unmatched, key=lambda item: _block_sort_key(blocks[item])):
        key = key_fn(blocks[index])
        if key is None:
            continue
        indexed.setdefault(key, []).append(index)
    return indexed


def _take_candidate(candidates: list[int], unmatched: set[int]) -> int | None:
    while candidates:
        candidate = candidates.pop(0)
        if candidate in unmatched:
            return candidate
    return None


def _exact_match_key(block: NormalizedBlock) -> tuple[str, str]:
    return (block.type, block.hash)


def _source_match_key(block: NormalizedBlock) -> tuple[Any, ...] | None:
    source = block.source
    if block.type == "ocr_page" and source.page is not None:
        return (block.type, source.page)
    if block.type == "sheet_row" and (source.sheet or source.row_index is not None):
        return (block.type, source.sheet, source.row_index)
    if block.type == "table_row" and source.row_index is not None:
        return (block.type, source.section, source.row_index)
    if block.type == "metadata" and (source.section or source.sheet or source.raw_label):
        return (block.type, source.section, source.sheet, source.page, source.row_index, source.raw_label)
    if block.type == "paragraph" and source.page is not None:
        return (block.type, source.page, source.section)
    return None


def _block_sort_key(block: NormalizedBlock) -> tuple[int, str, str, str]:
    return (block.order_index, block.type, _source_identity(block.source), block.hash)


def _source_identity(source: BlockSource | None) -> str:
    if source is None:
        return ""
    return "|".join(
        [
            source.section,
            str(source.page) if source.page is not None else "",
            source.sheet,
            str(source.row_index) if source.row_index is not None else "",
            source.column,
            source.raw_label,
        ]
    )


def _make_changed_change(
    doc_a: NormalizedDocument,
    doc_b: NormalizedDocument,
    block_a: NormalizedBlock,
    block_b: NormalizedBlock,
    reason: str,
) -> ComparisonChange:
    return ComparisonChange(
        change_id=_make_change_id("changed", block_a.type, block_a=block_a, block_b=block_b),
        change_type="changed",
        block_type=block_a.type,
        source_a=block_a.source,
        source_b=block_b.source,
        text_a=block_a.text,
        text_b=block_b.text,
        hash_a=block_a.hash,
        hash_b=block_b.hash,
        reason=f"matched_by_{reason}",
    )


def _make_removed_change(doc_a: NormalizedDocument, doc_b: NormalizedDocument, block: NormalizedBlock) -> ComparisonChange:
    return ComparisonChange(
        change_id=_make_change_id("removed", block.type, block_a=block, block_b=None),
        change_type="removed",
        block_type=block.type,
        source_a=block.source,
        source_b=None,
        text_a=block.text,
        text_b="",
        hash_a=block.hash,
        hash_b="",
        reason="unmatched_in_revised",
    )


def _make_added_change(doc_a: NormalizedDocument, doc_b: NormalizedDocument, block: NormalizedBlock) -> ComparisonChange:
    return ComparisonChange(
        change_id=_make_change_id("added", block.type, block_a=None, block_b=block),
        change_type="added",
        block_type=block.type,
        source_a=None,
        source_b=block.source,
        text_a="",
        text_b=block.text,
        hash_a="",
        hash_b=block.hash,
        reason="unmatched_in_baseline",
    )


def _make_change_id(
    change_type: str,
    block_type: str,
    *,
    block_a: NormalizedBlock | None,
    block_b: NormalizedBlock | None,
) -> str:
    seed = "\n".join(
        [
            change_type,
            block_type,
            block_a.hash if block_a else "",
            block_b.hash if block_b else "",
            _source_identity(block_a.source if block_a else None),
            _source_identity(block_b.source if block_b else None),
        ]
    )
    return f"{change_type}:{_short_hash(seed, length=16)}"
