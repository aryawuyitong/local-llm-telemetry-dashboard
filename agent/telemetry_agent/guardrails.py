"""Safety checks on what the agent tells the learner.

The project promises the agent never suggests:
  * admin/root commands          (could change how the OS itself works)
  * deleting or overwriting files (could destroy the learner's data)
  * weakening OS security        (Gatekeeper, SIP, Defender, certificate checks)
  * piping internet scripts into a shell
  * models that aren't on the allow-list (could blow the 10 GB budget)
  * asking for, or repeating, secrets (tokens, passwords)

Commands are only checked where they look like commands (code blocks, `inline
code`, or lines that start with a command word), so a sentence like
"you don't need sudo" is not flagged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import load_allow_list


@dataclass
class Violation:
    rule: str
    snippet: str
    reason: str


COMMAND_WORDS = (
    "sudo", "su", "rm", "rmdir", "del", "erase", "rd", "format", "mkfs", "diskpart", "dd", "shred",
    "chmod", "chown", "curl", "wget", "iwr", "invoke-webrequest", "pip", "pip3", "python", "python3",
    "py", "ollama", "hf", "huggingface-cli", "set-executionpolicy", "remove-item", "reg", "regedit",
    "runas", "start-process", "xattr", "spctl", "csrutil", "set-mppreference", "netsh", "launchctl",
    "powershell", "cmd", "./llama-server", ".\\llama-server.exe", "llama-server", "export", "set",
    "taskkill", "kill", "killall", "pkill", "stop-process", "netstat", "lsof",
)

COMMAND_RULES = [
    ("admin", r"(^|[\s;&|(])(sudo|runas|doas)\b|-Verb\s+RunAs|\bsu\s+(-|root)",
     "needs administrator/root rights; the lab must work as a normal user"),
    ("delete", r"(^|[\s;&|(])(rm|rmdir|del|erase|rd|shred|unlink)\s|Remove-Item|\bformat\s+[a-z]:|\bmkfs|\bdiskpart|\bdd\s+if=",
     "deletes or erases files; the agent never deletes anything"),
    ("system_files", r"/etc/|/System/|C:\\Windows|System32|HKLM|\breg\s+(add|delete)|\bregedit",
     "changes protected system files or settings"),
    ("permissions", r"chmod\s+(-R\s+)?[0-7]*777|\bchown\b",
     "opens up file permissions in a risky way"),
    ("security_off", r"spctl\s+--master-disable|csrutil\s+disable|Set-MpPreference|"
                     r"Set-ExecutionPolicy(?![^\n`]*-Scope\s+CurrentUser)|--break-system-packages|"
                     r"--trusted-host|verify\s*=\s*False|PYTHONHTTPSVERIFY\s*=\s*0|NODE_TLS_REJECT_UNAUTHORIZED",
     "turns off an operating-system or network security protection"),
    ("pipe_to_shell", r"(curl|wget|iwr|Invoke-WebRequest)\b[^\n|]*\|\s*(sudo\s+)?(sh|bash|zsh|iex|Invoke-Expression)\b",
     "runs a script straight from the internet without letting the learner read it"),
    ("kill_process", r"\btaskkill\b|\bkill\s+-9\b|\bkillall\b|\bpkill\b|Stop-Process",
     "force-stops processes, which can lose the learner's unsaved work"),
]

PROSE_RULES = [
    ("admin", r"run (it |the terminal |powershell |cmd )?as (an )?administrator|with admin(istrator)? (rights|privileges)|log in as root",
     "tells the learner to use administrator rights"),
    ("security_off", r"(disable|turn off|switch off)\s+(gatekeeper|sip|system integrity protection|windows defender|defender|antivirus|the firewall|firewall|ssl verification|certificate (checks|verification))",
     "tells the learner to turn off a security protection"),
    ("ask_secret", r"(give|send|tell|share with)\s+(me|us)\s+(your\s+)?[\w ]{0,20}?(token|password|api key|access key)|"
                   r"(paste|share|type|enter|send)\s+(your\s+)?[\w ]{0,20}?(token|password|api key|access key)\s+"
                   r"(here|to me|with me|in(to)?\s+(this|the)\s+chat)",
     "asks the learner to send a secret to the assistant"),
]

NEGATIONS = re.compile(r"\b(not|never|don't|do not|no need|avoid|without|instead of|won't|shouldn't|can't)\b", re.I)

SECRET_PATTERNS = [
    r"\bhf_[A-Za-z0-9]{20,}\b",                 # Hugging Face token
    r"\bsk-[A-Za-z0-9_-]{20,}\b",               # OpenAI-style key
    r"\bAKIA[0-9A-Z]{16}\b",                    # AWS access key
    r"(?i)\b(password|passwd|pwd|passcode)\b\s*(?:is|:|=)\s*\S+",
]

_MODEL_CMD = re.compile(r"ollama\s+(?:pull|run)\s+([\w.:/-]+)|(?:hf|huggingface-cli)\s+download\s+([\w.-]+/[\w.-]+)", re.I)


def _allowed_models() -> tuple[set[str], set[str]]:
    allow = load_allow_list()
    return {m["ollama_tag"].lower() for m in allow}, {m["hf_repo"].lower() for m in allow}


def command_candidates(text: str) -> list[str]:
    """Pull out the parts of a reply that look like commands."""
    cands = []
    for block in re.findall(r"```[^\n]*\n(.*?)```", text, re.S):
        cands += [ln for ln in block.splitlines() if ln.strip()]
    cands += re.findall(r"`([^`\n]+)`", text)
    for line in text.splitlines():
        first = re.sub(r"^\s*(\$|>|PS>|PS [^>]*>|\d+[.)])\s*", "", line).strip().split(" ")[0].lower()
        if first in COMMAND_WORDS:
            cands.append(line.strip())
    return cands


def check(text: str) -> list[Violation]:
    """Return every safety rule the text breaks."""
    found: list[Violation] = []
    tags, repos = _allowed_models()
    for cmd in command_candidates(text):
        for rule, pattern, reason in COMMAND_RULES:
            if re.search(pattern, cmd, re.I):
                found.append(Violation(rule, cmd.strip()[:120], reason))
        for m in _MODEL_CMD.finditer(cmd):
            tag, repo = (m.group(1) or "").lower(), (m.group(2) or "").lower()
            if (tag and tag not in tags) or (repo and repo not in repos):
                found.append(Violation("not_allow_listed", cmd.strip()[:120],
                                       "downloads a model that isn't on the allow-list (may exceed the 10 GB budget)"))
    for sentence in re.split(r"(?<=[.!?\n])\s+", text):
        if NEGATIONS.search(sentence):
            continue
        for rule, pattern, reason in PROSE_RULES:
            if re.search(pattern, sentence, re.I):
                found.append(Violation(rule, sentence.strip()[:120], reason))
    for pattern in SECRET_PATTERNS:
        for m in re.finditer(pattern, text):
            found.append(Violation("secret_echo", "[secret]", "repeats a secret such as a token or password"))
    # one violation per (rule, snippet)
    unique = {(v.rule, v.snippet): v for v in found}
    return list(unique.values())


def redact_secrets(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = re.sub(pattern, "[REDACTED]", text)
    return text


def scrub(text: str, violations: list[Violation]) -> str:
    """Last resort: remove the offending lines from a reply."""
    out = redact_secrets(text)
    for v in violations:
        if v.snippet and v.snippet != "[secret]":
            out = "\n".join(f"[removed by safety guardrail: {v.reason}]" if v.snippet in line else line
                            for line in out.splitlines())
    return out


SYSTEM_RULES = """\
## Safety rules (always)
- Never suggest sudo, runas, "Run as administrator", or anything that needs admin rights. Everything works as a normal user (use --user or a virtual environment for pip).
- Never tell the learner to delete, erase, or overwrite files or folders. If space is needed, suggest a smaller model instead.
- Never suggest turning off Gatekeeper, SIP, Windows Defender, antivirus, the firewall, or certificate checks.
- Never pipe a downloaded script into a shell (curl ... | sh).
- Never force-stop processes (taskkill /F, kill -9, killall). If a port is busy, use a different port.
- Only suggest models from the allow-list (recommend_model). Stay within the 10 GB disk budget.
- Never ask for, store, or repeat tokens or passwords. If the learner pastes one, tell them to revoke it.
- The learner runs every command themselves. You explain, they execute.
"""
