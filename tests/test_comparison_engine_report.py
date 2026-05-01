import unittest

from comparison_engine import compare_normalized_documents, normalize_extracted_document, render_comparison_markdown


def normalize(content: str, *, filename: str = "document.txt", file_format: str = "txt"):
    return normalize_extracted_document(filename=filename, file_format=file_format, content=content)


class ComparisonEngineReportTests(unittest.TestCase):
    def test_identical_comparison_report_contains_summary_and_empty_sections(self) -> None:
        result = compare_normalized_documents(normalize("Alpha.\n\nBeta."), normalize("Alpha.\n\nBeta."))

        report = render_comparison_markdown(result)

        self.assertIn("# Сравнение документов", report)
        self.assertIn("- Добавлено: 0", report)
        self.assertIn("- Удалено: 0", report)
        self.assertIn("- Изменено: 0", report)
        self.assertIn("- Без изменений: 2", report)
        self.assertIn("## Изменённые блоки\n\nНет изменений.", report)
        self.assertIn("## Добавленные блоки\n\nНет изменений.", report)
        self.assertIn("## Удалённые блоки\n\nНет изменений.", report)

    def test_changed_paragraph_report_contains_before_and_after(self) -> None:
        result = compare_normalized_documents(normalize("Payment term is 10 days."), normalize("Payment term is 15 days."))

        report = render_comparison_markdown(result)

        self.assertIn("## Изменённые блоки", report)
        self.assertIn("Было:", report)
        self.assertIn("Стало:", report)
        self.assertIn("Payment term is 10 days.", report)
        self.assertIn("Payment term is 15 days.", report)

    def test_added_and_removed_sections_are_rendered(self) -> None:
        result = compare_normalized_documents(
            normalize("DOCX Body\nKeep.\n\nold | row", filename="a.docx", file_format="docx"),
            normalize("DOCX Body\nKeep.\n\nDOCX Header\nAdd.", filename="b.docx", file_format="docx"),
        )

        report = render_comparison_markdown(result)

        self.assertIn("## Добавленные блоки", report)
        self.assertIn("## Удалённые блоки", report)
        self.assertIn("Add.", report)
        self.assertIn("old \\| row", report)

    def test_table_and_sheet_rows_remain_readable(self) -> None:
        result = compare_normalized_documents(
            normalize(
                "Sheet: Orders\nContractID | Vendor | Amount\nCNT-001 | Alpha LLC | 100000\n",
                filename="orders-a.xlsx",
                file_format="xlsx",
            ),
            normalize(
                "Sheet: Orders\nContractID | Vendor | Amount\nCNT-001 | Alpha LLC | 150000\n",
                filename="orders-b.xlsx",
                file_format="xlsx",
            ),
        )

        report = render_comparison_markdown(result)

        self.assertIn("sheet_row", report)
        self.assertIn("CNT-001 \\| Alpha LLC \\| 100000", report)
        self.assertIn("CNT-001 \\| Alpha LLC \\| 150000", report)

    def test_long_text_is_truncated(self) -> None:
        long_a = "A" * 120
        long_b = "B" * 120
        result = compare_normalized_documents(normalize(long_a), normalize(long_b))

        report = render_comparison_markdown(result, max_text_chars=40)

        self.assertIn("...", report)
        self.assertNotIn("A" * 80, report)
        self.assertNotIn("B" * 80, report)

    def test_max_items_per_section_reports_hidden_count(self) -> None:
        doc_a = normalize("Base.")
        doc_b = normalize("\n\n".join(["Base.", "Add 1.", "Add 2.", "Add 3."]))
        result = compare_normalized_documents(doc_a, doc_b)

        report = render_comparison_markdown(result, max_items_per_section=1)

        self.assertIn("Add 1.", report)
        self.assertNotIn("Add 2.", report)
        self.assertIn("... ещё 2 элементов не показано", report)

    def test_to_markdown_is_deterministic(self) -> None:
        result = compare_normalized_documents(normalize("A.\n\nB."), normalize("A.\n\nC."))

        first = result.to_markdown()
        second = result.to_markdown()

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
