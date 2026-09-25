"""The `stepcap app` window (tkinter). Logic lives in ``controller``, the look in ``theme``.

Views in one window:
  home       where to save, Start, options (folded), recent recordings; tick two or
             more recent recordings to combine them into one skill or compare them
  recording  a compact always-on-top bar: time, step count, Pause, Undo, Note, Stop;
             its screen rectangle is sent to the recorder so clicking it is not a step
             and it is painted out of the screenshots
  finished   two groups: for AI agents (create SKILL.md, add it to Claude Code / Codex,
             optionally generalise it with the agent CLI first) and for people (open the
             guide, printable checklist, edit steps, share)
  combined   the agent group for several recordings of the same task

Slow work (building, the agent CLI) runs on a thread; its result comes back through
``self.jobs`` and is applied in ``poll`` on the Tk thread.
"""

from __future__ import annotations

import base64
import contextlib
import io
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from stepcap.gui import controller as ctl
from stepcap.gui import theme as theme_mod

POLL_MS = 100
ICONS = ("icon-256.png", "icon-32.png")  # stepcap/assets, largest first
BAR_MARGIN = 6  # extra pixels around the bar that also do not count as steps
RECENT = 6  # recent recordings on the home view
WRAP = 560


def set_icon(root: tk.Misc) -> list[tk.PhotoImage]:
    """Window / taskbar icon. Without the files (or with an old Tk) only the icon is lost."""
    icons: list[tk.PhotoImage] = []
    with contextlib.suppress(Exception):
        base = resources.files("stepcap") / "assets"
        for name in ICONS:
            data = base64.b64encode((base / name).read_bytes()).decode("ascii")
            icons.append(tk.PhotoImage(master=root, data=data))
        root.iconphoto(True, *icons)  # type: ignore[attr-defined]
    return icons  # keep a reference: Tk forgets images Python garbage-collects


def header_icon(root: tk.Misc, size: int = 44) -> tk.PhotoImage | None:
    """The app icon scaled smoothly for the home header (Pillow, no ImageTk needed)."""
    with contextlib.suppress(Exception):
        from PIL import Image

        src = resources.files("stepcap") / "assets" / ICONS[0]
        img = Image.open(io.BytesIO(src.read_bytes())).convert("RGBA")
        buf = io.BytesIO()
        img.resize((size, size), Image.Resampling.LANCZOS).save(buf, "PNG")
        return tk.PhotoImage(master=root, data=base64.b64encode(buf.getvalue()).decode("ascii"))
    return None


