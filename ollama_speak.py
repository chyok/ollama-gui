#!/usr/bin/env python3
"""
ollama_speak.py
Ollama GUI (Tkinter) + Piper TTS Speech Toggle (stream-synchronized speaking)

Base project: https://github.com/chyok/ollama-gui
Enhancements: Dr. Eric O. Flores
Revision Date: February 9, 2026

This build adds:
- PiperSpeaker (Piper -> optional SoX pitch -> aplay) with clear diagnostics
- Speech Enable/Disable toggle
- Voice selection (Joe default)
- Timbre presets (Normal / Tenor / Bright Tenor) using SoX pitch
- Stop Speaking button

ARCH FIXES (per problem statement):
1) Sentence-level buffer interception from streaming tokens
2) Serialized consumer pattern (queue + single playback worker)
3) Markdown sanitization before TTS
4) In-memory JSON config caching for voice models
"""

import sys
import json
import time
import pprint
import platform
import webbrowser
import os
import shutil
import subprocess
import threading
import queue
import re
from pathlib import Path

import urllib.parse
import urllib.request
import urllib.error

from threading import Thread, Event
from typing import Optional, List, Generator, Callable, Any, Dict, Tuple

try:
    import tkinter as tk
    from tkinter import ttk, font, messagebox, filedialog
except (ModuleNotFoundError, ImportError):
    print(
        "Your Python installation does not include the Tk library. \n"
        "Please refer to https://github.com/chyok/ollama-gui?tab=readme-ov-file#-qa"
    )
    sys.exit(0)

__version__ = "1.4.0"
__revision_date__ = "September 6, 2026"


# -------------------- Piper TTS CONFIG --------------------
DEFAULT_PIPER_BIN = "/home/eric/.local/bin/piper"  # adjust if your path differs
FALLBACK_PIPER_BIN = "piper"                       # use from PATH if available

DEFAULT_VOICE_DIRS = (
    Path.home() / ".local/share/piper/voices",
    Path("/opt/piper/voices"),
)

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ollama-speak"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Timbre presets via SoX pitch (cents); 100 cents = 1 semitone
TIMBRE_PRESETS = {
    "Normal": 0,
    "Tenor (+350¢)": 350,
    "Bright Tenor (+450¢)": 450,
}

DEBUG_LOG = True
# ----------------------------------------------------------


# ---------------- Sentence detection (stream -> sentences) ----------------
# End-of-sentence delimiters: . ! ? \n
# We extract the earliest complete sentence(s) and keep the remainder in buffer.
_SENTENCE_SPLIT_RE = re.compile(r"""
    (                       # capture a sentence
      .*?                   # minimal
      (?:[.!?]+|\n)         # sentence delimiter(s) or newline
    )
""", re.VERBOSE | re.DOTALL)

# A fallback flush if the model streams a long fragment with no punctuation:
_MAX_BUFFER_BEFORE_SOFT_FLUSH = 500
# ------------------------------------------------------------------------


def _voice_label(model_path: Path) -> str:
    """Create a stable, human-readable label from a Piper model filename."""
    stem = model_path.name.removesuffix(".onnx")
    match = re.match(r"(?P<locale>[a-z]{2}_[A-Z]{2})-(?P<name>.+)-(?P<quality>x_low|low|medium|high)$", stem)
    if not match:
        return stem

    language_names = {
        "de_DE": "German (Germany)",
        "en_US": "English (United States)",
        "es_AR": "Spanish (Argentina)",
        "es_ES": "Spanish (Spain)",
        "es_MX": "Spanish (Mexico)",
        "it_IT": "Italian (Italy)",
    }
    locale = match.group("locale")
    language = language_names.get(locale, locale)
    voice_name = match.group("name").replace("_", " ").title()
    quality = match.group("quality").replace("_", "-").title()
    return f"{language} — {voice_name} [{quality}]"


def discover_voice_models() -> Dict[str, str]:
    """Discover complete Piper model/config pairs in configured voice directories."""
    directories = []
    custom_dir = os.environ.get("OLLAMA_SPEAK_VOICE_DIR")
    if custom_dir:
        directories.append(Path(custom_dir).expanduser())
    directories.extend(DEFAULT_VOICE_DIRS)

    voices: Dict[str, str] = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for model_path in sorted(directory.glob("*.onnx")):
            if not Path(str(model_path) + ".json").is_file():
                continue
            label = _voice_label(model_path)
            if label in voices:
                label = f"{label} — {directory}"
            voices[label] = str(model_path)
    return voices


