import asyncio
import builtins
import io
import os
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

os.environ.setdefault("SECRET_KEY", "test-secret-key-1234567890-test-abcdef")
os.environ.setdefault("COOKIE_SECURE", "false")

import parser_stage
from app import (
    DOCUMENT_NO_INFORMATION_RESPONSE,
    DOCUMENT_TRUNCATION_MARKER,
    IMAGE_OCR_MAX_DIMENSION,
    IMAGE_OCR_TIMEOUT_SECONDS,
    MAX_DOCUMENT_CHARS,
    MAX_PARSED_DOCUMENT_CHARS,
    MAX_PDF_PAGES,
    MAX_UPLOAD_FILES,
    MAX_UPLOAD_TOTAL_SIZE_BYTES,
    apply_document_budget,
    build_document_prompt,
    extract_text_from_image,
    extract_text_from_pdf,
    log_file_parse_observability,
    log_upload_rejection,
    normalize_document_response,
    normalize_upload_content_type,
    response_requires_document_retry,
    sanitize_upload_filename,
    stage_uploads,
    upload_content_type_is_allowed,
)


class UploadBackendTests(unittest.TestCase):
    def _write_docx_fixture(self, path: Path, body_xml: str, extra_parts: dict[str, str | bytes] | None = None) -> None:
        document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{body_xml}<w:sectPr /></w:body>
