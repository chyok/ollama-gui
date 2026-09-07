# Ollama GUI + Ollama Speak (Tkinter)

A lightweight, local-first desktop GUI for **Ollama** built with **Python + Tkinter**—plus an enhanced variant (**Ollama Speak**) that adds **offline speech output** so you can *listen* to model responses.

This repository is a fork of **ollama-gui** by **chyok**, with usability improvements and a speech-enabled GUI.

---

## Contents

- [Projects in This Fork](#projects-in-this-fork)
- [Key Update (02/10/2026)](#key-update-02102026)
- [Requirements](#requirements)
- [Ollama Setup](#ollama-setup)
- [Piper Setup (Speech Version)](#piper-setup-speech-version)
- [Install](#install)
- [Run](#run)
- [Using Ollama Speak](#using-ollama-speak)
- [Troubleshooting](#troubleshooting)
- [Credits](#credits)
- [License](#license)
- [Disclaimer](#disclaimer)

---

## Projects in This Fork

### 1) `ollama_gui.py` — Improved GUI
Enhancements focused on stability and usability:

- Safer cancel/stop behavior using `threading.Event`
- Network timeouts to prevent hangs
- UI thread-safety improvements for background threads
- Improved menu structure (About dialog + revision metadata)
- Keyboard behavior improvements (binds `<Return>` only to avoid breaking shortcuts)

### 2) `ollama_speak.py` — GUI With Speech Output
Adds an offline TTS pipeline (Piper + ALSA) with optional timbre adjustment:

- Speech toggle (Enable/Disable)
- **Sentence-synchronized speaking during streaming** (see update below)
- Stop Speaking button
- Voice selection (e.g., Joe/Amy)
- Optional timbre lift (e.g., “Tenor”) using **SoX pitch shift**

---

## Key Update (02/10/2026)

The speech engine is now designed for natural, low-latency streaming output:

- **Sentence-level buffering:** streaming chunks are collected until a sentence boundary (`.`, `!`, `?`, newline) is detected, then spoken as a complete thought.
- **Serialized playback:** a single background worker thread consumes a thread-safe queue so audio playback remains sequential (prevents `aplay` device-busy collisions).
- **Markdown sanitization:** formatting tokens are removed before speech so punctuation/markup is not read aloud.
- **Voice JSON caching:** model `.onnx.json` metadata (e.g., `sample_rate`) is cached in memory after first load to reduce disk I/O during streaming.

---

## Requirements

### System
- Linux recommended (Pop!_OS / Ubuntu tested)
- **Ollama** installed and running locally
- Python 3.10+ recommended

### Python
- Tkinter (usually included with system Python)
- No extra Python packages required for the GUI itself

If Tkinter is missing:

```bash
sudo apt update
sudo apt install python3-tk -y
````

### Speech Dependencies (for `ollama_speak.py`)

**Required**

* `piper` (offline TTS)
* `alsa-utils` (provides `aplay`)

**Optional (recommended)**

* `sox` (pitch/timbre presets like Tenor)

Install audio tools:

```bash
sudo apt update
sudo apt install alsa-utils sox -y
```

---

## Ollama Setup

Start the server:

```bash
ollama serve
```

Verify it responds:

```bash
curl http://127.0.0.1:11434/api/tags
```

Pull a model (example):

```bash
ollama pull llama3
```

---

## Piper Setup (Speech Version)

You need a Piper binary and at least one voice model.

### Piper binary

Examples:

* `/home/eric/.local/bin/piper` (default path in the script)
* `piper` available in `$PATH`

Verify:

```bash
command -v piper && piper --version
```

### Voice models

This fork expects voice models like:

* `/opt/piper/voices/en_US-joe-medium.onnx`
* `/opt/piper/voices/en_US-amy-low.onnx`

Each model must also have its JSON next to it:

* `en_US-joe-medium.onnx.json`
* `en_US-amy-low.onnx.json`

---

## Install

```bash
git clone <your-fork-url>
cd <repo-folder>
```

---

## Run

### Standard GUI

```bash
python3 ollama_gui.py
```

### Speech GUI

```bash
python3 ollama_speak.py
```

---

## Using Ollama Speak

1. Enable **Speech**
2. Select a voice (Joe default)
3. Ask your question
4. The GUI speaks responses **sentence-by-sentence** during streaming
5. Use **Stop Speaking** to interrupt current playback and clear queued speech

### Timbre / Tenor Presets

Tenor/bright presets use SoX pitch shifting. If you don’t have SoX:

```bash
sudo apt install sox -y
```

---

## Troubleshooting

### “I hear nothing”

* Confirm Ollama returns text normally in the GUI

* Verify `aplay` exists:

  ```bash
  command -v aplay
  ```

* Verify Piper runs:

  ```bash
  command -v piper && piper --version
  ```

* Verify your voice model and `.json` file exist at the configured path

### “ALSA device busy” or garbled audio

The speech GUI uses serialized playback to prevent collisions. If you still see this:

* Ensure no other application is holding the audio device
* Try stopping speech, then re-enabling it

### Voice sounds too deep / bass-heavy

* Use a tenor/bright preset (SoX pitch shift)
* Switch to a different Piper voice model

---

## Credits

* **Original Project:** `ollama-gui` by **chyok**
* **This Fork:** Enhancements and speech GUI additions by **Dr. Eric O. Flores**

---

## License

This fork follows the upstream license unless you explicitly change it.
Retain the original license file from the upstream repository.

---

## Disclaimer

This project is intended for local use with user-provided models and resources.
All trademarks and model names belong to their respective owners.

```
