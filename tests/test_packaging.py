import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PackagingMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pyproject_text = (PROJECT_ROOT / "pyproject.toml").read_text(
            encoding="utf-8"
        )

    def _string_value(self, key):
        match = re.search(
            rf'^{re.escape(key)}\s*=\s*"([^"]+)"',
            self.pyproject_text,
            flags=re.MULTILINE,
        )
        self.assertIsNotNone(match, f"Missing string metadata field: {key}")
        return match.group(1)

    def test_project_identity_and_entry_point(self):
        self.assertEqual("ollama-speak", self._string_value("name"))
        self.assertEqual("README.md", self._string_value("readme"))
        self.assertEqual(
            "ollama_speak:run",
            self._string_value("ollama-speak"),
        )

    def test_metadata_version_matches_module(self):
        source = (PROJECT_ROOT / "ollama_speak.py").read_text(encoding="utf-8")
        match = re.search(
            r'^__version__\s*=\s*["\']([^"\']+)["\']',
            source,
            flags=re.MULTILINE,
        )
        self.assertIsNotNone(match)
        self.assertEqual(self._string_value("version"), match.group(1))

    def test_declared_project_files_exist(self):
        for relative_path in (
            "LICENSE",
            "README.md",
            "INSTALL.md",
            "MANIFEST.in",
            "ollama_speak.py",
        ):
            with self.subTest(path=relative_path):
                self.assertTrue((PROJECT_ROOT / relative_path).is_file())

    def test_runtime_has_no_third_party_python_dependencies(self):
        self.assertIsNotNone(
            re.search(
                r"^dependencies\s*=\s*\[\s*\]",
                self.pyproject_text,
                flags=re.MULTILINE,
            )
        )


if __name__ == "__main__":
    unittest.main()