</w:document>
"""
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", document_xml)
            for name, content in (extra_parts or {}).items():
                archive.writestr(name, content)

    def _xlsx_cell_ref(self, column_index: int, row_index: int) -> str:
        name = ""
        column = column_index
        while column:
            column, remainder = divmod(column - 1, 26)
            name = chr(ord("A") + remainder) + name
        return f"{name}{row_index}"

    def _write_xlsx_fixture(
        self,
        path: Path,
        sheets: list[tuple[str, list[list[object]]]],
        sheet_options: dict[str, dict[str, object]] | None = None,
    ) -> None:
        shared_strings: list[str] = []
        shared_indexes: dict[str, int] = {}
        workbook_sheets: list[str] = []
        relationships: list[str] = []
        sheet_documents: list[tuple[str, str]] = []
        options_by_sheet = sheet_options or {}

        def shared_index(value: object) -> int:
            text = str(value)
            if text not in shared_indexes:
                shared_indexes[text] = len(shared_strings)
                shared_strings.append(text)
            return shared_indexes[text]

        for sheet_index, (sheet_name, rows) in enumerate(sheets, start=1):
            options = options_by_sheet.get(sheet_name, {})
            sheet_state = str(options.get("state", "") or "")
            state_attr = f' state="{sheet_state}"' if sheet_state else ""
            relationship_id = f"rId{sheet_index}"
            workbook_sheets.append(
                f'<sheet name="{sheet_name}" sheetId="{sheet_index}"{state_attr} r:id="{relationship_id}"/>'
            )
            relationships.append(
                f'<Relationship Id="{relationship_id}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{sheet_index}.xml"/>'
            )

            hidden_rows = set(options.get("hidden_rows", []))
            row_xml: list[str] = []
            for row_index, row in enumerate(rows, start=1):
                cell_xml: list[str] = []
                for column_index, value in enumerate(row, start=1):
                    reference = self._xlsx_cell_ref(column_index, row_index)
                    if isinstance(value, dict):
                        cached_value = value.get("cached")
                        cached_xml = f"<v>{cached_value}</v>" if cached_value is not None else ""
                        cell_xml.append(f'<c r="{reference}"><f>{value["formula"]}</f>{cached_xml}</c>')
                    elif value is None:
                        cell_xml.append(f'<c r="{reference}"/>')
                    else:
                        cell_xml.append(f'<c r="{reference}" t="s"><v>{shared_index(value)}</v></c>')
                hidden_attr = ' hidden="1"' if row_index in hidden_rows else ""
                row_xml.append(f'<row r="{row_index}"{hidden_attr}>{"".join(cell_xml)}</row>')

            hidden_columns = options.get("hidden_columns", [])
            cols_xml = ""
            if hidden_columns:
                col_entries = []
                for min_column, max_column in hidden_columns:
                    col_entries.append(f'<col min="{min_column}" max="{max_column}" hidden="1"/>')
                cols_xml = f"<cols>{''.join(col_entries)}</cols>"

            merge_refs = options.get("merge_refs", [])
            merge_xml = ""
            if merge_refs:
                merge_xml = (
                    f'<mergeCells count="{len(merge_refs)}">'
                    + "".join(f'<mergeCell ref="{merge_ref}"/>' for merge_ref in merge_refs)
                    + "</mergeCells>"
                )

            sheet_documents.append(
                (
                    f"xl/worksheets/sheet{sheet_index}.xml",
                    (
                        '<?xml version="1.0" encoding="UTF-8"?>'
                        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                        f'{cols_xml}<sheetData>{"".join(row_xml)}</sheetData>{merge_xml}'
                        "</worksheet>"
                    ),
                )
            )

        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{"".join(workbook_sheets)}</sheets>'
            "</workbook>"
        )
        rels_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{"".join(relationships)}'
            "</Relationships>"
        )
        shared_strings_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + "".join(f"<si><t>{value}</t></si>" for value in shared_strings)
            + "</sst>"
        )

        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("xl/workbook.xml", workbook_xml)
            archive.writestr("xl/_rels/workbook.xml.rels", rels_xml)
            archive.writestr("xl/sharedStrings.xml", shared_strings_xml)
            for sheet_path, sheet_xml in sheet_documents:
                archive.writestr(sheet_path, sheet_xml)

    def test_sanitize_upload_filename_blocks_traversal_and_prefixes_uuid(self):
        safe_name = sanitize_upload_filename("../../etc/passwd.txt")
        self.assertTrue(safe_name.endswith("-passwd.txt"))
        self.assertNotIn("/", safe_name)
        self.assertNotIn("..", safe_name)
        self.assertRegex(safe_name, r"^[0-9a-f]{12}-")

    def test_build_document_prompt_truncates_total_context(self):
        prompt = build_document_prompt(
            "Сделай summary",
            [
                {"name": "a.txt", "content": "A" * (MAX_PARSED_DOCUMENT_CHARS + 500)},
                {"name": "b.txt", "content": "B" * 500},
            ],
        )
        self.assertIn(DOCUMENT_TRUNCATION_MARKER, prompt)
        document_section = prompt.split("# ДОКУМЕНТЫ", 1)[1].split("# ЗАПРОС ПОЛЬЗОВАТЕЛЯ", 1)[0]
        self.assertLessEqual(len(document_section), MAX_PARSED_DOCUMENT_CHARS + 200)

    def test_apply_document_budget_preserves_names_when_budget_is_exhausted(self):
        budgeted = apply_document_budget(
            [
                {"name": "a.txt", "content": "A" * MAX_DOCUMENT_CHARS},
                {"name": "b.txt", "content": "B" * 500},
            ]
        )

        self.assertEqual([document["name"] for document in budgeted], ["a.txt", "b.txt"])
        self.assertEqual(budgeted[-1]["content"], DOCUMENT_TRUNCATION_MARKER)

    def test_build_document_prompt_contains_strict_antihallucination_rules(self):
        prompt = build_document_prompt(
            "Какая сумма указана в документе?",
            [{"name": "report.txt", "content": "Сумма договора: 1500 руб."}],
        )
        self.assertIn("ЕДИНСТВЕННЫЙ источник данных", prompt)
        self.assertIn("буквальное содержимое файлов", prompt)
        self.assertIn("НЕ имеешь права выдумывать информацию", prompt)
        self.assertIn(DOCUMENT_NO_INFORMATION_RESPONSE, prompt)
        self.assertIn("[Документ 1: report.txt]", prompt)

    def test_build_document_prompt_handles_blank_request(self):
        prompt = build_document_prompt(
            "",
            [{"name": "report.txt", "content": "Текст документа"}],
        )
        self.assertIn("Пользователь не уточнил задачу", prompt)
        self.assertIn("Если запрос пустой или неясный", prompt)

    def test_build_document_prompt_rejects_whitespace_only_documents(self):
        with self.assertRaises(ValueError) as error:
            build_document_prompt(
                "Сделай summary",
                [
                    {"name": "empty.txt", "content": ""},
                    {"name": "spaces.txt", "content": "   \n\t   "},
                ],
            )

        self.assertEqual(str(error.exception), "Не удалось извлечь текст из выбранных файлов")

    def test_response_requires_document_retry_detects_inaccessible_file_phrases(self):
        self.assertTrue(response_requires_document_retry("Я не имею доступа к файлам и не могу прочитать документ."))
        self.assertTrue(response_requires_document_retry(""))
        self.assertFalse(response_requires_document_retry("В документе указана сумма 1500 руб."))

    def test_normalize_document_response_keeps_specific_missing_fields(self):
        self.assertEqual(
            normalize_document_response("В документе не указана дата договора."),
            "В документе не указана дата договора.",
        )
        self.assertEqual(
            normalize_document_response("Нет информации о дате."),
            "Нет информации о дате.",
        )
        self.assertEqual(
            normalize_document_response("Сумма договора: 1500 руб."),
            "Сумма договора: 1500 руб.",
        )

    def test_retry_document_prompt_does_not_force_exact_no_info_phrase(self):
        prompt = parser_stage.build_retry_document_prompt(
            "Какая дата указана в документе?",
            [{"name": "report.txt", "content": "Сумма договора: 1500 руб."}],
        )

        self.assertIn("Нельзя говорить, что у тебя нет доступа к файлам", prompt)
        self.assertIn(DOCUMENT_NO_INFORMATION_RESPONSE, prompt)
        self.assertNotIn("верни только точную фразу", prompt)
        self.assertNotIn("Ответь ровно так", prompt)

    def test_stage_uploads_rejects_unsupported_extension(self):
        upload = UploadFile(filename="malware.exe", file=io.BytesIO(b"payload"))
        with self.assertRaises(HTTPException) as error:
            asyncio.run(stage_uploads([upload]))
        self.assertEqual(error.exception.status_code, 400)

    def test_stage_uploads_rejects_oversized_file(self):
        with tempfile.NamedTemporaryFile() as handle:
            handle.seek((50 * 1024 * 1024) + 1)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            upload = UploadFile(filename="big.txt", file=handle)
            with self.assertRaises(HTTPException) as error:
                    asyncio.run(stage_uploads([upload]))
        self.assertEqual(error.exception.status_code, 413)

    def test_stage_uploads_rejects_too_many_files(self):
        uploads = [UploadFile(filename=f"{index}.txt", file=io.BytesIO(b"x")) for index in range(MAX_UPLOAD_FILES + 1)]

        with self.assertRaises(HTTPException) as error:
            asyncio.run(stage_uploads(uploads))

        self.assertEqual(error.exception.status_code, 400)
        self.assertIn(str(MAX_UPLOAD_FILES), error.exception.detail)

    def test_stage_uploads_rejects_total_request_size_limit(self):
        uploads = [
            UploadFile(filename="a.txt", file=io.BytesIO(b"12345")),
            UploadFile(filename="b.txt", file=io.BytesIO(b"67890")),
        ]

        with mock.patch.object(parser_stage, "MAX_UPLOAD_TOTAL_SIZE_BYTES", 8):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(stage_uploads(uploads))

        self.assertEqual(error.exception.status_code, 413)
        self.assertIn("Суммарный размер файлов", error.exception.detail)

    def test_stage_uploads_accepts_supported_extension_and_content_type_pairs(self):
        cases = [
            ("notes.txt", "text/plain"),
            ("orders.csv", "text/csv"),
            ("orders.csv", "application/csv"),
            ("report.pdf", "application/pdf"),
            ("contract.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("orders.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("scan.png", "image/png"),
            ("photo.jpg", "image/jpeg"),
            ("photo.jpeg", "image/jpeg"),
        ]

        for filename, content_type in cases:
            with self.subTest(filename=filename, content_type=content_type):
                upload = UploadFile(
                    filename=filename,
                    file=io.BytesIO(b"payload"),
                    headers=Headers({"content-type": content_type}),
                )
                temp_dir, staged_files = asyncio.run(stage_uploads([upload]))
                try:
                    self.assertEqual(len(staged_files), 1)
                    self.assertEqual(staged_files[0]["content_type"], content_type)
                finally:
                    temp_dir.cleanup()

    def test_stage_uploads_allows_generic_content_type_for_allowed_extension(self):
        upload = UploadFile(
            filename="report.pdf",
            file=io.BytesIO(b"payload"),
            headers=Headers({"content-type": "application/octet-stream"}),
        )

        temp_dir, staged_files = asyncio.run(stage_uploads([upload]))
        try:
            self.assertEqual(staged_files[0]["content_type"], "application/octet-stream")
        finally:
            temp_dir.cleanup()

    def test_stage_uploads_allows_empty_content_type_for_allowed_extension(self):
        upload = UploadFile(
            filename="notes.txt",
            file=io.BytesIO(b"payload"),
            headers=Headers({}),
        )

        temp_dir, staged_files = asyncio.run(stage_uploads([upload]))
        try:
            self.assertEqual(staged_files[0]["content_type"], "application/octet-stream")
        finally:
            temp_dir.cleanup()

    def test_upload_content_type_helpers_normalize_and_allow_compatible_types(self):
        self.assertEqual(normalize_upload_content_type("text/plain; charset=utf-8"), "text/plain")
        self.assertTrue(upload_content_type_is_allowed(".txt", "text/plain; charset=utf-8"))
        self.assertTrue(upload_content_type_is_allowed(".csv", "text/plain; charset=utf-8"))
        self.assertTrue(upload_content_type_is_allowed(".csv", "application/csv"))
        self.assertTrue(upload_content_type_is_allowed(".pdf", "application/octet-stream"))
        self.assertTrue(upload_content_type_is_allowed(".xlsx", "application/octet-stream"))

    def test_stage_uploads_rejects_content_type_mismatch(self):
        upload = UploadFile(
            filename="report.pdf",
            file=io.BytesIO(b"payload"),
            headers=Headers({"content-type": "image/png"}),
        )

        with self.assertRaises(HTTPException) as error:
            asyncio.run(stage_uploads([upload]))

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(error.exception.detail, "Поддерживаются только TXT, CSV, PDF, DOCX, XLSX, PNG, JPG и JPEG.")

    def test_stage_uploads_rejects_other_unsupported_extensions(self):
        for filename in ("malware.sh", "payload.bin", "legacy.xls"):
            with self.subTest(filename=filename):
                upload = UploadFile(filename=filename, file=io.BytesIO(b"payload"))
                with self.assertRaises(HTTPException) as error:
                    asyncio.run(stage_uploads([upload]))
                self.assertEqual(error.exception.status_code, 400)

    def test_stage_uploads_logs_only_safe_metadata_for_rejected_upload(self):
        upload = UploadFile(
            filename="../../evil.pdf",
            file=io.BytesIO(b"payload"),
            headers=Headers({"content-type": "image/png"}),
        )

        with self.assertLogs("app", level="WARNING") as captured:
            with self.assertRaises(HTTPException):
                asyncio.run(stage_uploads([upload], username="alice"))

        joined_logs = "\n".join(captured.output)
        self.assertIn("upload_rejected reason=content_type_mismatch", joined_logs)
        self.assertIn("extension=.pdf", joined_logs)
        self.assertIn("content_type=image/png", joined_logs)
        self.assertIn("username=alice", joined_logs)
        self.assertIn("filename=", joined_logs)
        self.assertNotIn("../../evil.pdf", joined_logs)

    def test_log_upload_rejection_normalizes_missing_values(self):
        with self.assertLogs("app", level="WARNING") as captured:
            log_upload_rejection(
                reason="unsupported_extension",
                safe_name="abc123-upload.bin",
                extension="<none>",
                content_type="",
                username=None,
            )

        joined_logs = "\n".join(captured.output)
        self.assertIn("content_type=application/octet-stream", joined_logs)
        self.assertIn("username=unknown", joined_logs)

    def test_log_file_parse_observability_logs_only_safe_metrics(self):
        with self.assertLogs("app", level="INFO") as captured:
            log_file_parse_observability(
                username="alice",
                job_kind="file_chat",
                file_count=2,
                staging_ms=15,
                parse_ms=28,
                original_doc_chars=1200,
                trimmed_doc_chars=800,
                terminal_status="success",
                error_type="none",
            )

        joined_logs = "\n".join(captured.output)
        self.assertIn("file_parse_observability", joined_logs)
        self.assertIn("username=alice", joined_logs)
        self.assertIn("job_kind=file_chat", joined_logs)
        self.assertIn("file_count=2", joined_logs)
        self.assertIn("receive_ms=15", joined_logs)
        self.assertIn("parse_ms=28", joined_logs)
        self.assertIn("doc_chars=800", joined_logs)
        self.assertIn("original_doc_chars=1200", joined_logs)
        self.assertIn("trimmed_doc_chars=800", joined_logs)

    def test_extract_text_from_csv_simple_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orders.csv"
            path.write_text("Name,Amount\nAlpha,100\nBeta,200\n", encoding="utf-8")

            text = parser_stage.extract_text_from_csv(path)

        self.assertEqual(text, "CSV: orders.csv\n\nName | Amount\nAlpha | 100\nBeta | 200")

    def test_extract_text_from_csv_trims_cells_and_bounds_rows_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orders.csv"
            path.write_text(
                " Name ; Amount ; Extra ;  \n Alpha ; 100 ; ignored ; \n Beta ; 200 ; ignored ; \n",
                encoding="utf-8",
            )

            with mock.patch.object(parser_stage, "MAX_SPREADSHEET_ROWS", 2), mock.patch.object(
                parser_stage, "MAX_SPREADSHEET_COLUMNS", 2
            ):
                text = parser_stage.extract_text_from_csv(path)

        self.assertIn("Name | Amount", text)
        self.assertIn("Alpha | 100", text)
        self.assertNotIn("Beta", text)
        self.assertNotIn("Extra", text)
        self.assertNotIn(" |  | ", text)

    def test_extract_text_from_csv_empty_file_returns_controlled_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.csv"
            path.write_text(" \n , , \n", encoding="utf-8")

            with self.assertRaises(RuntimeError) as error:
                parser_stage.extract_text_from_csv(path)

        self.assertEqual(str(error.exception), parser_stage.spreadsheet_empty_detail())

    def test_extract_text_from_xlsx_simple_workbook(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orders.xlsx"
            self._write_xlsx_fixture(path, [("Orders", [["Item", "Qty"], ["Widget", "3"]])])

            text = parser_stage.extract_text_from_xlsx(path)

        self.assertIn("Sheet: Orders", text)
        self.assertIn("Item | Qty", text)
        self.assertIn("Widget | 3", text)

    def test_extract_text_from_xlsx_bounds_sheet_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orders.xlsx"
            self._write_xlsx_fixture(
                path,
                [
                    ("Orders", [["Item", "Qty"], ["Widget", "3"]]),
                    ("Archive", [["Old", "99"]]),
                ],
            )

            with mock.patch.object(parser_stage, "MAX_SPREADSHEET_SHEETS", 1):
                text = parser_stage.extract_text_from_xlsx(path)

        self.assertIn("Sheet: Orders", text)
        self.assertNotIn("Archive", text)
        self.assertNotIn("Old | 99", text)

    def test_extract_text_from_xlsx_empty_workbook_returns_controlled_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.xlsx"
            self._write_xlsx_fixture(path, [("Orders", [])])

            with self.assertRaises(RuntimeError) as error:
                parser_stage.extract_text_from_xlsx(path)

        self.assertEqual(str(error.exception), parser_stage.spreadsheet_empty_detail())

    def test_extract_text_from_xlsx_corrupted_file_returns_controlled_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.xlsx"
            path.write_bytes(b"not-a-zip")

            with self.assertRaises(RuntimeError) as error:
                parser_stage.extract_text_from_xlsx(path)

        self.assertEqual(str(error.exception), parser_stage.xlsx_parse_failed_detail())

    def test_extract_text_from_xlsx_uses_cached_formula_value_without_formula_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "formula.xlsx"
            self._write_xlsx_fixture(
                path,
                [("Orders", [["Metric", "Value"], ["Cached", {"formula": "2+5", "cached": "7"}]])],
            )

            text = parser_stage.extract_text_from_xlsx(path)

        self.assertIn("Cached | 7", text)
        self.assertIn("Formula: B2 formula: =2+5 cached: 7", text)

    def test_extract_text_from_xlsx_reports_merge_formula_and_hidden_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metadata.xlsx"
            self._write_xlsx_fixture(
                path,
                [
                    (
                        "Orders",
                        [
                            ["Report title", None, None],
                            ["Metric", "Value"],
                            ["Total", {"formula": "SUM(B2:B3)", "cached": "300"}],
                            ["Pending", {"formula": "SUM(C2:C3)"}],
                        ],
                    ),
                    ("Archive", [["Old", "1"]]),
                ],
                sheet_options={
                    "Orders": {
                        "hidden_columns": [(2, 2)],
                        "hidden_rows": {4},
                        "merge_refs": ["A1:C1"],
                    },
                    "Archive": {"state": "hidden"},
                },
            )

            text = parser_stage.extract_text_from_xlsx(path)

        self.assertIn("Merged cells: A1:C1 = Report title", text)
        self.assertIn("Formula: B3 formula: =SUM(B2:B3) cached: 300", text)
        self.assertIn("Formula: B4 formula: =SUM(C2:C3) cached: unavailable", text)
        self.assertIn("Hidden columns: B", text)
        self.assertIn("Hidden row: 4", text)
        self.assertIn("Hidden sheet: Archive (state=hidden)", text)

    def test_parse_uploaded_file_dispatches_csv_and_xlsx(self):
        with mock.patch.object(parser_stage, "extract_text_from_csv", return_value="csv") as csv_mock, mock.patch.object(
            parser_stage, "extract_text_from_xlsx", return_value="xlsx"
        ) as xlsx_mock:
            self.assertEqual(parser_stage.parse_uploaded_file(Path("/tmp/orders.csv")), "csv")
            self.assertEqual(parser_stage.parse_uploaded_file(Path("/tmp/orders.xlsx")), "xlsx")

        csv_mock.assert_called_once()
        xlsx_mock.assert_called_once()

    def test_extract_text_from_docx_preserves_simple_paragraphs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paragraphs.docx"
            self._write_docx_fixture(
                path,
                """
