"""Build, smoke test, and archive the desktop app for this machine's OS and architecture."""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
APP = "Local AI Lab"


def platform_target():
    system = platform.system()
    arch = {"aarch64": "arm64", "arm64": "arm64", "amd64": "x64", "x86_64": "x64"}.get(platform.machine().lower())
    if system == "Darwin" and arch in {"arm64", "x64"}:
        return f"macos-{arch}"
    if system == "Windows" and arch == "x64":
        return "windows-x64"
    raise SystemExit("Build on a supported Mac (Apple silicon or Intel) or Windows x64 host.")


def build(work: Path):
    target = platform_target()
    dist = work / "dist"
    resources = work / "resources"
    work.mkdir(parents=True, exist_ok=True)
    if resources.exists():
        shutil.rmtree(resources)
    shutil.copytree(ROOT / "portal", resources / "portal", ignore=shutil.ignore_patterns("tests", "*.md", ".DS_Store"))
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", APP, "--paths", str(ROOT / "agent"), "--workpath", str(work / "build"),
        "--specpath", str(work), "--distpath", str(dist),
        "--add-data", f"{resources / 'portal'}:portal",
        "--add-data", f"{ROOT / 'agent/skill'}:agent/skill",
    ]
    if target.startswith("macos-"):
        command.extend(["--osx-bundle-identifier", "org.localailab.desktop"])
    subprocess.run(command + [str(ROOT / "scripts/local_lab_app.py")], cwd=work, check=True)
    mac = target.startswith("macos-")
    app = dist / (APP + ".app" if mac else APP)
    executable = app / "Contents" / "MacOS" / APP if mac else app / (APP + ".exe")
    subprocess.run([str(executable), "--self-test"], cwd=work, check=True, timeout=45)
    archive = work / f"Local-AI-Lab-{target}.zip"
    if mac:
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(archive)], check=True)
    else:
        with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=6) as out:
            for path in sorted(app.rglob("*")):
                if path.is_file():
                    out.write(path, path.relative_to(dist))
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".build" / "desktop")
    args = parser.parse_args()
    print(build(args.output_dir.resolve()))
