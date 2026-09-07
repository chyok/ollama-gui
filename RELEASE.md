# Release qualification

This checklist produces and verifies the Python source and wheel distributions
without modifying the system Python installation.

## 1. Establish a clean candidate

Run from the repository root:

```bash
git status --short
python3 -m py_compile ollama_speak.py tests/test_ollama_speak.py \
  tests/test_packaging.py
python3 -m unittest discover -s tests -v
git diff --check HEAD
```

The working tree must contain only the intended release changes, and every
test must pass.

## 2. Build distributions

Install the standards-based build frontend in an isolated pipx environment:

```bash
pipx install build
```

Build into a fresh `dist/` directory:

```bash
pyproject-build --no-isolation
```

Expected artifacts for version 1.4.0:

```text
dist/ollama_speak-1.4.0-py3-none-any.whl
dist/ollama_speak-1.4.0.tar.gz
```

Generated `build/`, `dist/`, and `*.egg-info/` paths are ignored by Git.

## 3. Inspect contents

```bash
unzip -l dist/ollama_speak-1.4.0-py3-none-any.whl
tar -tzf dist/ollama_speak-1.4.0.tar.gz | sort
```

The wheel is the installed runtime and must contain the maintained
`ollama_speak.py` module, metadata, console entry point, and license. It must
not contain tests, legacy programs, configuration, voice models, or caches.

The source distribution must contain the maintained source, project metadata,
license, current documentation, regression tests, and historical files under
`legacy/`. It must not contain build output, caches, local configuration,
Piper binaries, or voice models.

## 4. Verify metadata and archives

If the `twine` module is available, validate both distribution formats:

```bash
python3 -m twine check dist/*
```

Record immutable checksums:

```bash
sha256sum dist/ollama_speak-1.4.0-py3-none-any.whl \
  dist/ollama_speak-1.4.0.tar.gz
```

## 5. Qualify the installed wheel

Install the exact wheel using pipx:

```bash
pipx install --force dist/ollama_speak-1.4.0-py3-none-any.whl
hash -r
command -v ollama-speak
ollama-speak
```

Qualify GUI startup, Ollama response streaming, multilingual speech, timbre,
stop controls, persistence, and clean shutdown. After closing:

```bash
pgrep -af 'ollama[_-]speak'
```

No application process should remain.

## 6. Publish only after qualification

Commit and tag only after the automated and runtime matrices pass. Before
publishing, verify that the version in `pyproject.toml` matches `__version__`
in `ollama_speak.py`, the release notes are current, and no secrets, voice
models, local settings, or generated packages are staged.