<w:p><w:r><w:t>First paragraph</w:t></w:r></w:p>
<w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>
""",
            )

            text = parser_stage.extract_text_from_docx(path)

        self.assertEqual(text, "First paragraph\n\nSecond paragraph")

    def test_extract_text_from_docx_preserves_table_rows_cells_and_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "table.docx"
            self._write_docx_fixture(
                path,
                """
<w:p><w:r><w:t>Project Helios configuration</w:t></w:r></w:p>
<w:p><w:r><w:t>   </w:t></w:r></w:p>
<w:tbl>
  <w:tr>
    <w:tc><w:p><w:r><w:t>parameter</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>value</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>unit</w:t></w:r></w:p></w:tc>
  </w:tr>
  <w:tr>
    <w:tc><w:p><w:r><w:t>max_tokens</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>2048</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>tokens</w:t></w:r></w:p></w:tc>
  </w:tr>
  <w:tr>
    <w:tc><w:p><w:r><w:t>temperature</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>0.2</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>ratio</w:t></w:r></w:p></w:tc>
  </w:tr>
  <w:tr>
    <w:tc><w:p><w:r><w:t>retry_limit</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>3</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>attempts</w:t></w:r></w:p></w:tc>
  </w:tr>
  <w:tr>
    <w:tc><w:p /></w:tc>
    <w:tc><w:p><w:r><w:t> </w:t></w:r></w:p></w:tc>
  </w:tr>
