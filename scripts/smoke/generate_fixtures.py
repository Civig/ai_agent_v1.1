#!/usr/bin/env python3
from __future__ import annotations

import binascii
import hashlib
import json
import struct
import zlib
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests" / "smoke" / "fixtures"


TXT_FIXTURES = {
    "txt/entities.txt": """# Smoke Fixture: Entity List
Project: Project Helios
Document code: SMK-ENT-001

Entities:
- ALPHA-17: primary telemetry sensor
- BRAVO-42: backup relay
- CHARLIE-09: audit node

Owner: Smoke QA
Region: EU-North
""",
    "txt/parameters_table.txt": """# Smoke Fixture: Parameters
parameter | value | unit | note
max_tokens | 2048 | tokens | deterministic test budget
temperature | 0.2 | ratio | low variance
retry_limit | 3 | attempts | bounded retry
ocr_timeout | 30 | seconds | parser guard
""",
    "txt/missing_fields.txt": """# Smoke Fixture: Partial Record
Ticket: SMK-PARTIAL-003
Owner: Smoke QA
Priority: Medium
Region: EU-North

Known missing fields:
- Budget is not provided.
- Final deadline is not provided.
""",
}


PDF_FIXTURES = {
    "pdf/entity_report.pdf": [
        [
            "Smoke Fixture PDF: Entity Report",
            "Project: Project Helios",
            "Document code: SMK-PDF-ENT-001",
            "Entities:",
            "- ALPHA-17: primary telemetry sensor",
            "- BRAVO-42: backup relay",
            "- CHARLIE-09: audit node",
            "Owner: Smoke QA",
        ]
    ],
    "pdf/parameter_table.pdf": [
        [
            "Smoke Fixture PDF: Parameter Table",
            "parameter        value   unit      note",
            "max_tokens       2048    tokens    deterministic test budget",
            "temperature      0.2     ratio     low variance",
            "retry_limit      3       attempts  bounded retry",
            "ocr_timeout      30      seconds   parser guard",
        ]
    ],
    "pdf/monthly_metrics.pdf": [
        [
            "Smoke Fixture PDF: Monthly Success Metrics",
            "Month      Success Rate   Resolved Tickets",
            "January    91%            118",
            "February   93%            126",
            "March      95%            139",
            "April      94%            132",
            "Metric owner: Smoke QA",
        ]
    ],
    "pdf/mixed_3p_report.pdf": [
        [
            "Smoke Fixture PDF: Mixed Report, page 1",
            "Project: Project Helios",
            "Summary: validation bundle for rented GPU hosts.",
            "Named entities: ALPHA-17, BRAVO-42, CHARLIE-09.",
        ],
        [
            "Smoke Fixture PDF: Mixed Report, page 2",
            "Configuration table:",
            "parameter        value   unit",
            "max_tokens       2048    tokens",
            "temperature      0.2     ratio",
            "retry_limit      3       attempts",
        ],
        [
            "Smoke Fixture PDF: Mixed Report, page 3",
            "Monthly metrics:",
            "January 91%, February 93%, March 95%, April 94%.",
            "Missing: no budget and no final deadline are provided.",
        ],
    ],
}


DOCX_FIXTURES = {
    "docx/table_and_paragraphs.docx": {
        "paragraphs": [
            "Smoke Fixture DOCX: Table and Paragraphs",
            "Project Helios uses deterministic parser smoke data.",
            "The table below contains transparent parameters.",
        ],
        "rows": [
            ["parameter", "value", "unit"],
            ["max_tokens", "2048", "tokens"],
            ["temperature", "0.2", "ratio"],
            ["retry_limit", "3", "attempts"],
        ],
    },
    "docx/mixed_content.docx": {
        "paragraphs": [
            "Smoke Fixture DOCX: Mixed Content",
            "Entities: ALPHA-17, BRAVO-42, CHARLIE-09.",
            "Monthly metrics: January 91%, February 93%, March 95%, April 94%.",
            "Budget and final deadline are not provided.",
        ],
        "rows": [
            ["month", "success_rate", "tickets"],
            ["January", "91%", "118"],
            ["February", "93%", "126"],
            ["March", "95%", "139"],
        ],
    },
}


