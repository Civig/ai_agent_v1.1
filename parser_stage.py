import csv
import json
import logging
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree

from fastapi import HTTPException, UploadFile

from config import settings

logger = logging.getLogger("app")

MAX_UPLOAD_FILE_SIZE_BYTES = settings.FILE_PROCESSING_MAX_FILE_SIZE_BYTES
MAX_UPLOAD_TOTAL_SIZE_BYTES = settings.FILE_PROCESSING_MAX_TOTAL_SIZE_BYTES
MAX_UPLOAD_FILES = settings.FILE_PROCESSING_MAX_FILES
GENERIC_UPLOAD_CONTENT_TYPES = {"", "application/octet-stream"}
ALLOWED_UPLOAD_MIME_TYPES: dict[str, set[str]] = {
    ".txt": {"text/plain"},
    ".csv": {"text/csv", "application/csv", "text/plain"},
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
}
MAX_DOCUMENT_CHARS = settings.FILE_PROCESSING_MAX_DOCUMENT_CHARS
MAX_PARSED_DOCUMENT_CHARS = MAX_DOCUMENT_CHARS
MAX_PDF_PAGES = settings.FILE_PROCESSING_MAX_PDF_PAGES
IMAGE_OCR_MAX_DIMENSION = settings.FILE_PROCESSING_IMAGE_MAX_DIMENSION
IMAGE_OCR_TIMEOUT_SECONDS = settings.FILE_PROCESSING_OCR_TIMEOUT_SECONDS
IMAGE_OCR_UPSCALE_TARGET_DIMENSION = min(1000, IMAGE_OCR_MAX_DIMENSION)
MAX_SPREADSHEET_ROWS = 200
MAX_SPREADSHEET_COLUMNS = 30
MAX_SPREADSHEET_SHEETS = 3
MAX_SPREADSHEET_CELL_CHARS = 500
DOCUMENT_TRUNCATION_MARKER = "[DOCUMENT_TRUNCATED]"
UPLOAD_UNSUPPORTED_TYPE_ERROR = "Поддерживаются только TXT, CSV, PDF, DOCX, XLSX, PNG, JPG и JPEG."
DOCUMENT_NO_INFORMATION_RESPONSE = "В предоставленных документах нет информации для ответа на этот вопрос."


def sanitize_upload_filename(filename: str) -> str:
    candidate = Path(filename or "upload.bin").name
    extension = Path(candidate).suffix.lower()
    stem = Path(candidate).stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "upload"
    safe_extension = re.sub(r"[^a-z0-9.]+", "", extension) or ".bin"
    safe_stem = safe_stem[:80]
    return f"{uuid.uuid4().hex[:12]}-{safe_stem}{safe_extension}"


def detect_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def normalize_upload_content_type(content_type: Optional[str]) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def upload_content_type_is_allowed(extension: str, content_type: Optional[str]) -> bool:
    allowed_content_types = ALLOWED_UPLOAD_MIME_TYPES.get(extension)
    if not allowed_content_types:
        return False

    normalized_content_type = normalize_upload_content_type(content_type)
    if normalized_content_type in GENERIC_UPLOAD_CONTENT_TYPES:
        return True

    return normalized_content_type in allowed_content_types


def log_upload_rejection(
    *,
    reason: str,
    safe_name: str,
    extension: str,
    content_type: Optional[str],
    username: Optional[str],
) -> None:
    logger.warning(
        "upload_rejected reason=%s filename=%s extension=%s content_type=%s username=%s",
        reason,
        safe_name,
        extension,
        normalize_upload_content_type(content_type) or "application/octet-stream",
        (username or "").strip() or "unknown",
    )


def log_file_pipeline_observability(
    *,
    username: str,
    job_kind: str,
    file_count: int,
    receive_ms: int,
    parse_ms: int,
    doc_chars: int,
    original_doc_chars: int,
    trimmed_doc_chars: int,
    terminal_status: str,
    error_type: str,
    target_logger: Optional[logging.Logger] = None,
) -> None:
    active_logger = target_logger or logger
    log_method = active_logger.warning if terminal_status == "failed" else active_logger.info
    log_method(
        "file_parse_observability username=%s job_kind=%s file_count=%s receive_ms=%s parse_ms=%s "
        "doc_chars=%s original_doc_chars=%s trimmed_doc_chars=%s terminal_status=%s error_type=%s",
        username,
        job_kind,
        file_count,
        receive_ms,
        parse_ms,
        doc_chars,
        original_doc_chars,
        trimmed_doc_chars,
        terminal_status,
        error_type,
    )


