import gc
import os
import json
import time
import tempfile
import threading
import unittest
import urllib.error

from unittest import mock

import _tkinter
import tkinter as tk

import ollama_gui
from ollama_gui import OllamaInterface, _error_message, _system_check, _version_tuple


class FakeResponse:
    """A stand-in for the object returned by urllib.request.urlopen"""

    def __init__(self, lines=(), status=200):
        self.lines = [json.dumps(i).encode("utf-8") + b"\n" for i in lines]
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __iter__(self):
        return iter(self.lines)

    def read(self, *_):
        return b"".join(self.lines)

    def close(self):
        pass


def http_error(code, body):
    return urllib.error.HTTPError("http://127.0.0.1:11434", code, "Error", {}, FakeResponse([body]))


def content(*texts):
    return iter([{"role": "assistant", "content": i} for i in texts])


class ErrorMessageTest(unittest.TestCase):
    def test_reason_from_ollama(self):
        e = http_error(404, {"error": "model 'x' not found"})
        self.assertEqual(_error_message(e), "model 'x' not found")

    def test_http_error_without_reason(self):
        e = urllib.error.HTTPError("http://127.0.0.1:11434", 502, "Bad Gateway", {}, None)
        self.assertEqual(_error_message(e), "HTTP Error 502: Bad Gateway")

    def test_other_error(self):
        self.assertEqual(_error_message(OSError("connection refused")), "connection refused")


class VersionTupleTest(unittest.TestCase):
    def test_compare_by_number_not_by_string(self):
        self.assertLess(_version_tuple("8.6.9"), _version_tuple("8.6.12"))
        self.assertLess(_version_tuple("8.6.12"), _version_tuple("8.6.13"))
        self.assertLess(_version_tuple("9"), _version_tuple("14"))

    def test_different_length(self):
        self.assertLess(_version_tuple("14"), _version_tuple("14.4.1"))
        self.assertLess(_version_tuple("14.4.1"), _version_tuple("15"))


class SystemCheckTest(unittest.TestCase):
    @staticmethod
    def check(system, mac_version, tcl_version):
        root = mock.Mock()
        root.tk.call.return_value = tcl_version
        with mock.patch("platform.system", return_value=system), \
                mock.patch("platform.mac_ver", return_value=(mac_version, ("", "", ""), "arm64")):
            return _system_check(root)

    def test_warn_on_sonoma_with_old_tcl(self):
        for mac_version in ("14", "14.0", "14.4", "14.4.1", "14.6.1"):
            for tcl_version in ("8.6.8", "8.6.12"):
                message = self.check("Darwin", mac_version, tcl_version)
                self.assertIsNotNone(message, (mac_version, tcl_version))
                self.assertIn("Tkinter Responsiveness Issue", message)

    def test_three_part_version_does_not_raise(self):
        # float("14.4.1") used to raise ValueError here
        self.assertIsNotNone(self.check("Darwin", "14.4.1", "8.6.12"))
        self.assertIsNone(self.check("Darwin", "13.6.7", "8.6.12"))
        self.assertIsNone(self.check("Darwin", "15.1.1", "8.6.12"))

    def test_no_warning_with_new_tcl(self):
        for tcl_version in ("8.6.13", "8.6.14", "9.0.1"):
            self.assertIsNone(self.check("Darwin", "14.4.1", tcl_version), tcl_version)

    def test_no_warning_on_other_macos(self):
        for mac_version in ("", "10.15.7", "13.6", "15.0", "26.1"):
            self.assertIsNone(self.check("Darwin", mac_version, "8.6.12"), mac_version)

    def test_no_warning_on_other_system(self):
        self.assertIsNone(self.check("Linux", "", "8.6.12"))
        self.assertIsNone(self.check("Windows", "", "8.6.12"))


