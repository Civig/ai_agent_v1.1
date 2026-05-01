import json
import unittest

from comparison_engine import compare_normalized_documents, normalize_extracted_document


def normalize(content: str, *, filename: str = "document.txt", file_format: str = "txt"):
    return normalize_extracted_document(filename=filename, file_format=file_format, content=content)


class ComparisonEngineDiffTests(unittest.TestCase):
    def test_identical_documents_have_only_unchanged_blocks(self) -> None:
        doc_a = normalize("First paragraph.\n\nSecond paragraph.")
        doc_b = normalize("First paragraph.\n\nSecond paragraph.")

        result = compare_normalized_documents(doc_a, doc_b)

        self.assertEqual(result.added, ())
        self.assertEqual(result.removed, ())
        self.assertEqual(result.changed, ())
        self.assertEqual(result.unchanged_count, 2)
        self.assertEqual(result.summary["total_a_blocks"], 2)
        self.assertEqual(result.summary["total_b_blocks"], 2)

    def test_added_paragraph_is_reported_as_added(self) -> None:
        doc_a = normalize("First paragraph.")
        doc_b = normalize("First paragraph.\n\nAdded paragraph.")

        result = compare_normalized_documents(doc_a, doc_b)

        self.assertEqual(len(result.added), 1)
        self.assertEqual(result.added[0].change_type, "added")
        self.assertEqual(result.added[0].text_b, "Added paragraph.")
        self.assertEqual(result.summary["added_count"], 1)

    def test_removed_paragraph_is_reported_as_removed(self) -> None:
        doc_a = normalize("First paragraph.\n\nRemoved paragraph.")
        doc_b = normalize("First paragraph.")

        result = compare_normalized_documents(doc_a, doc_b)

        self.assertEqual(len(result.removed), 1)
        self.assertEqual(result.removed[0].change_type, "removed")
        self.assertEqual(result.removed[0].text_a, "Removed paragraph.")
        self.assertEqual(result.summary["removed_count"], 1)

    def test_changed_paragraph_uses_order_fallback(self) -> None:
        doc_a = normalize("Payment term is 10 days.")
        doc_b = normalize("Payment term is 15 days.")

        result = compare_normalized_documents(doc_a, doc_b)

        self.assertEqual(len(result.changed), 1)
        self.assertEqual(result.changed[0].change_type, "changed")
        self.assertEqual(result.changed[0].block_type, "paragraph")
        self.assertEqual(result.changed[0].text_a, "Payment term is 10 days.")
        self.assertEqual(result.changed[0].text_b, "Payment term is 15 days.")

    def test_docx_table_row_change_is_detected(self) -> None:
        content_a = """DOCX Body
parameter | value | unit
temperature | 0.2 | ratio
"""
        content_b = """DOCX Body
parameter | value | unit
temperature | 0.4 | ratio
"""
        doc_a = normalize(content_a, filename="contract-a.docx", file_format="docx")
        doc_b = normalize(content_b, filename="contract-b.docx", file_format="docx")

        result = compare_normalized_documents(doc_a, doc_b)

        self.assertEqual(result.unchanged_count, 1)
        self.assertEqual(len(result.changed), 1)
        self.assertEqual(result.changed[0].block_type, "table_row")
        self.assertIn("0.2", result.changed[0].text_a)
        self.assertIn("0.4", result.changed[0].text_b)

    def test_xlsx_sheet_row_change_is_detected(self) -> None:
        content_a = """Sheet: Orders
ContractID | Vendor | Amount
CNT-001 | Alpha LLC | 100000
"""
        content_b = """Sheet: Orders
ContractID | Vendor | Amount
CNT-001 | Alpha LLC | 150000
"""
        doc_a = normalize(content_a, filename="orders-a.xlsx", file_format="xlsx")
        doc_b = normalize(content_b, filename="orders-b.xlsx", file_format="xlsx")

        result = compare_normalized_documents(doc_a, doc_b)

        self.assertEqual(len(result.changed), 1)
        self.assertEqual(result.changed[0].block_type, "sheet_row")
        self.assertEqual(result.changed[0].source_a.sheet, "Orders")
        self.assertEqual(result.changed[0].source_b.sheet, "Orders")
        self.assertIn("100000", result.changed[0].text_a)
        self.assertIn("150000", result.changed[0].text_b)

    def test_metadata_change_is_detected(self) -> None:
        content_a = """Sheet metadata: Orders
Formula: C2 formula: =A1+B1 cached: 100000
"""
        content_b = """Sheet metadata: Orders
Formula: C2 formula: =A1+B1 cached: 150000
"""
        doc_a = normalize(content_a, filename="orders-a.xlsx", file_format="xlsx")
        doc_b = normalize(content_b, filename="orders-b.xlsx", file_format="xlsx")

        result = compare_normalized_documents(doc_a, doc_b)

        self.assertEqual(len(result.changed), 1)
        self.assertEqual(result.changed[0].block_type, "metadata")
        self.assertIn("100000", result.changed[0].text_a)
        self.assertIn("150000", result.changed[0].text_b)

    def test_result_to_dict_is_json_serializable(self) -> None:
        doc_a = normalize("Alpha.")
        doc_b = normalize("Beta.")

        result = compare_normalized_documents(doc_a, doc_b)
        payload = result.to_dict()
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)

        self.assertIn("summary", payload)
        self.assertIn("changed", payload)
        self.assertIn("changed_count", encoded)
        self.assertEqual(payload["summary"]["changed_count"], 1)

    def test_same_inputs_produce_stable_result(self) -> None:
        doc_a = normalize("A.\n\nB.")
        doc_b = normalize("A.\n\nC.")

        first = compare_normalized_documents(doc_a, doc_b).to_dict()
        second = compare_normalized_documents(doc_a, doc_b).to_dict()

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