def _max_size_megabytes(size_bytes: int) -> int:
    return max(1, size_bytes // (1024 * 1024))


def upload_file_too_large_detail(filename: str) -> str:
    return f"Файл {filename} превышает лимит {_max_size_megabytes(MAX_UPLOAD_FILE_SIZE_BYTES)} MB"


def upload_total_size_exceeded_detail() -> str:
    return (
        "Суммарный размер файлов превышает лимит "
        f"{_max_size_megabytes(MAX_UPLOAD_TOTAL_SIZE_BYTES)} MB"
    )


def pdf_page_limit_exceeded_detail(page_count: int) -> str:
    return f"PDF-документ превышает лимит страниц: {page_count}. Максимум: {MAX_PDF_PAGES}"


def pdf_parse_failed_detail() -> str:
    return "Не удалось извлечь текст из PDF"


def docx_parse_failed_detail() -> str:
    return "Не удалось извлечь текст из DOCX"


def csv_parse_failed_detail() -> str:
    return "Не удалось извлечь текст из CSV"


def xlsx_parse_failed_detail() -> str:
    return "Не удалось извлечь текст из XLSX"


def spreadsheet_empty_detail() -> str:
    return "Таблица не содержит извлекаемых данных"


def pdf_no_text_layer_detail() -> str:
    return "PDF не содержит извлекаемого текстового слоя; OCR для PDF пока не поддержан"


def image_dimension_limit_exceeded_detail(width: int, height: int) -> str:
    return (
        f"Изображение превышает лимит размера: {width}x{height}. "
        f"Максимум: {IMAGE_OCR_MAX_DIMENSION}px"
    )


def image_parse_failed_detail() -> str:
    return "Не удалось извлечь текст из изображения"


def ocr_timeout_exceeded_detail() -> str:
    return f"OCR превысил лимит времени {IMAGE_OCR_TIMEOUT_SECONDS:g} сек"


def prepare_image_for_ocr(image: Any) -> Any:
    from PIL import Image, ImageOps  # type: ignore

    prepared = ImageOps.autocontrast(image.convert("L"))
    width, height = prepared.size
    max_dimension = max(width, height)
    if max_dimension <= 0 or max_dimension >= IMAGE_OCR_UPSCALE_TARGET_DIMENSION:
        return prepared

    scale = min(
        2.0,
        IMAGE_OCR_UPSCALE_TARGET_DIMENSION / max_dimension,
        IMAGE_OCR_MAX_DIMENSION / max_dimension,
    )
    if scale <= 1.0:
        return prepared

    resized = (
        max(1, min(IMAGE_OCR_MAX_DIMENSION, int(round(width * scale)))),
        max(1, min(IMAGE_OCR_MAX_DIMENSION, int(round(height * scale)))),
    )
    if resized == prepared.size:
        return prepared

    resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.BICUBIC)
    return prepared.resize(resized, resampling)


def trim_document_content(content: str) -> str:
    normalized = (content or "").strip()
    if len(normalized) <= MAX_PARSED_DOCUMENT_CHARS:
        return normalized

    marker = f"\n{DOCUMENT_TRUNCATION_MARKER}"
    snippet_limit = max(0, MAX_PARSED_DOCUMENT_CHARS - len(marker))
    snippet = normalized[:snippet_limit].rstrip()
    return f"{snippet}{marker}" if snippet else DOCUMENT_TRUNCATION_MARKER


def extract_text_from_txt(path: Path) -> str:
    chunks = []
    consumed = 0
    hard_limit = MAX_PARSED_DOCUMENT_CHARS + 1
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        while consumed < hard_limit:
            chunk = handle.read(min(4096, hard_limit - consumed))
            if not chunk:
                break
            chunks.append(chunk)
            consumed += len(chunk)
    return trim_document_content("".join(chunks))


def _trim_spreadsheet_cell(value: Any) -> str:
    normalized = str(value if value is not None else "").replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized = re.sub(r"[ \t\f\v]+", " ", normalized)
    normalized = re.sub(r"\n+", " ", normalized)
    if len(normalized) <= MAX_SPREADSHEET_CELL_CHARS:
        return normalized
    return normalized[:MAX_SPREADSHEET_CELL_CHARS].rstrip()


def _format_table_rows(rows: list[list[str]]) -> str:
    formatted_rows: list[str] = []
    for row in rows[:MAX_SPREADSHEET_ROWS]:
        bounded_row = [_trim_spreadsheet_cell(cell) for cell in row[:MAX_SPREADSHEET_COLUMNS]]
        while bounded_row and not bounded_row[-1]:
            bounded_row.pop()
        if any(bounded_row):
            formatted_rows.append(" | ".join(bounded_row))
    return "\n".join(formatted_rows).strip()


def extract_text_from_csv(path: Path) -> str:
    try:
        raw_bytes = path.read_bytes()
        try:
            text = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw_bytes.decode("utf-8", errors="replace")

        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|") if sample.strip() else csv.excel
        except csv.Error:
            dialect = csv.excel

        reader = csv.reader(text.splitlines(), dialect)
        rows: list[list[str]] = []
        for index, row in enumerate(reader):
            if index >= MAX_SPREADSHEET_ROWS:
                break
            rows.append(row[:MAX_SPREADSHEET_COLUMNS])

        table_text = _format_table_rows(rows)
        if not table_text:
            raise RuntimeError(spreadsheet_empty_detail())
        return trim_document_content(f"CSV: {path.name}\n\n{table_text}")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(csv_parse_failed_detail()) from exc