</w:tbl>
<w:p><w:r><w:t>Review complete</w:t></w:r></w:p>
""",
            )

            text = parser_stage.extract_text_from_docx(path)

        self.assertIn("Project Helios", text)
        self.assertIn("max_tokens | 2048", text)
        self.assertIn("temperature | 0.2", text)
        self.assertIn("retry_limit | 3", text)
        self.assertIn("parameter | value | unit", text)
        self.assertIn("Review complete", text)
        self.assertLess(text.index("Project Helios"), text.index("parameter | value | unit"))
        self.assertLess(text.index("retry_limit | 3"), text.index("Review complete"))
        self.assertNotIn("0,2", text)
        self.assertNotIn(" |  | ", text)

    def test_extract_text_from_docx_includes_headers_and_footers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "headers-footers.docx"
            self._write_docx_fixture(
                path,
                '<w:p><w:r><w:t>Body paragraph</w:t></w:r></w:p>',
                {
                    "word/header1.xml": (
                        '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                        "<w:p><w:r><w:t>Quarterly Header</w:t></w:r></w:p>"
                        "</w:hdr>"
                    ),
                    "word/footer1.xml": (
                        '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                        "<w:p><w:r><w:t>Confidential Footer</w:t></w:r></w:p>"
                        "</w:ftr>"
                    ),
                },
            )

            text = parser_stage.extract_text_from_docx(path)

        self.assertIn("DOCX Body", text)
        self.assertIn("Body paragraph", text)
        self.assertIn("DOCX Header", text)
        self.assertIn("Quarterly Header", text)
        self.assertIn("DOCX Footer", text)
        self.assertIn("Confidential Footer", text)

    def test_extract_text_from_docx_includes_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "comments.docx"
            self._write_docx_fixture(
                path,
                '<w:p><w:r><w:t>Body paragraph</w:t></w:r></w:p>',
                {
                    "word/comments.xml": (
                        '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                        '<w:comment w:id="1" w:author="Synthetic QA">'
                        "<w:p><w:r><w:t>Reviewer comment text</w:t></w:r></w:p>"
                        "</w:comment>"
                        "</w:comments>"
                    )
                },
            )

            text = parser_stage.extract_text_from_docx(path)

        self.assertIn("DOCX Comments", text)
        self.assertIn("Reviewer comment text", text)

    def test_extract_text_from_docx_reports_tracked_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tracked.docx"
            self._write_docx_fixture(
                path,
                """
