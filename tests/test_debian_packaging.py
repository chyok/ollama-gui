import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEBIAN_DIR = PROJECT_ROOT / "packaging" / "debian"


class DebianPackagingTests(unittest.TestCase):
    def test_control_declares_runtime_dependencies(self):
        control = (DEBIAN_DIR / "control.in").read_text(encoding="utf-8")
        self.assertIn("Package: ollama-speak", control)
        self.assertIn("Version: @VERSION@", control)
        self.assertIn("Architecture: all", control)
        depends = re.search(r"^Depends: (.+)$", control, flags=re.MULTILINE)
        self.assertIsNotNone(depends)
        for dependency in ("python3", "python3-tk", "alsa-utils"):
            self.assertIn(dependency, depends.group(1))

    def test_launcher_uses_system_python_module(self):
        launcher = (DEBIAN_DIR / "ollama-speak").read_text(encoding="utf-8")
        self.assertTrue(launcher.startswith("#!/bin/sh\n"))
        self.assertIn('exec python3 -m ollama_speak "$@"', launcher)

    def test_build_script_uses_safe_staging_and_expected_destinations(self):
        script = (DEBIAN_DIR / "build-deb.sh").read_text(encoding="utf-8")
        self.assertIn("set -eu", script)
        self.assertIn("mktemp -d", script)
        self.assertIn("dpkg-deb --root-owner-group --build", script)
        self.assertNotIn("tomllib", script)
        for destination in (
            "usr/bin/ollama-speak",
            "usr/lib/python3/dist-packages/ollama_speak.py",
            "usr/share/applications",
            "usr/share/icons/hicolor/scalable/apps",
            "usr/share/metainfo",
            "usr/share/doc/ollama-speak",
        ):
            with self.subTest(destination=destination):
                self.assertIn(destination, script)

    def test_debian_copyright_uses_machine_readable_format(self):
        copyright_text = (DEBIAN_DIR / "copyright").read_text(encoding="utf-8")
        self.assertIn("copyright-format/1.0", copyright_text)
        self.assertIn("License: MIT", copyright_text)

    @unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb is not installed")
    def test_build_script_constructs_expected_deb(self):
        with tempfile.TemporaryDirectory() as output_dir:
            subprocess.run(
                ["sh", str(DEBIAN_DIR / "build-deb.sh"), output_dir],
                cwd=PROJECT_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            package = Path(output_dir) / "ollama-speak_1.4.0_all.deb"
            self.assertTrue(package.is_file())
            fields = subprocess.check_output(
                ["dpkg-deb", "--field", str(package)],
                text=True,
            )
            self.assertIn("Package: ollama-speak", fields)
            self.assertIn("Version: 1.4.0", fields)
            self.assertIn("Architecture: all", fields)
            contents = subprocess.check_output(
                ["dpkg-deb", "--contents", str(package)],
                text=True,
            )
            self.assertNotIn("drwxrwx", contents)


if __name__ == "__main__":
    unittest.main()
