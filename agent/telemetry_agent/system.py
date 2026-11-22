"""Read-only facts about the learner's machine. Works on macOS, Windows, and Linux."""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil

GB = 1024 ** 3


def cpu_model() -> str:
    system = platform.system()
    try:
        if system == "Darwin":
            return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                  capture_output=True, text=True, timeout=5).stdout.strip()
        if system == "Linux":
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
        if system == "Windows":
            # platform.processor() gives "Intel64 Family 6 Model 198 ..."; the registry has the name people know.
            # Reading HKEY_LOCAL_MACHINE needs no administrator rights.
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                name = " ".join(str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).split())
            if name:
                return name
    except (OSError, subprocess.SubprocessError):
        pass
    return platform.processor() or platform.machine()


# Names Windows gives built-in graphics that share system memory, even when the brand also makes separate cards:
# "AMD Radeon(TM) Graphics" and "Intel(R) Arc(TM) Graphics" sit in the processor; "Radeon RX 7600" and "Arc A770" don't.
_DEDICATED = re.compile(r"nvidia|geforce|quadro|rtx|radeon.*\b(rx|pro)\b|\barc\b.*\b[ab]\d{3}", re.I)
GPU_UNCHECKED = "unchecked"


def gpu_name() -> str | None:
    """A read-only look for a dedicated graphics chip. Never installs or changes anything.
    Returns the chip's name, None when the laptop says it has none, or GPU_UNCHECKED when the lookup itself failed."""
    looked = False
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=5).stdout.strip().splitlines()
            looked = True
            if out:
                name, _, mib = out[0].partition(",")
                mib = mib.strip()
                return f"{name.strip()} ({round(int(mib) / 1024)} GB)" if mib.isdigit() else name.strip()
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    if platform.system() == "Windows":
        try:
            # Windows may print adapter names in a local code page; replace anything undecodable rather than fail.
            result = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8)
            if result.returncode == 0:
                looked = True
                names = [n.strip() for n in result.stdout.splitlines() if n.strip() and "basic" not in n.lower()]
                dedicated = [n for n in names if _DEDICATED.search(n)]
                if dedicated or names:
                    return (dedicated or names)[0]
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        return None if looked else GPU_UNCHECKED
    return None


def os_name() -> str:
    return {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}.get(platform.system(), platform.system())


def os_version() -> str:
    if platform.system() == "Darwin":
        return platform.mac_ver()[0]
    return platform.release()


def is_admin() -> bool:
    if hasattr(os, "geteuid"):
        return os.geteuid() == 0
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def hardware_info(models_dir: Path) -> dict:
    vm = psutil.virtual_memory()
    disk_path = models_dir if models_dir.exists() else Path.home()
    disk = shutil.disk_usage(disk_path)
    arch = platform.machine().lower()
    apple_silicon = platform.system() == "Darwin" and arch in ("arm64", "aarch64")
    gpu = None if apple_silicon else gpu_name()
    return {
        "os": os_name(),
        "os_version": os_version(),
        "arch": "arm64" if arch in ("arm64", "aarch64") else ("x64" if arch in ("x86_64", "amd64") else arch),
        "cpu_model": cpu_model(),
        "cpu_cores_physical": psutil.cpu_count(logical=False),
        "cpu_cores_logical": psutil.cpu_count(logical=True),
        "total_ram_gb": round(vm.total / GB, 1),
        "available_ram_gb": round(vm.available / GB, 1),
        "free_disk_gb": round(disk.free / GB, 1),
        "gpu": ("Apple GPU (Metal, shares system RAM)" if apple_silicon else
                "couldn't check (Windows didn't answer the graphics lookup)" if gpu == GPU_UNCHECKED else
                (gpu or "not detected (CPU inference assumed)")),
        "python": sys.version.split()[0],
        "running_as_admin": is_admin(),
        "platform_validation": "Checked on a physical Windows 11 laptop (Nov 14, 2026): setup, first reply and benchmark.",
        "gpu_detection": ("Apple unified-memory capability inferred from OS/architecture." if apple_silicon else
                          "Graphics chip name read from nvidia-smi or Windows; Ollama decides whether it uses it."),
    }


