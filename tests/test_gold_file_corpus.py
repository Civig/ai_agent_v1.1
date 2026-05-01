import csv
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "tests" / "smoke" / "fixtures" / "gold" / "manifest.json"
REQUIRED_FIELDS = {
    "id",
    "format",
    "path",
    "scenario",
    "expected_status",
    "expected_entities",
    "expected_values",
    "expected_controlled_error_substring",
    "notes",
    "unsupported_features",
}
ALLOWED_STATUSES = {"success", "failure"}
ALLOWED_FORMATS = {"txt", "csv", "xlsx", "docx", "pdf", "png", "jpg", "jpeg", "xls"}
TEXT_FORMATS = {"txt", "csv", "xls"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_scalar_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values: list[str] = []
        for nested in value.values():
            values.extend(iter_scalar_strings(nested))
        return values
    if isinstance(value, list):
        values = []
        for nested in value:
            values.extend(iter_scalar_strings(nested))
        return values
    return []


class GoldFileCorpusTests(unittest.TestCase):
    def load_manifest(self) -> dict[str, Any]:
        with MANIFEST_PATH.open(encoding="utf-8") as handle:
            return json.load(handle)

    def fixture_path(self, entry: dict[str, Any]) -> Path:
        relative_path = Path(entry["path"])
        self.assertFalse(relative_path.is_absolute(), entry["id"])
        self.assertNotIn("..", relative_path.parts, entry["id"])
        path = (REPO_ROOT / relative_path).resolve()
        path.relative_to(REPO_ROOT.resolve())
        return path

    def test_manifest_schema_paths_sizes_and_hashes_are_valid(self) -> None:
        manifest = self.load_manifest()

        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["fixture_count"], len(manifest["fixtures"]))
        self.assertLessEqual(manifest["max_fixture_bytes"], 2 * 1024 * 1024)

        seen_ids: set[str] = set()
        for entry in manifest["fixtures"]:
            missing = REQUIRED_FIELDS.difference(entry)
            self.assertFalse(missing, f"{entry.get('id', '<missing id>')} missing {sorted(missing)}")
            self.assertNotIn(entry["id"], seen_ids)
            seen_ids.add(entry["id"])

            self.assertIn(entry["format"], ALLOWED_FORMATS, entry["id"])
            self.assertIn(entry["expected_status"], ALLOWED_STATUSES, entry["id"])
            self.assertIsInstance(entry["expected_entities"], list, entry["id"])
            self.assertIsInstance(entry["expected_values"], dict, entry["id"])
            self.assertIsInstance(entry["unsupported_features"], list, entry["id"])
            self.assertTrue(entry["scenario"].strip(), entry["id"])
            self.assertTrue(entry["notes"].strip(), entry["id"])

            if entry["expected_status"] == "failure":
                self.assertTrue(entry["expected_controlled_error_substring"].strip(), entry["id"])
                self.assertTrue(entry["unsupported_features"], entry["id"])
            else:
                self.assertEqual(entry["expected_controlled_error_substring"], "", entry["id"])

            path = self.fixture_path(entry)
            self.assertTrue(path.exists(), entry["id"])
            self.assertLessEqual(path.stat().st_size, manifest["max_fixture_bytes"], entry["id"])
            self.assertEqual(entry["bytes"], path.stat().st_size, entry["id"])
            self.assertEqual(entry["sha256"], sha256(path), entry["id"])
            self.assertEqual(path.suffix.lower().lstrip("."), entry["format"], entry["id"])

    def test_text_fixtures_contain_declared_entities_and_values(self) -> None:
        manifest = self.load_manifest()

        for entry in manifest["fixtures"]:
            if entry["format"] not in TEXT_FORMATS:
                continue

            text = self.fixture_path(entry).read_text(encoding="utf-8")
            expected_terms = list(entry["expected_entities"])
            expected_terms.extend(iter_scalar_strings(entry["expected_values"]))
            for term in expected_terms:
                self.assertIn(term, text, f"{entry['id']} missing {term}")

    def test_csv_fixture_matches_declared_headers_and_rows(self) -> None:
        manifest = self.load_manifest()
        csv_entries = [entry for entry in manifest["fixtures"] if entry["format"] == "csv"]
        self.assertTrue(csv_entries)

        for entry in csv_entries:
            with self.fixture_path(entry).open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

            expected = entry["expected_values"]
            self.assertEqual(reader.fieldnames, expected["headers"], entry["id"])
            self.assertEqual(rows, expected["rows"], entry["id"])

    def test_unsupported_and_roadmap_gaps_are_explicit(self) -> None:
        manifest = self.load_manifest()

        failure_entries = [entry for entry in manifest["fixtures"] if entry["expected_status"] == "failure"]
        self.assertTrue(failure_entries)
        for entry in failure_entries:
            self.assertTrue(entry["unsupported_features"], entry["id"])
            for feature in entry["unsupported_features"]:
                self.assertIsInstance(feature, str, entry["id"])
                self.assertTrue(feature.strip(), entry["id"])

        gaps = manifest.get("roadmap_gaps", [])
        self.assertTrue(gaps)
        for gap in gaps:
            self.assertIn(gap["format"], ALLOWED_FORMATS, gap)
            self.assertTrue(gap["reason"].strip(), gap)


if __name__ == "__main__":
    unittest.main()