def _xml_local_name(tag: Any) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _xml_attr_local(element: ElementTree.Element, name: str) -> str:
    for key, value in element.attrib.items():
        if _xml_local_name(key) == name:
            return value
    return ""


def _docx_node_text(node: ElementTree.Element) -> str:
    chunks: list[str] = []
    for child in node.iter():
        child_name = _xml_local_name(child.tag)
        if child_name == "t" and child.text:
            chunks.append(child.text)
        elif child_name in {"br", "cr"}:
            chunks.append("\n")
        elif child_name == "tab":
            chunks.append("\t")
    return "".join(chunks).strip()


def _docx_table_text(table: ElementTree.Element) -> str:
    rows: list[str] = []
    for row in table:
        if _xml_local_name(row.tag) != "tr":
            continue

        cells: list[str] = []
        for cell in row:
            if _xml_local_name(cell.tag) != "tc":
                continue
            paragraph_texts = [
                _docx_node_text(paragraph)
                for paragraph in cell
                if _xml_local_name(paragraph.tag) == "p"
            ]
            paragraph_texts = [text for text in paragraph_texts if text]
            cells.append(" ".join(paragraph_texts).strip())

        if any(cell for cell in cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows).strip()


def _docx_flat_text(root: ElementTree.Element) -> str:
    chunks: list[str] = []
    for node in root.iter():
        node_name = _xml_local_name(node.tag)
        if node_name == "t" and node.text:
            chunks.append(node.text)
        elif node_name == "p":
            chunks.append("\n")
    return trim_document_content("".join(chunks))


def _docx_change_text(node: ElementTree.Element) -> str:
    chunks: list[str] = []
    for child in node.iter():
        child_name = _xml_local_name(child.tag)
        if child_name in {"t", "delText"} and child.text:
            chunks.append(child.text)
        elif child_name in {"br", "cr"}:
            chunks.append("\n")
        elif child_name == "tab":
            chunks.append("\t")
    return trim_document_content("".join(chunks))


def _docx_tracked_changes_text(xml_bytes: bytes) -> str:
    root = ElementTree.fromstring(xml_bytes)
    lines: list[str] = []
    for node in root.iter():
        node_name = _xml_local_name(node.tag)
        if node_name not in {"ins", "del"}:
            continue
        text = _docx_change_text(node)
        if not text:
            continue
        label = "Inserted" if node_name == "ins" else "Deleted"
        lines.append(f"{label}: {text}")
    return "\n".join(lines)


def extract_docx_document_xml_text(xml_bytes: bytes) -> str:
    root = ElementTree.fromstring(xml_bytes)
    body = next((child for child in root if _xml_local_name(child.tag) == "body"), None)
    if body is None:
        return _docx_flat_text(root)

    blocks: list[str] = []
    for child in body:
        child_name = _xml_local_name(child.tag)
        if child_name == "p":
            text = _docx_node_text(child)
            if text:
                blocks.append(text)
        elif child_name == "tbl":
            text = _docx_table_text(child)
            if text:
                blocks.append(text)

    if not blocks:
        return _docx_flat_text(root)
    return trim_document_content("\n\n".join(blocks))


def _docx_part_texts(archive: zipfile.ZipFile, prefix: str) -> list[str]:
    texts: list[str] = []
    for name in sorted(archive.namelist()):
        if not name.startswith(prefix) or not name.endswith(".xml"):
            continue
        text = extract_docx_document_xml_text(archive.read(name))
        if text:
            texts.append(text)
    return texts


def _docx_optional_part_text(archive: zipfile.ZipFile, name: str) -> str:
    try:
        return extract_docx_document_xml_text(archive.read(name))
    except KeyError:
        return ""


def _docx_tracked_changes_blocks(archive: zipfile.ZipFile) -> list[str]:
    blocks: list[str] = []
    for name in sorted(archive.namelist()):
        if not name.startswith("word/") or not name.endswith(".xml"):
            continue
        text = _docx_tracked_changes_text(archive.read(name))
        if text:
            blocks.append(text)
    return blocks


def _docx_contains_embedded_images(archive: zipfile.ZipFile) -> bool:
    if any(name.startswith("word/media/") and not name.endswith("/") for name in archive.namelist()):
        return True

    for name in sorted(archive.namelist()):
        if not name.startswith("word/") or not name.endswith(".xml"):
            continue
        root = ElementTree.fromstring(archive.read(name))
        if any(_xml_local_name(node.tag) in {"drawing", "pict", "blip"} for node in root.iter()):
            return True
    return False


