"""`stepcap shell`: real bash / zsh through a pseudo-terminal (POSIX only)."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from stepcap.session import TERMINAL_FILE, load_session, write_json
from stepcap.shell import ShellError, parse_record, pick_shell
from stepcap.simulate import simulate
from stepcap.skill.run import SkillOptions, run_skill

GH = "ghp_" + "Z1x2C3v4B5n6M7a8S9d0F1g2H3j4K5l6Q7w8"
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="bash/zsh + pty")


def test_parse_record():
    ev = parse_record(b"1790000000,25\t1\t/tmp\tgit push origin main")
    assert ev == {
        "kind": "terminal",
        "time": 1790000000.25,
        "command": "git push origin main",
        "cwd": "/tmp",
        "exit": 1,
    }
    assert parse_record(b"garbage") is None
    assert parse_record(b"1\t0\t/\t   ") is None


def test_rejects_non_session_and_unknown_shell(tmp_path):
    from stepcap.shell import run_shell

    with pytest.raises(ShellError, match="not a stepcap session"):
        run_shell(tmp_path)
    if sys.platform != "win32":
        with pytest.raises(ShellError, match="bash or zsh"):
            pick_shell("fish")


def _drive(session: Path, shell: str, lines: list[str]) -> str:
    """Run `stepcap shell` in a pty, type ``lines``, return what was printed."""
    import pty
    import select

    pid, fd = pty.fork()
    if pid == 0:  # child
        os.environ["HOME"] = str(session.parent / "home")
        os.execv(
            sys.executable,
            [sys.executable, "-m", "stepcap", "shell", str(session), "--shell", shell],
        )
    out = b""

    def pump_until_prompts(n: int, timeout: float = 20.0) -> None:
        nonlocal out
        end = time.time() + timeout
        while out.count(b"[stepcap]") < n and time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.1)
            if r:
                try:
                    out += os.read(fd, 4096)
                except OSError:
                    return

    pump_until_prompts(1)
    for k, line in enumerate(lines, 2):
        os.write(fd, (line + "\n").encode())
        pump_until_prompts(k)  # the next prompt = the hook has run for this command
    os.write(fd, b"exit\n")
    os.waitpid(pid, 0)
    with contextlib.suppress(OSError):
        out += os.read(fd, 65536)
    return out.decode("utf-8", "replace")


@posix_only
@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_real_shell_records_commands(tmp_path, spec, shell):
    if not shutil.which(shell):
        pytest.skip(f"{shell} not installed")
    (tmp_path / "home").mkdir()
    session = tmp_path / "s"
    simulate(spec, session)
    meta = json.loads((session / "session.json").read_text("utf-8"))
    meta["t0_epoch"] = time.time() - 3600  # every command lands after the last step
    write_json(session / "session.json", meta)

    printed = _drive(session, shell, ["echo hello", "false", f"export T={GH}", "cd /"])
    assert "[stepcap]" in printed
    lines = (session / TERMINAL_FILE).read_text("utf-8").splitlines()
    cmds = [json.loads(x) for x in lines]
    assert [c["command"] for c in cmds] == [
        "echo hello",
        "false",
        "export T=[REDACTED:github-token]",
        "cd /",
    ]
    assert [c["exit"] for c in cmds] == [0, 1, 0, 0]
    assert GH not in (session / TERMINAL_FILE).read_text("utf-8")

    _, events = load_session(session)
    term = [e for e in events if e["kind"] == "terminal"]
    assert len(term) == 4 and all(e["seq"] == 13 for e in term)  # after the 12 steps
    res = run_skill(session, SkillOptions(out_dir=tmp_path / "out", name="demo"))
    body = (Path(res.skill_dir) / "SKILL.md").read_text("utf-8")
    assert "Ran in a terminal: `false` (exit status 1)" in body and res.ok


def test_simulated_terminal_event_is_placed_before_next_step(tmp_path, spec):
    spec = json.loads(json.dumps(spec))
    spec["events"].insert(2, {"kind": "terminal", "command": "git pull", "exit": 0})
    simulate(spec, tmp_path / "s")
    res = run_skill(tmp_path / "s", SkillOptions(out_dir=tmp_path / "out", name="demo"))
    body = (Path(res.skill_dir) / "SKILL.md").read_text("utf-8")
    step3 = body.split("3. **", 1)[1].split("4. **", 1)[0]
    assert "Ran in a terminal: `git pull`" in step3
