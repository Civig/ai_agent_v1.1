from __future__ import annotations

import unittest

from scripts.smoke.smoke_common import contains_expected_text, evaluate_expectations


class SmokeExpectationEvaluatorNormalizationTests(unittest.TestCase):
    def test_month_localization_aliases_do_not_fail_file_chat_cases(self) -> None:
        case = {
            "expected_status": "success",
            "must_contain": ["January", "February", "March", "April"],
            "must_not_contain": ["December"],
        }

        result = evaluate_expectations(
            response_text="**Январь** 91%; Февраль 93%; Марта 95%; `Апрель` 94%.",
            case=case,
            actual_status="success",
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["forbidden"], [])

    def test_markdown_whitespace_and_simple_punctuation_are_normalized(self) -> None:
        case = {
            "expected_status": "success",
            "must_contain": ["Project Helios", "max_tokens", "2048", "temperature", "0.2"],
            "must_not_contain": ["Project Apollo"],
        }

        result = evaluate_expectations(
            response_text="`Project`: **Helios**\nmax_tokens:\u00a02048; temperature: 0.2",
            case=case,
            actual_status="success",
        )

        self.assertTrue(result["passed"])

    def test_exact_tokens_and_missing_list_remain_compatible(self) -> None:
        case = {
            "expected_status": "success",
            "must_contain": ["ALPHA-17", "BRAVO-42"],
            "must_not_contain": ["DELTA-99"],
        }

        passed = evaluate_expectations(response_text="alpha-17 and BRAVO-42", case=case, actual_status="success")
        failed = evaluate_expectations(response_text="ALPHA-17 and DELTA-99", case=case, actual_status="success")

        self.assertTrue(passed["passed"])
        self.assertFalse(failed["passed"])
        self.assertEqual(failed["missing"], ["BRAVO-42"])
        self.assertEqual(failed["forbidden"], ["DELTA-99"])

    def test_numeric_and_entity_mismatches_stay_failures(self) -> None:
        self.assertTrue(contains_expected_text("ALPHA-17 score 98", "17"))
        self.assertFalse(contains_expected_text("score 38", "98"))
        self.assertFalse(contains_expected_text("value 1", "17"))
        self.assertFalse(contains_expected_text("ALPHA-1 score 38", "ALPHA-17"))

        case = {
            "expected_status": "success",
            "must_contain": ["98", "17", "ALPHA-17"],
            "must_not_contain": [],
        }
        result = evaluate_expectations(response_text="ALPHA-1 score 38", case=case, actual_status="success")

        self.assertFalse(result["passed"])
        self.assertEqual(result["missing"], ["98", "17", "ALPHA-17"])


if __name__ == "__main__":
    unittest.main()
