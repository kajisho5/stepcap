# Roadmap

Status: `done` · `in-progress` · `planned`. The plan is this table; a GitHub issue is
opened only when an item is being discussed or worked on. The earlier one-issue-per-row
[`roadmap`](https://github.com/kajisho5/stepcap/issues?q=label%3Aroadmap) issues (#2 … #43,
#59 … #63) were closed on 2026-09-25 so that open issues mean bugs and questions; reopen
one to discuss it. Numbers are stable; new ideas get the next free number.

| ID | Status | Area | Item |
|---|---|---|---|
| RM-001 | done | record | Global click / double / right-click, drag and scroll capture (Windows, macOS, Linux X11) |
| RM-002 | done | record | Screenshot per step on a background writer thread with click→saved latency stats |
| RM-003 | done | privacy | Typed text off by default; forced masking in password / login windows |
| RM-004 | done | privacy | `--exclude-app` skips events and screenshots |
| RM-005 | done | build | Dedupe identical consecutive screens (area similarity > 0.98) |
| RM-006 | done | build | Numbered double-ring annotation, drag/scroll arrows, key-cap labels, `--zoom` crops |
| RM-007 | done | build | Markdown + single-file HTML (TOC, dark/light, print CSS) + steps.json |
| RM-008 | done | build | Idempotent rebuilds that keep human / agent edits; `--lang en/ja` |
| RM-009 | done | edit | Local edit UI: reorder, delete, rename, blur, rebuild |
| RM-010 | done | agents | Agent Skill (`skills/stepcap/SKILL.md`) for Claude Code / Codex / Cursor |
| RM-011 | done | dev | `simulate` for CI and reproducible README demos |
| RM-012 | done | dist | release-please, PyPI trusted publishing, PyInstaller binaries, CodeQL |
| RM-013 | planned | build | Direct PDF export (`-f pdf`) without a browser |
| RM-014 | planned | build | DOCX export for Word-based manual workflows |
| RM-015 | planned | build | Confluence storage-format export (paste-ready XHTML) |
| RM-016 | planned | build | Notion-friendly export (image upload hints, callouts) |
| RM-017 | planned | build | Custom HTML templates / themes (logo, colours, fonts) |
| RM-018 | planned | build | Configurable marker style (colour, size, shape, spotlight dimming) |
| RM-019 | planned | build | Step grouping into sections (by window / app change) |
| RM-020 | done | build | Local OCR names clicked elements the OS does not name (Windows / macOS built-in, tesseract on Linux; `--no-ocr`) |
| RM-021 | done | build | Use accessibility APIs (UIA / AX) to name clicked controls and get exact frames (AT-SPI: RM-069) |
| RM-022 | planned | build | More UI languages for automatic texts (zh, ko, de, fr, es) |
| RM-023 | planned | build | Animated GIF / WebP per step option for drags |
| RM-024 | planned | build | Include a CJK-capable font for simulate / captions |
| RM-025 | planned | record | Wayland support via xdg-desktop-portal (ScreenCast + RemoteDesktop/InputCapture) |
| RM-026 | planned | record | Capture only the active window instead of the whole monitor (`--window`) |
| RM-027 | planned | record | Region capture (`--region x,y,w,h`) for demos |
| RM-028 | planned | record | Hover-only steps (manual hotkey that marks the pointer position) |
| RM-029 | planned | record | Mouse cursor overlay in screenshots |
| RM-030 | done | record | Small floating recorder window with stop / pause / note (`stepcap app`; tray icon not planned) |
| RM-031 | planned | record | Detect and describe keyboard-only navigation (Tab sequences) |
| RM-032 | planned | record | Per-app exclusion by process path / bundle id, not only name |
| RM-033 | planned | record | Resume recording into an existing session (`record --append`) |
| RM-034 | planned | record | Configurable double-click / drag / scroll thresholds in a config file |
| RM-035 | planned | privacy | Automatic redaction presets (e-mail addresses, credit-card-like numbers) |
| RM-036 | planned | privacy | Redact window titles in outputs (`--redact-titles`) |
| RM-037 | planned | privacy | Encrypted session folders (age / password-based) |
| RM-038 | planned | privacy | `stepcap scrub` to delete raw/ after a final build |
| RM-039 | planned | edit | Undo / redo history in the editor |
| RM-040 | planned | edit | Crop, arrow and text-callout annotations in the editor |
| RM-041 | planned | edit | Merge / split steps in the editor |
| RM-042 | planned | edit | Replace a step's screenshot / add a screenshot from file |
| RM-043 | planned | edit | Keyboard shortcuts and accessibility audit of the editor |
| RM-044 | done | agents | `stepcap mcp`: MCP server (list_sessions, get_steps, step_image, build_guide, make_skill, check_skill) |
| RM-045 | planned | agents | `stepcap describe` prompt pack for local LLMs (Ollama) — opt-in |
| RM-046 | done | agents | JSON Schemas for session.json, events.jsonl, steps.json, terminal.jsonl (`stepcap schema`) |
| RM-047 | planned | dist | Signed and notarised macOS binary; signed Windows binary |
| RM-048 | planned | dist | Homebrew, Scoop and winget packages |
| RM-049 | planned | dist | Linux arm64 and macOS x64 binaries |
| RM-050 | planned | dev | Real-hook integration tests on Xvfb in CI (optional job) |
| RM-051 | planned | dev | Documentation site with a full CLI reference |
| RM-052 | planned | dev | Performance benchmark for 4K / multi-monitor recording |
| RM-053 | planned | build | Batch build for many sessions and a combined index page |
| RM-054 | planned | build | Diff two recordings of the same procedure (changed steps) |
| RM-055 | done | build | Frame the clicked element (image-based detection, ring fallback, draw/remove in `edit`, `--marker box\|ring`) |
| RM-056 | done | build | Arrows (automatic for small targets, hand-drawn in `edit`) and `--spotlight` |
| RM-057 | done | build | Printable A4 checklist (`checklist.html`): tick boxes, target crops, notes, sign-off |
| RM-058 | done | agents | `stepcap skill`: SKILL.md draft (Goal / Inputs / Steps / notes) + annotated references, always validated, `--install claude\|codex` |
| RM-059 | done | agents | `--agent claude\|codex`: the user's own agent CLI generalises the draft after a y/N file listing |
| RM-060 | done | build | `stepcap export --format guide\|skill\|both` and `stepcap check-skill` |
| RM-061 | done | record | Context events: app switches, `--record-urls` (macOS Safari / Chrome / Edge / Arc), `--record-clipboard` |
| RM-062 | done | privacy | Secret masking (GitHub / AWS / OpenAI / Anthropic keys, JWT, URL passwords, card numbers) before anything is written |
| RM-063 | done | record | `stepcap shell`: bash / zsh commands with exit status as terminal events (macOS / Linux) |
| RM-064 | done | record | Browser URL on Windows for `--record-urls` (UI Automation address bar: Chrome, Edge and other Chromium browsers; not Firefox) |
| RM-065 | planned | record | `stepcap shell` for Windows PowerShell |
| RM-066 | done | record | Voice notes: `record --voice`, local speech-to-text (faster-whisper), narration in guide + skill, voice edition binaries |
| RM-067 | done | agents | Check a skill against its recording: apps, elements, inputs, URLs, commands, notes still mentioned (`check-skill --session`) |
| RM-068 | planned | agents | One skill from several recordings of the same task (merge variants, detect inputs) |
| RM-069 | planned | record | Element names on Linux via AT-SPI |
| RM-070 | planned | record | Browser URL on Linux for `--record-urls` (AT-SPI address bar) |
| RM-071 | done | build | `stepcap share`: password-protected single-file guide (AES-GCM, decrypted in the browser) |
