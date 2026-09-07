Below are listed the ollama GUI enahcements that have been implemented in this fork:

* **Proper Stop/Cancel behavior**
  Replaced the old “button state hack” with a real `threading.Event` cancellation signal, so streaming/chat can be stopped reliably and cleanly.

* **Network timeouts added**
  Added timeouts to Ollama HTTP calls so the GUI doesn’t hang indefinitely when the host is unreachable or slow.

* **Tkinter thread-safety fixes**
  Moved UI updates onto the Tk main thread using `root.after()` helpers, preventing random freezes/crashes caused by background threads touching widgets directly.

* **Keyboard handling fix (shortcuts preserved)**
  Changed input binding to use **only `<Return>`** (instead of `<Key>`), so standard shortcuts like **Ctrl+C / Ctrl+V** aren’t intercepted or broken.

* **Menu/About cleanup + revision metadata**
  “Help” was revised into a clearer **About** dialog/menu and updated to include version/revision details and contributor credits (chyok + Dr. Eric O. Flores).
