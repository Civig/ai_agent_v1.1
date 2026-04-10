import re
import unittest
from pathlib import Path


class BuildReproducibilityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.requirements_text = (cls.repo_root / "requirements.txt").read_text(encoding="utf-8-sig")
        cls.requirements_lock_text = (cls.repo_root / "requirements.lock").read_text(encoding="utf-8")
        cls.dockerfile_text = (cls.repo_root / "Dockerfile").read_text(encoding="utf-8-sig")
        cls.compose_text = (cls.repo_root / "docker-compose.yml").read_text(encoding="utf-8")
        cls.env_example_text = (cls.repo_root / ".env.example").read_text(encoding="utf-8")
        cls.install_ru_text = (cls.repo_root / "docs" / "INSTALL_ru.md").read_text(encoding="utf-8")
        cls.security_ru_text = (cls.repo_root / "docs" / "SECURITY_ru.md").read_text(encoding="utf-8")

    @staticmethod
    def _normalize_requirement_name(requirement_line: str) -> str:
        line = requirement_line.strip()
        line = line.split("#", 1)[0].strip()
        match = re.match(r"^([A-Za-z0-9_.-]+)", line)
        if not match:
            raise AssertionError(f"Cannot parse requirement line: {requirement_line!r}")
        return match.group(1).lower().replace("_", "-")

    def test_requirements_lock_exists_and_pins_direct_dependencies(self):
        lock_names: set[str] = set()
        for line in self.requirements_lock_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            self.assertIn("==", line, msg=f"Unpinned lock line: {line}")
            lock_names.add(self._normalize_requirement_name(line))

        direct_requirements = [
            line.strip()
            for line in self.requirements_text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertTrue(direct_requirements, "requirements.txt should not be empty")

        for requirement in direct_requirements:
            normalized = self._normalize_requirement_name(requirement)
            self.assertIn(
                normalized,
                lock_names,
                msg=f"Direct requirement {requirement!r} is missing from requirements.lock",
            )

    def test_dockerfile_uses_lockfile_and_pinned_python_base_digest(self):
        self.assertIn("ARG PYTHON_BASE_IMAGE=python:3.11-slim@sha256:", self.dockerfile_text)
        self.assertIn("COPY requirements.txt requirements.lock ./", self.dockerfile_text)
        self.assertIn("pip install --no-cache-dir -r requirements.lock", self.dockerfile_text)
        self.assertNotIn("pip install --no-cache-dir -r requirements.txt", self.dockerfile_text)

    def test_compose_uses_pinned_image_baseline_without_latest(self):
        self.assertNotIn("ollama/ollama:latest", self.compose_text)
        self.assertIn("${REDIS_IMAGE:-redis@sha256:", self.compose_text)
        self.assertIn("${POSTGRES_IMAGE:-postgres@sha256:", self.compose_text)
        self.assertIn("${OLLAMA_IMAGE:-ollama/ollama@sha256:", self.compose_text)
        self.assertIn("${NGINX_IMAGE:-nginx@sha256:", self.compose_text)

    def test_env_example_exposes_image_baseline_overrides(self):
        self.assertIn("REDIS_IMAGE=redis@sha256:", self.env_example_text)
        self.assertIn("POSTGRES_IMAGE=postgres@sha256:", self.env_example_text)
        self.assertIn("OLLAMA_IMAGE=ollama/ollama@sha256:", self.env_example_text)
        self.assertIn("NGINX_IMAGE=nginx@sha256:", self.env_example_text)

    def test_docs_describe_reproducible_build_baseline(self):
        self.assertIn("requirements.lock", self.install_ru_text)
        self.assertIn("reproducible build baseline", self.install_ru_text.lower())
        self.assertIn("requirements.lock", self.security_ru_text)
        self.assertIn("pinned", self.security_ru_text.lower())
