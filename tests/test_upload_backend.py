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
    def _write_docx_fixture(self, path: Path, body_xml: str) -> None:
        document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{body_xml}<w:sectPr /></w:body>
</w:document>
"""
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", document_xml)

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
            ("report.pdf", "application/pdf"),
            ("contract.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
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
        self.assertTrue(upload_content_type_is_allowed(".pdf", "application/octet-stream"))

    def test_stage_uploads_rejects_content_type_mismatch(self):
        upload = UploadFile(
            filename="report.pdf",
            file=io.BytesIO(b"payload"),
            headers=Headers({"content-type": "image/png"}),
        )

        with self.assertRaises(HTTPException) as error:
            asyncio.run(stage_uploads([upload]))

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(error.exception.detail, "Поддерживаются только TXT, PDF, DOCX, PNG, JPG и JPEG.")

    def test_stage_uploads_rejects_other_unsupported_extensions(self):
        for filename in ("malware.sh", "payload.bin"):
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
