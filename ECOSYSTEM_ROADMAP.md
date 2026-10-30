# Roadmap — stepcap

Part of the [AI Video Production OS](https://github.com/kajisho5/AI-video-production-OS/blob/main/docs/ecosystem/ROADMAP.md) ecosystem: department **補助 (Utility)**, status `active`.
Written from a read-only audit of this repository on 2026-10-30. Each step below is meant to be one pull request; tick it off by linking the PR. This repository's own feature roadmap stays in [ROADMAP.md](ROADMAP.md); this file covers only its place in the ecosystem.

## Where it stands

v0.1.7, Python 3.11+. record, build, edit, simulate, skill, export, share, diff, transcribe, mcp, doctor, ... 31 test modules, CI on 3 OSes. SKILL.md at skills/stepcap/.

## What this repository owns

`ecosystem.json` gives each job to exactly one repository. Work outside this list belongs to its owner and is handed over, not re-implemented.

| Owned job | Status | Note |
|---|---|---|
| 画面収録→手順書 | done | outputs screenshots / Markdown / HTML / SKILL.md; optional how-to MP4 (`stepcap video`, through ffmpeg-skill) |

## Wiring

Not a production step; not wired to the agent (by design).

## Steps

- [x] **1. `contract --json` in the OS schema** — provides guide.build, skill.draft
  - Done when: validates in CI
- [x] **2. Optional how-to video export** — steps -> MP4 via ffmpeg-skill (not raw ffmpeg) ([#79](https://github.com/kajisho5/stepcap/pull/79))
  - Done when: ffmpeg-skill check passes the file
- [ ] **3. Transcription overlap note** — keep the built-in engine or hand off to transcription-skill
  - Done when: written decision

## Boundaries

faster-whisper voice notes duplicate transcription-skill's engine.

---
Engine for every media operation: [ffmpeg-skill](https://github.com/kajisho5/ffmpeg-skill) (42 tools, treated as complete). Orchestrator: [video-production-agent](https://github.com/kajisho5/video-production-agent).
