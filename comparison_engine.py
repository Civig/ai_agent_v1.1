"""Internal helpers for future document comparison normalization.

This module intentionally does not run comparison, call an LLM, expose API
surface, or affect the existing file-chat runtime path.
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
