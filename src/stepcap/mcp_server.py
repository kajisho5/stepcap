"""`stepcap mcp`: recordings, guides and skills as MCP tools for agents (RM-044).

An agent (Claude Code, Codex, Gemini CLI, Cursor, ...) starts this server over
stdio and can then list recordings, read their steps (with the annotated
screenshot of any step as an image), build the guide, write / install a skill
and check a skill against its recording. Starting a recording is deliberately
not offered: capturing the user's screen and input stays a human decision.

Paths must be inside the allowed roots (``--root``, default: the window's
save folder ~/Documents/stepcap and the current directory). Needs the optional
MCP SDK: ``pip install "stepcap[mcp]"``.
"""

# No `from __future__ import annotations`: the MCP SDK reads the tool signatures,
# and the Image type is imported inside build_server().

from pathlib import Path
from typing import Any

from stepcap.session import SESSION_FILE, STEPS_FILE, is_session, read_json

INSTALL_HINT = 'pip install "stepcap[mcp]"'
IMAGE_WIDTH = 1280
_STEP_FIELDS = ("id", "kind", "title", "description", "app_name", "window_title", "keys")


class ToolError(Exception):
    pass


class Tools:
    """The tool implementations, independent of the MCP SDK (tested directly)."""

    def __init__(self, roots: list[Path] | None = None, home: Path | None = None) -> None:
        self.home = home  # base of user-scope skill folders (tests); default: home folder
        if roots is None:
            from stepcap.gui.controller import default_root

            roots = [default_root(), Path.cwd()]
        self.roots = [Path(r).expanduser().resolve() for r in roots]

    # -------------------------------------------------------------- paths
    def _inside(self, path: Path) -> Path:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self.roots[0] / p  # relative paths are relative to the first root
        p = p.resolve()
        if not any(p == r or r in p.parents for r in self.roots):
            allowed = ", ".join(str(r) for r in self.roots)
            raise ToolError(
                f"{p} is outside the allowed folders ({allowed}); see stepcap mcp --root"
            )
        return p

    def _session(self, session: str) -> Path:
        p = self._inside(Path(session))
        if not is_session(p):
            raise ToolError(f"{p} is not a stepcap recording (no events.jsonl)")
        return p

    # -------------------------------------------------------------- tools
    def list_sessions(self) -> dict[str, Any]:
        found = []
        for root in self.roots:
            if not root.is_dir():
                continue
            candidates = [root, *(p for p in root.iterdir() if p.is_dir())]
            for p in candidates:
                if not is_session(p):
                    continue
                meta = read_json(p / SESSION_FILE) if (p / SESSION_FILE).is_file() else {}
                stats = meta.get("stats") or {}
                found.append(
                    {
                        "session": str(p),
                        "title": meta.get("title"),
                        "started": meta.get("started"),
                        "steps": stats.get("events"),
                        "has_guide": (p / "guide.html").is_file(),
                        "voice_notes": (p / "voice.jsonl").is_file(),
                    }
                )
        found.sort(key=lambda s: s.get("started") or "", reverse=True)
        return {"roots": [str(r) for r in self.roots], "sessions": found}

    def get_steps(self, session: str) -> dict[str, Any]:
        from stepcap.skill import draft
        from stepcap.skill.recording import load_recording

        s = self._session(session)
        _, doc, events = load_recording(s)
        before, after, trailing = draft._context_by_step(doc, events)
        steps = []
        for n, st in enumerate(doc["steps"], 1):
            item: dict[str, Any] = {"number": n}
            item.update({k: st[k] for k in _STEP_FIELDS if st.get(k)})
            if st.get("element"):
                item["element"] = st["element"]
            if st.get("input"):
                item["input"] = st["input"]
            ctx = [draft._context_line(e) for e in before.get(st["id"], [])]
            ctx += [draft._context_line(e) for e in after.get(st["id"], [])]
            if any(ctx):
                item["context"] = [c for c in ctx if c]
            item["has_image"] = bool(st.get("screenshot"))
            steps.append(item)
        out: dict[str, Any] = {
            "session": str(s),
            "title": doc.get("title"),
            "lang": doc.get("lang"),
            "steps": steps,
        }
        tail = [c for c in (draft._context_line(e) for e in trailing) if c]
        if tail:
            out["after_last_step"] = tail
        return out

    def step_image(self, session: str, step: int) -> bytes:
        """PNG of step ``step`` (1-based) with the frame / ring / arrows, like the guide."""
        from PIL import Image

        from stepcap.build import annotate
        from stepcap.build import steps as steps_mod
        from stepcap.skill.recording import load_recording

        s = self._session(session)
        _, doc, _ = load_recording(s)
        if not 1 <= step <= len(doc["steps"]):
            raise ToolError(f"step must be 1-{len(doc['steps'])}")
        st = doc["steps"][step - 1]
        if not st.get("screenshot"):
            raise ToolError(f"step {step} has no screenshot")
        base = Image.open(steps_mod.ensure_work_copy(s, st["screenshot"])).convert("RGB")
        img, _ = annotate.render(
            base,
            st,
            step,
            IMAGE_WIDTH,
            None,
            doc.get("marker") or "box",
            bool(doc.get("spotlight")),
            bool(doc.get("auto_arrows", True)),
        )
        return annotate.encode(img, "png", 85)

    def build_guide(self, session: str, lang: str | None = None) -> dict[str, Any]:
        from stepcap.build.pipeline import BuildOptions, run_build

        s = self._session(session)
        if lang not in (None, "en", "ja"):
            raise ToolError("lang must be en or ja")
        res = run_build(s, BuildOptions(lang=lang))
        return {
            "session": str(s),
            "steps": res.steps,
            "guide_html": str(s / "guide.html"),
            "guide_md": str(s / "guide.md"),
            "checklist_html": str(s / "checklist.html"),
            "steps_json": str(s / STEPS_FILE),
        }

    def make_skill(
        self,
        session: str,
        out_dir: str | None = None,
        name: str | None = None,
        install: str = "none",
        scope: str = "user",
        replace: bool = False,
    ) -> dict[str, Any]:
        from stepcap.gui.controller import export_dir
        from stepcap.skill.run import SkillError, SkillOptions, run_skill

        s = self._session(session)
        out = self._inside(Path(out_dir)) if out_dir else export_dir(s) / "skill"
        try:
            res = run_skill(
                s,
                SkillOptions(
                    out_dir=out,
                    name=name,
                    install=install,
                    scope=scope,
                    force=replace,
                    home=self.home,
                ),
            )
        except SkillError as exc:
            raise ToolError(str(exc)) from exc
        data = res.to_dict()
        data["skill_md"] = str(Path(res.skill_dir) / "SKILL.md")
        return data

    def check_skill(self, skill_dir: str, session: str | None = None) -> dict[str, Any]:
        from stepcap.skill import coverage
        from stepcap.skill.validate import validate_skill

        d = self._inside(Path(skill_dir))
        problems, info = validate_skill(d)
        out: dict[str, Any] = {"skill_dir": str(d), "ok": not problems, "problems": problems}
        out.update(info)
        if session and not problems:
            out["coverage"] = coverage.check_dir(d, self._session(session)).to_dict()
        return out


