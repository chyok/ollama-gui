import configparser
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LINUX_DIR = PROJECT_ROOT / "packaging" / "linux"
APP_ID = "io.github.drericflores.ollama-speak"


class LinuxDesktopIntegrationTests(unittest.TestCase):
    def test_desktop_entry_launches_installed_command(self):
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        loaded = parser.read(
            LINUX_DIR / f"{APP_ID}.desktop",
            encoding="utf-8",
        )
        self.assertEqual(1, len(loaded))
        entry = parser["Desktop Entry"]
        self.assertEqual("Application", entry["Type"])
        self.assertEqual("ollama-speak", entry["Exec"])
        self.assertEqual("ollama-speak", entry["TryExec"])
        self.assertEqual("ollama-speak", entry["Icon"])
        self.assertEqual("false", entry["Terminal"])

    def test_desktop_categories_are_terminated(self):
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        parser.read(LINUX_DIR / f"{APP_ID}.desktop", encoding="utf-8")
        categories = parser["Desktop Entry"]["Categories"]
        self.assertTrue(categories.endswith(";"))
        self.assertIn("Utility", categories.split(";"))

    def test_appstream_identity_and_launcher_match(self):
        root = ET.parse(LINUX_DIR / f"{APP_ID}.metainfo.xml").getroot()
        self.assertEqual("desktop-application", root.attrib["type"])
        self.assertEqual(APP_ID, root.findtext("id"))
        launchable = root.find("launchable")
        self.assertIsNotNone(launchable)
        self.assertEqual("desktop-id", launchable.attrib["type"])
        self.assertEqual(f"{APP_ID}.desktop", (launchable.text or "").strip())
        self.assertEqual("ollama-speak", root.findtext("provides/binary"))

    def test_icon_is_scalable_svg(self):
        icon = LINUX_DIR / "ollama-speak.svg"
        root = ET.parse(icon).getroot()
        self.assertTrue(root.tag.endswith("svg"))
        self.assertEqual("0 0 512 512", root.attrib["viewBox"])


if __name__ == "__main__":
    unittest.main()
