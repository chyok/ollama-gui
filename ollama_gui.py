import json
import time
import platform
import webbrowser
import unicodedata

import urllib.parse
import urllib.request
import tkinter as tk

from tkinter import ttk, font, messagebox
from threading import Thread
from typing import Optional, List, Tuple


def _system_check(root: tk.Tk) -> Optional[str]:
    """
    Detected some system and software compatibility issues,
    and returned the information in the form of a string to alert the user

    :param root: Tk instance
    :return: None or message string
    """

    def _version_tuple(v):
        """A lazy way to avoid importing third-party libraries"""
        filled = []
        for point in v.split("."):
            filled.append(point.zfill(8))
        return tuple(filled)

    # Tcl and macOS issue: https://github.com/python/cpython/issues/110218
    if platform.system().lower() == "darwin":
        version = platform.mac_ver()[0]
        if version and 14 <= float(version) < 15:
            tcl_version = root.tk.call("info", "patchlevel")
            if _version_tuple(tcl_version) <= _version_tuple("8.6.12"):
                return ("Warning: Tkinter Responsiveness Issue Detected\n\n"
                        "You may experience unresponsive GUI elements when "
                        "your cursor is inside the window during startup. "
                        "This is a known issue with Tcl/Tk versions 8.6.12 "
                        "and older on macOS Sonoma.\n\nTo resolve this:\n"
                        "Update to Python 3.11.7+ or 3.12+\n"
                        "Or install Tcl/Tk 8.6.13 or newer separately\n\n"
                        "Temporary workaround: Move your cursor out of "
                        "the window and back in if elements become unresponsive.\n\n"
                        "For more information, visit: https://github.com/python/cpython/issues/110218")


def calculate_text_width(text: str) -> int:
    """
    Calculate the given text width.

    Tabs are counted as 8 spaces, East Asian wide characters as 2 spaces,
    and all other characters as 1 space.

    :param text: The input text to measure.
    :return: The calculated height of the text.
    """
    return sum(
        8 if char == "\t"
        else 2 if unicodedata.east_asian_width(char) in 'WF'
        else 1 for char in text
    )