FONT = {
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    ":": ["00000", "01100", "01100", "00000", "01100", "01100", "00000"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01110"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    "J": ["00111", "00010", "00010", "00010", "10010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
}


def pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_pdf(path: Path, pages: list[list[str]]) -> None:
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    page_object_ids = [4 + index * 2 for index in range(len(pages))]
    kids = " ".join(f"{object_id} 0 R" for object_id in page_object_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii"))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for index, lines in enumerate(pages):
        page_id = 4 + index * 2
        content_id = page_id + 1
        stream_lines = ["BT", "/F1 11 Tf", "14 TL", "72 760 Td"]
        for line in lines:
            stream_lines.append(f"({pdf_escape(line)}) Tj")
            stream_lines.append("T*")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1")
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
        objects.append(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream")

    content = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, payload in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{object_id} 0 obj\n".encode("ascii"))
        content.extend(payload)
        content.extend(b"\nendobj\n")
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
    path.write_bytes(bytes(content))


def paragraph_xml(text: str) -> str:
    return f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>"


def table_xml(rows: list[list[str]]) -> str:
    xml_rows = []
    for row in rows:
        cells = "".join(f"<w:tc>{paragraph_xml(cell)}</w:tc>" for cell in row)
        xml_rows.append(f"<w:tr>{cells}</w:tr>")
    return f"<w:tbl>{''.join(xml_rows)}</w:tbl>"


def write_docx(path: Path, paragraphs: list[str], rows: list[list[str]]) -> None:
    body = "".join(paragraph_xml(item) for item in paragraphs) + table_xml(rows)
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{body}<w:sectPr /></w:body>
</w:document>
"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        write_stable_zip_member(archive, "[Content_Types].xml", content_types)
        write_stable_zip_member(archive, "_rels/.rels", rels)
        write_stable_zip_member(archive, "word/document.xml", document_xml)


def write_stable_zip_member(archive: zipfile.ZipFile, name: str, content: str) -> None:
    info = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, content.encode("utf-8"))


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)


def draw_text(canvas: bytearray, width: int, height: int, x: int, y: int, text: str, scale: int) -> None:
    for char in text.upper():
        glyph = FONT.get(char, FONT[" "])
        for row_index, row in enumerate(glyph):
            for col_index, bit in enumerate(row):
                if bit != "1":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        px = x + col_index * scale + dx
                        py = y + row_index * scale + dy
                        if 0 <= px < width and 0 <= py < height:
                            offset = (py * width + px) * 3
                            canvas[offset : offset + 3] = b"\x00\x00\x00"
        x += (len(glyph[0]) + 1) * scale


def write_png(path: Path, width: int, height: int, text_lines: list[str]) -> None:
    canvas = bytearray(b"\xff" * width * height * 3)
    y = 28
    for line in text_lines:
        draw_text(canvas, width, height, 28, y, line, 6)
        y += 58
    scanlines = bytearray()
    row_size = width * 3
    for row in range(height):
        scanlines.append(0)
        start = row * row_size
        scanlines.extend(canvas[start : start + row_size])
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(bytes(scanlines), level=9))
        + png_chunk(b"IEND", b"")
    )
    path.write_bytes(payload)


def write_text_fixtures() -> list[Path]:
    paths: list[Path] = []
    for relative, content in TXT_FIXTURES.items():
        path = FIXTURE_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    return paths


def write_binary_fixtures() -> list[Path]:
    paths: list[Path] = []
    for relative, pages in PDF_FIXTURES.items():
        path = FIXTURE_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        write_pdf(path, pages)
        paths.append(path)
    for relative, payload in DOCX_FIXTURES.items():
        path = FIXTURE_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        write_docx(path, payload["paragraphs"], payload["rows"])
        paths.append(path)
    image_success = FIXTURE_ROOT / "images" / "ocr_success.png"
    image_success.parent.mkdir(parents=True, exist_ok=True)
    write_png(image_success, 760, 180, ["OCR PASS", "ALPHA-17 SCORE 98"])
    paths.append(image_success)

    image_oversized = FIXTURE_ROOT / "images" / "oversized_dimension.png"
    write_png(image_oversized, 2201, 2201, ["OVERSIZED", "DIMENSION 2201"])
    paths.append(image_oversized)
    return paths


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(paths: list[Path]) -> Path:
    manifest = {
        "generated_by": "scripts/smoke/generate_fixtures.py",
        "fixture_count": len(paths),
        "fixtures": [
            {
                "path": str(path.relative_to(REPO_ROOT)),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in sorted(paths)
        ],
    }
    target = FIXTURE_ROOT / "generated" / "manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def main() -> int:
    paths = write_text_fixtures() + write_binary_fixtures()
    manifest = write_manifest(paths)
    print(f"Generated {len(paths)} fixtures")
    print(manifest.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
