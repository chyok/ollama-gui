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

The issue affects macOS Sonoma users running applications that use Tcl/Tk versions 8.6.12 or older, including various Python versions. When the mouse cursor is inside the Tkinter window during startup, GUI elements become unresponsive to clicks.

Solution:  
Update to Tcl/Tk version 8.6.13 or newer, which fixes this problem. For Python users, this can be done by:

Using Python 3.11.7 or later, which bundles the fixed Tcl/Tk version.
Using Python 3.12 or later, which already includes the fix.
For other Python versions, installing Tcl/Tk 8.6.13+ separately (e.g., via Homebrew) and ensuring Python uses this version.

here is the issue: https://github.com/python/cpython/issues/110218

## License

This project is licensed under the [MIT License](LICENSE).

