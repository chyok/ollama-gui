import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "ollama_speak.py"
if not MODULE_PATH.exists():
    MODULE_PATH = PROJECT_ROOT / "upload/ollama-speak.py"
SPEC = importlib.util.spec_from_file_location("ollama_speak", MODULE_PATH)
ollama_speak = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ollama_speak)


class TextProcessingTests(unittest.TestCase):
    def test_extracts_complete_sentences_and_remainder(self):
        sentences, remainder = ollama_speak._extract_sentences("One. Two! partial")
        self.assertEqual(["One.", " Two!"], sentences)
        self.assertEqual(" partial", remainder)

    def test_strips_markdown_without_losing_link_text(self):
        text = ollama_speak._strip_markdown("**Bold** and [link](https://example.com)")
        self.assertEqual("Bold and link", text)


class OllamaProtocolTests(unittest.TestCase):
    def test_filters_embedding_only_models(self):
        payload = {
            "models": [
                {"name": "embed", "capabilities": ["embedding"]},
                {"name": "chat", "capabilities": ["completion", "tools"]},
                {"name": "legacy"},
            ]
        }
        self.assertEqual(["chat", "legacy"], ollama_speak.filter_chat_models(payload))

    def test_rejects_malformed_model_payload(self):
        with self.assertRaisesRegex(ValueError, "models list"):
            ollama_speak.filter_chat_models({"models": "invalid"})

    def test_parses_stream_content(self):
        line = b'{"message":{"role":"assistant","content":"hello"}}\n'
        self.assertEqual("hello", ollama_speak.parse_chat_stream_line(line, 1))

    def test_propagates_ollama_stream_error(self):
        with self.assertRaisesRegex(RuntimeError, "model unavailable"):
            ollama_speak.parse_chat_stream_line(b'{"error":"model unavailable"}\n', 2)

    def test_rejects_invalid_stream_json(self):
        with self.assertRaisesRegex(ValueError, "line 3"):
            ollama_speak.parse_chat_stream_line(b'{invalid}\n', 3)


class ConversationValidationTests(unittest.TestCase):
    def test_accepts_valid_history(self):
        history = [{"role": "user", "content": "hello"}]
        self.assertEqual(history, ollama_speak.validate_chat_history(history))

    def test_rejects_non_object_entry(self):
        with self.assertRaisesRegex(ValueError, "not an object"):
            ollama_speak.validate_chat_history(["invalid"])

    def test_rejects_unknown_role(self):
        with self.assertRaisesRegex(ValueError, "invalid role"):
            ollama_speak.validate_chat_history([{"role": "root", "content": "hello"}])

    def test_rejects_non_text_content(self):
        with self.assertRaisesRegex(ValueError, "non-text"):
            ollama_speak.validate_chat_history([{"role": "user", "content": 42}])


class VoiceAndSettingsTests(unittest.TestCase):
    def test_multilingual_voice_label(self):
        path = Path("es_MX-ald-medium.onnx")
        self.assertEqual("Spanish (Mexico) — Ald [Medium]", ollama_speak._voice_label(path))

    def test_discovers_only_complete_voice_pairs(self):
        old_custom = os.environ.get("OLLAMA_SPEAK_VOICE_DIR")
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "de_DE-thorsten-medium.onnx").write_bytes(b"model")
                (root / "de_DE-thorsten-medium.onnx.json").write_text("{}")
                (root / "it_IT-incomplete-medium.onnx").write_bytes(b"model")
                os.environ["OLLAMA_SPEAK_VOICE_DIR"] = directory
                voices = ollama_speak.discover_voice_models()
                self.assertIn("German (Germany) — Thorsten [Medium]", voices)
                self.assertFalse(any("Incomplete" in label for label in voices))
        finally:
            if old_custom is None:
                os.environ.pop("OLLAMA_SPEAK_VOICE_DIR", None)
            else:
                os.environ["OLLAMA_SPEAK_VOICE_DIR"] = old_custom

    def test_settings_round_trip_and_permissions(self):
        old_dir = ollama_speak.CONFIG_DIR
        old_file = ollama_speak.CONFIG_FILE
        try:
            with tempfile.TemporaryDirectory() as directory:
                ollama_speak.CONFIG_DIR = Path(directory)
                ollama_speak.CONFIG_FILE = Path(directory) / "config.json"
                expected = {"model": "qwen", "timbre": "Normal"}
                ollama_speak.save_settings(expected)
                self.assertEqual(expected, ollama_speak.load_settings())
                self.assertEqual(0o600, ollama_speak.CONFIG_FILE.stat().st_mode & 0o777)
        finally:
            ollama_speak.CONFIG_DIR = old_dir
            ollama_speak.CONFIG_FILE = old_file

    def test_nested_and_legacy_sample_rates(self):
        speaker = ollama_speak.PiperSpeaker(piper_bin="/missing/piper")
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                nested = root / "nested.onnx"
                nested.write_bytes(b"model")
                Path(str(nested) + ".json").write_text(
                    json.dumps({"audio": {"sample_rate": 22050}})
                )
                legacy = root / "legacy.onnx"
                legacy.write_bytes(b"model")
                Path(str(legacy) + ".json").write_text(json.dumps({"sample_rate": 16000}))
                self.assertEqual(22050, speaker.get_voice_sample_rate(str(nested)))
                self.assertEqual(16000, speaker.get_voice_sample_rate(str(legacy)))
        finally:
            speaker.shutdown()

    def test_stop_then_begin_session(self):
        speaker = ollama_speak.PiperSpeaker(piper_bin="/missing/piper")
        try:
            speaker.stop()
            self.assertTrue(speaker._stop_event.is_set())
            speaker.begin_session()
            self.assertFalse(speaker._stop_event.is_set())
        finally:
            speaker.shutdown()


if __name__ == "__main__":
    unittest.main()