class WorkerThreadTest(unittest.TestCase):
    """
    The functions running in the worker threads must not touch any widget,
    they can only queue the calls for the main thread.

    Every widget here is a child of one mock, so `self.widgets.mock_calls`
    records each call made to any of them.
    """

    def setUp(self):
        self.widgets = mock.MagicMock()

        app = OllamaInterface.__new__(OllamaInterface)
        app.root = self.widgets.root
        app.layout = self.widgets.layout
        for name in OllamaInterface.__annotations__:
            setattr(app, name, getattr(self.widgets, name))

        app.api_url = "http://127.0.0.1:11434"
        app.chat_history = []
        app.label_widgets = []
        app.ai_label = None
        app.ui_queue = ollama_gui.queue.Queue()
        app.stop_event = threading.Event()
        self.app = app

    def run_in_worker(self, func, *args):
        """Run the function in another thread, and make sure no widget was used"""
        thread = threading.Thread(target=func, args=args, daemon=True)
        thread.start()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.widgets.mock_calls, [], "widget used in the worker thread")

    def test_update_model_select(self):
        self.app.fetch_models = lambda: ["llama3:latest", "phi3:latest"]
        self.run_in_worker(self.app.update_model_select)

        self.app.drain_ui_queue()
        self.widgets.model_select.__setitem__.assert_called_once_with(
            "values", ["llama3:latest", "phi3:latest"])
        self.widgets.model_select.set.assert_called_once_with("llama3:latest")
        self.widgets.send_button.state.assert_called_once_with(["!disabled"])
        self.widgets.refresh_button.state.assert_called_once_with(["!disabled"])

    def test_update_model_select_without_model(self):
        self.app.fetch_models = lambda: []
        self.run_in_worker(self.app.update_model_select)

        self.app.drain_ui_queue()
        self.widgets.model_select.set.assert_called_once_with("You need download a model!")
        self.widgets.send_button.state.assert_called_once_with(["disabled"])
        self.widgets.refresh_button.state.assert_called_once_with(["!disabled"])

    def test_update_model_select_with_bad_host(self):
        self.app.fetch_models = mock.Mock(side_effect=OSError("connection refused"))
        self.run_in_worker(self.app.update_model_select)

        self.app.drain_ui_queue()
        self.widgets.model_select.set.assert_called_once_with("Error! Please check the host.")
        self.widgets.send_button.state.assert_called_once_with(["disabled"])
        self.widgets.refresh_button.state.assert_called_once_with(["!disabled"])

    def test_update_model_list(self):
        self.app.fetch_models = lambda: ["llama3:latest", "phi3:latest"]
        self.run_in_worker(self.app.update_model_list)

        self.app.drain_ui_queue()
        self.widgets.models_list.delete.assert_called_once_with(0, tk.END)
        self.assertEqual(
            self.widgets.models_list.insert.call_args_list,
            [mock.call(tk.END, "llama3:latest"), mock.call(tk.END, "phi3:latest")])

    def test_update_model_list_with_bad_host(self):
        self.app.fetch_models = mock.Mock(side_effect=OSError("connection refused"))
        self.run_in_worker(self.app.update_model_list)

        self.app.drain_ui_queue()
        self.widgets.models_list.insert.assert_not_called()
        self.widgets.log_textbox.insert.assert_called_once_with(
            tk.END, "Error! Please check the Ollama host.\n")

    def test_update_model_list_after_window_closed(self):
        self.widgets.models_list.winfo_exists.return_value = 0
        self.app.fetch_models = lambda: ["llama3:latest"]
        self.run_in_worker(self.app.update_model_list)

        self.app.drain_ui_queue()
        self.widgets.models_list.delete.assert_not_called()
        self.widgets.models_list.insert.assert_not_called()

    def test_generate_ai_response(self):
        self.app.fetch_chat_stream_result = mock.Mock(return_value=content("Hel", "lo"))
        self.app.append_ai_text = mock.Mock()
        self.app.finish_ai_response = mock.Mock()
        messages = [{"role": "user", "content": "hi"}]
        self.run_in_worker(self.app.generate_ai_response, "llama3", messages, self.app.stop_event)

        self.app.fetch_chat_stream_result.assert_called_once_with(
            "llama3", messages, self.app.stop_event)
        self.app.append_ai_text.assert_not_called()
        self.app.finish_ai_response.assert_not_called()

        self.app.drain_ui_queue()
        self.assertEqual(
            self.app.append_ai_text.call_args_list, [mock.call("Hel", ""), mock.call("lo", "")])
        self.app.finish_ai_response.assert_called_once_with("Hello", "", None)

    def test_generate_ai_response_with_thinking(self):
        self.app.fetch_chat_stream_result = mock.Mock(return_value=iter([
            {"content": "", "thinking": "Hm"},
            {"content": "", "thinking": "m."},
            {"content": "Hel"},
            {"content": "lo"},
        ]))
        self.app.append_ai_text = mock.Mock()
        self.app.finish_ai_response = mock.Mock()
        self.run_in_worker(self.app.generate_ai_response, "qwen3", [], self.app.stop_event)

        self.app.drain_ui_queue()
        self.assertEqual(
            self.app.append_ai_text.call_args_list,
            [mock.call("", "Hm"), mock.call("", "m."), mock.call("Hel", ""), mock.call("lo", "")])
        self.app.finish_ai_response.assert_called_once_with("Hello", "Hmm.", None)

    def test_generate_ai_response_with_error(self):
        def broken_stream(*_):
            yield {"content": "Hel"}
            raise OSError("connection reset")

        self.app.fetch_chat_stream_result = broken_stream
        self.app.append_ai_text = mock.Mock()
        self.app.finish_ai_response = mock.Mock()
        self.run_in_worker(self.app.generate_ai_response, "llama3", [], self.app.stop_event)

        self.app.drain_ui_queue()
        self.app.append_ai_text.assert_called_once_with("Hel", "")
        self.app.finish_ai_response.assert_called_once_with("Hel", "", "connection reset")

    def test_delete_model(self):
        self.app.fetch_models = lambda: []
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            self.run_in_worker(self.app.delete_model, "llama3:latest")

        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/delete")
        self.assertEqual(request.get_method(), "DELETE")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"model": "llama3:latest"})

        self.app.drain_ui_queue()
        self.widgets.log_textbox.delete.assert_called_once_with(1.0, tk.END)
        self.widgets.log_textbox.insert.assert_called_once_with(
            tk.END, "Model deleted successfully.\n")
        self.widgets.models_list.delete.assert_called_once_with(0, tk.END)

    def test_delete_model_with_error(self):
        self.app.fetch_models = lambda: []
        error = http_error(404, {"error": "model 'llama3:latest' not found"})
        with mock.patch("urllib.request.urlopen", side_effect=error):
            self.run_in_worker(self.app.delete_model, "llama3:latest")

        self.app.drain_ui_queue()
        self.widgets.log_textbox.insert.assert_called_once_with(
            tk.END, "Failed to delete model: model 'llama3:latest' not found\n")
        self.widgets.models_list.delete.assert_called_once_with(0, tk.END)

    def test_delete_model_without_name(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            self.run_in_worker(self.app.delete_model, "")

        urlopen.assert_not_called()
        self.app.drain_ui_queue()
        self.widgets.log_textbox.delete.assert_called_once_with(1.0, tk.END)
        self.widgets.log_textbox.insert.assert_not_called()

    def test_download_model(self):
        self.app.fetch_models = lambda: ["phi3:latest"]
        response = FakeResponse([
            {"status": "pulling manifest"},
            {"status": "downloading", "total": 100, "completed": 40},
            {"status": "success"},
        ])
        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            self.run_in_worker(self.app.download_model, "phi3")

        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/pull")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"model": "phi3", "stream": True})

        self.app.drain_ui_queue()
        self.assertEqual(
            self.widgets.log_textbox.insert.call_args_list,
            [mock.call(tk.END, "pulling manifest\n"),
             mock.call(tk.END, "downloading [40/100]\n"),
             mock.call(tk.END, "success\n")])
        self.assertEqual(
            self.widgets.download_button.state.call_args_list,
            [mock.call(["disabled"]), mock.call(["!disabled"])])
        self.widgets.models_list.insert.assert_called_once_with(tk.END, "phi3:latest")
        self.widgets.model_select.set.assert_called_once_with("phi3:latest")

    def test_download_model_with_error(self):
        self.app.fetch_models = lambda: []
        with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")):
            self.run_in_worker(self.app.download_model, "phi3")

        self.app.drain_ui_queue()
        self.widgets.log_textbox.insert.assert_called_once_with(
            tk.END, "Failed to download model: boom\n")
        self.assertEqual(
            self.widgets.download_button.state.call_args_list,
            [mock.call(["disabled"]), mock.call(["!disabled"])])

    def test_fetch_chat_stream_result(self):
        response = FakeResponse([
            {"message": {"role": "assistant", "content": "Hel"}, "done": False},
            {"message": {"role": "assistant", "content": "lo"}, "done": False},
            {"done": True},
        ])
        messages = [{"role": "user", "content": "hi"}]
        result = []

        def worker():
            result.extend(self.app.fetch_chat_stream_result("llama3", messages, self.app.stop_event))

        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            self.run_in_worker(worker)

        self.assertEqual(
            result,
            [{"role": "assistant", "content": "Hel"}, {"role": "assistant", "content": "lo"}])
        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"model": "llama3", "messages": messages, "stream": True})

    def test_fetch_chat_stream_result_stopped(self):
        response = FakeResponse([
            {"message": {"role": "assistant", "content": "Hel"}},
            {"message": {"role": "assistant", "content": "lo"}},
        ])
        with mock.patch("urllib.request.urlopen", return_value=response):
            stream = self.app.fetch_chat_stream_result("llama3", [], self.app.stop_event)
            self.assertEqual(next(stream)["content"], "Hel")
            self.app.stop_event.set()
            self.assertEqual(list(stream), [])

    def test_fetch_chat_stream_result_with_error_line(self):
        response = FakeResponse([
            {"message": {"role": "assistant", "content": "Hel"}},
            {"error": "an error was encountered while running the model"},
        ])
        with mock.patch("urllib.request.urlopen", return_value=response):
            stream = self.app.fetch_chat_stream_result("llama3", [], self.app.stop_event)
            self.assertEqual(next(stream)["content"], "Hel")
            with self.assertRaisesRegex(RuntimeError, "an error was encountered"):
                next(stream)

    def test_fetch_models(self):
        response = FakeResponse([{"models": [{"name": "llama3:latest"}, {"name": "phi3:latest"}]}])
        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            self.assertEqual(self.app.fetch_models(), ["llama3:latest", "phi3:latest"])
        urlopen.assert_called_once_with("http://127.0.0.1:11434/api/tags")

    def test_drain_ui_queue_runs_calls_in_order(self):
        result = []
        self.app.run_on_ui(result.append, 1)
        self.app.run_on_ui(result.append, 2)
        self.app.run_on_ui(lambda value=None: result.append(value), value=3)
        self.assertEqual(result, [])

        self.app.drain_ui_queue()
        self.assertEqual(result, [1, 2, 3])

    def test_process_ui_queue_keeps_polling_after_error(self):
        self.app.run_on_ui(mock.Mock(side_effect=ValueError("boom")))
        with self.assertRaises(ValueError):
            self.app.process_ui_queue()
        self.widgets.root.after.assert_called_once_with(
            ollama_gui.UI_POLL_INTERVAL, self.app.process_ui_queue)


