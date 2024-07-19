---
layout: default
---

![ollama-gui-1 2 0](https://github.com/user-attachments/assets/a4bb979b-68a4-4062-b484-7542f2a866e0)

## 🚀 Features
### v1.1.0
+ 📁 One file project.
+ 📦 No external dependencies, only **tkinter** which is usually bundled.
+ 🔍 Auto check ollama model list.
+ 🌐 Customizable ollama host support.
+ 💬 Multiple conversations.
+ 📋 Menu bar and right-click menu.
+ 🛑 Stop generating at any time.

### v1.2.0

+ 🗂️ Model Management: Download and Delete Models.
+ 🎨 UI Enhancement: Bubble dialog theme.
+ 📝 Editable Conversation History.



## 📎 Before Start

We need to set up llama service first.

Please refer to:   
+ [Ollama](https://ollama.com/)  
+ [Ollama Github](https://github.com/ollama/ollama)

## ⚙️ Run

Choose any way you like:
> **Note: If you are using a Mac and the system version is Sonoma, please refer to the Q&A at the bottom.**

### binary file

| Platform            | Download Link                                            |
| ------------------- | -------------------------------------------------------- |
| Windows             | [Download](https://github.com/chyok/ollama-gui/releases) |
| Mac (Apple Silicon) | [Download](https://github.com/chyok/ollama-gui/releases) |
| Linux               | [Download](https://github.com/chyok/ollama-gui/releases) |

### source code

```
python ollama_gui.py
```

### using pip

```
pip install ollama-gui
ollama-gui
```

## 📋 Q&A
### I'm using a Mac, why does the application sometimes not respond when I click on it?

The issue affects macOS Sonoma users running applications that use Tcl/Tk versions 8.6.12 or older, including various Python versions.  
When the mouse cursor is inside the Tkinter window during startup, GUI elements become unresponsive to clicks.

Solution:  
Update to Tcl/Tk version 8.6.13 or newer, which fixes this problem.   

For Python users, this can be done by:  
Using Python 3.11.7 or later, which bundles the fixed Tcl/Tk version.  
Using Python 3.12 or later, which already includes the fix.  
https://www.python.org/downloads/macos/

For other Python versions, installing Tcl/Tk 8.6.13+ separately (e.g., via Homebrew) and ensuring Python uses this version.

Here is the issue: https://github.com/python/cpython/issues/110218

------




### ImportError: No module named 'Tkinter'

This probably happens because the Tk library is not installed.

For Ubuntu or other distros with Apt:

```
sudo apt-get install python3-tk
```

For Fedora:

```
sudo dnf install python3-tkinter
```

For macOS:

```
brew install python-tk
```

For Windows:

make sure to **check in the Python install the optional feature "tcl/tk and IDLE"**.  

Refer to: https://stackoverflow.com/questions/25905540/importerror-no-module-named-tkinter