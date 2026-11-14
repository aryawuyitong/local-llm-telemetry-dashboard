"""Desktop entry point for the packaged, loopback-only Lab Helper."""
from __future__ import annotations

import secrets
import sys
import threading
import urllib.error
import urllib.request
import webbrowser

from telemetry_agent.config import FROZEN, PORTAL_DIR, SKILL_DIR, Settings, lab_install_roots
from telemetry_agent.helper import Lab, create_server


def launch():
    token = secrets.token_urlsafe(32)
    server = create_server(Lab(), token, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    return server, base, token


def stop(server):
    server.shutdown()
    server.server_close()


def self_test():
    """Verify that the bundle can start and serve its own assets without Ollama."""
    assert (SKILL_DIR / "models.json").is_file()
    assert (PORTAL_DIR / "index.html").is_file()
    if FROZEN:
        results = Settings().results_dir.resolve()
        assert all(not results.is_relative_to(path.resolve()) for path in lab_install_roots())
    server, base, _ = launch()
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        for path in ("/", "/app.js", "/lab.js", "/style.css"):
            with direct.open(base + path, timeout=5) as response:
                assert response.status == 200 and response.read(1), path
        try:
            direct.open(base + "/api/status", timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 401  # A browser without the launch token cannot use the helper.
        else:
            raise AssertionError("The local API accepted a request without a launch token.")
    finally:
        stop(server)


def main():
    if sys.argv[1:] == ["--self-test"]:
        self_test()
        return

    import tkinter as tk
    from tkinter import messagebox, ttk

    window = tk.Tk()
    window.title("Local AI Lab")
    window.resizable(False, False)
    try:
        server, base, token = launch()
    except (OSError, RuntimeError, ValueError) as exc:
        messagebox.showerror("Local AI Lab", f"The Lab Helper could not start.\n\n{exc}", parent=window)
        window.destroy()
        return
    url = f"{base}/#t={token}"

    def open_lab():
        if not webbrowser.open(url):
            messagebox.showinfo("Open your lab", "Use Copy private link and paste it into your browser.", parent=window)

    def copy_link():
        window.clipboard_clear()
        window.clipboard_append(url)

    def quit_lab():
        stop(server)
        window.destroy()

    frame = ttk.Frame(window, padding=20)
    frame.grid()
    ttk.Label(frame, text="Local AI Lab").grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(frame, text="Keep this window open while you use the lab in your browser.").grid(
        row=1, column=0, columnspan=3, sticky="w", pady=(6, 16)
    )
    ttk.Button(frame, text="Open lab in browser", command=open_lab).grid(row=2, column=0, padx=(0, 6))
    ttk.Button(frame, text="Copy private link", command=copy_link).grid(row=2, column=1, padx=(0, 6))
    ttk.Button(frame, text="Quit", command=quit_lab).grid(row=2, column=2)
    window.protocol("WM_DELETE_WINDOW", quit_lab)
    if sys.platform == "darwin":
        window.createcommand("::tk::mac::Quit", quit_lab)
    window.after(250, open_lab)
    window.mainloop()


if __name__ == "__main__":
    main()