def load_settings() -> Dict[str, Any]:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def save_settings(settings: Dict[str, Any]) -> None:
    """Atomically save non-sensitive application preferences."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(CONFIG_FILE)


def filter_chat_models(payload: Any) -> List[str]:
    """Return only Ollama models that can perform completion/chat."""
    if not isinstance(payload, dict):
        raise ValueError("Ollama model response must be a JSON object")
    raw_models = payload.get("models", [])
    if not isinstance(raw_models, list):
        raise ValueError("Ollama model response contains an invalid models list")

    models = []
    for model in raw_models:
        if not isinstance(model, dict):
            raise ValueError("Ollama model response contains an invalid model entry")
        capabilities = model.get("capabilities")
        if capabilities is not None and not isinstance(capabilities, list):
            raise ValueError("Ollama model capabilities must be a list")
        if capabilities and "completion" not in capabilities:
            continue
        name = model.get("name")
        if isinstance(name, str) and name.strip():
            models.append(name)
    return models


def parse_chat_stream_line(line: bytes, line_number: int) -> Optional[str]:
    """Validate one newline-delimited Ollama streaming response."""
    if not line.strip():
        return None
    try:
        payload = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid Ollama stream data at line {line_number}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid Ollama stream object at line {line_number}")
    if payload.get("error"):
        raise RuntimeError(f"Ollama reported an error: {payload['error']}")
    message = payload.get("message")
    if message is None:
        return None
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise ValueError(f"Invalid Ollama message at line {line_number}")
    return message["content"]


def validate_chat_history(history: Any) -> List[dict]:
    """Validate untrusted conversation JSON before using it in the GUI or API."""
    if not isinstance(history, list):
        raise ValueError("Conversation must contain a JSON list")
    if len(history) > 10000:
        raise ValueError("Conversation contains too many messages")

    validated = []
    allowed_roles = {"system", "user", "assistant"}
    total_characters = 0
    for index, item in enumerate(history, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Conversation entry {index} is not an object")
        role = item.get("role")
        content = item.get("content")
        if role not in allowed_roles:
            raise ValueError(f"Conversation entry {index} has an invalid role")
        if not isinstance(content, str):
            raise ValueError(f"Conversation entry {index} has non-text content")
        total_characters += len(content)
        if total_characters > 10_000_000:
            raise ValueError("Conversation text exceeds the 10 MB safety limit")
        validated.append({"role": role, "content": content})
    return validated


def describe_network_error(error: Exception) -> str:
    """Preserve useful HTTP and connection diagnostics for users and logs."""
    if isinstance(error, urllib.error.HTTPError):
        detail = ""
        try:
            detail = error.read().decode("utf-8", errors="replace").strip()
        except OSError:
            pass
        suffix = f": {detail}" if detail else ""
        return f"HTTP {error.code} {error.reason}{suffix}"
    if isinstance(error, urllib.error.URLError):
        return f"Connection failed: {error.reason}"
    return str(error) or error.__class__.__name__


def _system_check(root: tk.Tk) -> Optional[str]:
    def _version_tuple(v):
        filled = []
        for point in v.split("."):
            filled.append(point.zfill(8))
        return tuple(filled)

    if platform.system().lower() == "darwin":
        version = platform.mac_ver()[0]
        if version and 14 <= float(version) < 15:
            tcl_version = root.tk.call("info", "patchlevel")
            if _version_tuple(tcl_version) <= _version_tuple("8.6.12"):
                return (
                    "Warning: Tkinter Responsiveness Issue Detected\n\n"
                    "You may experience unresponsive GUI elements when "
                    "your cursor is inside the window during startup. "
                    "This is a known issue with Tcl/Tk versions 8.6.12 "
                    "and older on macOS Sonoma.\n\nTo resolve this:\n"
                    "Update to Python 3.11.7+ or 3.12+\n"
                    "Or install Tcl/Tk 8.6.13 or newer separately\n\n"
                    "Temporary workaround: Move your cursor out of "
                    "the window and back in if elements become unresponsive.\n\n"
                    "For more information, visit: https://github.com/python/cpython/issues/110218"
                )
    return None


def resolve_piper_bin() -> str:
    if os.path.exists(DEFAULT_PIPER_BIN) and os.access(DEFAULT_PIPER_BIN, os.X_OK):
        return DEFAULT_PIPER_BIN
    p = shutil.which(FALLBACK_PIPER_BIN)
    if p:
        return p
    return DEFAULT_PIPER_BIN


def _spawn_with_logger(cmd, **popen_kwargs):
    p = subprocess.Popen(cmd, **popen_kwargs)
    if DEBUG_LOG and popen_kwargs.get("stderr") == subprocess.PIPE:
        def _pump(proc, label):
            try:
                for line in iter(proc.stderr.readline, b''):
                    sys.stderr.write(f'[{label}] {line.decode(errors="ignore")}')
            except Exception:
                pass
        t = threading.Thread(target=_pump, args=(p, cmd[0]), daemon=True)
        t.start()
    return p


def _extract_sentences(buffer: str) -> Tuple[List[str], str]:
    """
    Given a growing buffer, return (sentences, remainder).
    Sentences include their delimiter.
    """
    if not buffer:
        return [], ""

    out: List[str] = []
    last_end = 0
    for m in _SENTENCE_SPLIT_RE.finditer(buffer):
        s = m.group(1)
        if s is not None:
            out.append(s)
            last_end = m.end()

    remainder = buffer[last_end:] if last_end > 0 else buffer
    return out, remainder


def _strip_markdown(text: str) -> str:
    """
    Transparent markdown sanitization:
    remove formatting tokens but keep readable words and punctuation.
    """
    t = text or ""
    if not t.strip():
        return ""

    # Remove fenced code blocks
    t = re.sub(r"```.*?```", " ", t, flags=re.DOTALL)
    # Remove inline code
    t = re.sub(r"`([^`]*)`", r"\1", t)
    # Bold/italic markers
    t = re.sub(r"\*\*(.*?)\*\*", r"\1", t)
    t = re.sub(r"\*(.*?)\*", r"\1", t)
    t = re.sub(r"__(.*?)__", r"\1", t)
    t = re.sub(r"_(.*?)_", r"\1", t)

    # Markdown links: [text](url) -> text
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)

    # Headings/bullets
    t = re.sub(r"^\s*#+\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.MULTILINE)

    # Collapse whitespace
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)

    return t.strip()


class PiperSpeaker:
    """
    Piper -> optional SoX pitch -> aplay speaker with:
    - serialized playback queue (single worker thread)
    - start/stop
    - last_error for GUI diagnostics
    - in-memory JSON caching per model_path
    """

    def __init__(self, piper_bin: Optional[str] = None):
        self.piper_bin = piper_bin or resolve_piper_bin()

        self._lock = threading.Lock()
        self._procs: List[subprocess.Popen] = []
        self._aplay_proc: Optional[subprocess.Popen] = None
        self._stop_event = threading.Event()
        self._shutdown_event = threading.Event()
        self._last_error: str = ""

        # Sentence queue + worker (serialized consumer)
        self._queue: "queue.Queue[Optional[Tuple[str, str, int]]]" = queue.Queue()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

        # JSON cache
        self._voice_json_cache: Dict[str, dict] = {}

    def set_error(self, msg: str) -> None:
        with self._lock:
            self._last_error = msg

    def get_last_error(self, clear: bool = True) -> str:
        with self._lock:
            msg = self._last_error
            if clear:
                self._last_error = ""
            return msg

    def is_speaking(self) -> bool:
        with self._lock:
            return self._aplay_proc is not None and self._aplay_proc.poll() is None

    def stop(self) -> None:
        """
        Stops current playback and clears pending queue items.
        """
        self._stop_event.set()

        # Clear queued sentences
        try:
            while True:
                _ = self._queue.get_nowait()
        except queue.Empty:
            pass

        # Kill current pipeline
        with self._lock:
            for p in self._procs:
                try:
                    if p and p.poll() is None:
                        p.kill()
                except Exception:
                    pass
            self._procs.clear()
            self._aplay_proc = None

    def begin_session(self) -> None:
        """Allow speech to resume after a previous Stop operation."""
        self._stop_event.clear()

    def shutdown(self) -> None:
        """Stop playback and terminate the speech worker cleanly."""
        self.stop()
        self._shutdown_event.set()
        self._queue.put(None)
        if self._worker.is_alive() and threading.current_thread() is not self._worker:
            self._worker.join(timeout=2.0)

    @staticmethod
    def _sanitize_text_basic(text: str) -> str:
        t = (text or "").strip()
        if not t:
            return ""
        t = "\n".join([line.strip() for line in t.splitlines()])
        t = t.replace("\r", "")
        return t

    def _load_voice_json_cached(self, model_path: str) -> dict:
        with self._lock:
            if model_path in self._voice_json_cache:
                return self._voice_json_cache[model_path]

        cfg_path = model_path + ".json"  # expects: *.onnx.json
        if not os.path.exists(cfg_path):
            raise FileNotFoundError(f"Missing voice JSON: {cfg_path}")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        with self._lock:
            self._voice_json_cache[model_path] = cfg
        return cfg

    def get_voice_sample_rate(self, model_path: str) -> int:
        """Return a validated Piper sample rate from current or legacy metadata."""
        cfg = self._load_voice_json_cached(model_path)
        audio = cfg.get("audio")
        sample_rate = audio.get("sample_rate") if isinstance(audio, dict) else None
        if sample_rate is None:
            sample_rate = cfg.get("sample_rate")
        if sample_rate is None:
            raise ValueError(f"Voice configuration has no sample rate: {model_path}.json")
        try:
            sample_rate = int(sample_rate)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Voice configuration has an invalid sample rate: {sample_rate!r}"
            ) from error
        if not 8000 <= sample_rate <= 192000:
            raise ValueError(f"Voice sample rate is outside the supported range: {sample_rate} Hz")
        return sample_rate

    def _validate_runtime(self, model_path: str, pitch_cents: int) -> int:
        issues = []
        if (not os.path.exists(self.piper_bin)) and (shutil.which(self.piper_bin) is None):
            issues.append(f"Piper binary not found: {self.piper_bin}")
        if shutil.which("aplay") is None:
            issues.append("aplay not found (install alsa-utils)")
        if pitch_cents != 0 and shutil.which("sox") is None:
            issues.append("SoX not found (required for the selected timbre)")
        if not model_path or not os.path.isfile(model_path):
            issues.append(f"Piper voice model not found: {model_path or '[none selected]'}")
        elif not os.path.isfile(model_path + ".json"):
            issues.append(f"Piper voice configuration not found: {model_path}.json")
        if issues:
            raise RuntimeError("Speech requirements are not ready:\n - " + "\n - ".join(issues))

        return self.get_voice_sample_rate(model_path)

    def enqueue_sentence(self, text: str, model_path: str, pitch_cents: int = 0) -> None:
        """
        Public API: enqueue sanitized sentence for serialized playback.
        """
        t = self._sanitize_text_basic(text)
        if not t:
            return

        # markdown sanitization (transparent)
        t = _strip_markdown(t)
        if not t:
            return

        self._queue.put((t, model_path, int(pitch_cents)))

    def _worker_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                item = self._queue.get()
                if item is None:
                    break
                text, model_path, pitch_cents = item
                # If stop was requested, drop items until cleared and reset stop flag
                if self._stop_event.is_set():
                    self._stop_event.clear()
                    continue
                self._speak_blocking(text, model_path=model_path, pitch_cents=pitch_cents)
            except Exception as e:
                self.set_error(str(e))
                sys.stderr.write(f"[PiperSpeaker] ERROR: {e}\n")

    def _speak_blocking(self, text: str, model_path: str, pitch_cents: int = 0) -> None:
        """
        Blocking speak of a single sentence.
        Called only by the worker thread to guarantee serialization.
        """
        self.set_error("")

        sample_rate = self._validate_runtime(model_path, pitch_cents)

        # Piper: raw PCM -> stdout
        piper_cmd = [
            self.piper_bin,
            "--model", model_path,
            "--length-scale", "1.0",
            "--output-raw",
        ]
        p1 = _spawn_with_logger(
            piper_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Optional SoX pitch stage
        pcm_source = p1.stdout
        p2 = None
        if pitch_cents != 0:
            sox_cmd = [
                "sox",
                "-t", "raw",
                "-r", str(sample_rate),
                "-e", "signed",
                "-b", "16",
                "-c", "1",
                "-L",
                "-",
                "-t", "raw",
                "-",
                "gain", "-3",
                "pitch", str(int(pitch_cents)),
            ]
            p2 = _spawn_with_logger(
                sox_cmd,
                stdin=p1.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            pcm_source = p2.stdout

        # aplay sink
        aplay_cmd = [
            "aplay",
            "-r", str(sample_rate),
            "-f", "S16_LE",
            "-t", "raw",
            "-",
        ]
        p3 = _spawn_with_logger(
            aplay_cmd,
            stdin=pcm_source,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        with self._lock:
            self._procs = [p for p in (p1, p2, p3) if p is not None]
            self._aplay_proc = p3

        # Feed Piper (newline helps)
        if p1.stdin:
            try:
                payload = (text.strip() + "\n").encode("utf-8")
                p1.stdin.write(payload)
            finally:
                try:
                    p1.stdin.close()
                except Exception:
                    pass

        # Wait for aplay or stop request
        try:
            while True:
                if self._stop_event.is_set():
                    break
                rc = p3.poll()
                if rc is not None:
                    break
                time.sleep(0.03)
        finally:
            with self._lock:
                for p in self._procs:
                    try:
                        if p and p.poll() is None:
                            p.kill()
                    except Exception:
                        pass
                self._procs.clear()
                self._aplay_proc = None


class OllamaInterface:
    chat_box: tk.Text
    user_input: tk.Text
    host_input: ttk.Entry
    progress: ttk.Progressbar
    stop_button: ttk.Button
    send_button: ttk.Button
    refresh_button: ttk.Button
    download_button: ttk.Button
    delete_button: ttk.Button
    model_select: ttk.Combobox
    log_textbox: tk.Text
    models_list: tk.Listbox

    def __init__(self, root: tk.Tk):
        self.root: tk.Tk = root
        self.settings = load_settings()
        self.api_url: str = str(self.settings.get("ollama_host", "http://127.0.0.1:11434"))
        self.chat_history: List[dict] = []
        self.label_widgets: List[tk.Label] = []
        self.default_font: str = font.nametofont("TkTextFont").actual()["family"]

        self._ui_alive: bool = True
        self._request_active: bool = False
        self.stop_event: Event = Event()
        self.net_timeout: int = 30

        self.piper = PiperSpeaker()
        self.voice_models = discover_voice_models()
        self.speech_enabled = tk.BooleanVar(value=False)
        saved_voice_path = str(self.settings.get("voice_model", ""))
        saved_voice_label = next(
            (label for label, path in self.voice_models.items() if path == saved_voice_path),
            "",
        )
        if not saved_voice_label:
            saved_voice_label = next(
                (label for label in self.voice_models if "Joe" in label),
                next(iter(self.voice_models), "No Piper voices found"),
            )
        self.voice_var = tk.StringVar(value=saved_voice_label)
        saved_timbre = str(self.settings.get("timbre", "Normal"))
        self.timbre_var = tk.StringVar(
            value=saved_timbre if saved_timbre in TIMBRE_PRESETS else "Normal"
        )
        self.piper_model_var = tk.StringVar(
            value=self.voice_models.get(saved_voice_label, "")
        )

        self.layout = LayoutManager(self)
        self.layout.init_layout()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.root.after(200, self.check_system)
        self.refresh_models()

    def ui(self, fn: Callable[..., Any], *args, **kwargs) -> None:
        if not self._ui_alive:
            return
        try:
            self.root.after(0, lambda: fn(*args, **kwargs))
        except Exception:
            pass

    def ui_sync(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        done = Event()
        result: Dict[str, Any] = {}

        def _runner():
            try:
                result["value"] = fn(*args, **kwargs)
            except Exception as e:
                result["error"] = e
            finally:
                done.set()

        if not self._ui_alive:
            return None

        try:
            self.root.after(0, _runner)
        except Exception:
            return None

        if not done.wait(timeout=5.0):
            raise RuntimeError("Timed out waiting for the Tkinter main thread")

        if "error" in result:
            raise result["error"]
        return result.get("value")

    def on_close(self):
        self.persist_settings()
        self._ui_alive = False
        try:
            self.stop_event.set()
        except Exception:
            pass
        try:
            self.piper.shutdown()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def copy_text(self, text: str):
        if text:
            self.chat_box.clipboard_clear()
            self.chat_box.clipboard_append(text)

    def copy_all(self):
        self.copy_text(pprint.pformat(self.chat_history))

    @staticmethod
    def open_homepage():
        webbrowser.open("https://github.com/drericflores/ollama-speak")

    def show_help(self):
        voice_model = self.piper_model_var.get()
        try:
            sample_rate = f"{self.piper.get_voice_sample_rate(voice_model)} Hz"
        except (OSError, ValueError, json.JSONDecodeError) as error:
            sample_rate = f"Unavailable ({error})"
        info = (
            "Project: Ollama Speak\n"
            f"Version: {__version__}\n"
            f"Revision Date: {__revision_date__}\n\n"
            "Contributors:\n"
            " - chyok (Original Author)\n"
            " - Dr. Eric O. Flores (Enhancements / Revisions)\n\n"
            "Speech:\n"
            f" - Piper binary: {self.piper.piper_bin}\n"
            f" - Voice model: {voice_model}\n"
            f" - Sample rate: {sample_rate}\n"
            f" - Timbre: {self.timbre_var.get()}\n\n"
            "Streaming speech behavior:\n"
            " - Speaks sentence-by-sentence during streaming\n"
            " - Uses serialized playback worker (no audio collisions)\n\n"
            "Keys:\n"
            " <Enter>: send\n"
            " <Shift+Enter>: new line\n"
            " <Double click dialog>: edit dialog\n"
        )
        messagebox.showinfo("About", info, parent=self.root)

    def show_about(self):
        self.show_help()

    def persist_settings(self) -> None:
        settings = {
            "ollama_host": self.api_url,
            "model": self.model_select.get() if hasattr(self, "model_select") else "",
            "voice_model": self.piper_model_var.get(),
            "timbre": self.timbre_var.get(),
        }
        try:
            save_settings(settings)
        except OSError as error:
            sys.stderr.write(f"[Settings] ERROR: {error}\n")

    def check_system(self):
        message = _system_check(self.root)
        if message is not None:
            messagebox.showwarning("Warning", message, parent=self.root)

    def append_text_to_chat(self, text: str, *args, use_label: bool = False):
        self.chat_box.config(state=tk.NORMAL)
        if use_label:
            cur_label_widget = self.label_widgets[-1]
            cur_label_widget.config(text=cur_label_widget.cget("text") + text)
        else:
            self.chat_box.insert(tk.END, text, *args)
        self.chat_box.see(tk.END)
        self.chat_box.config(state=tk.DISABLED)

    def append_log_to_inner_textbox(self, message: Optional[str] = None, clear: bool = False):
        if self.log_textbox.winfo_exists():
            self.log_textbox.config(state=tk.NORMAL)
            if clear:
                self.log_textbox.delete(1.0, tk.END)
            elif message:
                self.log_textbox.insert(tk.END, message + "\n")
            self.log_textbox.config(state=tk.DISABLED)
            self.log_textbox.see(tk.END)

    def resize_inner_text_widget(self, event: tk.Event):
        for i in self.label_widgets:
            current_width = event.widget.winfo_width()
            max_width = int(current_width) * 0.7
            i.config(wraplength=max_width)

    def show_error(self, text):
        self.model_select.set(text)
        self.model_select.config(foreground="red")
        self.model_select["values"] = []
        self.send_button.state(["disabled"])

    def show_process_bar(self):
        self.progress.grid(row=0, column=0, sticky="nsew")
        self.stop_button.grid(row=0, column=1, padx=20)
        self.progress.start(5)

    def hide_process_bar(self):
        self.progress.stop()
        self.stop_button.grid_remove()
        self.progress.grid_remove()

    def request_stop(self):
        # stops both LLM streaming AND current/queued speech
        self.stop_event.set()
        try:
            self.piper.stop()
        except Exception:
            pass
        try:
            self.stop_button.state(["disabled"])
        except Exception:
            pass

    def prepare_new_request(self):
        self.stop_event.clear()
        self.piper.begin_session()
        try:
            self.stop_button.state(["!disabled"])
        except Exception:
            pass

    def handle_key_press(self, event: tk.Event):
        if event.keysym == "Return":
            if event.state & 0x1 == 0x1:
                self.user_input.insert("end", "\n")
            elif "disabled" not in self.send_button.state():
                self.on_send_button(event)
            return "break"

    def refresh_models(self):
        self.update_host()
        self.model_select.config(foreground="black")
        self.model_select.set("Waiting...")
        self.send_button.state(["disabled"])
        self.refresh_button.state(["disabled"])
        Thread(target=self.update_model_select, daemon=True).start()

    def update_host(self):
        host = self.host_input.get().strip()
        if host:
            self.api_url = host.rstrip("/")
            self.persist_settings()

    def update_model_select(self):
        try:
            models = self.fetch_models()

            def _apply_models():
                self.model_select["values"] = models
                if models:
                    preferred = str(self.settings.get("model", ""))
                    self.model_select.set(preferred if preferred in models else models[0])
                    self.send_button.state(["!disabled"])
                else:
                    self.show_error("You need download a model!")

            self.ui(_apply_models)

        except (OSError, ValueError, json.JSONDecodeError) as error:
            detail = describe_network_error(error)
            sys.stderr.write(f"[Ollama models] ERROR: {detail}\n")
            self.ui(self.show_error, f"Model refresh failed: {detail}")
        finally:
            self.ui(lambda: self.refresh_button.state(["!disabled"]))

    def update_model_list(self):
        try:
            models = self.fetch_models()

            def _populate():
                if self.models_list.winfo_exists():
                    self.models_list.delete(0, tk.END)
                    for model in models:
                        self.models_list.insert(tk.END, model)

            self.ui(_populate)

        except (OSError, ValueError, json.JSONDecodeError) as error:
            detail = describe_network_error(error)
            sys.stderr.write(f"[Ollama models] ERROR: {detail}\n")
            self.ui(self.append_log_to_inner_textbox, f"Model refresh failed: {detail}")

    def _update_voice_model_from_ui(self):
        key = (self.voice_var.get() or "").strip()
        model = self.voice_models.get(key, "")
        self.piper_model_var.set(model)

    def on_model_changed(self, _=None):
        self.persist_settings()

    def _get_pitch_cents(self) -> int:
        return int(TIMBRE_PRESETS.get(self.timbre_var.get(), 0))

    def on_toggle_speech(self):
        if not self.speech_enabled.get():
            try:
                self.piper.stop()
            except Exception:
                pass
            return

        try:
            self._update_voice_model_from_ui()
            model_path = self.piper_model_var.get()
            pitch_cents = self._get_pitch_cents()
            _ = self.piper._validate_runtime(model_path, pitch_cents)
        except Exception as e:
            self.speech_enabled.set(False)
            messagebox.showerror(
                "Speech Not Ready",
                "Speech could not be enabled.\n\n"
                f"Reason:\n{e}\n\n"
                "Verify:\n"
                f" - Piper exists: {self.piper.piper_bin}\n"
                f" - Model exists: {self.piper_model_var.get()}\n"
                f" - JSON exists: {self.piper_model_var.get()}.json\n"
                " - 'aplay' exists (alsa-utils)\n"
                " - 'sox' exists (required for Tenor presets)\n",
                parent=self.root
            )

    def on_voice_changed(self, _=None):
        self._update_voice_model_from_ui()
        self.persist_settings()
        if self.speech_enabled.get():
            self.on_toggle_speech()

    def on_timbre_changed(self, _=None):
        self.persist_settings()
        if self.speech_enabled.get():
            self.on_toggle_speech()

    def test_voice(self):
        self._update_voice_model_from_ui()
        model_path = self.piper_model_var.get()
        if not model_path:
            messagebox.showerror(
                "Voice Test", "No complete Piper voice model was discovered.", parent=self.root
            )
            return

        locale = Path(model_path).name[:5]
        samples = {
            "de_DE": "Die Sprachausgabe von Ollama Speak funktioniert einwandfrei.",
            "en_US": "Ollama Speak voice testing is operational.",
            "es_MX": "La síntesis de voz de Ollama Speak funciona correctamente.",
            "es_ES": "La síntesis de voz de Ollama Speak funciona correctamente.",
            "it_IT": "La sintesi vocale di Ollama Speak funziona correttamente.",
        }
        try:
            pitch_cents = self._get_pitch_cents()
            self.piper._validate_runtime(model_path, pitch_cents)
            self.piper.stop()
            self.piper.begin_session()
            self.piper.enqueue_sentence(
                samples.get(locale, "Ollama Speak voice testing is operational."),
                model_path=model_path,
                pitch_cents=pitch_cents,
            )
        except Exception as error:
            messagebox.showerror("Voice Test Failed", str(error), parent=self.root)

    def stop_speaking(self):
        try:
            self.piper.stop()
        except Exception:
            pass

    def on_send_button(self, _=None):
        if self._request_active:
            return
        message = self.user_input.get("1.0", "end-1c")
        if message:
            self._request_active = True
            self.prepare_new_request()
            self.send_button.state(["disabled"])
            self.refresh_button.state(["disabled"])

            model_name = self.model_select.get()
            speech_enabled = bool(self.speech_enabled.get())
            self._update_voice_model_from_ui()
            model_path = self.piper_model_var.get()
            pitch_cents = self._get_pitch_cents()

            self.layout.create_inner_label(on_right_side=True, msg_index=len(self.chat_history))
            self.append_text_to_chat(f"{message}", use_label=True)
            self.append_text_to_chat("\n\n")
            self.user_input.delete("1.0", "end")
            self.chat_history.append({"role": "user", "content": message})
            history_snapshot = [dict(item) for item in self.chat_history]
            Thread(
                target=self.generate_ai_response,
                args=(model_name, history_snapshot, speech_enabled, model_path, pitch_cents),
                daemon=True,
            ).start()

    def generate_ai_response(
        self,
        model_name: str,
        history_snapshot: List[dict],
        speech_enabled: bool,
        model_path: str,
        pitch_cents: int,
    ):
        ai_message = ""
        stream_buffer = ""  # <-- sentence buffer interception
        try:
            self.ui_sync(self.show_process_bar)
            self.ui(self.append_text_to_chat, f"{model_name}\n", ("Bold",))

            self.ui_sync(lambda: self.layout.create_inner_label(on_right_side=False, msg_index=len(self.chat_history)))

            for chunk in self.fetch_chat_stream_result(model_name, history_snapshot):
                if self.stop_event.is_set():
                    break

                # UI streaming
                self.ui(self.append_text_to_chat, f"{chunk}", use_label=True)
                ai_message += chunk

                # Sentence-level buffer interception (stream -> sentences)
                if speech_enabled:
                    stream_buffer += chunk

                    sentences, stream_buffer = _extract_sentences(stream_buffer)
                    for s in sentences:
                        self.piper.enqueue_sentence(s, model_path=model_path, pitch_cents=pitch_cents)

                    # Soft flush if model goes on without punctuation
                    if len(stream_buffer) > _MAX_BUFFER_BEFORE_SOFT_FLUSH:
                        # flush a safe chunk (not ideal, but avoids long silence)
                        soft = stream_buffer.strip()
                        stream_buffer = ""
                        if soft:
                            self.piper.enqueue_sentence(soft, model_path=model_path, pitch_cents=pitch_cents)

            # End-of-stream handling
            if self.stop_event.is_set():
                if ai_message.strip():
                    self.chat_history.append({"role": "assistant", "content": ai_message})
                self.ui(self.append_text_to_chat, "\n\n[Stopped]\n\n", ("Error",))
            else:
                self.chat_history.append({"role": "assistant", "content": ai_message})
                self.ui(self.append_text_to_chat, "\n\n")

                # Flush remainder fragment at end (if any)
                if speech_enabled:
                    rem = (stream_buffer or "").strip()
                    if rem:
                        self.piper.enqueue_sentence(rem, model_path=model_path, pitch_cents=pitch_cents)

                # Check speech worker error (async)
                def _check_speech_error():
                    err = self.piper.get_last_error(clear=True)
                    if err:
                        messagebox.showerror(
                            "Speech Error",
                            "Speech failed.\n\n"
                            f"{err}\n\n"
                            "Common causes:\n"
                            " - Piper path wrong\n"
                            " - Voice model/.json missing\n"
                            " - 'aplay' missing\n"
                            " - 'sox' missing (Tenor presets)\n",
                            parent=self.root
                        )
                self.ui(lambda: self.root.after(350, _check_speech_error))

        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
            detail = describe_network_error(error)
            sys.stderr.write(f"[Ollama chat] ERROR: {detail}\n")
            self.ui(self.append_text_to_chat, f"\nAI error: {detail}\n\n", ("Error",))
        finally:
            def _finish_request():
                self._request_active = False
                self.hide_process_bar()
                self.send_button.state(["!disabled"])
                self.refresh_button.state(["!disabled"])
                self.stop_button.state(["!disabled"])
            self.ui(_finish_request)

    def fetch_models(self) -> List[str]:
        with urllib.request.urlopen(
            urllib.parse.urljoin(self.api_url, "/api/tags"),
            timeout=self.net_timeout,
        ) as response:
            return filter_chat_models(json.load(response))

    def fetch_chat_stream_result(
        self, model_name: str, messages: List[dict]
    ) -> Generator[str, None, None]:
        request = urllib.request.Request(
            urllib.parse.urljoin(self.api_url, "/api/chat"),
            data=json.dumps(
                {
                    "model": model_name,
                    "messages": messages,
                    "stream": True,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.net_timeout) as resp:
            for line_number, line in enumerate(resp, start=1):
                if self.stop_event.is_set():
                    break
                content = parse_chat_stream_line(line, line_number)
                if content is not None:
                    yield content

    def delete_model(self, model_name: str):
        self.ui(self.append_log_to_inner_textbox, clear=True)
        if not model_name:
            return
        req = urllib.request.Request(
            urllib.parse.urljoin(self.api_url, "/api/delete"),
            data=json.dumps({"name": model_name}).encode("utf-8"),
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.net_timeout) as response:
                if response.status == 200:
                    self.ui(self.append_log_to_inner_textbox, "Model deleted successfully.")
                elif response.status == 404:
                    self.ui(self.append_log_to_inner_textbox, "Model not found.")
                else:
                    self.ui(self.append_log_to_inner_textbox, f"Delete returned status: {response.status}")
        except Exception as e:
            self.ui(self.append_log_to_inner_textbox, f"Failed to delete model: {e}")
        finally:
            Thread(target=self.update_model_list, daemon=True).start()
            Thread(target=self.update_model_select, daemon=True).start()

    def download_model(self, model_name: str, insecure: bool = False):
        self.ui(self.append_log_to_inner_textbox, clear=True)
        if not model_name:
            return
        self.ui(lambda: self.download_button.state(["disabled"]))
        req = urllib.request.Request(
            urllib.parse.urljoin(self.api_url, "/api/pull"),
            data=json.dumps({"name": model_name, "insecure": insecure, "stream": True}).encode("utf-8"),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.net_timeout) as response:
                for line in response:
                    if self.stop_event.is_set():
                        self.ui(self.append_log_to_inner_textbox, "Download stopped.")
                        break
                    data = json.loads(line.decode("utf-8"))
                    log = data.get("error") or data.get("status") or "No response"
                    if "status" in data:
                        total = data.get("total")
                        completed = data.get("completed", 0)
                        if total:
                            log += f" [{completed}/{total}]"
                    self.ui(self.append_log_to_inner_textbox, log)
        except Exception as e:
            self.ui(self.append_log_to_inner_textbox, f"Failed to download model: {e}")
        finally:
            Thread(target=self.update_model_list, daemon=True).start()
            Thread(target=self.update_model_select, daemon=True).start()

            def _reenable():
                if self.download_button.winfo_exists():
                    self.download_button.state(["!disabled"])
            self.ui(_reenable)

    def clear_chat(self):
        for i in self.label_widgets:
            i.destroy()
        self.label_widgets.clear()
        self.chat_box.config(state=tk.NORMAL)
        self.chat_box.delete(1.0, tk.END)
        self.chat_box.config(state=tk.DISABLED)
        self.chat_history.clear()

    def save_chat(self):
        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Save Chat As",
        )
        if filepath:
            target = Path(filepath)
            temporary = target.with_name(target.name + ".tmp")
            try:
                temporary.write_text(
                    json.dumps(self.chat_history, indent=2) + "\n", encoding="utf-8"
                )
                temporary.replace(target)
            except (OSError, TypeError, ValueError) as error:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                messagebox.showerror(
                    "Save Conversation Failed", str(error), parent=self.root
                )

    def load_chat(self):
        filepath = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Load Chat",
        )
        if not filepath:
            return
        try:
            path = Path(filepath)
            if path.stat().st_size > 20_000_000:
                raise ValueError("Conversation file exceeds the 20 MB safety limit")
            history = validate_chat_history(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror(
                "Load Conversation Failed", str(error), parent=self.root
            )
            return

        self.clear_chat()
        self.chat_history = history
        for idx, message in enumerate(self.chat_history):
            if message["role"] != "user":
                self.append_text_to_chat(f"{self.model_select.get()}\n", ("Bold",))
                self.layout.create_inner_label(on_right_side=False, msg_index=idx)
            else:
                self.layout.create_inner_label(on_right_side=True, msg_index=idx)
            self.append_text_to_chat(message["content"], use_label=True)
            self.append_text_to_chat("\n\n")


class LayoutManager:
    def __init__(self, interface: OllamaInterface):
        self.interface: OllamaInterface = interface
        self.management_window: Optional[tk.Toplevel] = None
        self.editor_window: Optional[tk.Toplevel] = None

    def init_layout(self):
        self._header_frame()
        self._chat_container_frame()
        self._processbar_frame()
        self._input_frame()

    def _header_frame(self):
        header_frame = ttk.Frame(self.interface.root)
        header_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=20)

        model_select = ttk.Combobox(header_frame, state="readonly", width=30)
        model_select.grid(row=0, column=0)
        model_select.bind("<<ComboboxSelected>>", self.interface.on_model_changed)

        settings_button = ttk.Button(header_frame, text="⚙️", command=self.show_model_management_window, width=3)
        settings_button.grid(row=0, column=1, padx=(5, 0))

        refresh_button = ttk.Button(header_frame, text="Refresh", command=self.interface.refresh_models)
        refresh_button.grid(row=0, column=2, padx=(5, 10))

        speech_chk = ttk.Checkbutton(
            header_frame,
            text="Speech",
            variable=self.interface.speech_enabled,
            command=self.interface.on_toggle_speech
        )
        speech_chk.grid(row=0, column=3, padx=(0, 8), sticky="w")

        voice_select = ttk.Combobox(
            header_frame,
            state="readonly",
            width=38,
            textvariable=self.interface.voice_var,
            values=list(self.interface.voice_models.keys())
        )
        voice_select.grid(row=1, column=0, columnspan=2, padx=(0, 8), pady=(8, 0), sticky="w")
        voice_select.bind("<<ComboboxSelected>>", self.interface.on_voice_changed)

        timbre_select = ttk.Combobox(
            header_frame,
            state="readonly",
            width=16,
            textvariable=self.interface.timbre_var,
            values=list(TIMBRE_PRESETS.keys())
        )
        if self.interface.timbre_var.get() not in TIMBRE_PRESETS:
            self.interface.timbre_var.set("Normal")
        timbre_select.grid(row=1, column=2, padx=(0, 8), pady=(8, 0), sticky="w")
        timbre_select.bind("<<ComboboxSelected>>", self.interface.on_timbre_changed)

        stop_speak_btn = ttk.Button(header_frame, text="Stop Speaking", command=self.interface.stop_speaking)
        stop_speak_btn.grid(row=1, column=3, padx=(0, 10), pady=(8, 0))

        test_voice_btn = ttk.Button(header_frame, text="Test Voice", command=self.interface.test_voice)
        test_voice_btn.grid(row=1, column=4, padx=(0, 10), pady=(8, 0))

        ttk.Label(header_frame, text="Host:").grid(row=1, column=5, padx=(10, 0), pady=(8, 0))

        host_input = ttk.Entry(header_frame, width=24)
        host_input.grid(row=1, column=6, padx=(5, 0), pady=(8, 0))
        host_input.insert(0, self.interface.api_url)

        self.interface.model_select = model_select
        self.interface.refresh_button = refresh_button
        self.interface.host_input = host_input

    def _chat_container_frame(self):
        chat_frame = ttk.Frame(self.interface.root)
        chat_frame.grid(row=1, column=0, sticky="nsew", padx=20)
        chat_frame.grid_columnconfigure(0, weight=1)
        chat_frame.grid_rowconfigure(0, weight=1)

        chat_box = tk.Text(
            chat_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=(self.interface.default_font, 12),
            spacing1=5,
            highlightthickness=0,
        )
        chat_box.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(chat_frame, orient="vertical", command=chat_box.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        chat_box.configure(yscrollcommand=scrollbar.set)

        chat_box_menu = tk.Menu(chat_box, tearoff=0)
        chat_box_menu.add_command(label="Copy All", command=self.interface.copy_all)
        chat_box_menu.add_separator()
        chat_box_menu.add_command(label="Clear Chat", command=self.interface.clear_chat)
        chat_box.bind("<Configure>", self.interface.resize_inner_text_widget)

        _right_click = "<Button-2>" if platform.system().lower() == "darwin" else "<Button-3>"
        chat_box.bind(_right_click, lambda e: chat_box_menu.post(e.x_root, e.y_root))

        self.interface.chat_box = chat_box

    def _processbar_frame(self):
        process_frame = ttk.Frame(self.interface.root, height=28)
        process_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=10)

        progress = ttk.Progressbar(process_frame, mode="indeterminate", style="LoadingBar.Horizontal.TProgressbar")
        stop_button = ttk.Button(process_frame, width=5, text="Stop", command=self.interface.request_stop)

        self.interface.progress = progress
        self.interface.stop_button = stop_button

    def _input_frame(self):
        input_frame = ttk.Frame(self.interface.root)
        input_frame.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 20))
        input_frame.grid_columnconfigure(0, weight=1)

        user_input = tk.Text(input_frame, font=(self.interface.default_font, 12), height=4, wrap=tk.WORD)
        user_input.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        user_input.bind("<Return>", self.interface.handle_key_press)

        send_button = ttk.Button(input_frame, text="Send", command=self.interface.on_send_button)
        send_button.grid(row=0, column=1)
        send_button.state(["disabled"])

        menubar = tk.Menu(self.interface.root)
        self.interface.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Save Chat", command=self.interface.save_chat)
        file_menu.add_command(label="Load Chat", command=self.interface.load_chat)
        file_menu.add_separator()
        file_menu.add_command(label="Model Management", command=self.show_model_management_window)
        file_menu.add_command(label="Exit", command=self.interface.on_close)

        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Copy All", command=self.interface.copy_all)
        edit_menu.add_command(label="Clear Chat", command=self.interface.clear_chat)

        about_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="About", menu=about_menu)
        about_menu.add_command(label="Source Code", command=self.interface.open_homepage)
        about_menu.add_command(label="About", command=self.interface.show_about)

        self.interface.user_input = user_input
        self.interface.send_button = send_button

    def show_model_management_window(self):
        self.interface.update_host()

        if self.management_window and self.management_window.winfo_exists():
            self.management_window.lift()
            return

        management_window = tk.Toplevel(self.interface.root)
        management_window.title("Model Management")
        screen_width = self.interface.root.winfo_screenwidth()
        screen_height = self.interface.root.winfo_screenheight()
        x = int((screen_width / 2) - (400 / 2))
        y = int((screen_height / 2) - (500 / 2))
        management_window.geometry(f"{400}x{500}+{x}+{y}")

        management_window.grid_columnconfigure(0, weight=1)
        management_window.grid_rowconfigure(3, weight=1)

        frame = ttk.Frame(management_window)
        frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        frame.grid_columnconfigure(0, weight=1)

        model_name_input = ttk.Entry(frame)
        model_name_input.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        def _download():
            arg = model_name_input.get().strip()
            if arg.startswith("ollama run "):
                arg = arg[11:]
            self.interface.stop_event.clear()
            Thread(target=self.interface.download_model, daemon=True, args=(arg,)).start()

        def _delete():
            arg = models_list.get(tk.ACTIVE).strip()
            Thread(target=self.interface.delete_model, daemon=True, args=(arg,)).start()

        download_button = ttk.Button(frame, text="Download", command=_download)
        download_button.grid(row=0, column=1, sticky="ew")

        tips = tk.Label(frame, text="find models: https://ollama.com/library", fg="blue", cursor="hand2")
        tips.bind("<Button-1>", lambda e: webbrowser.open("https://ollama.com/library"))
        tips.grid(row=1, column=0, sticky="W", padx=(0, 5), pady=5)

        list_action_frame = ttk.Frame(management_window)
        list_action_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        list_action_frame.grid_columnconfigure(0, weight=1)
        list_action_frame.grid_rowconfigure(0, weight=1)

        models_list = tk.Listbox(list_action_frame)
        models_list.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(list_action_frame, orient="vertical", command=models_list.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        models_list.config(yscrollcommand=scrollbar.set)

        delete_button = ttk.Button(list_action_frame, text="Delete", command=_delete)
        delete_button.grid(row=0, column=2, sticky="ew", padx=(5, 0))

        log_textbox = tk.Text(management_window)
        log_textbox.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0, 10))
        log_textbox.config(state="disabled")

        self.management_window = management_window
        self.interface.log_textbox = log_textbox
        self.interface.download_button = download_button
        self.interface.delete_button = delete_button
        self.interface.models_list = models_list

        Thread(target=self.interface.update_model_list, daemon=True).start()

    def create_inner_label(self, on_right_side: bool = False, msg_index: Optional[int] = None):
        background = "#48a4f2" if on_right_side else "#eaeaea"
        foreground = "white" if on_right_side else "black"
        max_width = int(self.interface.chat_box.winfo_reqwidth()) * 0.7
        inner_label = tk.Label(
            self.interface.chat_box,
            justify=tk.LEFT,
            wraplength=max_width,
            background=background,
            highlightthickness=0,
            highlightbackground=background,
            foreground=foreground,
            padx=8,
            pady=8,
            font=(self.interface.default_font, 12),
            borderwidth=0,
        )
        self.interface.label_widgets.append(inner_label)
        self.interface.chat_box.window_create(tk.END, window=inner_label)
        if on_right_side:
            idx = self.interface.chat_box.index("end-1c").split(".")[0]
            self.interface.chat_box.tag_add("Right", f"{idx}.0", f"{idx}.end")
        return inner_label


def run():
    root = tk.Tk()
    root.title("Ollama Speak")

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    root.geometry(f"1060x600+{(screen_width - 1060) // 2}+{(screen_height - 600) // 2}")

    root.grid_columnconfigure(0, weight=1)
    root.grid_rowconfigure(1, weight=1)
    root.grid_rowconfigure(2, weight=0)
    root.grid_rowconfigure(3, weight=0)

    app = OllamaInterface(root)

    app.chat_box.tag_configure("Bold", foreground="#ff007b", font=(app.default_font, 10, "bold"))
    app.chat_box.tag_configure("Error", foreground="red")
    app.chat_box.tag_configure("Right", justify="right")

    root.mainloop()


if __name__ == "__main__":
    run()
