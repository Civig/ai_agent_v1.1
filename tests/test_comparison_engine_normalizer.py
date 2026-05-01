import json
import unittest

from comparison_engine import normalize_extracted_document, normalize_text_for_compare


class ComparisonEngineNormalizerTests(unittest.TestCase):
    def test_generic_txt_normalization_creates_stable_paragraph_blocks(self) -> None:
        content = "First paragraph with ALPHA-17.\n\nSecond paragraph with score 98.\n\n"

        first = normalize_extracted_document(filename="notes.txt", file_format="txt", content=content)
        second = normalize_extracted_document(filename="notes.txt", file_format="txt", content=content)

        self.assertEqual(first.format, "txt")
        self.assertEqual([block.type for block in first.blocks], ["paragraph", "paragraph"])
        self.assertEqual([block.block_id for block in first.blocks], [block.block_id for block in second.blocks])
        self.assertEqual([block.hash for block in first.blocks], [block.hash for block in second.blocks])
        self.assertTrue(all(block.text for block in first.blocks))
        self.assertEqual(first.blocks[0].normalized_text, "first paragraph with alpha-17.")
        self.assertEqual(normalize_text_for_compare("  Alpha\r\n  17  "), "alpha 17")

    def test_docx_markers_create_paragraph_table_and_metadata_blocks(self) -> None:
        content = """DOCX Body
Intro paragraph for contract.

parameter | value | unit
max_tokens | 2048 | tokens

DOCX Header
Confidential header

DOCX Footer
Page 1

DOCX Comments
Reviewer: check amount

Tracked changes
Inserted: payment term
"""

        document = normalize_extracted_document(filename="contract.docx", file_format="docx", content=content)
        block_types = [block.type for block in document.blocks]
        metadata_sections = {block.source.section for block in document.blocks if block.type == "metadata"}

        self.assertIn("paragraph", block_types)
        self.assertIn("table_row", block_types)
        self.assertIn("metadata", block_types)
        self.assertTrue({"header", "footer", "comments", "tracked_changes"}.issubset(metadata_sections))
        table_rows = [block for block in document.blocks if block.type == "table_row"]
        self.assertEqual(table_rows[0].cells, ("parameter", "value", "unit"))
        self.assertEqual(table_rows[0].source.section, "body")

    def test_xlsx_markers_create_sheet_rows_and_metadata_blocks(self) -> None:
        content = """Sheet: Orders
ContractID | Vendor | Amount
CNT-001 | Alpha LLC | 100000

Sheet metadata: Orders
Formula: C2 formula: =A1+B1 cached: 100000
Merged cells: A1:C1 = Report title
Hidden row: 4
Hidden sheet: Archive (state=hidden)
"""

        document = normalize_extracted_document(filename="orders.xlsx", file_format="xlsx", content=content)
        sheet_rows = [block for block in document.blocks if block.type == "sheet_row"]
        metadata = [block for block in document.blocks if block.type == "metadata"]

        self.assertEqual(len(sheet_rows), 2)
        self.assertTrue(all(block.source.sheet == "Orders" for block in sheet_rows))
        self.assertEqual(sheet_rows[1].source.row_index, 2)
        self.assertGreaterEqual(len(metadata), 4)
        self.assertTrue(any("Formula:" in block.text for block in metadata))
        self.assertTrue(any("Hidden sheet:" in block.text for block in metadata))

    def test_pdf_ocr_page_markers_create_ocr_page_blocks(self) -> None:
        content = """PDF OCR Page 1
ALPHA-17 OCR SCORE 98

PDF OCR Page 2
BRAVO-42 OCR SCORE 97
"""

        document = normalize_extracted_document(filename="scan.pdf", file_format="pdf", content=content)

        self.assertEqual([block.type for block in document.blocks], ["ocr_page", "ocr_page"])
        self.assertEqual([block.source.page for block in document.blocks], [1, 2])
        self.assertIn("ALPHA-17", document.blocks[0].text)

    def test_document_to_dict_is_json_serializable_and_contains_block_sources(self) -> None:
        document = normalize_extracted_document(
            filename="orders.csv",
            file_format="csv",
            content="CSV: orders.csv\n\nContractID | Vendor\nCNT-001 | Alpha LLC\n",
        )

        payload = document.to_dict()
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)

        self.assertIn("orders.csv", encoded)
        self.assertEqual(payload["filename"], "orders.csv")
        self.assertEqual(payload["format"], "csv")
        self.assertEqual(payload["blocks"][0]["type"], "table_row")
        self.assertIn("block_id", payload["blocks"][0])
        self.assertIn("hash", payload["blocks"][0])
        self.assertEqual(payload["blocks"][0]["source"]["filename"], "orders.csv")
        self.assertEqual(payload["blocks"][0]["cells"], ["ContractID", "Vendor"])

    def test_same_input_produces_same_document_and_block_ids(self) -> None:
        kwargs = {
            "filename": "report.pdf",
            "file_format": "pdf",
            "content": "Line one.\n\nLine two.",
            "parser_version": "parser-v1",
        }

        first = normalize_extracted_document(**kwargs)
        second = normalize_extracted_document(**kwargs)

        self.assertEqual(first.document_id, second.document_id)
        self.assertEqual([block.block_id for block in first.blocks], [block.block_id for block in second.blocks])
        self.assertEqual([block.hash for block in first.blocks], [block.hash for block in second.blocks])


if __name__ == "__main__":
    unittest.main()
