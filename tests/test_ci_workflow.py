import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


class ContinuousIntegrationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_has_read_only_permissions_and_concurrency(self):
        self.assertIn("permissions:\n  contents: read", self.workflow)
        self.assertIn("cancel-in-progress: true", self.workflow)

    def test_python_support_matrix_is_covered(self):
        for version in ('"3.10"', '"3.11"', '"3.12"'):
            with self.subTest(version=version):
                self.assertIn(version, self.workflow)
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)

    def test_linux_metadata_is_validated(self):
        self.assertIn("desktop-file-validate", self.workflow)
        self.assertIn("appstreamcli validate", self.workflow)

    def test_all_release_candidates_and_checksums_are_uploaded(self):
        for artifact in (
            "ollama_speak-1.4.0-py3-none-any.whl",
            "ollama_speak-1.4.0.tar.gz",
            "ollama-speak_1.4.0_all.deb",
            "SHA256SUMS",
        ):
            with self.subTest(artifact=artifact):
                self.assertIn(artifact, self.workflow)
        self.assertIn("actions/upload-artifact@v6", self.workflow)


if __name__ == "__main__":
    unittest.main()
