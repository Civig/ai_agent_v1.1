#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import zlib
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


REPO_ROOT = Path(__file__).resolve().parents[2]
GOLD_ROOT = REPO_ROOT / "tests" / "smoke" / "fixtures" / "gold"
MAX_FIXTURE_BYTES = 2 * 1024 * 1024


CSV_ROWS = [
    ["ContractID", "Vendor", "Amount", "Currency", "Status"],
    ["CNT-001", "Alpha LLC", "100000", "RUB", "Active"],
    ["CNT-002", "Beta LLC", "250000", "RUB", "Review"],
]

XLSX_SHEETS = [
    (
        "Orders",
        [
            ["ContractID", "Vendor", "Amount", "Currency", "Status"],
            ["CNT-001", "Alpha LLC", "100000", "RUB", "Active"],
            ["CNT-002", "Beta LLC", "250000", "RUB", "Review"],
        ],
    ),
    (
        "Metrics",
        [
            ["Month", "SuccessRate", "Tickets"],
            ["January", "91", "118"],
            ["February", "93", "126"],
            ["March", "95", "139"],
        ],
    ),
]


def write_stable_zip_member(archive: zipfile.ZipFile, name: str, content: str | bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    payload = content.encode("utf-8") if isinstance(content, str) else content
    archive.writestr(info, payload)


def xlsx_cell_ref(column_index: int, row_index: int) -> str:
    name = ""
    column = column_index
    while column:
        column, remainder = divmod(column - 1, 26)
        name = chr(ord("A") + remainder) + name
    return f"{name}{row_index}"


def write_xlsx(path: Path, sheets: list[tuple[str, list[list[str]]]]) -> None:
    shared_strings: list[str] = []
    shared_indexes: dict[str, int] = {}
    workbook_sheets: list[str] = []
    relationships: list[str] = []
    sheet_documents: list[tuple[str, str]] = []

    def shared_index(value: str) -> int:
        if value not in shared_indexes:
            shared_indexes[value] = len(shared_strings)
            shared_strings.append(value)
        return shared_indexes[value]

    for sheet_index, (sheet_name, rows) in enumerate(sheets, start=1):
        relationship_id = f"rId{sheet_index}"
        workbook_sheets.append(
            f'<sheet name="{escape(sheet_name)}" sheetId="{sheet_index}" r:id="{relationship_id}"/>'
        )
        relationships.append(
            f'<Relationship Id="{relationship_id}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{sheet_index}.xml"/>'
        )

        row_xml: list[str] = []
        for row_index, row in enumerate(rows, start=1):
            cell_xml: list[str] = []
            for column_index, value in enumerate(row, start=1):
                reference = xlsx_cell_ref(column_index, row_index)
                cell_xml.append(f'<c r="{reference}" t="s"><v>{shared_index(value)}</v></c>')
            row_xml.append(f'<row r="{row_index}">{"".join(cell_xml)}</row>')

        sheet_documents.append(
            (
                f"xl/worksheets/sheet{sheet_index}.xml",
                (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    f'<sheetData>{"".join(row_xml)}</sheetData>'
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
        + "".join(f"<si><t>{escape(value)}</t></si>" for value in shared_strings)
        + "</sst>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for index in range(1, len(sheets) + 1)
        )
        + "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        write_stable_zip_member(archive, "[Content_Types].xml", content_types)
        write_stable_zip_member(archive, "_rels/.rels", root_rels)
        write_stable_zip_member(archive, "xl/workbook.xml", workbook_xml)
        write_stable_zip_member(archive, "xl/_rels/workbook.xml.rels", rels_xml)
        write_stable_zip_member(archive, "xl/sharedStrings.xml", shared_strings_xml)
        for name, content in sheet_documents:
            write_stable_zip_member(archive, name, content)


def pdf_object(payload: bytes) -> bytes:
    return payload + b"\n"


def write_pdf(path: Path, objects: list[bytes]) -> None:
    content = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, payload in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{object_id} 0 obj\n".encode("ascii"))
        content.extend(pdf_object(payload))
        content.extend(b"endobj\n")
    xref_offset = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    content.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(content))


def write_image_only_pdf(path: Path) -> None:
    pixels = zlib.compress(
        bytes(
            [
                255,
                255,
                255,
                40,
                40,
                40,
                40,
                40,
                40,
                255,
                255,
                255,
            ]
        ),
        level=9,
    )
    image_stream = (
        b"<< /Type /XObject /Subtype /Image /Width 2 /Height 2 "
        b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
        + f"/Length {len(pixels)}".encode("ascii")
        + b" >>\nstream\n"
        + pixels
        + b"\nendstream"
    )
    page_stream = b"q\n120 0 0 120 72 620 cm\n/Im1 Do\nQ"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(page_stream)).encode("ascii") + b" >>\nstream\n" + page_stream + b"\nendstream",
        image_stream,
    ]
    write_pdf(path, objects)