def extract_text_from_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            body_text = extract_docx_document_xml_text(archive.read("word/document.xml"))

            extra_blocks: list[str] = []
            header_text = "\n\n".join(_docx_part_texts(archive, "word/header"))
            if header_text:
                extra_blocks.append(f"DOCX Header\n{header_text}")

            footer_text = "\n\n".join(_docx_part_texts(archive, "word/footer"))
            if footer_text:
                extra_blocks.append(f"DOCX Footer\n{footer_text}")

            comments_text = _docx_optional_part_text(archive, "word/comments.xml")
            if comments_text:
                extra_blocks.append(f"DOCX Comments\n{comments_text}")

            tracked_changes = "\n".join(_docx_tracked_changes_blocks(archive))
            if tracked_changes:
                extra_blocks.append(f"Tracked changes\n{tracked_changes}")

            if _docx_contains_embedded_images(archive):
                extra_blocks.append("Embedded images\nDOCX contains embedded images; OCR inside DOCX is not supported yet")

        if not extra_blocks:
            return body_text

        blocks = [f"DOCX Body\n{body_text}"] if body_text else []
        blocks.extend(extra_blocks)
        return trim_document_content("\n\n".join(blocks))
    except Exception as exc:
        raise RuntimeError(docx_parse_failed_detail()) from exc


def _xlsx_relationship_target(target: str) -> str:
    normalized = (target or "").strip().lstrip("/")
    if normalized.startswith("xl/"):
        return normalized
    return f"xl/{normalized}"


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        xml_bytes = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ElementTree.fromstring(xml_bytes)
    return [_docx_node_text(item) for item in root.iter() if _xml_local_name(item.tag) == "si"]


def _xlsx_cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    value_node = next((child for child in cell if _xml_local_name(child.tag) == "v"), None)

    if cell_type == "inlineStr":
        inline_node = next((child for child in cell if _xml_local_name(child.tag) == "is"), None)
        return _docx_node_text(inline_node) if inline_node is not None else ""

    raw_value = (value_node.text or "") if value_node is not None else ""
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)]
        except (IndexError, ValueError):
            return ""
    if cell_type == "b":
        return "TRUE" if raw_value == "1" else "FALSE" if raw_value == "0" else raw_value
    return raw_value


