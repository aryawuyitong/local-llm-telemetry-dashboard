"""Start here on Windows: double-click this file.

It does the same as agent\\Start Lab Helper.bat, but as a plain Python file, so Windows Smart App
Control lets it run (it opens with Python, which is signed, instead of an unsigned batch file).
It is plain text, so you can read it before you run it.

On the first run it creates a private Python environment in agent\\.venv and installs the one
package the lab needs (psutil). It installs nothing anywhere else, needs no administrator rights
and changes no settings. Delete agent\\.venv to undo it.
"""
import os
import subprocess
import sys
from pathlib import Path

AGENT = Path(__file__).resolve().parent / "agent"
LAB_PYTHON = AGENT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def stop(message: str) -> None:
    print(message)
    input("Press Enter to close this window.")
    sys.exit(1)


def main() -> None:
    if sys.version_info < (3, 11):
        stop(f"The lab needs Python 3.11 or newer, and this is Python {sys.version.split()[0]}.\n"
             "Install the latest Python from https://www.python.org/downloads/ , then double-click this file again.")
    if not (AGENT / "requirements.txt").is_file():
        stop("The agent folder is missing. Download the lab again and unzip the whole folder.")
    os.chdir(AGENT)

    if not LAB_PYTHON.is_file():
        print("First run: creating the lab's private Python environment in this folder.")
        print("This only adds a .venv folder in the agent folder. Delete that folder to undo it.")
        if subprocess.call([sys.executable, "-m", "venv", ".venv"]) != 0:
            stop("Setup failed. Delete the agent\\.venv folder, then try again. If it fails again, send this window's text to the team.")
        if subprocess.call([str(LAB_PYTHON), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                            "-r", "requirements.txt"]) != 0:
            stop("Installing the lab's package failed. Check your internet connection, delete the agent\\.venv folder, then try again.")

    check = "import sys, psutil; assert sys.version_info >= (3, 11)"
    if subprocess.call([str(LAB_PYTHON), "-c", check], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        stop("The agent\\.venv folder is missing Python 3.11+ or a package. Delete that folder, then double-click this file again.")

    try:
        code = subprocess.call([str(LAB_PYTHON), "-m", "telemetry_agent.helper"])
    except KeyboardInterrupt:
        code = 0
    if code != 0:
        stop("The helper stopped. Read the error above and contact the project team.")


if __name__ == "__main__":
    main()