INSTRUCTIONS = (
    "stepcap recordings are folders of steps (clicks, typing, notes) with screenshots, "
    "recorded by a person to show how a task is done. Use list_sessions to find one, "
    "get_steps to read it and step_image to look at a step. make_skill writes an Agent "
    "Skill (SKILL.md) from it and can install it for an agent; improve its text, then run "
    "check_skill with the session to see what the recording showed but the skill no "
    "longer mentions."
)


def build_server(tools: Tools):
    try:
        from mcp.server import MCPServer
        from mcp.server.mcpserver import Image
        from mcp.server.mcpserver.exceptions import ToolError as SDKToolError
    except ImportError as exc:
        raise ToolError(f"the MCP SDK is not installed ({exc}); {INSTALL_HINT}") from exc
    from stepcap import __version__

    server = MCPServer("stepcap", instructions=INSTRUCTIONS, version=__version__)

    def guard(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError as exc:  # shown to the agent as the tool's error message
            raise SDKToolError(str(exc)) from exc

    @server.tool()
    def list_sessions() -> dict[str, Any]:
        """List stepcap recordings in the allowed folders (newest first)."""
        return guard(tools.list_sessions)

    @server.tool()
    def get_steps(session: str) -> dict[str, Any]:
        """Steps of a recording: number, kind, title, description, app, window, clicked
        element, typed input variable, and context (URLs, terminal commands, narration)."""
        return guard(tools.get_steps, session)

    @server.tool()
    def step_image(session: str, step: int) -> Image:
        """Annotated screenshot (PNG) of one step (1-based), as in the guide."""
        return Image(data=guard(tools.step_image, session, step), format="png")

    @server.tool()
    def build_guide(session: str, lang: str | None = None) -> dict[str, Any]:
        """Build guide.html, guide.md and checklist.html in the recording folder (keeps
        edits in steps.json). lang: en or ja."""
        return guard(tools.build_guide, session, lang)

    @server.tool()
    def make_skill(
        session: str,
        out_dir: str | None = None,
        name: str | None = None,
        install: str = "none",
        scope: str = "user",
        replace: bool = False,
    ) -> dict[str, Any]:
        """Write an Agent Skill (SKILL.md + annotated references) from a recording. install:
        none, claude, agents (Codex / Gemini CLI / Cursor), codex, gemini, cursor or an agent
        from agents.toml; scope user or project. Existing skills are only replaced with
        replace=true. Validated; the result includes coverage of the recording."""
        return guard(tools.make_skill, session, out_dir, name, install, scope, replace)

    @server.tool()
    def check_skill(skill_dir: str, session: str | None = None) -> dict[str, Any]:
        """Validate a skill folder (Agent Skills spec, size, links, secrets). With session:
        also list what the recording showed but SKILL.md no longer mentions."""
        return guard(tools.check_skill, skill_dir, session)

    return server


def serve(roots: list[Path] | None = None) -> None:
    build_server(Tools(roots)).run("stdio")