def _xlsx_column_name(column_index: int) -> str:
    name = ""
    column = column_index
    while column > 0:
        column, remainder = divmod(column - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name or str(column_index)


def _xlsx_hidden_column_label(column: ElementTree.Element) -> str:
    try:
        min_column = int(column.attrib.get("min", "0"))
        max_column = int(column.attrib.get("max", str(min_column)))
    except ValueError:
        return column.attrib.get("min", "unknown")

    start = _xlsx_column_name(min_column)
    end = _xlsx_column_name(max_column)
    return start if start == end else f"{start}:{end}"


def _xlsx_sheet_rows(root: ElementTree.Element, shared_strings: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in root.iter():
        if _xml_local_name(row.tag) != "row":
            continue
        cells: list[str] = []
        for cell in row:
            if _xml_local_name(cell.tag) != "c":
                continue
            cells.append(_xlsx_cell_value(cell, shared_strings))
            if len(cells) >= MAX_SPREADSHEET_COLUMNS:
                break
        rows.append(cells)
        if len(rows) >= MAX_SPREADSHEET_ROWS:
            break
    return rows


def _xlsx_formula_text(cell: ElementTree.Element) -> str:
    formula_node = next((child for child in cell if _xml_local_name(child.tag) == "f"), None)
    formula = (formula_node.text or "").strip() if formula_node is not None else ""
    if formula and not formula.startswith("="):
        formula = f"={formula}"
    return formula


def _xlsx_cell_map(root: ElementTree.Element, shared_strings: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    row_count = 0
    for row in root.iter():
        if _xml_local_name(row.tag) != "row":
            continue
        row_count += 1
        if row_count > MAX_SPREADSHEET_ROWS:
            break

        cell_count = 0
        for cell in row:
            if _xml_local_name(cell.tag) != "c":
                continue
            cell_count += 1
            if cell_count > MAX_SPREADSHEET_COLUMNS:
                break
            reference = cell.attrib.get("r", "")
            value = _xlsx_cell_value(cell, shared_strings)
            if reference and value:
                values[reference] = value
    return values


def _xlsx_sheet_metadata(
    *,
    sheet_name: str,
    sheet_state: str,
    root: ElementTree.Element,
    shared_strings: list[str],
) -> str:
    lines: list[str] = []

    def add_line(line: str) -> None:
        if len(lines) < MAX_SPREADSHEET_ROWS:
            lines.append(line)

    if sheet_state and sheet_state != "visible":
        add_line(f"Hidden sheet: {sheet_name} (state={sheet_state})")

    for column in root.iter():
        if _xml_local_name(column.tag) != "col":
            continue
        if column.attrib.get("hidden") in {"1", "true", "TRUE"}:
            add_line(f"Hidden columns: {_xlsx_hidden_column_label(column)}")
        if len(lines) >= MAX_SPREADSHEET_ROWS:
            break

    cell_values = _xlsx_cell_map(root, shared_strings)
    for merge_cell in root.iter():
        if _xml_local_name(merge_cell.tag) != "mergeCell":
            continue
        merge_ref = merge_cell.attrib.get("ref", "").strip()
        if not merge_ref:
            continue
        top_left = merge_ref.split(":", 1)[0]
        top_left_value = cell_values.get(top_left, "")
        suffix = f" = {top_left_value}" if top_left_value else ""
        add_line(f"Merged cells: {merge_ref}{suffix}")
        if len(lines) >= MAX_SPREADSHEET_ROWS:
            break

    row_count = 0
    for row in root.iter():
        if _xml_local_name(row.tag) != "row":
            continue
        row_count += 1
        if row_count > MAX_SPREADSHEET_ROWS:
            break

        row_ref = row.attrib.get("r", str(row_count))
        if row.attrib.get("hidden") in {"1", "true", "TRUE"}:
            add_line(f"Hidden row: {row_ref}")

        cell_count = 0
        for cell in row:
            if _xml_local_name(cell.tag) != "c":
                continue
            cell_count += 1
            if cell_count > MAX_SPREADSHEET_COLUMNS:
                break
            formula = _xlsx_formula_text(cell)
            if not formula:
                continue

            value_node = next((child for child in cell if _xml_local_name(child.tag) == "v"), None)
            cached = _xlsx_cell_value(cell, shared_strings) if value_node is not None else ""
            formula_text = _trim_spreadsheet_cell(formula)
            cached_text = _trim_spreadsheet_cell(cached) if cached else "unavailable"
            reference = cell.attrib.get("r", "unknown")
            add_line(f"Formula: {reference} formula: {formula_text} cached: {cached_text}")

    return "\n".join(lines)


def _xlsx_workbook_sheets(archive: zipfile.ZipFile) -> list[tuple[str, str, str]]:
    workbook_root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    rels_root = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))

    relationships: dict[str, str] = {}
    for relationship in rels_root:
        if _xml_local_name(relationship.tag) == "Relationship":
            rel_id = relationship.attrib.get("Id", "")
            target = relationship.attrib.get("Target", "")
            if rel_id and target:
                relationships[rel_id] = _xlsx_relationship_target(target)

    sheets: list[tuple[str, str, str]] = []
    for node in workbook_root.iter():
        if _xml_local_name(node.tag) != "sheet":
            continue
        sheet_name = node.attrib.get("name", "Sheet").strip() or "Sheet"
        sheet_state = node.attrib.get("state", "visible").strip() or "visible"
        rel_id = _xml_attr_local(node, "id")
        sheet_path = relationships.get(rel_id)
        if sheet_path:
            sheets.append((sheet_name, sheet_path, sheet_state))
        if len(sheets) >= MAX_SPREADSHEET_SHEETS:
            break
    return sheets


def extract_text_from_xlsx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            shared_strings = _xlsx_shared_strings(archive)
            blocks: list[str] = []
            for sheet_name, sheet_path, sheet_state in _xlsx_workbook_sheets(archive):
                sheet_root = ElementTree.fromstring(archive.read(sheet_path))
                table_text = _format_table_rows(_xlsx_sheet_rows(sheet_root, shared_strings))
                if table_text:
                    blocks.append(f"Sheet: {sheet_name}\n\n{table_text}")
                metadata_text = _xlsx_sheet_metadata(
                    sheet_name=sheet_name,
                    sheet_state=sheet_state,
                    root=sheet_root,
                    shared_strings=shared_strings,
                )
                if metadata_text:
                    blocks.append(f"Sheet metadata: {sheet_name}\n\n{metadata_text}")

        if not blocks:
            raise RuntimeError(spreadsheet_empty_detail())
        return trim_document_content("\n\n".join(blocks))
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(xlsx_parse_failed_detail()) from exc


def _trim_pdf_text_or_raise(text_fragments: list[str]) -> str:
    text = trim_document_content("\n".join(text_fragments))
    if not text.strip():
        raise RuntimeError(pdf_no_text_layer_detail())
    return text


def extract_text_from_pdf(path: Path) -> str:
    parse_errors: list[Exception] = []
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        parse_errors.append(exc)
    else:
        try:
            reader = PdfReader(str(path))
            page_count = len(reader.pages)
            if page_count > MAX_PDF_PAGES:
                raise RuntimeError(pdf_page_limit_exceeded_detail(page_count))
            return _trim_pdf_text_or_raise([(page.extract_text() or "") for page in reader.pages])
        except RuntimeError:
            raise
        except Exception as exc:
            parse_errors.append(exc)

    try:
        import fitz  # type: ignore
    except ImportError as exc:
        if any(not isinstance(error, ImportError) for error in parse_errors):
            raise RuntimeError(pdf_parse_failed_detail()) from parse_errors[-1]
        raise RuntimeError("PDF parser unavailable on server") from exc

    try:
        document = fitz.open(path)
        try:
            page_count = len(document)
            if page_count > MAX_PDF_PAGES:
                raise RuntimeError(pdf_page_limit_exceeded_detail(page_count))
            return _trim_pdf_text_or_raise([document[index].get_text() for index in range(page_count)])
        finally:
            document.close()
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(pdf_parse_failed_detail()) from exc


def extract_text_from_image(path: Path) -> str:
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError as exc:
        raise RuntimeError("OCR parser unavailable on server") from exc

    try:
        with Image.open(path) as image:
            width, height = image.size
            if max(width, height) > IMAGE_OCR_MAX_DIMENSION:
                raise RuntimeError(image_dimension_limit_exceeded_detail(width, height))
            try:
                prepared_image = prepare_image_for_ocr(image)
                return trim_document_content(pytesseract.image_to_string(prepared_image, timeout=IMAGE_OCR_TIMEOUT_SECONDS))
            except RuntimeError as exc:
                if "timeout" in str(exc).lower():
                    raise RuntimeError(ocr_timeout_exceeded_detail()) from exc
                raise RuntimeError(image_parse_failed_detail()) from exc
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(image_parse_failed_detail()) from exc


def parse_uploaded_file(path: Path) -> str:
    extension = detect_extension(path.name)
    if extension == ".txt":
        return extract_text_from_txt(path)
    if extension == ".csv":
        return extract_text_from_csv(path)
    if extension == ".docx":
        return extract_text_from_docx(path)
    if extension == ".xlsx":
        return extract_text_from_xlsx(path)
    if extension == ".pdf":
        return extract_text_from_pdf(path)
    if extension in {".png", ".jpg", ".jpeg"}:
        return extract_text_from_image(path)
    raise ValueError(UPLOAD_UNSUPPORTED_TYPE_ERROR)


def apply_document_budget(extracted_documents: list[dict[str, str]]) -> list[dict[str, str]]:
    budgeted_documents: list[dict[str, str]] = []
    consumed_chars = 0

    for document in extracted_documents:
        name = (document.get("name") or "").strip() or "document"
        content = (document.get("content") or "").strip()
        if not content:
            continue

        remaining = MAX_DOCUMENT_CHARS - consumed_chars
        if remaining <= 0:
            budgeted_documents.append({"name": name, "content": DOCUMENT_TRUNCATION_MARKER})
            continue

        if len(content) > remaining:
            marker = f"\n{DOCUMENT_TRUNCATION_MARKER}"
            snippet_limit = max(0, remaining - len(marker))
            snippet = content[:snippet_limit].rstrip()
            content = f"{snippet}{marker}" if snippet else DOCUMENT_TRUNCATION_MARKER

        consumed_chars += len(content)
        budgeted_documents.append({"name": name, "content": content})

    return budgeted_documents


def _build_document_prompt(
    message: str,
    extracted_documents: list[dict[str, str]],
    *,
    force_documents: bool,
) -> str:
    document_chunks = []
    budgeted_documents = apply_document_budget(extracted_documents)

    for index, document in enumerate(budgeted_documents, start=1):
        content = document["content"].strip()
        if not content:
            continue
        document_chunks.append(f"[Документ {index}: {document['name']}]\n{content}")

    if not document_chunks:
        raise ValueError("Не удалось извлечь текст из выбранных файлов")

    document_block = "\n\n".join(document_chunks)
    request_text = message.strip() or "Пользователь не уточнил задачу"
    extra_guard = ""
    if force_documents:
        extra_guard = (
            "\n# ДОПОЛНИТЕЛЬНОЕ ТРЕБОВАНИЕ\n"
            "Текст документов уже передан тебе ниже. "
            "Нельзя говорить, что у тебя нет доступа к файлам, документам или вложениям. "
            "Если фактов недостаточно, кратко укажи, каких сведений не хватает, без выдумок.\n"
        )

    return f"""
Ты — корпоративный AI-ассистент.

---

# КРИТИЧЕСКОЕ ПРАВИЛО

Ты НЕ имеешь права выдумывать информацию.

---

# РАБОТА С ДОКУМЕНТАМИ

- Документы уже загружены.
- Их текст приведён ниже.
- Блок ДОКУМЕНТЫ ниже — это уже извлечённое буквальное содержимое файлов.
- Это твой ЕДИНСТВЕННЫЙ источник данных.
- Отвечай как корпоративный аналитик: кратко, точно, по существу.

---

# ЗАПРЕЩЕНО

- говорить, что у тебя нет доступа к файлам
- игнорировать документы
- придумывать факты, цифры, даты, имена, выводы
- дополнять ответ предположениями
- использовать фразы вроде "скорее всего", если этого нет в тексте

---

# ЕСЛИ ДАННЫХ НЕДОСТАТОЧНО

- Если в документах есть частичный ответ, дай его и прямо назови недостающие сведения.
- Если конкретный факт отсутствует, скажи это предметно, например: "В документе не указана дата".
- Используй фразу "{DOCUMENT_NO_INFORMATION_RESPONSE}" только когда в документах нет никаких сведений, позволяющих ответить на вопрос.

---

# ПОВЕДЕНИЕ

- Если вопрос пользователя конкретный: ответь только по документам.
- Если пользователь спрашивает "что в файле", "что в документе" или просит показать содержимое, передай содержание прямо по тексту документа без выдумок.
- Если запрос пустой или неясный: предложи один из вариантов действий кратким списком.
- Если документы противоречат друг другу: прямо укажи на противоречие и не делай догадок.
{extra_guard}
---

# ДОКУМЕНТЫ

{document_block}

---

# ЗАПРОС ПОЛЬЗОВАТЕЛЯ

{request_text}
""".strip()


def build_document_prompt(message: str, extracted_documents: list[dict[str, str]]) -> str:
    return _build_document_prompt(message, extracted_documents, force_documents=False)


def build_retry_document_prompt(message: str, extracted_documents: list[dict[str, str]]) -> str:
    return _build_document_prompt(message, extracted_documents, force_documents=True)


def build_file_chat_job_metadata(
    *,
    retry_prompt: Optional[str],
    staged_files: list[dict[str, Any]],
    doc_chars: int = 0,
) -> dict[str, Any]:
    return {
        "retry_prompt": (retry_prompt or "").strip() or None,
        "suppress_token_stream": True,
        "doc_chars": max(0, int(doc_chars)),
        "files": [
            {
                "name": file_info["name"],
                "size": int(file_info["size"]),
            }
            for file_info in staged_files
        ],
    }


async def stage_uploads_to_directory(
    files: list[UploadFile],
    *,
    target_dir: Path,
    username: Optional[str] = None,
) -> list[dict[str, Any]]:
    if not files:
        raise HTTPException(status_code=400, detail="Не выбраны файлы")
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(status_code=400, detail=f"Максимум файлов за запрос: {MAX_UPLOAD_FILES}")

    staged_files: list[dict[str, Any]] = []
    total_size = 0
    try:
        for upload in files:
            safe_name = sanitize_upload_filename(upload.filename or "upload.bin")
            display_name = Path(upload.filename or safe_name).name or safe_name
            suffix = detect_extension(safe_name)
            normalized_content_type = normalize_upload_content_type(upload.content_type)
            if suffix not in ALLOWED_UPLOAD_MIME_TYPES:
                log_upload_rejection(
                    reason="unsupported_extension",
                    safe_name=safe_name,
                    extension=suffix or "<none>",
                    content_type=normalized_content_type,
                    username=username,
                )
                raise HTTPException(status_code=400, detail=UPLOAD_UNSUPPORTED_TYPE_ERROR)
            if not upload_content_type_is_allowed(suffix, normalized_content_type):
                log_upload_rejection(
                    reason="content_type_mismatch",
                    safe_name=safe_name,
                    extension=suffix,
                    content_type=normalized_content_type,
                    username=username,
                )
                raise HTTPException(status_code=400, detail=UPLOAD_UNSUPPORTED_TYPE_ERROR)

            target_path = target_dir / safe_name
            size = 0
            with target_path.open("wb") as target:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_UPLOAD_FILE_SIZE_BYTES:
                        log_upload_rejection(
                            reason="file_too_large",
                            safe_name=safe_name,
                            extension=suffix,
                            content_type=normalized_content_type,
                            username=username,
                        )
                        raise HTTPException(status_code=413, detail=upload_file_too_large_detail(safe_name))
                    total_size += len(chunk)
                    if total_size > MAX_UPLOAD_TOTAL_SIZE_BYTES:
                        log_upload_rejection(
                            reason="total_request_too_large",
                            safe_name=safe_name,
                            extension=suffix,
                            content_type=normalized_content_type,
                            username=username,
                        )
                        raise HTTPException(status_code=413, detail=upload_total_size_exceeded_detail())
                    target.write(chunk)

            staged_files.append(
                {
                    "name": display_name,
                    "safe_name": safe_name,
                    "path": target_path,
                    "size": size,
                    "content_type": normalized_content_type or "application/octet-stream",
                }
            )
    finally:
        for upload in files:
            await upload.close()

    return staged_files


def shared_staging_paths(staging_id: str, *, staging_root: str) -> dict[str, Path]:
    safe_staging_id = re.sub(r"[^a-zA-Z0-9_-]+", "", staging_id or "").strip() or "staging"
    root = Path(staging_root) / "staging" / safe_staging_id
    meta_dir = root / "meta"
    return {
        "root": root,
        "raw_dir": root / "raw",
        "meta_dir": meta_dir,
        "request_path": meta_dir / "request.json",
        "parser_path": meta_dir / "parser.json",
    }


async def stage_uploads_to_shared_root(
    files: list[UploadFile],
    *,
    staging_root: str,
    username: Optional[str] = None,
) -> dict[str, Any]:
    staging_id = uuid.uuid4().hex
    paths = shared_staging_paths(staging_id, staging_root=staging_root)
    try:
        paths["raw_dir"].mkdir(parents=True, exist_ok=False)
        paths["meta_dir"].mkdir(parents=True, exist_ok=True)
        staged_files_with_paths = await stage_uploads_to_directory(files, target_dir=paths["raw_dir"], username=username)
        staged_files = [
            {
                "name": file_info["name"],
                "safe_name": file_info["safe_name"],
                "size": file_info["size"],
                "content_type": file_info["content_type"],
            }
            for file_info in staged_files_with_paths
        ]

        request_payload = {
            "staging_id": staging_id,
            "username": (username or "").strip() or "unknown",
            "created_at": int(time.time()),
            "files": staged_files,
        }
        parser_payload = {
            "staging_id": staging_id,
            "status": "staged",
            "updated_at": int(time.time()),
            "files": staged_files,
            "raw_deleted": False,
        }
        paths["request_path"].write_text(json.dumps(request_payload, ensure_ascii=False), encoding="utf-8")
        paths["parser_path"].write_text(json.dumps(parser_payload, ensure_ascii=False), encoding="utf-8")
        return {
            "staging_id": staging_id,
            "files": staged_files,
        }
    except Exception:
        shutil.rmtree(paths["root"], ignore_errors=True)
        raise


def load_staged_request(staging_id: str, *, staging_root: str) -> dict[str, Any]:
    paths = shared_staging_paths(staging_id, staging_root=staging_root)
    if not paths["request_path"].exists():
        raise FileNotFoundError(f"Staging request metadata not found for {staging_id}")
    return json.loads(paths["request_path"].read_text(encoding="utf-8"))


def extract_documents_from_staging(staged_files: list[dict[str, Any]]) -> list[dict[str, str]]:
    extracted: list[dict[str, str]] = []
    for file_info in staged_files:
        text = parse_uploaded_file(file_info["path"])
        extracted.append({"name": file_info["name"], "content": text})
    return extracted


def extract_documents_from_shared_staging(staging_id: str, *, staging_root: str) -> list[dict[str, str]]:
    request_payload = load_staged_request(staging_id, staging_root=staging_root)
    paths = shared_staging_paths(staging_id, staging_root=staging_root)
    extracted: list[dict[str, str]] = []
    for file_info in request_payload.get("files", []):
        safe_name = file_info.get("safe_name")
        if not safe_name:
            continue
        text = parse_uploaded_file(paths["raw_dir"] / safe_name)
        extracted.append({"name": file_info.get("name") or safe_name, "content": text})
    return extracted


def prepare_parser_job_artifacts(
    *,
    staging_id: str,
    message: str,
    history: list[dict[str, Any]],
    model_key: str,
    model_name: str,
    staging_root: str,
) -> dict[str, Any]:
    request_payload = load_staged_request(staging_id, staging_root=staging_root)
    staged_files = request_payload.get("files", [])
    extracted_documents = extract_documents_from_shared_staging(staging_id, staging_root=staging_root)
    budgeted_documents = apply_document_budget(extracted_documents)
    final_prompt = build_document_prompt(message, extracted_documents)
    retry_prompt = build_retry_document_prompt(message, extracted_documents)
    return {
        "staging_id": staging_id,
        "files": staged_files,
        "original_doc_chars": sum(len((document.get("content") or "").strip()) for document in extracted_documents),
        "trimmed_doc_chars": sum(len((document.get("content") or "").strip()) for document in budgeted_documents),
        "prepared_llm_job": {
            "job_kind": "file_chat",
            "model_key": model_key,
            "model_name": model_name,
            "prompt": final_prompt,
            "history": history,
            "file_chat": build_file_chat_job_metadata(
                retry_prompt=retry_prompt,
                staged_files=staged_files,
                doc_chars=sum(len((document.get("content") or "").strip()) for document in budgeted_documents),
            ),
        },
    }


def write_parser_result_metadata(
    staging_id: str,
    *,
    staging_root: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    paths = shared_staging_paths(staging_id, staging_root=staging_root)
    existing: dict[str, Any] = {}
    if paths["parser_path"].exists():
        existing = json.loads(paths["parser_path"].read_text(encoding="utf-8"))
    merged = {
        **existing,
        **payload,
        "staging_id": staging_id,
        "updated_at": int(time.time()),
    }
    paths["meta_dir"].mkdir(parents=True, exist_ok=True)
    paths["parser_path"].write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    return merged


def delete_staged_raw_files(staging_id: str, *, staging_root: str) -> bool:
    paths = shared_staging_paths(staging_id, staging_root=staging_root)
    if not paths["raw_dir"].exists():
        return False
    shutil.rmtree(paths["raw_dir"], ignore_errors=True)
    return not paths["raw_dir"].exists()
