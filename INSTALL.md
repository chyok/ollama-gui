# Installing Ollama Speak

Ollama Speak is a Linux desktop client. Its wheel installs the application;
Ollama, Tk, Piper, ALSA, optional SoX, and voice data remain external.

## Requirements

- Linux (Pop!_OS and Ubuntu qualified)
- Python 3.10 or newer with Tk 8.6+
- Ollama running locally or reachable over HTTP
- Piper, `aplay`, and a complete Piper voice pair for speech
- SoX for Tenor and Bright Tenor presets

On Pop!_OS or Ubuntu:

```bash
sudo apt update
sudo apt install --yes python3-tk alsa-utils sox pipx
```

## Ollama

Install Ollama using its official instructions, then verify it:

```bash
systemctl is-active ollama
ollama --version
curl --fail --silent --show-error http://127.0.0.1:11434/api/tags |
  python3 -m json.tool
```

Install at least one chat/completion model. Ollama Speak intentionally excludes
embedding-only models from its model menu.

## Piper and voices

Install Piper in an isolated pipx environment:

```bash
pipx install piper-tts
hash -r
command -v piper
pipx list
```

Some Piper releases interpret `piper --version` as synthesis and report a
missing model. `pipx list` is the reliable package-version check.

Each voice needs its `.onnx` model and adjacent `.onnx.json` configuration.
Install voices per user:

```bash
voice_dir="$HOME/.local/share/piper/voices"
mkdir -p "$voice_dir"

"$HOME/.local/share/pipx/venvs/piper-tts/bin/python" \
  -m piper.download_voices \
  --download-dir "$voice_dir" \
  en_US-joe-medium \
  de_DE-thorsten-medium \
  it_IT-paola-medium \
  es_MX-ald-medium
```

Ollama Speak searches, in order:

1. `$OLLAMA_SPEAK_VOICE_DIR`, when set
2. `~/.local/share/piper/voices`
3. `/opt/piper/voices`

Verify the voice pairs:

```bash
find "$voice_dir" -maxdepth 1 -type f \
  \( -name '*.onnx' -o -name '*.onnx.json' \) -printf '%f\n' | sort
```

Voice models are separate works and may use licenses different from Ollama
Speak. Review each voice model card and license before redistribution. No voice
model is bundled in the wheel.

## Build and install

From the repository checkout:

```bash
python3 -m py_compile ollama_speak.py tests/test_ollama_speak.py
python3 -m unittest discover -s tests -v
mkdir -p build/wheels
python3 -m pip wheel --no-deps --no-build-isolation \
  --wheel-dir build/wheels .
pipx install --force build/wheels/ollama_speak-1.4.0-py3-none-any.whl
```

Run the installed command:

```bash
ollama-speak
```

Settings are stored at `$XDG_CONFIG_HOME/ollama-speak/config.json`, or
`~/.config/ollama-speak/config.json` when `XDG_CONFIG_HOME` is unset. The file
is written with mode `0600`.

## Troubleshooting

If models do not appear, confirm that the configured Ollama host responds and
that a completion-capable model is installed.

If speech cannot be enabled, verify the external components and voice pair:

```bash
command -v piper
command -v aplay
command -v sox
test -f /path/to/voice.onnx
test -f /path/to/voice.onnx.json
```

SoX may be absent with Normal timbre. Piper and `aplay` are required for all
speech. If playback is silent, inspect ALSA devices with `aplay -l` and verify
that another process is not holding the desired device.

Remove only the application with:

```bash
pipx uninstall ollama-speak
```

This does not remove Ollama, Piper, voices, or user configuration.