class InterfaceTest(unittest.TestCase):
    """Run the real interface with a faked Ollama server"""

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f"Tk is not available: {e}")
        self.root.withdraw()
        self.addCleanup(self.close)

        for target, value in (
                ("ollama_gui._system_check", mock.Mock(return_value=None)),
                ("ollama_gui.OllamaInterface.fetch_models", mock.Mock(return_value=["llama3:latest"])),
                ("time.sleep", mock.Mock()),
        ):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.app = OllamaInterface(self.root)
        self.wait_until(lambda: self.app.model_select.get() == "llama3:latest")

    def close(self):
        self.root.destroy()
        for thread in threading.enumerate():
            if thread is not threading.current_thread():
                thread.join(1)
        # Tcl aborts if the interpreter is freed by another thread,
        # so free it here instead of in a gc run of some worker thread
        self.app = self.root = None
        gc.collect()

    def wait_until(self, condition, timeout=5):
        # root.update() may never return while the progress bar is animating,
        # it keeps the event queue busy on macOS, so handle the events one by one
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            if not self.root.dooneevent(_tkinter.DONT_WAIT):
                threading.Event().wait(0.005)
        self.fail("timeout")

    def is_idle(self):
        return ("disabled" not in self.app.send_button.state()
                and "disabled" not in self.app.refresh_button.state()
                and "disabled" not in self.app.stop_button.state()
                and self.app.progress.winfo_manager() == "")

    def send(self, message):
        self.app.user_input.insert("1.0", message)
        self.app.on_send_button()

    def chat_text(self):
        return self.app.chat_box.get("1.0", "end-1c")

    def thinking_text(self):
        ranges = self.app.chat_box.tag_ranges("Thinking")
        return [self.app.chat_box.get(*ranges[i:i + 2]) for i in range(0, len(ranges), 2)]

    def test_model_select(self):
        self.assertEqual(self.app.model_select.get(), "llama3:latest")
        self.assertEqual(list(self.app.model_select["values"]), ["llama3:latest"])
        self.assertTrue(self.is_idle())

    def test_model_select_with_bad_host(self):
        OllamaInterface.fetch_models.side_effect = OSError("connection refused")
        self.app.refresh_models()
        self.assertEqual(self.app.model_select.get(), "Waiting...")

        self.wait_until(lambda: self.app.model_select.get() != "Waiting...")
        self.assertEqual(self.app.model_select.get(), "Error! Please check the host.")
        self.assertIn("disabled", self.app.send_button.state())
        self.assertNotIn("disabled", self.app.refresh_button.state())

    def test_send_message(self):
        self.app.fetch_chat_stream_result = mock.Mock(return_value=content("Hel", "lo"))
        self.send("hi")

        # the ui is locked by the main thread before the worker starts
        self.assertIn("disabled", self.app.send_button.state())
        self.assertIn("disabled", self.app.refresh_button.state())
        self.assertEqual(self.app.progress.winfo_manager(), "grid")
        self.assertEqual(self.app.user_input.get("1.0", "end-1c"), "")

        self.wait_until(self.is_idle)
        self.app.fetch_chat_stream_result.assert_called_once_with(
            "llama3:latest", [{"role": "user", "content": "hi"}], self.app.stop_event)
        self.assertEqual(
            self.app.chat_history,
            [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello"}])
        self.assertEqual([i.cget("text") for i in self.app.label_widgets], ["hi", "Hello"])
        self.assertEqual(self.chat_text(), "\n\nllama3:latest\n\n\n")
        self.assertIsNone(self.app.ai_label)

    def test_ai_error(self):
        self.app.fetch_chat_stream_result = mock.Mock(side_effect=OSError("connection refused"))
        self.send("hi")
        self.wait_until(self.is_idle)

        self.assertEqual(self.chat_text(), "\n\nllama3:latest\n\nAI error! connection refused\n\n")
        start, end = self.app.chat_box.tag_ranges("Error")
        self.assertEqual(self.app.chat_box.get(start, end), "\nAI error! connection refused\n\n")
        self.assertEqual(self.app.chat_history, [{"role": "user", "content": "hi"}])

    def test_ai_error_while_streaming(self):
        def stream(*_):
            yield {"content": "Hel"}
            raise RuntimeError("an error was encountered while running the model")

        self.app.fetch_chat_stream_result = stream
        self.send("hi")
        self.wait_until(self.is_idle)

        self.assertEqual(self.app.label_widgets[-1].cget("text"), "Hel")
        self.assertIn("AI error! an error was encountered while running the model", self.chat_text())
        self.assertEqual(self.app.chat_history, [{"role": "user", "content": "hi"}])

    def test_thinking_is_kept_but_not_sent_back(self):
        self.app.fetch_chat_stream_result = mock.Mock(side_effect=lambda *_: iter([
            {"content": "", "thinking": "Hm"},
            {"content": "", "thinking": "m."},
            {"content": "Hel"},
            {"content": "lo"},
        ]))
        self.send("hi")
        self.wait_until(self.is_idle)

        # the thinking is above the label, and the label only has the answer
        self.assertEqual(self.thinking_text(), ["Hmm.\n"])
        self.assertEqual(self.chat_text(), "\n\nllama3:latest\nHmm.\n\n\n")
        self.assertEqual(self.app.label_widgets[-1].cget("text"), "Hello")
        self.assertEqual(
            self.app.chat_history[-1],
            {"role": "assistant", "content": "Hello", "thinking": "Hmm."})

        self.send("again")
        self.wait_until(self.is_idle)
        self.assertEqual(
            self.app.fetch_chat_stream_result.call_args[0][1],
            [{"role": "user", "content": "hi"},
             {"role": "assistant", "content": "Hello"},
             {"role": "user", "content": "again"}])
        self.assertEqual(self.thinking_text(), ["Hmm.\n", "Hmm.\n"])
        self.assertEqual(self.app.chat_history[1]["thinking"], "Hmm.")

    def test_answer_without_thinking(self):
        self.app.fetch_chat_stream_result = mock.Mock(return_value=content("Hello"))
        self.send("hi")
        self.wait_until(self.is_idle)

        self.assertEqual(self.thinking_text(), [])
        self.assertEqual(self.app.chat_history[-1], {"role": "assistant", "content": "Hello"})

    def test_stop_while_thinking(self):
        def stream(_model, _messages, stop_event):
            yield {"content": "", "thinking": "Hmm."}
            stop_event.wait(5)

        self.app.fetch_chat_stream_result = stream
        self.send("hi")
        self.wait_until(lambda: self.thinking_text() == ["Hmm.\n"])

        self.app.stop_button.invoke()
        self.wait_until(self.is_idle)
        self.assertEqual(self.thinking_text(), ["Hmm.\n"])
        self.assertEqual(self.app.label_widgets[-1].cget("text"), "")
        self.assertEqual(
            self.app.chat_history[-1], {"role": "assistant", "content": "", "thinking": "Hmm."})

    def test_save_and_load_chat_with_thinking(self):
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Hello", "thinking": "Hmm."},
            {"role": "user", "content": "again"},
            {"role": "assistant", "content": "Hi again"},
        ]
        self.app.chat_history = list(history)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "chat.json")
            with mock.patch("tkinter.filedialog.asksaveasfilename", return_value=path), \
                    mock.patch("tkinter.filedialog.askopenfilename", return_value=path):
                self.app.save_chat()
                self.app.load_chat()

        self.assertEqual(self.app.chat_history, history)
        self.assertEqual(self.thinking_text(), ["Hmm.\n"])
        self.assertEqual(
            [i.cget("text") for i in self.app.label_widgets], ["hi", "Hello", "again", "Hi again"])
        self.assertEqual(
            self.chat_text(), "\n\nllama3:latest\nHmm.\n\n\n\n\nllama3:latest\n\n\n")

    def test_stop(self):
        def stream(_model, _messages, stop_event):
            yield {"content": "Hel"}
            stop_event.wait(5)
            if not stop_event.is_set():
                yield {"content": "lo"}

        self.app.fetch_chat_stream_result = stream
        self.send("hi")
        self.wait_until(lambda: self.app.label_widgets[-1].cget("text") == "Hel")

        self.app.stop_button.invoke()
        self.assertIn("disabled", self.app.stop_button.state())

        self.wait_until(self.is_idle)
        self.assertEqual(
            self.app.chat_history,
            [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hel"}])

    def test_clear_chat_while_generating(self):
        def stream(_model, _messages, stop_event):
            yield {"content": "Hel"}
            stop_event.wait(5)
            yield {"content": "lo"}

        self.app.fetch_chat_stream_result = stream
        self.send("hi")
        self.wait_until(lambda: self.app.label_widgets[-1].cget("text") == "Hel")

        self.app.clear_chat()
        self.wait_until(self.is_idle)
        self.assertEqual(self.app.chat_history, [])
        self.assertEqual(self.app.label_widgets, [])
        self.assertEqual(self.chat_text(), "")

    def test_widgets_are_only_used_in_main_thread(self):
        threads = set()
        tk_call = self.root.tk.call

        class TkApp:
            """Forward everything to the real tkapp, and record the calling thread"""

            def __getattr__(self, name):
                return getattr(tk_app, name)

            @staticmethod
            def call(*args):
                threads.add(threading.current_thread())
                return tk_call(*args)

        tk_app = self.root.tk
        widgets = [self.root, self.app.chat_box, self.app.user_input, self.app.model_select,
                   self.app.progress, self.app.stop_button, self.app.send_button,
                   self.app.refresh_button]
        for widget in widgets:
            widget.tk = TkApp()
        self.addCleanup(lambda: [setattr(widget, "tk", tk_app) for widget in widgets])

        self.app.fetch_chat_stream_result = mock.Mock(return_value=content("Hel", "lo"))
        self.send("hi")
        self.wait_until(self.is_idle)
        self.app.refresh_models()
        self.wait_until(self.is_idle)

        self.assertEqual(threads, {threading.main_thread()})


if __name__ == "__main__":
    unittest.main()