def calculate_text(text: str, width: int) -> Tuple[int, int]:
    """
    Calculate the height need of the given text.


    :param text: The input text to measure.
    :param width: The input entry width.
    :return: The calculated height of the text and the max width of the text.
    """

    all_lines = text.split("\n")
    height = len(all_lines)
    max_width = 0
    for i in all_lines:
        if len(i):
            single_str_width = calculate_text_width(i)
            max_width = max(max_width, single_str_width)
            height += ((single_str_width + width - 1) // width) - 1

    return height, max_width


class OllamaInterface:
    chat_box: tk.Text
    user_input: tk.Text
    host_input: ttk.Entry
    progress: ttk.Progressbar
    stop_button: ttk.Button
    send_button: ttk.Button
    refresh_button: ttk.Button
    model_select: ttk.Combobox

    def __init__(self, root: tk.Tk):
        self.root: tk.Tk = root
        self.api_url: str = "http://127.0.0.1:11434"
        self.chat_history: List[dict] = []
        self.text_widgets: List[tk.Text] = []
        self.default_font: str = font.nametofont("TkTextFont").actual()["family"]

        LayoutManager(self).init_layout()

        self.root.after(200, self.check_system)
        self.refresh_models()

    def _copy_text(self, text):
        if text:
            self.chat_box.clipboard_clear()
            self.chat_box.clipboard_append(text)

    def copy_select(self):
        if self.chat_box.tag_ranges("sel"):
            selected_text = self.chat_box.get("sel.first", "sel.last")
            self._copy_text(selected_text)

    def copy_all(self):
        content = self.chat_box.get("1.0", tk.END)
        content = content.strip()
        self._copy_text(content)

    @staticmethod
    def open_homepage():
        webbrowser.open("https://github.com/chyok/ollama-gui")

    def show_about(self):
        info = "Project: Ollama GUI\nAuthor: chyok\nGithub: https://github.com/chyok/ollama-gui"
        messagebox.showinfo("About", info, parent=self.root)

    def check_system(self):
        message = _system_check(self.root)
        if message is not None:
            messagebox.showwarning("Warning", message, parent=self.root)

    def append_text_to_chat(self, text, *args):
        self.chat_box.config(state=tk.NORMAL)
        self.chat_box.insert(tk.END, text, *args)
        self.chat_box.see(tk.END)
        self.chat_box.config(state=tk.DISABLED)

    def create_inner_text_widget(self, on_right_side: bool = False):
        background = "#48a4f2" if on_right_side else "#eaeaea"
        foreground = "white" if on_right_side else "black"
        inner_text = tk.Text(self.chat_box, width=1, height=1,
                             wrap=tk.WORD, background=background,
                             highlightthickness=0,
                             highlightbackground=background,
                             foreground=foreground, padx=5, pady=5,
                             font=(self.default_font, 12),
                             borderwidth=0)

        self.chat_box.window_create(tk.END, window=inner_text)
        self.text_widgets.append(inner_text)
        if on_right_side:
            idx = self.chat_box.index(tk.INSERT).split(".")[0]
            self.chat_box.tag_add("Right", f"{idx}.0", f"{idx}.end")

    def _resize_text_widget(self, text_widget: tk.Text):
        limited_width = int(self.chat_box.cget("width") * 0.7)

        all_text = text_widget.get("1.0", "end-1c")
        height, width = calculate_text(all_text, limited_width)
        if height > 1:
            width = limited_width

        text_widget.config(width=width,
                           height=height)

    def append_child_text_to_chat(self, text, *args):
        self.chat_box.config(state=tk.NORMAL)
        cur_text_widget = self.text_widgets[-1]
        cur_text_widget.insert(tk.END, text)
        self._resize_text_widget(cur_text_widget)

        self.chat_box.config(state=tk.DISABLED)

    def show_process_bar(self):
        self.progress.grid(row=0, column=0, sticky="nsew")
        self.stop_button.grid(row=0, column=1, padx=20)
        self.progress.start(5)

    def hide_process_bar(self):
        self.progress.stop()
        self.stop_button.grid_remove()
        self.progress.grid_remove()

    def handle_key_press(self, event):
        if event.keysym == "Return":
            if event.state & 0x1 == 0x1:  # Shift key is pressed
                self.user_input.insert("end", "\n")
            elif "disabled" not in self.send_button.state():
                self.on_send_button(event)
            return "break"

    def refresh_models(self):
        self.model_select.config(foreground="black")
        self.model_select.set("Waiting...")
        self.send_button.state(["disabled"])
        self.refresh_button.state(["disabled"])
        self.api_url = self.host_input.get()
        Thread(target=self.fetch_models, daemon=True).start()

    def fetch_models(self):
        try:
            with urllib.request.urlopen(f"{self.api_url}/api/tags") as response:
                data = json.load(response)
                models = [model["name"] for model in data["models"]]
                self.root.after(0, self.update_model_select, models)
        except Exception:  # noqa
            self.root.after(0, self.show_error, "Error! Please check the host.")
        finally:
            self.root.after(0, lambda: self.refresh_button.state(["!disabled"]))

    def update_model_select(self, models):
        self.model_select["values"] = models
        if models:
            self.model_select.set(models[0])
            self.send_button.state(["!disabled"])
        else:
            self.show_error("You need download a model!")

    def show_error(self, text):
        self.model_select.set(text)
        self.model_select.config(foreground="red")
        self.model_select["values"] = []
        self.send_button.state(["disabled"])

    def on_send_button(self, _=None):
        message = self.user_input.get("1.0", "end-1c")
        if message:
            self.append_text_to_chat(f"You\n", ("Bold", "You", "Right"))
            self.create_inner_text_widget(on_right_side=True)

            self.append_child_text_to_chat(f"{message}")
            self.append_text_to_chat(f"\n\n")
            self.user_input.delete("1.0", "end")
            self.chat_history.append({"role": "user", "content": message})

            Thread(
                target=self.generate_ai_response,
                daemon=True,
            ).start()

    def generate_ai_response(self):
        self.show_process_bar()
        self.send_button.state(["disabled"])
        self.refresh_button.state(["disabled"])

        try:
            self.append_text_to_chat(
                f"AI ({self.model_select.get()})\n", ("Bold", "AI")
            )
            ai_message = ""
            self.create_inner_text_widget()
            for i in self._request_ollama():
                self.append_child_text_to_chat(f"{i}")
                ai_message += i
            self.chat_history.append({"role": "assistant", "content": ai_message})
            self.append_text_to_chat("\n\n")
        except Exception:  # noqa
            self.append_text_to_chat(tk.END, f"\nAI error!\n\n", ("Error",))
        finally:
            self.hide_process_bar()
            self.send_button.state(["!disabled"])
            self.refresh_button.state(["!disabled"])
            self.stop_button.state(["!disabled"])

    def _request_ollama(self):
        request = urllib.request.Request(
            f"{self.api_url}/api/chat",
            data=json.dumps(
                {
                    "model": self.model_select.get(),
                    "messages": self.chat_history,
                    "stream": True,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(request) as resp:
            for line in resp:
                if "disabled" in self.stop_button.state():  # stop
                    break
                data = json.loads(line.decode("utf-8"))
                if "message" in data:
                    time.sleep(0.01)
                    yield data["message"]["content"]

    def clear_chat(self):
        for i in self.text_widgets:
            i.destroy()
        self.chat_box.config(state=tk.NORMAL)
        self.chat_box.delete(1.0, tk.END)
        self.chat_box.config(state=tk.DISABLED)
        self.chat_history.clear()


class LayoutManager:
    """
    Manages the layout and arrangement of the OllamaInterface.

    The LayoutManager is responsible for the visual organization and positioning
    of the various components within the OllamaInterface, such as the header,
    chat container, progress bar, and input fields. It handles the sizing,
    spacing, and alignment of these elements to create a cohesive and
    user-friendly layout.
    """

    def __init__(self, interface: OllamaInterface):
        self.interface: OllamaInterface = interface

    def init_layout(self):
        self._header_frame()
        self._chat_container_frame()
        self._processbar_frame()
        self._input_frame()

    def _header_frame(self):
        header_frame = ttk.Frame(self.interface.root)
        header_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=20)
        header_frame.grid_columnconfigure(2, weight=1)

        model_select = ttk.Combobox(header_frame, state="readonly", width=30)
        model_select.grid(row=0, column=0)

        refresh_button = ttk.Button(
            header_frame, text="Refresh"
        )
        refresh_button.grid(row=0, column=1, padx=(10, 0))

        ttk.Label(header_frame, text="Host:").grid(row=0, column=3, padx=(10, 0))

        host_input = ttk.Entry(header_frame, width=24)
        host_input.grid(row=0, column=4, padx=(5, 15))
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
            chat_frame, wrap=tk.WORD, state=tk.DISABLED, font=(self.interface.default_font, 12),
            highlightthickness=0
        )
        chat_box.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(
            chat_frame, orient="vertical", command=chat_box.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")

        chat_box.configure(yscrollcommand=scrollbar.set)

        chat_box_menu = tk.Menu(chat_box, tearoff=0)
        chat_box_menu.add_command(label="Copy", command=self.interface.copy_select)
        chat_box_menu.add_command(label="Copy All", command=self.interface.copy_all)
        chat_box_menu.add_separator()
        chat_box_menu.add_command(label="Clear Chat", command=self.interface.clear_chat)

        _right_click = "<Button-2>" if platform.system().lower() == "darwin" else "<Button-3>"
        chat_box.bind(_right_click, lambda e: chat_box_menu.post(e.x_root, e.y_root))

        self.interface.chat_box = chat_box

    def _processbar_frame(self):
        process_frame = ttk.Frame(self.interface.root, height=28)
        process_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=10)

        progress = ttk.Progressbar(
            process_frame, mode="indeterminate", style="LoadingBar.Horizontal.TProgressbar"
        )

        stop_button = ttk.Button(
            process_frame,
            width=5,
            text="Stop",
            command=lambda: stop_button.state(["disabled"]),
        )

        self.interface.progress = progress
        self.interface.stop_button = stop_button

    def _input_frame(self):
        input_frame = ttk.Frame(self.interface.root)
        input_frame.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 20))
        input_frame.grid_columnconfigure(0, weight=1)

        user_input = tk.Text(
            input_frame, font=(self.interface.default_font, 12), height=4, wrap=tk.WORD
        )
        user_input.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        user_input.bind("<Key>", self.interface.handle_key_press)

        send_button = ttk.Button(
            input_frame,
            text="Send",
            command=self.interface.on_send_button,
        )
        send_button.grid(row=0, column=1)
        send_button.state(["disabled"])

        menubar = tk.Menu(self.interface.root)
        self.interface.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Exit", command=self.interface.root.quit)

        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Copy All", command=self.interface.copy_all)
        edit_menu.add_command(label="Clear Chat", command=self.interface.clear_chat)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Source Code", command=self.interface.open_homepage)
        help_menu.add_command(label="About", command=self.interface.show_about)

        self.interface.user_input = user_input
        self.interface.send_button = send_button


def run():
    root = tk.Tk()

    root.title("Ollama GUI")
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    root.geometry(f"800x600+{(screen_width - 800) // 2}+{(screen_height - 600) // 2}")

    root.grid_columnconfigure(0, weight=1)
    root.grid_rowconfigure(1, weight=1)
    root.grid_rowconfigure(2, weight=0)
    root.grid_rowconfigure(3, weight=0)

    app = OllamaInterface(root)

    app.chat_box.tag_configure("Bold", font=(app.default_font, 12, "bold"))
    app.chat_box.tag_configure("Error", foreground="red")
    app.chat_box.tag_configure("You", foreground="#007bff", font=(app.default_font, 15, "bold"))
    app.chat_box.tag_configure("AI", foreground="#ff007b", font=(app.default_font, 15, "bold"))
    app.chat_box.tag_configure("Right", justify="right")

    root.mainloop()


if __name__ == "__main__":
    run()
