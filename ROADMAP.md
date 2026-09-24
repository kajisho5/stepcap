# Roadmap

Status: `done` · `in-progress` · `planned`. Every `planned` item has a GitHub issue
labelled [`roadmap`](https://github.com/kajisho5/stepcap/issues?q=label%3Aroadmap).
Numbers are stable; new ideas get the next free number. RM-013 … RM-054 are
issues #2 … #43 (created 2026-09-24; `scripts/roadmap_to_issues.py` adds new rows).

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
| RM-020 | planned | build | Optional local OCR to name the clicked element (off by default) |
| RM-021 | planned | build | Use accessibility APIs (UIA / AX / AT-SPI) to name clicked controls and get exact frames |
| RM-022 | planned | build | More UI languages for automatic texts (zh, ko, de, fr, es) |
| RM-023 | planned | build | Animated GIF / WebP per step option for drags |
| RM-024 | planned | build | Include a CJK-capable font for simulate / captions |
| RM-025 | planned | record | Wayland support via xdg-desktop-portal (ScreenCast + RemoteDesktop/InputCapture) |
| RM-026 | planned | record | Capture only the active window instead of the whole monitor (`--window`) |
| RM-027 | planned | record | Region capture (`--region x,y,w,h`) for demos |
| RM-028 | planned | record | Hover-only steps (manual hotkey that marks the pointer position) |
| RM-029 | planned | record | Mouse cursor overlay in screenshots |
| RM-030 | planned | record | Tray icon / small floating recorder window with stop / pause / note |
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
| RM-044 | planned | agents | MCP server exposing sessions, steps and build to agents |
| RM-045 | planned | agents | `stepcap describe` prompt pack for local LLMs (Ollama) — opt-in |
| RM-046 | planned | agents | JSON Schema for steps.json and events.jsonl |
| RM-047 | planned | dist | Signed and notarised macOS binary; signed Windows binary |
| RM-048 | planned | dist | Homebrew, Scoop and winget packages |
| RM-049 | planned | dist | Linux arm64 and macOS x64 binaries |
| RM-050 | planned | dev | Real-hook integration tests on Xvfb in CI (optional job) |
| RM-051 | planned | dev | Documentation site with a full CLI reference |
| RM-052 | planned | dev | Performance benchmark for 4K / multi-monitor recording |
| RM-053 | planned | build | Batch build for many sessions and a combined index page |
| RM-054 | planned | build | Diff two recordings of the same procedure (changed steps) |
| RM-055 | done | build | Frame the clicked element (image-based detection, ring fallback, draw/remove in `edit`, `--marker box\|ring`) |
