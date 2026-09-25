# Permissions

`stepcap record` needs two things from the operating system: **global input hooks**
(to see clicks and keys in every app) and **screen capture**. Run `stepcap doctor`
first: it checks both and prints the exact fix for your OS. `stepcap record` runs the
same checks and refuses to start (non-zero exit) instead of producing an empty session.

## macOS

Grant these to the app that runs stepcap (Terminal, iTerm2, VS Code, …), not to
Python itself. After changing a permission, **quit and reopen that app**.

| Permission | Where | Why |
|---|---|---|
| Accessibility | System Settings › Privacy & Security › Accessibility | global mouse/keyboard hooks (pynput event tap) |
| Input Monitoring | System Settings › Privacy & Security › Input Monitoring | keyboard events on recent macOS |
| Screen Recording | System Settings › Privacy & Security › Screen & System Audio Recording | screenshots show only the wallpaper without it; window titles are empty too |

Notes
- If you launch stepcap from different terminals, each one needs the permissions.
- The PyInstaller binary is a separate app from macOS's point of view: grant the
  terminal you start it from.
- Window names come from the Quartz window list (no extra prompt). Only if that
  fails stepcap falls back to `osascript`, which may trigger an
  "… wants to control System Events" prompt (Automation). Denying it only means
  steps are titled without the window name.
- `record --record-urls` asks the browser for the front tab's URL with AppleScript
  (Safari, Google Chrome, Microsoft Edge, Arc). macOS shows "… wants to control
  <browser>" once per browser (Privacy & Security › Automation). Denying it only
  means no URLs are recorded for that browser; stepcap stops asking it.
- `record --record-clipboard` reads the clipboard with `pbpaste` (no prompt).
- `record --voice` records the microphone: macOS asks once for **Microphone**
  access for the app that runs stepcap (Privacy & Security › Microphone). Without it
  the audio is silent and no voice notes are written.

On Linux, `--record-clipboard` needs `xclip` or `xsel` (`sudo apt install xclip`).

## Windows

No permission dialog is needed. Two limitations:

- **Elevated windows**: Windows (UIPI) does not deliver input from an elevated
  ("Run as administrator") window to a normal process. To document admin tools, start
  stepcap from an elevated terminal too.
- **Secure desktop**: UAC prompts, the lock screen and Ctrl+Alt+Del are never
  captured (by design of Windows).
- `record --voice`: Settings › Privacy & security › Microphone › "Let desktop apps
  access your microphone" must be on.
- `record --record-urls` reads the address bar of Chrome and Edge (and the Chromium-based
  Brave, Vivaldi, Opera) with UI Automation (no prompt). Firefox is not supported: by
  default it exposes only its window frame to UI Automation, not the address bar. What the bar shows is recorded: Chrome and
  Edge hide `https://`, which stepcap adds back; text you are typing into the bar (a
  search) is ignored.
- stepcap makes itself per-monitor DPI aware so click positions match screenshots on
  scaled (125 %, 150 %…) and mixed-DPI multi-monitor setups.

## Linux

- **X11 only** in v0.1. Global hooks use the X RECORD extension and screen capture
  uses X11. On a **Wayland** session both are blocked by design, so stepcap stops with
  an error. Choose an "Xorg"/"X11" session on the login screen (GNOME: gear icon;
  KDE: session selector).
- `DISPLAY` must be set (run it from a terminal inside the desktop session, not over
  plain SSH).
- Optional: `sudo apt install xdotool` (or your distro's package) for more reliable
  window names; without it stepcap uses python-xlib.
- Installing from source on Linux compiles `evdev` (a pynput dependency): you may need
  `sudo apt install python3-dev gcc`. The release binaries don't need this.
- `record --voice` uses PortAudio for the microphone: `sudo apt install libportaudio2`
  (also for the voice edition binary).

## Privacy defaults

- Typed text is **not stored** unless you pass `--record-typing`; only the number of
  characters and whether Enter was pressed.
- Even with `--record-typing`, text is masked while the window title contains
  password / パスワード / 1Password / Bitwarden / KeePass / LastPass / Keychain /
  sign in / login / ログイン / サインイン.
- `--exclude-app NAME` skips events *and screenshots* while an app or window whose
  name contains NAME is in front.
- Nothing leaves your machine: no network calls, no telemetry, no account.
  Screenshots are stored in `SESSION_DIR/raw/` — treat that folder as sensitive.
- `stepcap build` reads text from a small area around each click when the app gave no
  element name (OCR on this computer; `--no-ocr` turns it off). The text becomes the step
  title, masked like other text.
- `--voice` is off by default. The microphone is recorded to `SESSION_DIR/audio.wav`,
  transcribed on this computer and then deleted (`--keep-audio` keeps it); while
  recording is paused silence is written instead. The only network access is the
  one-time download of the speech model from Hugging Face (cached afterwards, e.g. in
  `~/.cache/huggingface`); the audio itself is never uploaded.
