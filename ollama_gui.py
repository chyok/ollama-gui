import sys
import json
import time
import queue
import pprint
import platform
import webbrowser

import urllib.error
import urllib.parse
import urllib.request

from threading import Thread, Event
from typing import Optional, List, Generator

try:
    import tkinter as tk
    from tkinter import ttk, font, messagebox, filedialog

except (ModuleNotFoundError, ImportError):
    print(
        "Your Python installation does not include the Tk library. \n"
        "Please refer to https://github.com/chyok/ollama-gui?tab=readme-ov-file#-qa")
    sys.exit(0)

__version__ = "1.3.0"

UI_POLL_INTERVAL = 20  # ms


def _version_tuple(v: str) -> tuple:
    """A lazy way to avoid importing third-party libraries"""
    filled = []
    for point in v.split("."):
        filled.append(point.zfill(8))
    return tuple(filled)


def _error_message(e: Exception) -> str:
    """Prefer the reason returned by Ollama: {"error": "..."}"""
    if isinstance(e, urllib.error.HTTPError):
        try:
            return json.load(e)["error"]
        except Exception:  # noqa
            pass
    return str(e)


def _system_check(root: tk.Tk) -> Optional[str]:
    """
    Detected some system and software compatibility issues,
    and returned the information in the form of a string to alert the user

    :param root: Tk instance
    :return: None or message string
    """

    # Tcl and macOS issue: https://github.com/python/cpython/issues/110218
    if platform.system().lower() == "darwin":
        # mac_ver may return "14", "14.4" or "14.4.1", so it can't be parsed as a float
        version = platform.mac_ver()[0]
        if version and _version_tuple("14") <= _version_tuple(version) < _version_tuple("15"):
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
        self.api_url: str = "http://127.0.0.1:11434"
        self.chat_history: List[dict] = []
        self.label_widgets: List[tk.Label] = []
        self.ai_label: Optional[tk.Label] = None
        self.ui_queue: queue.Queue = queue.Queue()
        self.stop_event: Event = Event()
        self.default_font: str = font.nametofont("TkTextFont").actual()["family"]

        self.layout = LayoutManager(self)
        self.layout.init_layout()

        self.root.after(200, self.check_system)
        self.root.after(UI_POLL_INTERVAL, self.process_ui_queue)
        self.refresh_models()

    def run_on_ui(self, func, *args, **kwargs):
        """
        Tkinter is not thread-safe, so the worker threads never touch
        the widgets, they queue the call and the main thread runs it.
        """
        self.ui_queue.put((func, args, kwargs))

    def drain_ui_queue(self):
        for _ in range(self.ui_queue.qsize()):
            try:
                func, args, kwargs = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            func(*args, **kwargs)

    def process_ui_queue(self):
        try:
            self.drain_ui_queue()
        finally:
            self.root.after(UI_POLL_INTERVAL, self.process_ui_queue)

    def copy_text(self, text: str):
        if text:
            self.chat_box.clipboard_clear()
            self.chat_box.clipboard_append(text)

    def copy_all(self):
        self.copy_text(pprint.pformat(self.chat_history))

    @staticmethod
    def open_homepage():
        webbrowser.open("https://github.com/chyok/ollama-gui")

    def show_help(self):
        info = ("Project: Ollama GUI\n"
                f"Version: {__version__}\n"
                "Author: chyok\n"
                "Github: https://github.com/chyok/ollama-gui\n\n"
                "<Enter>: send\n"
                "<Shift+Enter>: new line\n"
                "<Double click dialog>: edit dialog\n")
        messagebox.showinfo("About", info, parent=self.root)

    def check_system(self):
        message = _system_check(self.root)
        if message is not None:
            messagebox.showwarning("Warning", message, parent=self.root)

    def append_text_to_chat(self,
                            text: str,
                            *args,
                            use_label: bool = False):
        self.chat_box.config(state=tk.NORMAL)
        if use_label:
            cur_label_widget = self.label_widgets[-1]
            cur_label_widget.config(text=cur_label_widget.cget("text") + text)
        else:
            self.chat_box.insert(tk.END, text, *args)
        self.chat_box.see(tk.END)
        self.chat_box.config(state=tk.DISABLED)

    def append_thinking(self, text: str):
        """Insert the thinking above the last label, under a header that folds it"""
        label = self.label_widgets[-1]
        self.chat_box.config(state=tk.NORMAL)
        if self.chat_box.tag_ranges(f"body{label}"):
            self.chat_box.insert(f"{label} -1c", text, ("Thinking", f"body{label}"))
        else:
            self.chat_box.insert(label, "▾ Thinking\n", ("ThinkingHeader", f"header{label}"),
                                 text + "\n", ("Thinking", f"body{label}"))
            self.chat_box.tag_bind(f"header{label}", "<Button-1>", lambda e: self.fold_thinking(label))
        self.chat_box.config(state=tk.DISABLED)

    def fold_thinking(self, label: tk.Label, fold: Optional[bool] = None):
        """Fold or unfold the thinking of the label, toggle if fold is None"""
        if not self.chat_box.tag_ranges(f"header{label}"):
            return
        arrow = f"header{label}.first"
        if fold is None:
            fold = self.chat_box.get(arrow) == "▾"
        self.chat_box.config(state=tk.NORMAL)
        self.chat_box.tag_configure(f"body{label}", elide=fold)
        self.chat_box.insert(arrow, "▸" if fold else "▾", ("ThinkingHeader", f"header{label}"))
        self.chat_box.delete(f"{arrow} +1c")
        self.chat_box.config(state=tk.DISABLED)

    def append_log_to_inner_textbox(self,
                                    message: Optional[str] = None,
                                    clear: bool = False):
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

    def handle_key_press(self, event: tk.Event):
        if event.keysym == "Return":
            if event.state & 0x1 == 0x1:  # Shift key is pressed
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
        self.api_url = self.host_input.get()

    def update_model_select(self):
        """Worker thread: fetch the models, the widgets are updated by the main thread"""
        try:
            models = self.fetch_models()
        except Exception:  # noqa
            models = None
        self.run_on_ui(self.set_model_select, models)

    def set_model_select(self, models: Optional[List[str]]):
        try:
            if models is None:
                self.show_error("Error! Please check the host.")
            elif models:
                self.model_select["values"] = models
                self.model_select.set(models[0])
                self.send_button.state(["!disabled"])
            else:
                self.show_error("You need download a model!")
        finally:
            self.refresh_button.state(["!disabled"])

    def update_model_list(self):
        """Worker thread: fetch the models, the widgets are updated by the main thread"""
        try:
            models = self.fetch_models()
        except Exception:  # noqa
            models = None
        self.run_on_ui(self.set_model_list, models)

    def set_model_list(self, models: Optional[List[str]]):
        if self.models_list.winfo_exists():
            self.models_list.delete(0, tk.END)
            if models is None:
                self.append_log_to_inner_textbox("Error! Please check the Ollama host.")
            else:
                for model in models:
                    self.models_list.insert(tk.END, model)

    def set_download_button_state(self, state: str):
        if self.download_button.winfo_exists():
            self.download_button.state([state])

    def on_send_button(self, _=None):
        message = self.user_input.get("1.0", "end-1c")
        if message:
            self.layout.create_inner_label(on_right_side=True)
            self.append_text_to_chat(f"{message}", use_label=True)
            self.append_text_to_chat(f"\n\n")
            self.user_input.delete("1.0", "end")
            self.chat_history.append({"role": "user", "content": message})

            self.show_process_bar()
            self.send_button.state(["disabled"])
            self.refresh_button.state(["disabled"])

            model = self.model_select.get()
            self.append_text_to_chat(f"{model}\n", ("Bold",))
            self.ai_label = self.layout.create_inner_label()
            self.stop_event = Event()

            # the thinking is only for display, it is not sent back as context
            messages = [{k: v for k, v in i.items() if k != "thinking"} for i in self.chat_history]

            Thread(
                target=self.generate_ai_response,
                args=(model, messages, self.stop_event),
                daemon=True,
            ).start()

    def on_stop_button(self):
        self.stop_event.set()
        self.stop_button.state(["disabled"])

    def generate_ai_response(self, model: str, messages: List[dict], stop_event: Event):
        """Worker thread: read the stream, the widgets are updated by the main thread"""
        thinking = ai_message = ""
        error = None
        try:
            for message in self.fetch_chat_stream_result(model, messages, stop_event):
                content, thought = message.get("content") or "", message.get("thinking") or ""
                self.run_on_ui(self.append_ai_text, content, thought)
                ai_message += content
                thinking += thought
        except Exception as e:  # noqa
            error = _error_message(e)
        finally:
            self.run_on_ui(self.finish_ai_response, ai_message, thinking, error)

    def append_ai_text(self, content: str, thinking: str = ""):
        # the label is gone if the chat was cleared while generating
        if self.ai_label in self.label_widgets:
            if thinking:
                self.append_thinking(thinking)
            if content and not self.ai_label.cget("text"):  # the answer starts
                self.fold_thinking(self.ai_label, True)
            self.append_text_to_chat(content, use_label=True)

    def finish_ai_response(self, ai_message: str, thinking: str = "", error: Optional[str] = None):
        try:
            if self.ai_label in self.label_widgets:
                if error:
                    self.append_text_to_chat(f"\nAI error! {error}\n\n", ("Error",))
                else:
                    message = {"role": "assistant", "content": ai_message}
                    if thinking:
                        message["thinking"] = thinking
                    self.chat_history.append(message)
                    self.append_text_to_chat("\n\n")
        finally:
            self.ai_label = None
            self.hide_process_bar()
            self.send_button.state(["!disabled"])
            self.refresh_button.state(["!disabled"])
            self.stop_button.state(["!disabled"])

    def fetch_models(self) -> List[str]:
        with urllib.request.urlopen(
                urllib.parse.urljoin(self.api_url, "/api/tags")
        ) as response:
            data = json.load(response)
            models = [model["name"] for model in data["models"]]
            return models

    def fetch_chat_stream_result(self,
                                 model: str,
                                 messages: List[dict],
                                 stop_event: Event) -> Generator:
        request = urllib.request.Request(
            urllib.parse.urljoin(self.api_url, "/api/chat"),
            data=json.dumps(
                {
                    "model": model,
                    "messages": messages,
                    "stream": True,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(request) as resp:
            for line in resp:
                if stop_event.is_set():  # stop
                    break
                data = json.loads(line.decode("utf-8"))
                if "error" in data:
                    raise RuntimeError(data["error"])
                if "message" in data:
                    time.sleep(0.01)
                    yield data["message"]

    def delete_model(self, model_name: str):
        self.run_on_ui(self.append_log_to_inner_textbox, clear=True)
        if not model_name:
            return

        req = urllib.request.Request(
            urllib.parse.urljoin(self.api_url, "/api/delete"),
            data=json.dumps({"model": model_name}).encode("utf-8"),
            method="DELETE",
        )
        try:
            urllib.request.urlopen(req).close()
            log = "Model deleted successfully."
        except Exception as e:  # noqa
            log = f"Failed to delete model: {_error_message(e)}"
        self.run_on_ui(self.append_log_to_inner_textbox, log)
        self.update_model_list()
        self.update_model_select()

    def download_model(self, model_name: str):
        self.run_on_ui(self.append_log_to_inner_textbox, clear=True)
        if not model_name:
            return

        self.run_on_ui(self.set_download_button_state, "disabled")

        req = urllib.request.Request(
            urllib.parse.urljoin(self.api_url, "/api/pull"),
            data=json.dumps({"model": model_name, "stream": True}).encode("utf-8"),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as response:
                for line in response:
                    data = json.loads(line.decode("utf-8"))
                    log = data.get("error") or data.get("status") or "No response"
                    if "status" in data:
                        total = data.get("total")
                        completed = data.get("completed", 0)
                        if total:
                            log += f" [{completed}/{total}]"
                    self.run_on_ui(self.append_log_to_inner_textbox, log)
        except Exception as e:
            self.run_on_ui(self.append_log_to_inner_textbox, f"Failed to download model: {_error_message(e)}")
        finally:
            self.update_model_list()
            self.update_model_select()
            self.run_on_ui(self.set_download_button_state, "!disabled")

    def clear_chat(self):
        self.stop_event.set()
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
            title="Save Chat As"
        )
        if filepath:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.chat_history, f, indent=2)

    def load_chat(self):
        filepath = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Load Chat"
        )
        if not filepath:
            return
        
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                history = json.load(f)
                if isinstance(history, list) and all("role" in item and "content" in item for item in history):
                    self.clear_chat()
                    self.chat_history = history

                    # Rebuild chat display
                    for message in self.chat_history:
                        if message["role"] != "user":
                            self.append_text_to_chat(f"{self.model_select.get()}\n", ("Bold",))
                            self.layout.create_inner_label(on_right_side=False)
                            if message.get("thinking"):
                                self.append_thinking(message["thinking"])
                                self.fold_thinking(self.label_widgets[-1], True)
                        else:
                            self.layout.create_inner_label(on_right_side=True)

                        self.append_text_to_chat(message["content"], use_label=True)
                        self.append_text_to_chat("\n\n")

                else:
                    messagebox.showerror("Error", "Invalid chat file format.", parent=self.root)
            except json.JSONDecodeError:
                messagebox.showerror("Error", "Could not decode JSON from file.", parent=self.root)


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
        header_frame.grid_columnconfigure(3, weight=1)

        model_select = ttk.Combobox(header_frame, state="readonly", width=30)
        model_select.grid(row=0, column=0)

        settings_button = ttk.Button(
            header_frame, text="⚙️", command=self.show_model_management_window, width=3
        )
        settings_button.grid(row=0, column=1, padx=(5, 0))

        refresh_button = ttk.Button(header_frame, text="Refresh", command=self.interface.refresh_models)
        refresh_button.grid(row=0, column=2, padx=(5, 0))

        ttk.Label(header_frame, text="Host:").grid(row=0, column=4, padx=(10, 0))

        host_input = ttk.Entry(header_frame, width=24)
        host_input.grid(row=0, column=5, padx=(5, 15))
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

        _right_click = (
            "<Button-2>" if platform.system().lower() == "darwin" else "<Button-3>"
        )
        chat_box.bind(_right_click, lambda e: chat_box_menu.post(e.x_root, e.y_root))

        self.interface.chat_box = chat_box

    def _processbar_frame(self):
        process_frame = ttk.Frame(self.interface.root, height=28)
        process_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=10)

        progress = ttk.Progressbar(
            process_frame,
            mode="indeterminate",
            style="LoadingBar.Horizontal.TProgressbar",
        )

        stop_button = ttk.Button(
            process_frame,
            width=5,
            text="Stop",
            command=self.interface.on_stop_button,
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
        file_menu.add_command(label="Save Chat", command=self.interface.save_chat)
        file_menu.add_command(label="Load Chat", command=self.interface.load_chat)
        file_menu.add_separator()
        file_menu.add_command(label="Model Management", command=self.show_model_management_window)
        file_menu.add_command(label="Exit", command=self.interface.root.quit)

        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        edit_menu.add_command(label="Copy All", command=self.interface.copy_all)
        edit_menu.add_command(label="Clear Chat", command=self.interface.clear_chat)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Source Code", command=self.interface.open_homepage)
        help_menu.add_command(label="Help", command=self.interface.show_help)

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
            Thread(
                target=self.interface.download_model, daemon=True, args=(arg,)
            ).start()

        def _delete():
            arg = models_list.get(tk.ACTIVE).strip()
            Thread(target=self.interface.delete_model, daemon=True, args=(arg,)).start()

        download_button = ttk.Button(frame, text="Download", command=_download)
        download_button.grid(row=0, column=1, sticky="ew")

        tips = tk.Label(
            frame,
            text="find models: https://ollama.com/library",
            fg="blue",
            cursor="hand2",
        )
        tips.bind("<Button-1>", lambda e: webbrowser.open("https://ollama.com/library"))
        tips.grid(row=1, column=0, sticky="W", padx=(0, 5), pady=5)

        list_action_frame = ttk.Frame(management_window)
        list_action_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        list_action_frame.grid_columnconfigure(0, weight=1)
        list_action_frame.grid_rowconfigure(0, weight=1)

        models_list = tk.Listbox(list_action_frame)
        models_list.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(
            list_action_frame, orient="vertical", command=models_list.yview
        )
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
        Thread(
            target=self.interface.update_model_list, daemon=True,
        ).start()

    def show_editor_window(self, _, inner_label):
        if self.editor_window and self.editor_window.winfo_exists():
            self.editor_window.lift()
            return

        editor_window = tk.Toplevel(self.interface.root)
        editor_window.title("Chat Editor")

        screen_width = self.interface.root.winfo_screenwidth()
        screen_height = self.interface.root.winfo_screenheight()

        x = int((screen_width / 2) - (400 / 2))
        y = int((screen_height / 2) - (300 / 2))

        editor_window.geometry(f"{400}x{300}+{x}+{y}")

        chat_editor = tk.Text(editor_window)
        chat_editor.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
        chat_editor.insert(tk.END, inner_label.cget("text"))

        editor_window.grid_rowconfigure(0, weight=1)
        editor_window.grid_columnconfigure(0, weight=1)
        editor_window.grid_columnconfigure(1, weight=1)

        def _save():
            idx = self.interface.label_widgets.index(inner_label)
            if len(self.interface.chat_history) > idx:
                self.interface.chat_history[idx]["content"] = chat_editor.get("1.0", "end-1c")
                inner_label.config(text=chat_editor.get("1.0", "end-1c"))

            editor_window.destroy()

        save_button = tk.Button(editor_window, text="Save", command=_save)
        save_button.grid(row=1, column=0, sticky="ew", padx=5, pady=5)

        cancel_button = tk.Button(
            editor_window, text="Cancel", command=editor_window.destroy
        )
        cancel_button.grid(row=1, column=1, sticky="ew", padx=5, pady=5)

        editor_window.grid_columnconfigure(0, weight=1, uniform="btn")
        editor_window.grid_columnconfigure(1, weight=1, uniform="btn")

        self.editor_window = editor_window

    def create_inner_label(self, on_right_side: bool = False) -> tk.Label:
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

        inner_label.bind(
            "<MouseWheel>",
            lambda e:
            self.interface.chat_box.yview_scroll(int(-1 * (e.delta / 120)), "units")
        )
        inner_label.bind("<Double-1>", lambda e: self.show_editor_window(e, inner_label))

        _right_menu = tk.Menu(inner_label, tearoff=0)
        _right_menu.add_command(
            label="Edit", command=lambda: self.show_editor_window(None, inner_label)
        )
        _right_menu.add_command(
            label="Copy This", command=lambda: self.interface.copy_text(inner_label.cget("text"))
        )
        _right_menu.add_separator()
        _right_menu.add_command(label="Clear Chat", command=self.interface.clear_chat)
        _right_click = (
            "<Button-2>" if platform.system().lower() == "darwin" else "<Button-3>"
        )
        inner_label.bind(_right_click, lambda e: _right_menu.post(e.x_root, e.y_root))
        self.interface.chat_box.window_create(tk.END, window=inner_label)
        if on_right_side:
            idx = self.interface.chat_box.index("end-1c").split(".")[0]
            self.interface.chat_box.tag_add("Right", f"{idx}.0", f"{idx}.end")
        return inner_label


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

    app.chat_box.tag_configure(
        "Bold", foreground="#ff007b", font=(app.default_font, 10, "bold")
    )
    app.chat_box.tag_configure("ThinkingHeader", foreground="#888888", font=(app.default_font, 10, "bold"))
    app.chat_box.tag_configure("Thinking", foreground="#888888", font=(app.default_font, 10),
                               lmargin1=14, lmargin2=14, spacing3=4)
    app.chat_box.tag_bind("ThinkingHeader", "<Enter>", lambda e: app.chat_box.config(cursor="hand2"))
    app.chat_box.tag_bind("ThinkingHeader", "<Leave>", lambda e: app.chat_box.config(cursor="xterm"))
    app.chat_box.tag_configure("Error", foreground="red")
    app.chat_box.tag_configure("Right", justify="right")

    root.mainloop()


if __name__ == "__main__":
    run()
