"""`stepcap shell SESSION_DIR`: a shell whose commands become ``terminal`` events.

Start it next to a running ``stepcap record`` (or afterwards, for the same
session). Every command you run is sent - through an inherited pipe, never a
temporary file - to this process, which masks secrets and appends it to
``SESSION_DIR/terminal.jsonl``. ``load_session`` merges those lines into the
event list by time, so ``stepcap skill`` shows them as "Ran in a terminal".

Recorded per command: the command line, its exit status, the working directory
and the wall-clock time it finished. Output is not recorded (it can contain
anything and cannot be masked reliably). Commands starting with a space are
skipped when the shell ignores them in history (bash ``HISTCONTROL=ignorespace``,
zsh ``setopt HIST_IGNORE_SPACE``).

Supported: bash and zsh on macOS and Linux. Windows (PowerShell) is not
supported yet.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from stepcap.session import TERMINAL_FILE, EventWriter, SessionError, is_session

MAX_COMMAND = 2000
SHELLS = ("bash", "zsh")

# Each hook writes "<epoch>\t<status>\t<cwd>\t<command>\0" to fd $STEPCAP_FD.
BASH_RC = r"""
[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"
__stepcap_hist=""
__stepcap_ready=""
__stepcap_log() {
  local st=$? line num="" cmd=""
  line=$(HISTTIMEFORMAT= builtin history 1)
  if [[ $line =~ ^[[:space:]]*([0-9]+)[*[:space:]]+(.*)$ ]]; then
    num=${BASH_REMATCH[1]}; cmd=${BASH_REMATCH[2]}
  fi
  if [ -n "$__stepcap_ready" ] && [ -n "$num" ] && [ "$num" != "$__stepcap_hist" ]; then
    printf '%s\t%s\t%s\t%s\0' "${EPOCHREALTIME:-$(date +%s)}" "$st" "$PWD" "$cmd" \
      >&"$STEPCAP_FD" 2>/dev/null
  fi
  __stepcap_hist=$num; __stepcap_ready=1
  return $st
}
PROMPT_COMMAND="__stepcap_log${PROMPT_COMMAND:+;$PROMPT_COMMAND}"
PS1="[stepcap] ${PS1:-\$ }"
"""

ZSH_ENV = r"""
if [ -f "$STEPCAP_HOME/.zshenv" ]; then
  __stepcap_zd=$ZDOTDIR; . "$STEPCAP_HOME/.zshenv"; ZDOTDIR=$__stepcap_zd
fi
"""
ZSH_RC = r"""
if [ -f "$STEPCAP_HOME/.zshrc" ]; then
  __stepcap_zd=$ZDOTDIR; ZDOTDIR="$STEPCAP_HOME"; . "$STEPCAP_HOME/.zshrc"; ZDOTDIR=$__stepcap_zd
fi
zmodload zsh/datetime 2>/dev/null
__stepcap_cmd=""
__stepcap_preexec() { __stepcap_cmd=$1 }
__stepcap_precmd() {
  local st=$?
  if [[ -n $__stepcap_cmd ]]; then
    printf '%s\t%s\t%s\t%s\0' "${EPOCHREALTIME:-$(date +%s)}" "$st" "$PWD" \
      "$__stepcap_cmd" >&$STEPCAP_FD 2>/dev/null
  fi
  __stepcap_cmd=""
}
autoload -Uz add-zsh-hook
add-zsh-hook preexec __stepcap_preexec
add-zsh-hook precmd __stepcap_precmd
PROMPT="[stepcap] ${PROMPT:-%# }"
"""


class ShellError(SessionError):
    pass


def pick_shell(requested: str | None) -> tuple[str, str]:
    """Return (kind, executable) for bash or zsh."""
    if sys.platform == "win32":
        raise ShellError(
            "stepcap shell is not available on Windows yet (bash and zsh on macOS / Linux only)"
        )
    candidates = [requested] if requested else [os.environ.get("SHELL") or "", "bash", "zsh"]
    for cand in candidates:
        if not cand:
            continue
        exe = cand if os.path.sep in cand else shutil.which(cand)
        kind = Path(cand).name
        if exe and kind in SHELLS and Path(exe).exists():
            return kind, exe
    if requested:
        raise ShellError(f"unsupported or missing shell {requested!r}; use bash or zsh")
    raise ShellError("neither bash nor zsh was found")


def parse_record(raw: bytes) -> dict[str, Any] | None:
    try:
        when, status, cwd, cmd = raw.decode("utf-8", errors="replace").split("\t", 3)
        t = float(when.replace(",", "."))  # EPOCHREALTIME uses the locale's decimal mark
    except ValueError:
        return None
    cmd = cmd.strip()
    if not cmd:
        return None
    ev: dict[str, Any] = {
        "kind": "terminal",
        "time": round(t, 3),
        "command": cmd[:MAX_COMMAND],
        "cwd": cwd,
    }
    with contextlib.suppress(ValueError):
        ev["exit"] = int(status)
    return ev


def _reader(fd: int, writer: EventWriter, counter: list[int]) -> None:
    buf = b""
    with os.fdopen(fd, "rb", buffering=0) as fh:
        while True:
            chunk = fh.read(4096)
            if not chunk:
                break
            buf += chunk
            *records, buf = buf.split(b"\0")
            for raw in records:
                ev = parse_record(raw)
                if ev is not None:
                    writer.write(ev)  # EventWriter masks secrets before writing
                    counter[0] += 1


def run_shell(session: Path, shell: str | None = None) -> dict[str, Any]:
    session = Path(session)
    if not is_session(session):
        raise ShellError(
            f"{session} is not a stepcap session; start `stepcap record -o {session}` first"
        )
    kind, exe = pick_shell(shell)
    read_fd, write_fd = os.pipe()
    writer = EventWriter(session / TERMINAL_FILE)
    counter = [0]
    reader = threading.Thread(target=_reader, args=(read_fd, writer, counter), daemon=True)
    reader.start()
    env = dict(os.environ, STEPCAP_FD=str(write_fd), STEPCAP_SESSION=str(session))
    with tempfile.TemporaryDirectory(prefix="stepcap-shell-") as tmp:
        if kind == "bash":
            rc = Path(tmp) / "bashrc"
            rc.write_text(BASH_RC, encoding="utf-8")
            cmd = [exe, "--rcfile", str(rc), "-i"]
        else:
            (Path(tmp) / ".zshenv").write_text(ZSH_ENV, encoding="utf-8")
            (Path(tmp) / ".zshrc").write_text(ZSH_RC, encoding="utf-8")
            env["STEPCAP_HOME"] = os.environ.get("ZDOTDIR") or str(Path.home())
            env["ZDOTDIR"] = tmp
            cmd = [exe, "-i"]
        print(
            f"stepcap: commands in this {kind} are added to {session} (secrets masked, output "
            "not recorded). Type `exit` to finish.",
            file=sys.stderr,
            flush=True,
        )
        try:
            proc = subprocess.run(cmd, env=env, pass_fds=(write_fd,), check=False)
        finally:
            os.close(write_fd)
            reader.join(5)
            writer.close()
    print(
        f"stepcap: {counter[0]} command(s) recorded in {session / TERMINAL_FILE}", file=sys.stderr
    )
    return {"session": str(session), "shell": kind, "commands": counter[0], "exit": proc.returncode}
