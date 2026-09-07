# Ollama Speak

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

Ollama Speak is a local-first Linux desktop client for Ollama with multilingual
offline speech powered by Piper. It provides a lightweight Tk interface,
streaming chat, conversation management, completion-model filtering, and
sentence-synchronized speech without cloud TTS.

The maintained application is `ollama_speak.py`. Earlier implementations are
preserved under [`legacy/`](legacy/) for attribution and historical reference,
but are not installed by the Python package.

## Features

- Discovers chat/completion models and excludes embedding-only models
- Streams responses while keeping Tk updates on the GUI thread
- Stops generation and queued speech cleanly
- Discovers complete Piper `.onnx` and `.onnx.json` voice pairs
- Supports multilingual installed Piper voices
- Reads the correct sample rate from each voice configuration
- Provides Normal, Tenor, and Bright Tenor timbre presets
- Persists host, model, voice, and timbre in a mode-`0600` settings file
- Uses only the Python standard library at runtime

## Runtime components

| Component | Purpose | Requirement |
|---|---|---|
| Python 3.10+ and Tk | Application and desktop interface | Required |
| Ollama | Model discovery and chat generation | Required |
| Piper | Offline speech synthesis | Required for speech |
| `aplay` (`alsa-utils`) | ALSA playback | Required for speech |
| SoX | Timbre/pitch processing | Required only for Tenor presets |
| Piper voice pair | Voice model and metadata | Required for speech |

The wheel intentionally does not bundle Ollama, Piper, audio tools, or voices.

## Quick start

On Pop!_OS or Ubuntu:

```bash
sudo apt update
sudo apt install --yes python3-tk alsa-utils sox pipx
pipx install piper-tts
```

Build and install Ollama Speak:

```bash
mkdir -p build/wheels
python3 -m pip wheel --no-deps --no-build-isolation \
  --wheel-dir build/wheels .
pipx install --force build/wheels/ollama_speak-1.4.0-py3-none-any.whl
ollama-speak
```

See [INSTALL.md](INSTALL.md) for Ollama verification, voice downloads, custom
voice directories, troubleshooting, and removal.

## Development qualification

```bash
python3 -m py_compile ollama_speak.py tests/test_ollama_speak.py
python3 -m unittest discover -s tests -v
python3 -m pip wheel --no-deps --no-build-isolation \
  --wheel-dir build/wheels .
```

The wheel contains the maintained module, metadata, console entry point, and
MIT license. Tests, legacy sources, settings, build artifacts, Piper binaries,
and voices are excluded.

## Configuration

Preferences are stored at:

```text
${XDG_CONFIG_HOME:-$HOME/.config}/ollama-speak/config.json
```

Add another voice directory without changing source:

```bash
export OLLAMA_SPEAK_VOICE_DIR=/path/to/piper/voices
ollama-speak
```

## Privacy and licensing

Chat traffic stays between the application and the configured Ollama host.
Speech is synthesized locally. Ollama Speak adds no telemetry or cloud service.

Ollama Speak uses the MIT License. Piper and Piper voice models are separate
works with their own licenses; review them before redistribution.

## Credits

- Original Ollama GUI project: **chyok**
- Consolidation, reliability work, and speech integration:
  **Dr. Eric O. Flores**

See [LICENSE](LICENSE) for the full license text.
