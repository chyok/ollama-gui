import json
import time
import platform

import urllib.parse
import urllib.request
import tkinter as tk

from tkinter import ttk, font, messagebox
from threading import Thread

_RIGHT_CLICK = "<Button-2>" if platform.system() == "Darwin" else "<Button-3>"


class AIChatInterface:
    def __init__(self, root):
        self.root = root
        self.api_url = "http://127.0.0.1:11434"
        self.chat_history = []
        self.default_font = font.nametofont("TkTextFont").actual()["family"]

        # header
        header_frame = ttk.Frame(root)
        header_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=20)
        header_frame.grid_columnconfigure(2, weight=1)

        self.model_select = ttk.Combobox(header_frame, state="readonly", width=30)
        self.model_select.grid(row=0, column=0)

        self.refresh_button = ttk.Button(
            header_frame, text="Refresh", command=self.refresh_models
        )
        self.refresh_button.grid(row=0, column=1, padx=(10, 0))

        ttk.Label(header_frame, text="Host:").grid(row=0, column=3, padx=(10, 0))

        self.host_input = ttk.Entry(header_frame, width=20)
        self.host_input.grid(row=0, column=4, padx=(5, 10))
        self.host_input.insert(0, self.api_url)

        # chat container
        chat_frame = ttk.Frame(root)
        chat_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        chat_frame.grid_columnconfigure(0, weight=1)
        chat_frame.grid_rowconfigure(0, weight=1)

        self.chat_box = tk.Text(
            chat_frame, wrap=tk.WORD, state=tk.DISABLED, font=(self.default_font, 12)
        )
        self.chat_box.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(
            chat_frame, orient="vertical", command=self.chat_box.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.chat_box.configure(yscrollcommand=scrollbar.set)

        # input area
        input_frame = ttk.Frame(root)
        input_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=20)
        input_frame.grid_columnconfigure(0, weight=1)

        self.user_input = tk.Text(
            input_frame, font=(self.default_font, 12), height=3, wrap=tk.WORD
        )
        self.user_input.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.user_input.bind("<Key>", self.handle_key_press)

        self.send_button = ttk.Button(
            input_frame,
            text="Send",
            command=self.on_send_button,
        )
        self.send_button.grid(row=0, column=1)
        self.send_button.state(["disabled"])

        self.chat_box.bind(_RIGHT_CLICK, self.show_right_click_menu)
        self.right_click_menu = tk.Menu(self.chat_box, tearoff=0)
        self.right_click_menu.add_command(label="Copy", command=self.copy_text)
        self.right_click_menu.add_command(label="Clear Chat", command=self.clear_chat)

        self.menubar = tk.Menu(root)
        root.config(menu=self.menubar)

        self.file_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="File", menu=self.file_menu)
        self.file_menu.add_command(label="Open Chat", command=self.open_chat)
        self.file_menu.add_command(label="Save Chat", command=self.save_chat)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=root.quit)

        self.edit_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Edit", menu=self.edit_menu)
        self.edit_menu.add_command(label="Clear Chat", command=self.clear_chat)

        self.help_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Help", menu=self.help_menu)
        self.help_menu.add_command(label="About", command=self.show_about)

        self.refresh_models()

    def open_chat(self):
        pass

    def save_chat(self):
        pass

    def show_about(self):
        info = "Project: Ollama GUI\nAuthor: chyok\nGithub: https://github.com/chyok/ollama-gui"
        messagebox.showinfo("About", info, parent=self.root)

    def show_right_click_menu(self, event):
        self.right_click_menu.post(event.x_root, event.y_root)

    def copy_text(self):
        if self.chat_box.tag_ranges("sel"):
            selected_text = self.chat_box.get("sel.first", "sel.last")
            if selected_text:
                self.chat_box.clipboard_clear()
                self.chat_box.clipboard_append(selected_text)

    def append_text_to_chat(self, text, *args):
        self.chat_box.config(state=tk.NORMAL)
        self.chat_box.insert(tk.END, text, *args)
        self.chat_box.see(tk.END)
        self.chat_box.config(state=tk.DISABLED)

    def handle_key_press(self, event):
        if event.keysym == "Return":
            if event.state & 0x1 == 0x1:  # Shift key is pressed
                self.user_input.insert("end", "\n")
            elif self.send_button.state() != ("disabled",):
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
        message = self.user_input.get("1.0", "end-1c").strip()
        if message:
            self.append_text_to_chat(f"User: \n", ("Bold", "User"))
            self.append_text_to_chat(f"{message}\n\n")
            self.user_input.delete("1.0", "end")
            self.chat_history.append({"role": "user", "content": message})

            Thread(
                target=self.generate_ai_response,
                daemon=True,
            ).start()

    def generate_ai_response(self):
        self.send_button.state(["disabled"])
        self.refresh_button.state(["disabled"])

        try:
            self.append_text_to_chat(
                f"AI ({self.model_select.get()}): \n", ("Bold", "AI")
            )
            ai_message = ""
            for i in self._request_ollama():
                self.append_text_to_chat(f"{i}")
                ai_message += i
            self.chat_history.append({"role": "assistant", "content": ai_message})
            self.append_text_to_chat("\n\n")
        except Exception:  # noqa
            self.append_text_to_chat(tk.END, f"\nAI error!\n\n", ("Error",))
        finally:
            self.send_button.state(["!disabled"])
            self.refresh_button.state(["!disabled"])

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
                data = json.loads(line.decode("utf-8"))
                if "message" in data:
                    time.sleep(0.01)
                    yield data["message"]["content"]

    def clear_chat(self):
        self.chat_box.config(state=tk.NORMAL)
        self.chat_box.delete(1.0, tk.END)
        self.chat_box.config(state=tk.DISABLED)
        self.chat_history.clear()


def run():
    root = tk.Tk()

    root.title("Ollama GUI")
    root.geometry("800x600")
    root.grid_columnconfigure(0, weight=1)
    root.grid_rowconfigure(1, weight=1)
    root.grid_rowconfigure(2, weight=0)

    app = AIChatInterface(root)

    app.chat_box.tag_configure("Bold", font=(app.default_font, 12, "bold"))
    app.chat_box.tag_configure("Error", foreground="red")
    app.chat_box.tag_configure("User", foreground="#007bff")
    app.chat_box.tag_configure("AI", foreground="#ff007b")

    root.mainloop()


if __name__ == "__main__":
    run()
