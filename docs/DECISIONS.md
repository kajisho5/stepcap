# Decisions

One line per decision, newest last. Format: `YYYY-MM-DD — decision — reason`.

- 2026-09-24 — Name stays `stepcap` — PyPI has no `stepcap` project (404) and no OSS tool of that name was found; the only hit is an unrelated finance company (StepCap, LLC).
- 2026-09-24 — Python 3.11+, runtime deps limited to Pillow, mss, pynput — per spec; everything else is stdlib.
- 2026-09-24 — Build backend: hatchling, src layout, version single-sourced in `pyproject.toml` + `__init__.py` (both bumped by release-please) — `importlib.metadata` is unreliable inside PyInstaller binaries.
- 2026-09-24 — `EventProcessor` is pure logic fed by both the recorder and `simulate` — debounce/drag/scroll/mask behaviour is identical in tests and real use, and testable without OS hooks.
- 2026-09-24 — Hook callbacks only enqueue; a processor thread grabs the screen, a writer thread encodes PNG — slow disks never block hooks (Windows removes slow low-level hooks) and click→grab latency is measured.
- 2026-09-24 — Screenshot is taken on mouse *press* — shows the UI state before the click changes it (what the reader must find).
- 2026-09-24 — Double-click = second press within 150 ms of the first *release* (configurable `--double-click-ms`) and within the drag threshold — spec says 150 ms; release→press is the stable part of a human double-click.
- 2026-09-24 — Drag threshold 12 logical px; scroll runs end after 0.8 s idle or on direction change.
- 2026-09-24 — Typing: default stores only char count + Enter; Tab ends a run (form fields); Enter/Esc outside typing and Ctrl/Alt/Cmd combos become `key` steps; arrows/F-keys ignored.
- 2026-09-24 — Forced mask list extends the spec (password/パスワード/1Password/Bitwarden/KeePass) with passwd, passcode, LastPass, Keychain, sign in/login/ログイン/サインイン — login pages usually contain password fields.
- 2026-09-24 — `--exclude-app` matches case-insensitive substrings of app name *or* window title — app names are not always available (best-effort lookup).
- 2026-09-24 — raw/ keeps lossless PNG (compress_level=1 for speed); the guide uses WebP q85 by default (`--image-format jpeg|png`) — spec: "PNG → WebP/JPEG on save, quality configurable".
- 2026-09-24 — Coordinates stored as absolute, monitor-relative and image-pixel (`img_x/img_y`) — handles HiDPI/Retina where image px ≠ logical px.
- 2026-09-24 — macOS window names via Quartz window list (pyobjc ships with pynput), osascript only as fallback — ~5 ms instead of ~150 ms per click and no Automation prompt; Linux falls back to python-xlib when xdotool is missing.
- 2026-09-24 — Dedupe measures changed *area* (grid of ~45 px blocks on a 320 px grayscale sample), threshold 0.98 — a per-pixel metric missed white menus opened over white UIs.
- 2026-09-24 — Dedupe compares with the first screenshot of the current run, not the previous one — avoids chaining a slow drift into one screen.
- 2026-09-24 — Reused screenshots share one `work/` file — a blur applied in `edit` covers every step that shows that screen.
- 2026-09-24 — Build output lives in the session dir (`guide.md`, `images/`, `guide.html`, `steps.json`) — matches the acceptance criteria; stale `images/step-*` files are removed, nothing else is deleted.
- 2026-09-24 — steps.json keeps `auto.title/description`; text equal to auto text is "untouched" and regenerated (e.g. `--lang`), anything else is preserved; `--reset` recreates — makes build idempotent and edit-safe.
- 2026-09-24 — HTML date comes from the session start, not "now" — rebuilding produces byte-identical files.
- 2026-09-24 — Key steps draw a key-cap pill and no ring; manual notes draw only the badge — a ring at the cursor would point at the wrong thing.
- 2026-09-24 — simulate draws with Pillow's bundled font (Pillow ≥ 10.1) — deterministic across OSes; it has no CJK glyphs, so demo screens are English.
- 2026-09-24 — New modules beyond the spec layout: `session.py` (dir I/O), `build/pipeline.py` (orchestration), `__main__.py` (python -m / PyInstaller entry).
- 2026-09-24 — GitHub Actions: checkout@v5, setup-python@v6, codeql-action@v4, upload-artifact@v6, release-please-action@v4 (Node 24 generation; upload-artifact v5 still defaulted to Node 20) + Dependabot for actions.
- 2026-09-24 — README comparison uses prices re-checked on vendor pages (Tango Pro $22/user/mo yearly for 1–2 users; FlowShare Professional $44 yearly / $49 monthly; Scribe Pro Personal $25 yearly) instead of the spec's $24 / $45 — the spec's figures were outdated; table carries the check date and links.
- 2026-09-24 — Edit UI reorders with Pointer Events instead of HTML5 drag-and-drop — works with touch, and HTML5 DnD never fired in headless Chromium, so it could not be tested.
- 2026-09-24 — Edit server: Host-header allowlist + JSON-only POST + Origin check + CSP — local unauthenticated server must resist DNS rebinding and CSRF.
- 2026-09-24 — Blur = pixelate then Gaussian — a plain Gaussian blur of text can be partially reversed.
- 2026-09-24 — release-please bootstrapped with `release-as: 0.1.0` (manifest 0.0.0) — with bump-patch-for-minor-pre-major a `feat` would otherwise produce 0.0.1. Removed right after v0.1.0 was released.
- 2026-09-24 — Binaries are built by a reusable workflow called from release.yml — releases created with GITHUB_TOKEN do not trigger `on: release` workflows.
- 2026-09-24 — PyInstaller gets pynput backends as explicit hidden imports (`scripts/build_binary.py`) — `--collect-submodules pynput` silently drops them when no display is available at build time; doctor falls back to `__version__` when dist-info is missing in frozen apps.
- 2026-09-24 — README images use absolute raw.githubusercontent.com URLs — relative paths do not render on PyPI.
- 2026-09-24 — ROADMAP issues were created through the GitHub API (no `gh` in the build environment); `scripts/roadmap_to_issues.py` is the idempotent `gh` equivalent for later rows.
