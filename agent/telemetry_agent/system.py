"""Read-only facts about the learner's machine. Works on macOS, Windows, and Linux."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
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
    except (OSError, subprocess.SubprocessError):
        pass
    return platform.processor() or platform.machine()


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
        "gpu": "Apple GPU (Metal, shares system RAM)" if apple_silicon else "not detected (CPU inference assumed)",
        "python": sys.version.split()[0],
        "running_as_admin": is_admin(),
    }