class App:
    def __init__(self, root: tk.Tk, lang: str | None = None) -> None:
        self.root = root
        self.lang = lang or ctl.ui_lang()
        self.t = ctl.TEXTS[self.lang]
        self.theme = theme_mod.apply(root)
        self.rec: ctl.RecorderProcess | None = None
        self.session: Path | None = None
        self.also: list[Path] = []  # more recordings for one combined skill
        self.steps = 0
        self.started = 0.0
        self.paused_for = 0.0
        self.paused_at: float | None = None
        self.last_exclude: tuple[int, int, int, int] | None = None
        root.title("stepcap")
        self.icons = set_icon(root)
        self.logo = header_icon(root)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root_dir = tk.StringVar(value=str(ctl.default_root()))
        self.name = tk.StringVar(value=ctl.new_session_name())
        self.opt_typing = tk.BooleanVar(value=False)
        self.opt_urls = tk.BooleanVar(value=False)
        self.opt_clip = tk.BooleanVar(value=False)
        self.opt_voice = tk.BooleanVar(value=False)
        self.voice_hint = ctl.voice_hint()
        self.guide_lang = tk.StringVar(value=self.lang)
        self.status = tk.StringVar(value="")
        self.status_label: ttk.Label | None = None
        self.status_pack: dict[str, Any] = {}
        self.status.trace_add("write", self._status_changed)
        self.refine = tk.BooleanVar(value=False)
        self.adv_open = False
        self.picked: list[Path] = []
        self.pick_vars: list[tk.BooleanVar] = []  # kept: a collected variable greys the box
        self.action_buttons: list[ttk.Button] = []
        self.sync_actions: Callable[[], None] = lambda: None
        self.jobs: queue.Queue[Callable[[], None]] = queue.Queue()
        self.busy = False
        self.frame: ttk.Frame | None = None
        self.show_home()
        root.after(POLL_MS, self.poll)

    # ------------------------------------------------------------------ helpers
    def _new_frame(self, padding: Any = 22) -> ttk.Frame:
        if self.frame is not None:
            self.frame.destroy()
        self.frame = ttk.Frame(self.root, padding=padding)
        self.frame.pack(fill="both", expand=True)
        self.action_buttons = []
        self.sync_actions = lambda: None
        self.status_label = None
        return self.frame

    def _muted(self, parent: tk.Misc, text: str, **kw: Any) -> ttk.Label:
        return ttk.Label(
            parent, text=text, font=self.theme.fonts["small"], foreground=self.theme.muted, **kw
        )

    def _para(self, parent: tk.Misc, text: str, width: int = WRAP, muted: bool = True) -> ttk.Label:
        """A paragraph, broken into lines like Japanese needs (see ``theme.wrap``)."""
        font = self.theme.fonts["small" if muted else "body"]
        text = theme_mod.wrap(text, tkfont.Font(root=self.root, font=font), width)
        if muted:
            return self._muted(parent, text, justify="left")
        return ttk.Label(parent, text=text, font=font, justify="left")

    def _status_row(self, parent: tk.Misc, **pack: Any) -> ttk.Label:
        """The status line of the view; packed with ``pack`` only while it has text."""
        self.status_label = ttk.Label(parent, justify="left", font=self.theme.fonts["body"])
        self.status_pack = pack
        self._status_changed()
        return self.status_label

    def _status_changed(self, *_: Any) -> None:
        label = self.status_label
        if label is None or not label.winfo_exists():
            return
        font = tkfont.Font(root=self.root, font=self.theme.fonts["body"])
        label.configure(text=theme_mod.wrap(self.status.get(), font, WRAP))
        if self.status.get() and not label.winfo_manager():
            label.pack(**self.status_pack)
        elif not self.status.get() and label.winfo_manager():
            label.pack_forget()

    def say(self, text: str, error: bool = False) -> None:
        """The status line; red for problems."""
        self.status.set(text)
        if self.status_label is not None and self.status_label.winfo_exists():
            self.status_label.configure(foreground=self.theme.red if error else "")

    def _dot(self, parent: tk.Misc, size: int, color: str) -> tk.Canvas:
        c = tk.Canvas(parent, width=size, height=size, highlightthickness=0, bg=self.theme.bg)
        c.create_oval(2, 2, size - 2, size - 2, fill=color, outline="", tags="dot")
        return c

    # ------------------------------------------------------------------ home
    def show_home(self, fresh: bool = True) -> None:
        t, f = self.t, self._new_frame()
        self.root.attributes("-topmost", False)
        self.root.resizable(True, True)
        self.root.unbind("<Configure>")
        if fresh:
            self.name.set(ctl.new_session_name())
        fonts = self.theme.fonts

        top = ttk.Frame(f)
        top.pack(fill="x", pady=(0, 14))
        if self.logo is not None:
            tk.Label(top, image=self.logo, bd=0, bg=self.theme.bg).pack(side="left", padx=(0, 12))
        head = ttk.Frame(top)
        head.pack(side="left", fill="x", expand=True)
        ttk.Label(head, text="stepcap", font=fonts["brand"]).pack(anchor="w")
        self._para(head, t["subtitle"], 470).pack(anchor="w")

        form = ttk.Frame(f)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text=t["save_to"]).grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.root_dir, font=fonts["body"]).grid(
            row=0, column=1, sticky="ew", padx=(12, 8), pady=4
        )
        ttk.Button(form, text=t["change"], command=self.choose_dir).grid(row=0, column=2, pady=4)
        ttk.Label(form, text=t["name"]).grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.name, font=fonts["body"]).grid(
            row=1, column=1, sticky="ew", padx=(12, 8), pady=4
        )

        ttk.Button(f, text=t["start"], style="Big.Accent.TButton", command=self.start).pack(
            fill="x", pady=(18, 6)
        )
        hint = self._muted(f, t["hint_keys"])
        hint.pack(anchor="center")
        self._status_row(f, anchor="w", pady=(6, 0), after=hint)

        self._options(f)

        sessions = ctl.recent_sessions(Path(self.root_dir.get()).expanduser())[:RECENT]
        self.recent = sessions
        self.picked, self.pick_vars = [], []
        if sessions:
            ttk.Separator(f).pack(fill="x", pady=16)
            ttk.Label(f, text=t["recent"], font=fonts["h"]).pack(anchor="w")
            if len(sessions) > 1:
                self._para(f, t["recent_hint"]).pack(anchor="w", pady=(0, 4))
            for s in sessions:
                self._recent_row(f, s)
            if len(sessions) > 1:
                row = ttk.Frame(f)
                row.pack(fill="x", pady=(8, 0))
                self.combine_btn = ttk.Button(row, command=self.combine)
                self.combine_btn.pack(side="left")
                self.compare_btn = ttk.Button(row, text=t["compare"], command=self.compare)
                self.compare_btn.pack(side="left", padx=6)
                self.action_buttons = [self.combine_btn, self.compare_btn]
                self.sync_actions = self._sync_picks
                self._sync_picks()

        foot = ttk.Frame(f)
        foot.pack(fill="x", pady=(18, 0))
        ttk.Button(foot, text=t["check"], command=self.run_doctor).pack(side="left")
        self.fit_on_screen()

    def _options(self, f: ttk.Frame) -> None:
        """Folded "Options": what else to record and the guide language, with a summary."""
        t = self.t
        adv = ttk.Frame(f)
        adv.pack(fill="x", pady=(14, 0))
        toggle = ttk.Button(adv, style="Toolbutton")
        toggle.pack(anchor="w")
        summary = self._muted(adv, "")
        box = ttk.Frame(adv, padding=(18, 4, 0, 0))
        options = (
            (self.opt_typing, "opt_typing", "short_typing"),
            (self.opt_urls, "opt_urls", "short_urls"),
            (self.opt_clip, "opt_clip", "short_clip"),
            (self.opt_voice, "opt_voice", "short_voice"),
        )
        for var, key, _ in options:
            text = t[key]
            if key == "opt_voice" and self.voice_hint:
                text += " " + t["voice_missing"].format(hint=self.voice_hint)
            cb = ttk.Checkbutton(box, text=text, variable=var)
            cb.pack(anchor="w", pady=2)
            if key == "opt_voice" and self.voice_hint:
                self.opt_voice.set(False)
                cb.state(["disabled"])
        lang = ttk.Frame(box)
        lang.pack(anchor="w", pady=(6, 0))
        ttk.Label(lang, text=t["guide_lang"]).pack(side="left")
        shown = tk.StringVar(value=ctl.LANG_NAMES.get(self.guide_lang.get(), "English"))
        combo = ttk.Combobox(
            lang, textvariable=shown, values=list(ctl.LANG_NAMES.values()), width=10
        )
        combo.state(["readonly"])
        combo.pack(side="left", padx=10)
        self._lang_shown = shown  # kept for the combobox

        def refresh(*_: Any) -> None:
            code = {v: k for k, v in ctl.LANG_NAMES.items()}.get(shown.get(), "en")
            self.guide_lang.set(code)
            on = [t[short] for var, _, short in options if var.get()]
            extra = t["list_sep"].join(on) if on else t["adv_none"]
            summary.configure(
                text=f"{t['adv_extra']}: {extra}   /   {t['guide_lang']}: {shown.get()}"
            )
            toggle.configure(text=("▾ " if self.adv_open else "▸ ") + t["advanced"])

        def flip() -> None:
            self.adv_open = not self.adv_open
            place()
            self.fit_on_screen()

        def place() -> None:
            summary.pack_forget()
            box.pack_forget()
            if self.adv_open:
                box.pack(fill="x")
            else:
                summary.pack(anchor="w", padx=(18, 0))
            refresh()

        toggle.configure(command=flip)
        combo.bind("<<ComboboxSelected>>", refresh)
        for var, _, _ in options:
            var.trace_add("write", refresh)
        place()

    def _recent_row(self, f: ttk.Frame, s: Path) -> None:
        t = self.t
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(6, 0))
        var = tk.BooleanVar(value=False)
        self.pick_vars.append(var)

        def toggled() -> None:
            if var.get():
                self.picked.append(s)
            elif s in self.picked:
                self.picked.remove(s)
            self._sync_picks()

        ttk.Checkbutton(row, variable=var, command=toggled).pack(side="left")
        ttk.Label(row, text=s.name).pack(side="left")
        meta = f"{ctl.when_text(ctl.session_time(s), t)}  ·  "
        meta += t["steps"].format(n=ctl.step_count(s))
        self._muted(row, meta).pack(side="left", padx=10)
        ttk.Button(row, text=t["open"], command=lambda: self.open_session(s)).pack(side="right")

    def _sync_picks(self) -> None:
        """Combine needs two or more ticked recordings, compare exactly two."""
        if not hasattr(self, "combine_btn") or not self.combine_btn.winfo_exists():
            return
        n = len(self.picked)
        self.combine_btn.configure(text=self.t["combine"].format(n=max(n, 2)))
        for b, ok in ((self.combine_btn, n >= 2), (self.compare_btn, n == 2)):
            b.state(["!disabled"] if ok and not self.busy else ["disabled"])

    def fit_on_screen(self) -> None:
        """Back to natural size, moved so the whole window is visible (after the bar)."""
        r = self.root
        r.geometry("")
        r.update_idletasks()
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        x = min(max(0, r.winfo_x()), max(0, sw - r.winfo_reqwidth() - 24))
        y = min(max(0, r.winfo_y()), max(0, sh - r.winfo_reqheight() - 48))
        r.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------ recording bar
    def show_bar(self) -> None:
        t, f = self.t, self._new_frame(padding=(14, 10))
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        top = ttk.Frame(f)
        top.pack(fill="x")
        self.rec_dot = self._dot(top, 14, self.theme.red)
        self.rec_dot.pack(side="left", padx=(0, 6))
        self.state_label = ttk.Label(
            top, text=t["rec"], font=self.theme.fonts["h"], foreground=self.theme.red
        )
        self.state_label.pack(side="left")
        self.time_label = ttk.Label(top, text="00:00", font=self.theme.fonts["mono"])
        self.time_label.pack(side="left", padx=(12, 0))
        self.bar_label = ttk.Label(top, text="", foreground=self.theme.muted)
        self.bar_label.pack(side="left", padx=(12, 12))
        self.stop_btn = ttk.Button(top, text=t["stop"], style="Accent.TButton", command=self.stop)
        self.stop_btn.pack(side="right")
        self.note_btn = ttk.Button(
            top, text=t["note"], command=lambda: self.rec and self.rec.send("manual")
        )
        self.note_btn.pack(side="right", padx=(6, 6))
        self.undo_btn = ttk.Button(top, text=t["undo"], command=self.undo)
        self.undo_btn.pack(side="right", padx=(6, 0))
        self.pause_btn = ttk.Button(top, text=t["pause"], command=self.toggle_pause)
        self.pause_btn.pack(side="right")
        self.note_row: ttk.Frame | None = None
        self.bar_frame = f
        self.update_bar()
        self.place_bar()
        self.root.bind("<Configure>", lambda e: self.send_exclude())

    def place_bar(self) -> None:
        """Top-right corner, fully on screen (also after the note row opens or closes)."""
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"+{max(0, sw - self.root.winfo_reqwidth() - 24)}+24")

    def show_note_entry(self) -> None:
        if self.note_row is not None:
            return
        t = self.t
        self.note_row = ttk.Frame(self.bar_frame)
        self.note_row.pack(fill="x", pady=(10, 0))
        ttk.Label(self.note_row, text=t["note_prompt"]).pack(side="left")
        entry = ttk.Entry(self.note_row, width=32, font=self.theme.fonts["body"])
        entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
        entry.focus_force()

        def answer(text: str | None) -> None:
            if self.rec:
                self.rec.send(f"note {text}" if text else "note-cancel")
            if self.note_row is not None:
                self.note_row.destroy()
                self.note_row = None
            self.place_bar()
            self.send_exclude()

        entry.bind("<Return>", lambda e: answer(entry.get().strip()))
        ttk.Button(
            self.note_row,
            text=t["ok"],
            style="Accent.TButton",
            command=lambda: answer(entry.get().strip()),
        ).pack(side="left", padx=(8, 0))
        ttk.Button(self.note_row, text=t["skip"], command=lambda: answer(None)).pack(
            side="left", padx=(6, 0)
        )
        self.place_bar()
        self.send_exclude()

    # ------------------------------------------------------------------ finished
    def show_finished(self, result: dict[str, Any]) -> None:
        t, f = self.t, self._new_frame()
        self.root.attributes("-topmost", False)
        self.root.resizable(True, True)
        self.root.unbind("<Configure>")
        self.also = []
        session = self.session
        n = result.get("events", self.steps)

        top = ttk.Frame(f)
        top.pack(fill="x")
        if n:
            check = tk.Canvas(top, width=34, height=34, highlightthickness=0, bg=self.theme.bg)
            check.create_oval(1, 1, 33, 33, fill=self.theme.green, outline="")
            check.create_line(
                10, 18, 15, 23, 25, 12, fill="white", width=3, capstyle="round", joinstyle="round"
            )
            check.pack(side="left", padx=(0, 12))
        head = ttk.Frame(top)
        head.pack(side="left", fill="x", expand=True)
        ttk.Label(head, text=t["saved"].format(n=n), font=self.theme.fonts["title"]).pack(
            anchor="w"
        )
        self._muted(head, str(session), wraplength=WRAP).pack(anchor="w")

        if session is not None and n:
            self._agents_group(f, session)
            people = ttk.LabelFrame(f, text=t["for_people"], padding=14)
            people.pack(fill="x", pady=(16, 0))
            row = ttk.Frame(people)
            row.pack(fill="x")
            for key, cmd in (
                ("open_guide", lambda: self.open_guide(session, "guide")),
                ("checklist", lambda: self.open_guide(session, "checklist")),
                ("edit", lambda: self.edit(session)),
                ("share", lambda: self.share(session)),
            ):
                b = ttk.Button(row, text=t[key], command=cmd)
                b.pack(side="left", padx=(0, 6))
                self.action_buttons.append(b)
        elif not n:
            ttk.Label(f, text=t["no_steps"], foreground=self.theme.red).pack(
                anchor="w", pady=(12, 0)
            )

        foot = ttk.Frame(f)
        foot.pack(fill="x", pady=(18, 0))
        if session is not None:
            ttk.Button(foot, text=t["open_folder"], command=lambda: ctl.open_path(session)).pack(
                side="left"
            )
            if n:
                b = ttk.Button(foot, text=t["export_all"], command=lambda: self.export(session))
                b.pack(side="left", padx=6)
                self.action_buttons.append(b)
        ttk.Button(foot, text="＋ " + t["new"], command=self.show_home).pack(side="right")
        self.status.set("")
        self._status_row(f, anchor="w", pady=(10, 0))
        self.fit_on_screen()

    def _agents_group(self, f: ttk.Frame, session: Path) -> None:
        """Skill buttons, the optional agent rewrite and the result line."""
        t = self.t
        agents = ttk.LabelFrame(f, text=t["for_agents"], padding=14)
        agents.pack(fill="x", pady=(18, 0))
        self._para(agents, t["agents_hint"], muted=False).pack(anchor="w")
        row = ttk.Frame(agents)
        row.pack(fill="x", pady=(10, 6))
        targets = [(t["add_claude"], "claude"), (t["add_agents"], "agents")]
        targets += [(t["add_to"].format(agent=label), n) for n, label in ctl.custom_installers()]
        targets.append((t["make_skill"], "none"))
        for i, (text, install) in enumerate(targets):
            b = ttk.Button(
                row,
                text=text,
                style="Accent.TButton" if i == 0 else "TButton",
                command=lambda i=install: self.skill(session, i),
            )
            b.pack(side="left", padx=(0, 6))
            self.action_buttons.append(b)
        self.refine_agent = ctl.refine_agent()
        self.refine.set(False)
        if self.refine_agent:
            label = t["refine"].format(agent=ctl.agent_label(self.refine_agent))
            ttk.Checkbutton(agents, text=label, variable=self.refine).pack(anchor="w")
        self.result_row = ttk.Frame(agents)
        self.result_row.pack(fill="x")

    def show_result(self, headline: str, cmd: str | None) -> None:
        """The "Added to Claude Code" line and a button that copies the command to run it."""
        for w in self.result_row.winfo_children():
            w.destroy()
        ttk.Label(
            self.result_row, text=headline, font=self.theme.fonts["h"], foreground=self.theme.green
        ).pack(side="left", pady=(10, 0))
        if cmd:

            def copy() -> None:
                self.root.clipboard_clear()
                self.root.clipboard_append(cmd)
                btn.configure(text=self.t["copied"].format(cmd=cmd))

            btn = ttk.Button(self.result_row, text=self.t["copy_cmd"].format(cmd=cmd), command=copy)
            btn.pack(side="right", pady=(10, 0))

    def show_combined(self, sessions: list[Path]) -> None:
        """One skill from several recordings of the same task (the first is the reference)."""
        t, f = self.t, self._new_frame()
        self.session, self.also = sessions[0], list(sessions[1:])
        ttk.Label(
            f, text=t["combine_title"].format(n=len(sessions)), font=self.theme.fonts["title"]
        ).pack(anchor="w")
        self._para(f, t["combine_hint"]).pack(anchor="w", pady=(2, 8))
        for i, s in enumerate(sessions):
            row = ttk.Frame(f)
            row.pack(fill="x")
            ttk.Label(row, text=f"{i + 1}.  {s.name}").pack(side="left")
            meta = t["steps"].format(n=ctl.step_count(s))
            if i == 0:
                meta = f"{t['reference']}  ·  {meta}"
            self._muted(row, meta).pack(side="left", padx=10)
        self._agents_group(f, sessions[0])
        foot = ttk.Frame(f)
        foot.pack(fill="x", pady=(18, 0))
        ttk.Button(foot, text=t["back"], command=self.show_home).pack(side="left")
        self.status.set("")
        self._status_row(f, anchor="w", pady=(10, 0))
        self.fit_on_screen()

    def open_session(self, session: Path) -> None:
        """A recent recording -> its finished view."""
        self.session = session
        self.show_finished({"events": ctl.step_count(session)})

    # ------------------------------------------------------------------ actions
    def choose_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.root_dir.get())
        if chosen:
            self.root_dir.set(chosen)
            self.show_home(fresh=False)

    def start(self) -> None:
        root = Path(self.root_dir.get()).expanduser()
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.say(str(exc), error=True)
            return
        self.session = ctl.free_dir(root, self.name.get())
        self.say(self.t["starting"])
        self.root.update_idletasks()
        argv = ctl.record_argv(
            self.session,
            self.opt_typing.get(),
            self.opt_urls.get(),
            self.opt_clip.get(),
            self.opt_voice.get() and not self.voice_hint,
        )
        self.rec = ctl.RecorderProcess(argv)
        self.steps, self.paused_for, self.paused_at = 0, 0.0, None

    def stop(self) -> None:
        if self.rec:
            self.rec.send("stop")

    def toggle_pause(self) -> None:
        if self.rec:
            self.rec.send("resume" if self.paused_at is not None else "pause")

    def undo(self) -> None:
        """Forget the newest step (a wrong click); the recorder answers with ``undone``."""
        if self.rec:
            self.rec.send("undo")

    def send_exclude(self) -> None:
        if not self.rec:
            return
        r = self.root
        r.update_idletasks()
        x0 = min(r.winfo_x(), r.winfo_rootx()) - BAR_MARGIN
        y0 = min(r.winfo_y(), r.winfo_rooty()) - BAR_MARGIN
        x1 = r.winfo_rootx() + r.winfo_width() + BAR_MARGIN
        y1 = r.winfo_rooty() + r.winfo_height() + BAR_MARGIN
        rect = (x0, y0, x1 - x0, y1 - y0)
        if rect != self.last_exclude:
            self.last_exclude = rect
            self.rec.exclude(*rect)

    def edit(self, session: Path) -> None:
        import subprocess

        subprocess.Popen([*ctl.self_command(), "edit", str(session)])

    def run_job(self, message: str, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        """Run ``work`` on a thread; ``done(result)`` (or the error) is applied on the Tk thread."""
        if self.busy:
            return
        self.busy = True
        self.say(message)
        for b in self.action_buttons:
            if b.winfo_exists():
                b.state(["disabled"])

        def finish(fn: Callable[[], None]) -> None:
            self.busy = False
            for b in self.action_buttons:
                if b.winfo_exists():
                    b.state(["!disabled"])
            self.sync_actions()
            fn()

        def thread() -> None:
            try:
                result = work()
            except Exception as exc:  # shown to the user, not raised in a Tk callback
                err = f"{type(exc).__name__}: {exc}"
                self.jobs.put(lambda: finish(lambda: self.say(err, error=True)))
                return
            self.jobs.put(lambda: finish(lambda: done(result)))

        threading.Thread(target=thread, daemon=True).start()

    def combine(self) -> None:
        if len(self.picked) >= 2:
            self.show_combined(list(self.picked))

    def compare(self) -> None:
        if len(self.picked) != 2:
            return
        a, b = self.picked

        def done(res: tuple[Path, dict[str, int]]) -> None:
            path, summary = res
            self.say(self.t["compared"].format(a=a.name, b=b.name, path=path, **summary))
            ctl.open_path(path)

        self.run_job(self.t["comparing"], lambda: ctl.compare_report(a, b), done)

    def open_guide(self, session: Path, which: str) -> None:
        lang = self.guide_lang.get()

        def done(paths: dict[str, Path]) -> None:
            self.say(str(paths[which]))
            ctl.open_path(paths[which])

        self.run_job(self.t["building"], lambda: ctl.build_guide(session, lang), done)

    def share(self, session: Path) -> None:
        """Password-protected copy of the guide, saved where the user chooses."""
        from tkinter import simpledialog

        t = self.t
        pw = simpledialog.askstring("stepcap", t["share_pw"], show="*", parent=self.root)
        if not pw:
            return
        if simpledialog.askstring("stepcap", t["share_pw2"], show="*", parent=self.root) != pw:
            self.say(t["share_mismatch"], error=True)
            return
        out_dir = ctl.export_dir(session)
        target = filedialog.asksaveasfilename(
            parent=self.root,
            initialdir=str(out_dir if out_dir.is_dir() else session.parent),
            initialfile=f"{session.name}-protected.html",
            defaultextension=".html",
            filetypes=[("HTML", "*.html")],
        )
        if not target:
            return
        lang = self.guide_lang.get()

        def done(path: Path) -> None:
            self.say(t["shared"].format(path=path))
            ctl.open_path(Path(path).parent)

        self.run_job(t["working"], lambda: ctl.share_guide(session, Path(target), pw, lang), done)

    def skill(self, session: Path, install: str) -> None:
        t = self.t
        also = tuple(self.also)
        replace = False
        if install != "none":
            try:
                name, target = ctl.skill_target(session, install)
            except Exception as exc:
                self.say(f"{type(exc).__name__}: {exc}", error=True)
                return
            if target.exists():
                if not messagebox.askyesno(
                    "stepcap", t["exists"].format(name=name, path=target), parent=self.root
                ):
                    return
                replace = True
        agent = "none"
        if self.refine.get() and self.refine_agent:
            label = ctl.agent_label(self.refine_agent)
            if not messagebox.askyesno(
                "stepcap", t["refine_confirm"].format(agent=label), parent=self.root
            ):
                return
            agent = self.refine_agent
        message = t["refining"].format(agent=ctl.agent_label(agent)) if agent != "none" else ""

        def done(res: Any) -> None:
            skill_dir = Path(res.skill_dir)
            if res.problems:
                self.say(t["skill_problems"].format(problems="\n".join(res.problems)), error=True)
                ctl.open_path(skill_dir)
            elif install != "none" and res.installed_to:
                label = ctl.agent_label(install)
                cmd = {"claude": f"/{res.name}", "agents": f"${res.name}"}.get(install)
                self.show_result(t["added_head"].format(agent=label), cmd)
                self.say(
                    t.get(f"installed_{install}", t["installed_other"]).format(
                        path=res.installed_to, name=res.name, agent=label
                    )
                )
            else:
                self.say(t["skill_made"].format(path=skill_dir / "SKILL.md"))
                ctl.open_path(skill_dir)
            note = ctl.coverage_note(res, t) if agent != "none" else ""
            if note and not res.problems:
                self.status.set(self.status.get() + "\n\n" + note)

        self.run_job(
            message or t["working"],
            lambda: ctl.make_skill(session, install, agent, replace, also=also),
            done,
        )

    def export(self, session: Path) -> None:
        lang = self.guide_lang.get()
        out = ctl.export_dir(session)

        def work() -> Path:
            from stepcap.build.pipeline import BuildOptions
            from stepcap.skill.run import SkillOptions, run_export

            run_export(
                session,
                "both",
                out,
                SkillOptions(out_dir=out / "skill", name=ctl.skill_name(session), force=True),
                BuildOptions(lang=lang),
            )
            return out

        def done(path: Path) -> None:
            self.say(self.t["exported"].format(path=path))
            ctl.open_path(path)

        self.run_job(self.t["exporting"], work, done)

    def run_doctor(self) -> None:
        import subprocess

        out = subprocess.run(
            [*ctl.self_command(), "doctor"], capture_output=True, text=True, encoding="utf-8"
        )
        win = tk.Toplevel(self.root)
        win.title(self.t["check"])
        win.configure(bg=self.theme.bg)
        text = tk.Text(win, width=100, height=24, wrap="word", relief="flat", padx=10, pady=8)
        text.insert("1.0", (out.stdout or "") + (out.stderr or ""))
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)
        theme_mod.dark_title_bar(win, self.theme.dark)

    # ------------------------------------------------------------------ events
    def poll(self) -> None:
        try:
            while True:
                try:
                    self.jobs.get_nowait()()
                except queue.Empty:
                    break
            if self.rec is not None:
                for ev in self.rec.drain():
                    self.handle(ev)
                if self.frame is not None and hasattr(self, "bar_label") and self.started:
                    self.update_bar()
        finally:
            self.root.after(POLL_MS, self.poll)

    def handle(self, ev: dict[str, Any]) -> None:
        kind = ev.get("event")
        if kind == "ready":
            self.started = time.monotonic()
            self.status.set("")
            self.show_bar()
            self.send_exclude()
        elif kind in ("step", "undone"):
            self.steps = int(ev.get("n", self.steps + 1 if kind == "step" else self.steps))
            if self.started:
                self.update_bar()
        elif kind == "paused":
            self.paused_at = time.monotonic()
            self.pause_btn.configure(text=self.t["resume"])
            self.update_bar()
        elif kind == "resumed":
            if self.paused_at is not None:
                self.paused_for += time.monotonic() - self.paused_at
            self.paused_at = None
            self.pause_btn.configure(text=self.t["pause"])
            self.update_bar()
        elif kind == "note_request":
            self.show_note_entry()
        elif kind == "transcribing":
            self.started = 0.0  # stop the clock; the bar shows the transcription
            self.rec_dot.pack_forget()
            self.state_label.pack_forget()
            self.time_label.pack_forget()
            self.bar_label.configure(text=self.t["transcribing"])
            for b in (self.pause_btn, self.undo_btn, self.note_btn, self.stop_btn):
                b.state(["disabled"])
            self.place_bar()
        elif kind == "done":
            self.rec, self.started = None, 0.0
            self.show_finished(ev)
        elif kind == "error":
            self.rec, self.started = None, 0.0
            self.show_home(fresh=False)
            self.say(f"{self.t['failed']}: {ev.get('message', '')}", error=True)
        elif kind == "exited" and self.rec is not None:
            tail = "\n".join(list(self.rec.stderr_tail)[-6:])
            self.rec, self.started = None, 0.0
            self.show_home(fresh=False)
            self.say(f"{self.t['failed']} (exit {ev.get('code')})\n{tail}", error=True)

    def update_bar(self) -> None:
        paused = self.paused_at is not None
        now = self.paused_at or time.monotonic()
        secs = max(0, int(now - self.started - self.paused_for)) if self.started else 0
        color = self.theme.muted if paused else self.theme.red
        self.state_label.configure(
            text=self.t["paused"] if paused else self.t["rec"], foreground=color
        )
        self.rec_dot.itemconfigure("dot", fill=color)
        self.time_label.configure(text=f"{secs // 60:02d}:{secs % 60:02d}")
        self.bar_label.configure(text=self.t["steps"].format(n=self.steps))
        self.undo_btn.state(["!disabled"] if self.steps else ["disabled"])

    def on_close(self) -> None:
        if self.rec is not None:
            self.rec.terminate()
        self.root.destroy()


def main(lang: str | None = None) -> int:
    from stepcap.capture.recorder import set_dpi_awareness

    set_dpi_awareness()  # Windows: bar coordinates in the same pixels as the recorder
    theme_mod.register_fonts()  # before the first window: its fonts already resolve
    root = tk.Tk()
    App(root, lang)
    root.mainloop()
    return 0