<w:p><w:ins w:id="1"><w:r><w:t>new clause</w:t></w:r></w:ins></w:p>
<w:p><w:del w:id="2"><w:r><w:delText>old clause</w:delText></w:r></w:del></w:p>
""",
            )

            text = parser_stage.extract_text_from_docx(path)

        self.assertIn("Tracked changes", text)
        self.assertIn("Inserted: new clause", text)
        self.assertIn("Deleted: old clause", text)

    def test_extract_text_from_docx_reports_embedded_images_without_ocr(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "embedded-image.docx"
            self._write_docx_fixture(
                path,
                '<w:p><w:r><w:t>Body paragraph</w:t></w:r></w:p>',
                {"word/media/image1.png": b"\x89PNG\r\n\x1a\n"},
            )

            text = parser_stage.extract_text_from_docx(path)

        self.assertIn("Embedded images", text)
        self.assertIn("DOCX contains embedded images; OCR inside DOCX is not supported yet", text)

    def test_extract_text_from_docx_maps_missing_document_xml_to_controlled_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing-document-xml.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types />")

            with self.assertRaises(RuntimeError) as error:
                parser_stage.extract_text_from_docx(path)

        self.assertEqual(str(error.exception), parser_stage.docx_parse_failed_detail())

    def test_extract_text_from_pdf_rejects_page_count_over_limit(self):
        class FakePage:
            def __init__(self, index):
                self.index = index

            def get_text(self):
                return f"page-{self.index}"

        class FakeDocument:
            def __len__(self):
                return MAX_PDF_PAGES + 1

            def __getitem__(self, index):
                return FakePage(index)

            def close(self):
                return None

        original_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pypdf":
                raise ImportError("pypdf unavailable")
            if name == "fitz":
                return types.SimpleNamespace(open=lambda path: FakeDocument())
            return original_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            with self.assertRaises(RuntimeError) as error:
                extract_text_from_pdf(Path("/tmp/fake.pdf"))

        self.assertIn(str(MAX_PDF_PAGES), str(error.exception))

    def test_extract_text_from_pdf_uses_pypdf_when_available(self):
        class FakePage:
            def __init__(self, text):
                self.text = text

            def extract_text(self):
                return self.text

        class FakePdfReader:
            def __init__(self, path):
                self.path = path
                self.pages = [FakePage("fallback-page-1"), FakePage("fallback-page-2")]

        original_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pypdf":
                return types.SimpleNamespace(PdfReader=FakePdfReader)
            return original_import(name, globals, locals, fromlist, level)

        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            handle.write(b"%PDF-1.4\n%dummy\n")
            handle.flush()
            with mock.patch("builtins.__import__", side_effect=fake_import):
                text = extract_text_from_pdf(Path(handle.name))

        self.assertEqual(text, "fallback-page-1\nfallback-page-2")

    def test_extract_text_from_pdf_rejects_empty_text_layer_without_ocr(self):
        class FakePage:
            def __init__(self, text):
                self.text = text

            def extract_text(self):
                return self.text

        class FakePdfReader:
            def __init__(self, path):
                self.path = path
                self.pages = [FakePage(None), FakePage("  \n\t"), FakePage("")]

        original_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pypdf":
                return types.SimpleNamespace(PdfReader=FakePdfReader)
            if name == "pytesseract":
                raise AssertionError("PDF no-text detection must not use image OCR")
            return original_import(name, globals, locals, fromlist, level)

        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            handle.write(b"%PDF-1.4\n%dummy\n")
            handle.flush()
            with mock.patch("builtins.__import__", side_effect=fake_import):
                with self.assertRaises(RuntimeError) as error:
                    extract_text_from_pdf(Path(handle.name))

        self.assertEqual(str(error.exception), parser_stage.pdf_no_text_layer_detail())

    def test_extract_text_from_pdf_falls_back_to_fitz_when_pypdf_is_unavailable(self):
        class FakePage:
            def __init__(self, text):
                self.text = text

            def get_text(self):
                return self.text

        class FakeDocument:
            def __len__(self):
                return 2

            def __getitem__(self, index):
                return FakePage(f"fitz-page-{index}")

            def close(self):
                return None

        original_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pypdf":
                raise ImportError("pypdf unavailable")
            if name == "fitz":
                return types.SimpleNamespace(open=lambda path: FakeDocument())
            return original_import(name, globals, locals, fromlist, level)

        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            handle.write(b"%PDF-1.4\n%dummy\n")
            handle.flush()
            with mock.patch("builtins.__import__", side_effect=fake_import):
                text = extract_text_from_pdf(Path(handle.name))

        self.assertEqual(text, "fitz-page-0\nfitz-page-1")

    def test_extract_text_from_pdf_raises_runtime_error_when_all_parsers_are_unavailable(self):
        original_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name in {"fitz", "pypdf"}:
                raise ImportError(f"{name} unavailable")
            return original_import(name, globals, locals, fromlist, level)

        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            handle.write(b"%PDF-1.4\n%dummy\n")
            handle.flush()
            with mock.patch("builtins.__import__", side_effect=fake_import):
                with self.assertRaises(RuntimeError) as error:
                    extract_text_from_pdf(Path(handle.name))

        self.assertEqual(str(error.exception), "PDF parser unavailable on server")

    def test_extract_text_from_pdf_maps_malformed_payload_to_controlled_error_with_pypdf(self):
        class FakePdfReader:
            def __init__(self, path):
                raise ValueError("broken pdf payload")

        original_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pypdf":
                return types.SimpleNamespace(PdfReader=FakePdfReader)
            if name == "fitz":
                return types.SimpleNamespace(open=lambda path: (_ for _ in ()).throw(ValueError("garbage pdf")))
            return original_import(name, globals, locals, fromlist, level)

        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            handle.write(b"not-a-real-pdf")
            handle.flush()
            with mock.patch("builtins.__import__", side_effect=fake_import):
                with self.assertRaises(RuntimeError) as error:
                    extract_text_from_pdf(Path(handle.name))

        self.assertEqual(str(error.exception), "Не удалось извлечь текст из PDF")

    def test_extract_text_from_pdf_maps_malformed_payload_to_controlled_error_with_fitz(self):
        original_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "pypdf":
                raise ImportError("pypdf unavailable")
            if name == "fitz":
                return types.SimpleNamespace(open=lambda path: (_ for _ in ()).throw(ValueError("garbage pdf")))
            return original_import(name, globals, locals, fromlist, level)

        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            handle.write(b"still-not-a-real-pdf")
            handle.flush()
            with mock.patch("builtins.__import__", side_effect=fake_import):
                with self.assertRaises(RuntimeError) as error:
                    extract_text_from_pdf(Path(handle.name))

        self.assertEqual(str(error.exception), "Не удалось извлечь текст из PDF")

    def test_prepare_image_for_ocr_grayscales_and_bounds_small_image_upscale(self):
        from PIL import Image

        source = Image.new("RGB", (120, 80), "white")
        prepared = parser_stage.prepare_image_for_ocr(source)

        self.assertEqual(source.mode, "RGB")
        self.assertEqual(prepared.mode, "L")
        self.assertGreater(prepared.size[0], source.size[0])
        self.assertGreater(prepared.size[1], source.size[1])
        self.assertLessEqual(max(prepared.size), parser_stage.IMAGE_OCR_MAX_DIMENSION)

    def test_prepare_image_for_ocr_keeps_large_image_within_guardrail(self):
        from PIL import Image

        source = Image.new(
            "RGB",
            (parser_stage.IMAGE_OCR_UPSCALE_TARGET_DIMENSION, max(1, parser_stage.IMAGE_OCR_UPSCALE_TARGET_DIMENSION // 2)),
            "white",
        )
        prepared = parser_stage.prepare_image_for_ocr(source)

        self.assertEqual(prepared.mode, "L")
        self.assertEqual(prepared.size, source.size)
        self.assertLessEqual(max(prepared.size), parser_stage.IMAGE_OCR_MAX_DIMENSION)

    def test_extract_text_from_image_passes_timeout_to_ocr(self):
        calls = {}

        class FakeImage:
            size = (800, 600)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        source_image = FakeImage()
        prepared_image = object()
        fake_image_module = types.SimpleNamespace(open=lambda path: source_image)

        def fake_image_to_string(image, *, timeout):
            calls["image"] = image
            calls["timeout"] = timeout
            return "ocr text"

        fake_pytesseract = types.SimpleNamespace(image_to_string=fake_image_to_string)

        with mock.patch.object(parser_stage, "prepare_image_for_ocr", return_value=prepared_image) as prepare_mock, mock.patch.dict(
            sys.modules,
            {
                "pytesseract": fake_pytesseract,
                "PIL": types.SimpleNamespace(Image=fake_image_module),
                "PIL.Image": fake_image_module,
            },
        ):
            text = extract_text_from_image(Path("/tmp/fake.png"))

        prepare_mock.assert_called_once_with(source_image)
        self.assertIs(calls["image"], prepared_image)
        self.assertEqual(text, "ocr text")
        self.assertEqual(calls["timeout"], IMAGE_OCR_TIMEOUT_SECONDS)

    def test_extract_text_from_image_preserves_raw_ocr_text_without_substitution(self):
        class FakeImage:
            size = (800, 600)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        fake_image_module = types.SimpleNamespace(open=lambda path: FakeImage())
        fake_pytesseract = types.SimpleNamespace(
            image_to_string=lambda image, *, timeout: "ALPHA-1 score 38"
        )

        with mock.patch.object(parser_stage, "prepare_image_for_ocr", return_value=object()), mock.patch.dict(
            sys.modules,
            {
                "pytesseract": fake_pytesseract,
                "PIL": types.SimpleNamespace(Image=fake_image_module),
                "PIL.Image": fake_image_module,
            },
        ):
            text = extract_text_from_image(Path("/tmp/fake.png"))

        self.assertEqual(text, "ALPHA-1 score 38")

    def test_extract_text_from_image_rejects_oversized_dimensions(self):
        class FakeImage:
            size = (IMAGE_OCR_MAX_DIMENSION + 1, 900)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        fake_image_module = types.SimpleNamespace(open=lambda path: FakeImage())
        fake_pytesseract = types.SimpleNamespace(image_to_string=lambda image, *, timeout: "ocr text")

        with mock.patch.object(
            parser_stage,
            "prepare_image_for_ocr",
            side_effect=AssertionError("preprocessing must not run for oversized images"),
        ) as prepare_mock, mock.patch.dict(
            sys.modules,
            {
                "pytesseract": fake_pytesseract,
                "PIL": types.SimpleNamespace(Image=fake_image_module),
                "PIL.Image": fake_image_module,
            },
        ):
            with self.assertRaises(RuntimeError) as error:
                extract_text_from_image(Path("/tmp/fake.png"))

        prepare_mock.assert_not_called()
        self.assertIn(str(IMAGE_OCR_MAX_DIMENSION), str(error.exception))

    def test_extract_text_from_image_maps_timeout_to_controlled_error(self):
        class FakeImage:
            size = (800, 600)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        fake_image_module = types.SimpleNamespace(open=lambda path: FakeImage())

        def fake_image_to_string(image, *, timeout):
            raise RuntimeError("Tesseract process timeout")

        fake_pytesseract = types.SimpleNamespace(image_to_string=fake_image_to_string)

        with mock.patch.object(parser_stage, "prepare_image_for_ocr", return_value=object()), mock.patch.dict(
            sys.modules,
            {
                "pytesseract": fake_pytesseract,
                "PIL": types.SimpleNamespace(Image=fake_image_module),
                "PIL.Image": fake_image_module,
            },
        ):
            with self.assertRaises(RuntimeError) as error:
                extract_text_from_image(Path("/tmp/fake.png"))

        self.assertIn(str(IMAGE_OCR_TIMEOUT_SECONDS).rstrip("0").rstrip("."), str(error.exception))

    def test_extract_text_from_image_maps_invalid_payload_to_controlled_error(self):
        def fake_open(path):
            raise OSError("cannot identify image file")

        fake_image_module = types.SimpleNamespace(open=fake_open)
        fake_pytesseract = types.SimpleNamespace(image_to_string=lambda image, *, timeout: "ocr text")

        with mock.patch.dict(
            sys.modules,
            {
                "pytesseract": fake_pytesseract,
                "PIL": types.SimpleNamespace(Image=fake_image_module),
                "PIL.Image": fake_image_module,
            },
        ):
            with self.assertRaises(RuntimeError) as error:
                extract_text_from_image(Path("/tmp/fake.png"))

        self.assertEqual(str(error.exception), "Не удалось извлечь текст из изображения")


if __name__ == "__main__":
    unittest.main()