def _within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _tree_bytes(roots: list[Path], excluded: list[Path], seconds: float = 10.0) -> tuple[int, bool]:
    """Count logical file bytes once. A bounded/incomplete scan is never verified."""
    deadline, total, seen, complete, count = time.monotonic() + seconds, 0, set(), True, 0
    roots = sorted({p.resolve() for p in roots if p.exists()}, key=lambda p: len(p.parts))
    roots = [p for p in roots if not any(_within(p, other) for other in roots if other != p and len(other.parts) < len(p.parts))]
    for root in roots:
        if root.is_file():
            try:
                total += root.stat().st_size
            except OSError:
                complete = False
            continue
        def onerror(_):
            nonlocal complete
            complete = False
        for folder, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__"}
                       and not Path(folder, d).is_symlink()
                       and not any(_within(Path(folder, d).resolve(), e) for e in excluded)]
            for name in files:
                count += 1
                if count > 200000 or time.monotonic() > deadline:
                    return total, False
                p = Path(folder, name)
                try:
                    real = p.resolve()
                    if real in seen or any(_within(real, e) for e in excluded):
                        continue
                    if p.is_symlink() and not any(_within(real, r) for r in roots):
                        complete = False
                        continue
                    seen.add(real)
                    if p.is_file():
                        total += p.stat().st_size
                except OSError:
                    complete = False
    return total, complete


def installation_footprint(settings) -> dict:
    """Measure lab/runtime/Python logical bytes, separately from model inventory.

    Runtime discovery and scan incompleteness are explicit; estimates are not
    silently promoted to a verified whole-installation budget.
    """
    from .config import ROOT
    binary = shutil.which("ollama" if settings.runtime == "ollama" else "llama-server")
    runtime = settings.runtime_install_dir
    distribution_expanded = False
    if runtime is not None and runtime.is_file():
        # A portable binary needs its sibling libraries/resources. Counting just
        # the executable would silently understate the installation footprint.
        runtime = runtime.parent
        distribution_expanded = True
    if runtime is None and binary:
        runtime = Path(binary).resolve()
        app = next((p for p in runtime.parents if p.suffix == ".app"), None)
        if app:
            runtime = app
        elif runtime.parent.name == "bin" and runtime.parent.parent.name not in {"usr", "local", "homebrew"}:
            runtime = runtime.parent.parent
        elif runtime.parent not in {Path("/usr/bin"), Path("/usr/local/bin"), Path("/opt/homebrew/bin"), Path("/bin")}:
            runtime = runtime.parent
        else:
            # A system-wide bin directory does not establish where the complete
            # runtime distribution and libraries live.
            runtime = None
    if runtime is None and settings.runtime == "ollama":
        candidates = [Path("/Applications/Ollama.app"), Path.home() / "Applications/Ollama.app"]
        if os.environ.get("LOCALAPPDATA"):
            candidates.append(Path(os.environ["LOCALAPPDATA"]) / "Programs/Ollama")
        runtime = next((p for p in candidates if p.exists()), None)
    # The project environment is part of this lab. A pre-existing base Python
    # distribution (for example a user's Anaconda installation) is not: it can
    # contain unrelated packages and make a bounded scan fail on a normal setup.
    roots = [ROOT, Path(sys.prefix)]
    if runtime is not None:
        roots.append(runtime)
    excluded = [settings.models_dir.resolve(), settings.runtime_models_dir.resolve(), settings.results_dir.resolve()]
    if Path(sys.prefix).resolve() != Path(sys.base_prefix).resolve():
        # A venv commonly symlinks its Python executable to the pre-existing
        # base interpreter. That known prerequisite is outside this project's
        # footprint; do not mistake the symlink for an unknown external file.
        excluded.append(Path(sys.base_prefix).resolve())
        # Some environments retain a second versioned Python link from the
        # interpreter recorded when the venv was created. It can differ from
        # sys.base_prefix after a shell activates another Python distribution.
        # Exclude only that exact, verified interpreter file, never its whole
        # distribution or any unrelated external link.
        config = Path(sys.prefix) / "pyvenv.cfg"
        try:
            values = {key.strip(): value.strip() for key, value in
                      (line.split("=", 1) for line in config.read_text(encoding="utf-8").splitlines() if "=" in line)}
            home_path = Path(values["home"].strip())
            executable_path = Path(values["executable"].strip())
            home, executable = home_path.resolve(), executable_path.resolve()
            if (home_path.is_absolute() and executable_path.is_absolute() and executable.is_file()
                    and executable.name.lower().startswith("python")
                    and _within(executable, home)):
                excluded.append(executable)
        except (OSError, KeyError, ValueError):
            pass
    size, complete = _tree_bytes(roots, excluded)
    known_runtime = runtime is not None and runtime.exists()
    return {"non_model_gb": round(size / GB, 6), "verified": complete and known_runtime,
            "basis": "Measured logical bytes of lab, project Python environment and discovered runtime; excludes a pre-existing base Python distribution, model inventory and result files.",
            "missing": ([] if known_runtime else ["runtime installation location"]) + ([] if complete else ["complete filesystem scan"]),
            "runtime_file_expanded_to_distribution": distribution_expanded,
            "model_storage_location_source": "explicit OLLAMA_MODELS" if "OLLAMA_MODELS" in os.environ else "conventional default; server storage location not independently verified"}
