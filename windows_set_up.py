"""Start the lab on Windows. In PowerShell, run:

    python "<the lab's folder>\\windows_set_up.py"

The website's start guide gives the exact line to copy. Running it with Python changes no security
setting, and Windows Smart App Control allows it. It is plain text, so you can read it before you run it.

On the first run it creates a private Python environment in agent\\.venv and installs the one
package the lab needs (psutil). It installs nothing anywhere else, needs no administrator rights
and changes no settings. Delete agent\\.venv to undo it.
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

AGENT = Path(__file__).resolve().parent / "agent"
LAB_PYTHON = AGENT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def stop(message: str) -> None:
    print(message)
    sys.exit(1)


def ready() -> bool:
    """The lab's environment exists and has Python 3.11+ and its one package."""
    check = "import sys, psutil; assert sys.version_info >= (3, 11)"
    return LAB_PYTHON.is_file() and subprocess.call([str(LAB_PYTHON), "-c", check],
                                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def wait_for_setup_lock() -> Path:
    """Only one Start window sets up at a time; a second one waits instead of using a half-built environment.
    The lock is a folder, because creating one is a single step that only one window can win."""
    lock, said = AGENT / ".setup-lock", False
    while True:
        try:
            lock.mkdir()
            return lock
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 600:  # left behind by a window that was closed mid-setup
                    shutil.rmtree(lock, ignore_errors=True)
                    continue
            except OSError:
                continue
            if not said:
                print("Another Start window is setting up the lab. Waiting for it to finish...")
                said = True
            time.sleep(2)


def main() -> None:
    if sys.version_info < (3, 11):
        stop(f"The lab needs Python 3.11 or newer, and this is Python {sys.version.split()[0]}.\n"
             "Install the latest Python from https://www.python.org/downloads/ , then run the start line again.")
    if not (AGENT / "requirements.txt").is_file():
        stop("The agent folder is missing. Download the lab again and unzip the whole folder.")
    os.chdir(AGENT)

    if not ready():
        lock = wait_for_setup_lock()
        try:
            if not ready():  # another window may have finished while this one waited
                shutil.rmtree(AGENT / ".venv", ignore_errors=True)  # a half-built one from an interrupted run
                print("First run: creating the lab's private Python environment in this folder.")
                print("This only adds a .venv folder in the agent folder. Delete that folder to undo it.")
                if subprocess.call([sys.executable, "-m", "venv", ".venv"]) != 0:
                    stop("Setup failed. Run the start line again. If it fails again, send this window's text to the team.")
                # --no-cache-dir: pip keeps no copy elsewhere, so deleting agent\\.venv really undoes the setup.
                if subprocess.call([str(LAB_PYTHON), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                                    "--no-cache-dir", "-r", "requirements.txt"]) != 0:
                    stop("Installing the lab's package failed. Check your internet connection, then run the start line again.")
        finally:
            shutil.rmtree(lock, ignore_errors=True)

    if not ready():
        stop("The agent\\.venv folder is missing Python 3.11+ or a package. Delete that folder, then run the start line again.")

    try:
        code = subprocess.call([str(LAB_PYTHON), "-m", "telemetry_agent.helper"])
    except KeyboardInterrupt:
        code = 0
    if code != 0:
        stop("The helper stopped. Read the error above and contact the project team.")


if __name__ == "__main__":
    main()
