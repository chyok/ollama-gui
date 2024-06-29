import json
import time

import urllib.parse
import urllib.request
import tkinter as tk

from tkinter import ttk, font
from contextlib import contextmanager
from typing import Union, Generator
from threading import Thread


@contextmanager
def widget_state_context(self: "AIChatInterface",
                         enable_sending: bool,
                         enable_typing: bool):
    try:
        if enable_typing:
            self.chat.config(state=tk.NORMAL)
        if not enable_sending:
            self.send_button.state(['disabled'])
        yield
    except Exception as _:
        self.chat.insert(tk.END, f"\nAI error!\n\n", ("error",))
    finally:
        self.chat.config(state=tk.DISABLED)
        self.send_button.state(['!disabled'])


class AIChatInterface:
    def __init__(self, root):
        self.root = root
        self.default_font = font.nametofont('TkTextFont').actual()["family"]
        root.title("AI Chat Interface")
        root.geometry("800x600")

        self.api_url = 'http://localhost:11434'
        self.chat_history = []

        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(1, weight=1)
        root.grid_rowconfigure(2, weight=0)

        # header
        header_frame = ttk.Frame(root)
        header_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=20)
        header_frame.grid_columnconfigure(2, weight=1)

        self.model_select = ttk.Combobox(header_frame, state="readonly", width=30)
        self.model_select.grid(row=0, column=0)

        self.refresh_button = ttk.Button(header_frame, text="Refresh", command=self.refresh_models)
        self.refresh_button.grid(row=0, column=1, padx=(10, 0))

        self.error_label = ttk.Label(header_frame, text="", foreground="red")
        self.error_label.grid(row=0, column=2, padx=(10, 0), sticky="w")

        host_label = ttk.Label(header_frame, text="Host:")
        host_label.grid(row=0, column=3, padx=(10, 0))

        self.host_input = ttk.Entry(header_frame, width=30)
        self.host_input.grid(row=0, column=4, padx=(5, 10))
        self.host_input.insert(0, self.api_url)

        clear_button = ttk.Button(header_frame, text="Clear Chat", command=self.clear_chat)
        clear_button.grid(row=0, column=5)

        # chat container
        chat_frame = ttk.Frame(root)
        chat_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        chat_frame.grid_columnconfigure(0, weight=1)
        chat_frame.grid_rowconfigure(0, weight=1)

        self.chat = tk.Text(chat_frame, wrap=tk.WORD, state=tk.DISABLED, font=(self.default_font, 12))
        self.chat.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(chat_frame, orient="vertical", command=self.chat.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.chat.configure(yscrollcommand=scrollbar.set)

        # input area
        input_frame = ttk.Frame(root)
        input_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=20)
        input_frame.grid_columnconfigure(0, weight=1)

        self.user_input = tk.Text(input_frame, font=(self.default_font, 12), height=3, wrap=tk.WORD)
        self.user_input.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.user_input.bind("<Key>", self.handle_key_press)

        self.send_button = ttk.Button(input_frame, text="  Send \n<Enter>", command=lambda: self.send_message(None))
        self.send_button.grid(row=0, column=1)
        self.send_button.state(['disabled'])
        self.refresh_models()

    def handle_key_press(self, event):
        if event.keysym == "Return":
            if event.state & 0x1 == 0x1:  # Shift key is pressed
                self.user_input.insert("end", "\n")
            else:
                if self.send_button.state() == ('disabled',):
                    return "break"
                self.send_message(event)
            return "break"
        else:
            return

    def refresh_models(self):
        self.model_select.set("waiting...")
        self.send_button.state(['disabled'])
        self.refresh_button.state(['disabled'])
        self.api_url = self.host_input.get()
        Thread(target=self.fetch_models).start()

    def fetch_models(self):
        try:
            with urllib.request.urlopen(f'{self.api_url}/api/tags') as response:
                data = json.load(response)
                models = [model['name'] for model in data['models']]
                self.root.after(0, self.update_model_select, models)
        except Exception as _:
            self.root.after(0, self.show_error)
        finally:
            self.root.after(0, lambda: self.refresh_button.state(['!disabled']))

    def update_model_select(self, models):
        self.model_select['values'] = models
        if models:
            self.model_select.set(models[0])
            self.send_button.state(['!disabled'])
            self.error_label.config(text="")
        else:
            self.show_error()

    def show_error(self):
        self.model_select.set('')
        self.model_select['values'] = []
        self.send_button.state(['disabled'])
        self.error_label.config(text="error")

    def send_message(self, event=None):
        message = self.user_input.get("1.0", "end-1c").strip()
        if message:
            self.add_message_to_chat("User", message)
            self.chat_history.append({"role": "user", "content": message})
            self.user_input.delete("1.0", "end")

            Thread(target=self.add_message_to_chat, args=(f"AI ({self.model_select.get()})",
                                                          self.generate_ai_response())).start()

    def add_message_to_chat(self, sender, message: Union[str, Generator]):
        with widget_state_context(self, enable_typing=True, enable_sending=False):
            self.chat.insert(tk.END, f"{sender}: \n", ("bold", f"{sender.lower()}_name"))
            if isinstance(message, str):
                self.chat.insert(tk.END, f"{message}")
            else:
                ai_message = ""
                for i in message:
                    self.chat.insert(tk.END, f"{i}")
                    ai_message += i
                    self.chat_history.append({"role": "assistant", "content": ai_message})

            self.chat.insert(tk.END, "\n\n")
            self.chat.see(tk.END)

    def generate_ai_response(self):
        request = urllib.request.Request(
            f'{self.api_url}/api/chat',
            data=json.dumps({
                "model": self.model_select.get(),
                "messages": self.chat_history,
                "stream": True,
            }).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )

        with urllib.request.urlopen(request) as resp:
            for line in resp.read().decode('utf-8').splitlines():
                if line.strip():
                    data = json.loads(line)
                    if 'message' in data:
                        new_content = data['message']['content']
                        time.sleep(0.01)  # add a small delay to improve readability
                        yield new_content

    def clear_chat(self):
        with widget_state_context(self, enable_typing=True, enable_sending=False):
            self.chat.delete(1.0, tk.END)
        self.chat_history.clear()


def run():
    root = tk.Tk()
    app = AIChatInterface(root)

    app.chat.tag_configure("bold", font=(app.default_font, 12, "bold"))
    app.chat.tag_configure("user_name", foreground="#007bff")
    app.chat.tag_configure("error", foreground="red")

    root.mainloop()


if __name__ == '__main__':
    run()