def write_missing_document_docx(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        write_stable_zip_member(
            archive,
            "[Content_Types].xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
            ),
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fixture_entry(
    *,
    fixture_id: str,
    fmt: str,
    path: Path,
    scenario: str,
    expected_status: str,
    expected_entities: list[str] | None = None,
    expected_values: dict[str, object] | None = None,
    expected_controlled_error_substring: str = "",
    unsupported_features: list[str] | None = None,
    notes: str,
) -> dict[str, object]:
    relative = path.relative_to(REPO_ROOT)
    return {
        "id": fixture_id,
        "format": fmt,
        "path": str(relative),
        "scenario": scenario,
        "expected_status": expected_status,
        "expected_entities": expected_entities or [],
        "expected_values": expected_values or {},
        "expected_controlled_error_substring": expected_controlled_error_substring,
        "unsupported_features": unsupported_features or [],
        "notes": notes,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def write_gold_files() -> None:
    orders_csv = GOLD_ROOT / "csv" / "orders.csv"
    orders_csv.parent.mkdir(parents=True, exist_ok=True)
    orders_csv.write_text("\n".join(",".join(row) for row in CSV_ROWS) + "\n", encoding="utf-8")

    write_xlsx(GOLD_ROOT / "xlsx" / "synthetic_workbook.xlsx", XLSX_SHEETS)
    write_image_only_pdf(GOLD_ROOT / "pdf" / "scanned_no_text_layer.pdf")
    (GOLD_ROOT / "pdf" / "malformed_payload.pdf").write_bytes(b"not-a-real-pdf\n")
    write_missing_document_docx(GOLD_ROOT / "docx" / "missing_document_xml.docx")

    unsupported_xls = GOLD_ROOT / "unsupported" / "orders.xls"
    unsupported_xls.parent.mkdir(parents=True, exist_ok=True)
    unsupported_xls.write_text("Synthetic legacy XLS placeholder; parser intentionally rejects .xls.\n", encoding="utf-8")


def build_manifest() -> dict[str, object]:
    existing = REPO_ROOT / "tests" / "smoke" / "fixtures"
    fixtures = [
        fixture_entry(
            fixture_id="txt_entities_alpha_bravo_charlie",
            fmt="txt",
            path=existing / "txt" / "entities.txt",
            scenario="TXT entity extraction baseline for file-chat grounding.",
            expected_status="success",
            expected_entities=["ALPHA-17", "BRAVO-42", "CHARLIE-09"],
            notes="Existing smoke fixture reused to avoid duplicate TXT content.",
        ),
        fixture_entry(
            fixture_id="txt_parameters_parser_budget",
            fmt="txt",
            path=existing / "txt" / "parameters_table.txt",
            scenario="TXT parameter extraction baseline with deterministic parser settings.",
            expected_status="success",
            expected_values={
                "max_tokens": "2048",
                "temperature": "0.2",
                "retry_limit": "3",
                "ocr_timeout": "30",
            },
            notes="Existing smoke fixture covers parser parameter values.",
        ),
        fixture_entry(
            fixture_id="csv_orders_contract_status",
            fmt="csv",
            path=GOLD_ROOT / "csv" / "orders.csv",
            scenario="CSV baseline for contract/order table extraction.",
            expected_status="success",
            expected_entities=["CNT-001", "CNT-002", "Alpha LLC", "Beta LLC"],
            expected_values={
                "headers": ["ContractID", "Vendor", "Amount", "Currency", "Status"],
                "rows": [
                    {
                        "ContractID": "CNT-001",
                        "Vendor": "Alpha LLC",
                        "Amount": "100000",
                        "Currency": "RUB",
                        "Status": "Active",
                    },
                    {
                        "ContractID": "CNT-002",
                        "Vendor": "Beta LLC",
                        "Amount": "250000",
                        "Currency": "RUB",
                        "Status": "Review",
                    },
                ],
            },
            notes="Synthetic CSV fixture added because CSV was covered only by unit tests.",
        ),
        fixture_entry(
            fixture_id="xlsx_orders_and_metrics",
            fmt="xlsx",
            path=GOLD_ROOT / "xlsx" / "synthetic_workbook.xlsx",
            scenario="XLSX baseline with Orders and Metrics worksheets.",
            expected_status="success",
            expected_entities=["CNT-001", "CNT-002", "January", "February", "March"],
            expected_values={
                "sheets": ["Orders", "Metrics"],
                "headers": {
                    "Orders": ["ContractID", "Vendor", "Amount", "Currency", "Status"],
                    "Metrics": ["Month", "SuccessRate", "Tickets"],
                },
                "metrics": {
                    "January": {"SuccessRate": "91", "Tickets": "118"},
                    "February": {"SuccessRate": "93", "Tickets": "126"},
                    "March": {"SuccessRate": "95", "Tickets": "139"},
                },
            },
            notes="Synthetic XLSX generated with lightweight OOXML and no runtime dependency.",
        ),
        fixture_entry(
            fixture_id="docx_project_helios_table",
            fmt="docx",
            path=existing / "docx" / "table_and_paragraphs.docx",
            scenario="DOCX paragraph plus table extraction baseline.",
            expected_status="success",
            expected_entities=["Project Helios"],
            expected_values={
                "table_header": "parameter | value | unit",
                "max_tokens": "2048",
                "temperature": "0.2",
                "retry_limit": "3",
            },
            notes="Existing DOCX smoke fixture already matches the gold table scenario.",
        ),
        fixture_entry(
            fixture_id="pdf_text_layer_entities",
            fmt="pdf",
            path=existing / "pdf" / "entity_report.pdf",
            scenario="PDF text-layer entity extraction baseline.",
            expected_status="success",
            expected_entities=["ALPHA-17", "BRAVO-42", "CHARLIE-09"],
            notes="Existing text-layer PDF fixture reused.",
        ),
        fixture_entry(
            fixture_id="pdf_text_layer_parameters",
            fmt="pdf",
            path=existing / "pdf" / "parameter_table.pdf",
            scenario="PDF text-layer parameter table extraction baseline.",
            expected_status="success",
            expected_values={
                "max_tokens": "2048",
                "temperature": "0.2",
                "retry_limit": "3",
                "ocr_timeout": "30",
            },
            notes="Existing text-layer PDF parameter fixture reused.",
        ),
        fixture_entry(
            fixture_id="pdf_scanned_no_text_layer",
            fmt="pdf",
            path=GOLD_ROOT / "pdf" / "scanned_no_text_layer.pdf",
            scenario="Image-only PDF negative case for controlled no-text-layer detection.",
            expected_status="failure",
            expected_controlled_error_substring="PDF не содержит извлекаемого текстового слоя",
            unsupported_features=["pdf_ocr_not_supported"],
            notes="Small synthetic PDF contains an image XObject and no text layer.",
        ),
        fixture_entry(
            fixture_id="pdf_malformed_payload",
            fmt="pdf",
            path=GOLD_ROOT / "pdf" / "malformed_payload.pdf",
            scenario="Malformed PDF negative case for controlled parse failure.",
            expected_status="failure",
            expected_controlled_error_substring="Не удалось извлечь текст из PDF",
            unsupported_features=["malformed_pdf"],
            notes="Tiny synthetic invalid payload mirrors existing parser unit-test coverage.",
        ),
        fixture_entry(
            fixture_id="png_ocr_success_alpha_score",
            fmt="png",
            path=existing / "images" / "ocr_success.png",
            scenario="PNG OCR-positive baseline for image file-chat.",
            expected_status="success",
            expected_entities=["ALPHA", "17", "98"],
            notes="Existing PNG smoke fixture reused; OCR execution is left to smoke, not manifest validation.",
        ),
        fixture_entry(
            fixture_id="docx_missing_document_xml",
            fmt="docx",
            path=GOLD_ROOT / "docx" / "missing_document_xml.docx",
            scenario="Malformed DOCX negative case for missing word/document.xml.",
            expected_status="failure",
            expected_controlled_error_substring="Не удалось извлечь текст из DOCX",
            unsupported_features=["malformed_docx_missing_document_xml"],
            notes="Small synthetic DOCX zip mirrors existing parser unit-test coverage.",
        ),
        fixture_entry(
            fixture_id="xls_unsupported_legacy_workbook",
            fmt="xls",
            path=GOLD_ROOT / "unsupported" / "orders.xls",
            scenario="Unsupported legacy XLS upload negative case.",
            expected_status="failure",
            expected_controlled_error_substring="Поддерживаются только TXT, CSV, PDF, DOCX, XLSX, PNG, JPG и JPEG",
            unsupported_features=["legacy_xls_not_supported"],
            notes="Synthetic placeholder; .xls remains intentionally unsupported.",
        ),
    ]

    return {
        "schema_version": 1,
        "description": "Golden synthetic parser/file-chat corpus for stable quality checks.",
        "generated_by": "scripts/smoke/generate_gold_corpus.py",
        "max_fixture_bytes": MAX_FIXTURE_BYTES,
        "fixture_count": len(fixtures),
        "fixtures": fixtures,
        "roadmap_gaps": [
            {
                "format": "jpg",
                "reason": "PNG OCR success is covered by an existing fixture; JPG OCR is intentionally deferred until a stable synthetic JPG OCR fixture is needed.",
            }
        ],
    }


def main() -> int:
    write_gold_files()
    manifest = build_manifest()
    target = GOLD_ROOT / "manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {manifest['fixture_count']} gold corpus entries")
    print(target.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
