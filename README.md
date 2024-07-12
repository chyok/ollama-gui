# Ollama-GUI

![GitHub License](https://img.shields.io/github/license/chyok/ollama-gui)
![PyPI - Version](https://img.shields.io/pypi/v/ollama-gui)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/ollama-gui)

A very simple ollama GUI, implemented using the built-in Python Tkinter library, with no additional dependencies.
Provide you with the simplest possible visual Ollama interface.

![ollama-gui-1-0-3](https://github.com/chyok/ollama-gui/assets/32629225/4a733a19-3201-4440-b6d5-eddd62294a0b)

+ one file project.
+ no external dependencies.

## Before Start

We need to set up llama service first.

Please refer to: [Ollama](https://ollama.com/)

## Run

Choose any way you like:
> **Note: If you are using a Mac and the system version is Sonoma, please refer to the Q&A at the bottom.**

### source code

`python ollama_gui.py`

### using pip

```
pip install ollama-gui
ollama-gui
```

### binary file

| Platform | Download Link                                            | 
|----------|----------------------------------------------------------|
| Windows  | [Download](https://github.com/chyok/ollama-gui/releases) |

## QA
### I'm using a Mac, why does the application sometimes not respond when I click on it?

The issue is that on macOS Sonoma, when the mouse cursor is inside the Tkinter window during its startup, the GUI elements within the window become unresponsive to clicks. This problem occurs specifically with Python 3.11 and does not affect older or newer versions of Python.

The root cause is related to changes in the Tcl/Tk library bundled with Python 3.11 on macOS. Upgrading the bundled Tcl/Tk to version 8.6.13 resolves the issue, as this version includes fixes for similar mouse event-related problems on macOS.

The solution is to update the Python 3.11 macOS installers to use the newer Tcl/Tk 8.6.13 library. This change has been merged and will be released in Python 3.11.7. Users affected by this bug can either wait for the 3.11.7 release or try using Python 3.12 or older versions like 3.10, which do not exhibit this problem.

here is the issue: https://github.com/python/cpython/issues/110218

## License

This project is licensed under the [MIT License](LICENSE).

