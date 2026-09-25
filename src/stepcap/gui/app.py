"""The `stepcap app` window (tkinter). Logic lives in ``controller``.

Three views in one window:
  home       where to save, options, Start, recent recordings
  recording  a compact always-on-top bar: time, step count, Pause, Note, Stop;
             its screen rectangle is sent to the recorder so clicking it is not a step
  finished   Edit steps (browser), Export guide + skill, Open folder, New recording
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from stepcap.gui import controller as ctl

POLL_MS = 100
BAR_MARGIN = 6  # extra pixels around the bar that also do not count as steps


class App:
    def __init__(self, root: tk.Tk, lang: str | None = None) -> None:
        self.root = root
        self.lang = lang or ctl.ui_lang()
        self.t = ctl.TEXTS[self.lang]
        self.rec: ctl.RecorderProcess | None = None
        self.session: Path | None = None
        self.steps = 0
        self.started = 0.0
        self.paused_for = 0.0
        self.paused_at: float | None = None
        self.last_exclude: tuple[int, int, int, int] | None = None
        root.title("stepcap")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root_dir = tk.StringVar(value=str(ctl.default_root()))
        self.name = tk.StringVar(value=ctl.new_session_name())
        self.opt_typing = tk.BooleanVar(value=False)
        self.opt_urls = tk.BooleanVar(value=False)
        self.opt_clip = tk.BooleanVar(value=False)
        self.guide_lang = tk.StringVar(value=self.lang)
        self.status = tk.StringVar(value="")
        self.frame: ttk.Frame | None = None
        self.show_home()
        root.after(POLL_MS, self.poll)

    # ------------------------------------------------------------------ views
    def _new_frame(self) -> ttk.Frame:
        if self.frame is not None:
            self.frame.destroy()
        self.frame = ttk.Frame(self.root, padding=14)
        self.frame.pack(fill="both", expand=True)
        return self.frame

    def show_home(self) -> None:
        t, f = self.t, self._new_frame()
        self.root.attributes("-topmost", False)
        self.root.resizable(True, True)
        self.name.set(ctl.new_session_name())
        ttk.Label(f, text="stepcap", font=("TkDefaultFont", 18, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(f, text=t["subtitle"]).grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text=t["save_to"]).grid(row=2, column=0, sticky="w", pady=(12, 2))
        ttk.Entry(f, textvariable=self.root_dir, width=46).grid(row=2, column=1, sticky="we")
        ttk.Button(f, text=t["change"], command=self.choose_dir).grid(row=2, column=2, padx=4)
        ttk.Label(f, text=t["name"]).grid(row=3, column=0, sticky="w", pady=2)
        ttk.Entry(f, textvariable=self.name, width=30).grid(row=3, column=1, sticky="w")
        for i, (var, key) in enumerate(
            (
                (self.opt_typing, "opt_typing"),
                (self.opt_urls, "opt_urls"),
                (self.opt_clip, "opt_clip"),
            )
        ):
            ttk.Checkbutton(f, text=t[key], variable=var).grid(
                row=4 + i, column=0, columnspan=3, sticky="w"
            )
        ttk.Label(f, text=t["guide_lang"]).grid(row=7, column=0, sticky="w", pady=2)
        ttk.Combobox(
            f, textvariable=self.guide_lang, values=("ja", "en"), width=6, state="readonly"
        ).grid(row=7, column=1, sticky="w")
        ttk.Button(f, text=t["start"], command=self.start).grid(
            row=8, column=0, columnspan=3, sticky="we", pady=(12, 4), ipady=8
        )
        ttk.Label(f, text=t["hint_keys"], foreground="#667").grid(
            row=9, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(f, textvariable=self.status, foreground="#a33", wraplength=520).grid(
            row=10, column=0, columnspan=3, sticky="w"
        )
        ttk.Button(f, text=t["check"], command=self.run_doctor).grid(
            row=11, column=0, sticky="w", pady=(8, 0)
        )
        sessions = ctl.recent_sessions(Path(self.root_dir.get()))
        if sessions:
            ttk.Label(f, text=t["recent"], font=("TkDefaultFont", 11, "bold")).grid(
                row=12, column=0, columnspan=3, sticky="w", pady=(14, 2)
            )
            for i, s in enumerate(sessions[:6]):
                row = ttk.Frame(f)
                row.grid(row=13 + i, column=0, columnspan=3, sticky="we")
                ttk.Label(row, text=s.name, width=24).pack(side="left")
                ttk.Button(row, text=t["edit"], command=lambda p=s: self.edit(p)).pack(side="left")
                ttk.Button(row, text=t["export"], command=lambda p=s: self.export(p)).pack(
                    side="left", padx=4
                )
                ttk.Button(row, text=t["open_folder"], command=lambda p=s: ctl.open_path(p)).pack(
                    side="left"
                )
        f.columnconfigure(1, weight=1)

    def show_bar(self) -> None:
        t, f = self.t, self._new_frame()
        self.frame.configure(padding=6)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.bar_label = ttk.Label(f, text="", font=("TkDefaultFont", 11, "bold"), width=22)
        self.bar_label.pack(side="left", padx=(2, 8))
        self.pause_btn = ttk.Button(f, text=t["pause"], command=self.toggle_pause)
        self.pause_btn.pack(side="left")
        ttk.Button(f, text=t["note"], command=lambda: self.rec and self.rec.send("manual")).pack(
            side="left", padx=4
        )
        ttk.Button(f, text=t["stop"], command=self.stop).pack(side="left")
        self.note_row: ttk.Frame | None = None
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
        self.note_row = ttk.Frame(self.root, padding=(6, 0, 6, 6))
        self.note_row.pack(fill="x")
        ttk.Label(self.note_row, text=t["note_prompt"]).pack(side="left")
        entry = ttk.Entry(self.note_row, width=32)
        entry.pack(side="left", padx=4)
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
        ttk.Button(self.note_row, text=t["ok"], command=lambda: answer(entry.get().strip())).pack(
            side="left"
        )
        ttk.Button(self.note_row, text=t["skip"], command=lambda: answer(None)).pack(side="left")
        self.place_bar()
        self.send_exclude()

    def show_finished(self, result: dict[str, Any]) -> None:
        t, f = self.t, self._new_frame()
        self.root.attributes("-topmost", False)
        self.root.resizable(True, True)
        self.root.unbind("<Configure>")
        session = self.session
        n = result.get("events", self.steps)
        ttk.Label(f, text=t["saved"].format(n=n), font=("TkDefaultFont", 14, "bold")).pack(
            anchor="w"
        )
        ttk.Label(f, text=str(session)).pack(anchor="w", pady=(0, 10))
        if not n:
            ttk.Label(f, text=t["no_steps"], foreground="#a33").pack(anchor="w")
        buttons = ttk.Frame(f)
        buttons.pack(anchor="w")
        if session is not None and n:
            ttk.Button(buttons, text=t["edit"], command=lambda: self.edit(session)).pack(
                side="left"
            )
            ttk.Button(buttons, text=t["export"], command=lambda: self.export(session)).pack(
                side="left", padx=4
            )
        if session is not None:
            ttk.Button(buttons, text=t["open_folder"], command=lambda: ctl.open_path(session)).pack(
                side="left"
            )
        ttk.Button(f, text=t["new"], command=self.show_home).pack(anchor="w", pady=(12, 0))
        ttk.Label(f, textvariable=self.status, wraplength=520).pack(anchor="w", pady=(8, 0))
        self.status.set("")

    # ------------------------------------------------------------------ actions
    def choose_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.root_dir.get())
        if chosen:
            self.root_dir.set(chosen)
            self.show_home()

    def start(self) -> None:
        root = Path(self.root_dir.get()).expanduser()
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.status.set(str(exc))
            return
        self.session = ctl.free_dir(root, self.name.get())
        self.status.set(self.t["starting"])
        self.root.update_idletasks()
        argv = ctl.record_argv(
            self.session, self.opt_typing.get(), self.opt_urls.get(), self.opt_clip.get()
        )
        self.rec = ctl.RecorderProcess(argv)
        self.steps, self.paused_for, self.paused_at = 0, 0.0, None

    def stop(self) -> None:
        if self.rec:
            self.rec.send("stop")

    def toggle_pause(self) -> None:
        if self.rec:
            self.rec.send("resume" if self.paused_at is not None else "pause")

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

    def export(self, session: Path) -> None:
        self.status.set(self.t["exporting"])
        lang = self.guide_lang.get()

        def work() -> None:
            from stepcap.build.pipeline import BuildOptions
            from stepcap.skill.run import SkillOptions, run_export

            out = ctl.export_dir(session)
            try:
                run_export(
                    session,
                    "both",
                    out,
                    SkillOptions(out_dir=out / "skill", force=True),
                    BuildOptions(lang=lang),
                )
                msg = self.t["exported"].format(path=out)
                self.root.after(0, lambda: (self.status.set(msg), ctl.open_path(out)))
            except Exception as exc:  # shown to the user, not raised in a Tk callback
                err = f"{type(exc).__name__}: {exc}"
                self.root.after(0, lambda: self.status.set(err))

        threading.Thread(target=work, daemon=True).start()

    def run_doctor(self) -> None:
        import subprocess

        out = subprocess.run(
            [*ctl.self_command(), "doctor"], capture_output=True, text=True, encoding="utf-8"
        )
        win = tk.Toplevel(self.root)
        win.title(self.t["check"])
        text = tk.Text(win, width=100, height=24, wrap="word")
        text.insert("1.0", (out.stdout or "") + (out.stderr or ""))
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ events
    def poll(self) -> None:
        try:
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
        elif kind == "step":
            self.steps = int(ev.get("n", self.steps + 1))
        elif kind == "paused":
            self.paused_at = time.monotonic()
            self.pause_btn.configure(text=self.t["resume"])
        elif kind == "resumed":
            if self.paused_at is not None:
                self.paused_for += time.monotonic() - self.paused_at
            self.paused_at = None
            self.pause_btn.configure(text=self.t["pause"])
        elif kind == "note_request":
            self.show_note_entry()
        elif kind == "done":
            self.rec, self.started = None, 0.0
            self.show_finished(ev)
        elif kind == "error":
            self.rec, self.started = None, 0.0
            self.show_home()
            self.status.set(f"{self.t['failed']}: {ev.get('message', '')}")
        elif kind == "exited" and self.rec is not None:
            tail = "\n".join(list(self.rec.stderr_tail)[-6:])
            self.rec, self.started = None, 0.0
            self.show_home()
            self.status.set(f"{self.t['failed']} (exit {ev.get('code')})\n{tail}")

    def update_bar(self) -> None:
        now = self.paused_at or time.monotonic()
        secs = int(now - self.started - self.paused_for)
        state = self.t["paused"] if self.paused_at is not None else "● " + self.t["rec"]
        steps = self.t["steps"].format(n=self.steps)
        self.bar_label.configure(text=f"{state}  {secs // 60:02d}:{secs % 60:02d}  ·  {steps}")

    def on_close(self) -> None:
        if self.rec is not None:
            self.rec.terminate()
        self.root.destroy()


def main(lang: str | None = None) -> int:
    from stepcap.capture.recorder import set_dpi_awareness

    set_dpi_awareness()  # Windows: bar coordinates in the same pixels as the recorder
    root = tk.Tk()
    App(root, lang)
    root.mainloop()
    return 0
