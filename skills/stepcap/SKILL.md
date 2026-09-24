---
name: stepcap
description: Work with a stepcap recording folder (steps.json + annotated screenshots). Use when the user gives you a stepcap session directory and asks either (A) to title, describe, clean up or translate the recorded procedure, how-to, manual or SOP for people - you write the step texts in steps.json and run `stepcap build`; or (B) to turn the recording into an Agent Skill / SKILL.md so an agent can repeat the task - you run `stepcap skill` for a draft and generalise it.
license: MIT
compatibility: Needs the stepcap CLI (`pipx install stepcap`) on PATH and an agent that can view local image files (Claude Code, Codex, Cursor, ...). Works offline.
metadata:
  project: https://github.com/kajisho5/stepcap
---

# stepcap: guide text for people, or a skill for agents

Two workflows. Pick by what the user asked for:

- **A. Guide for people** ("write the steps", "make the manual", "translate the guide") -> Procedure A.
- **B. Skill for agents** ("make a skill", "SKILL.md", "so Claude/Codex can do this") -> Procedure B.

A stepcap session folder looks like this:

```
SESSION_DIR/
  steps.json      <- the only file you edit
  images/         step-001.webp ... (annotated: numbered frame or ring on the click)
  work/           screenshots without markers (blurred copies live here)
  raw/            original screenshots - never modify, never copy elsewhere
  events.jsonl    raw event log - read only
  guide.md / guide.html / checklist.html   generated - never edit by hand
```

## Procedure A: guide for people

1. **Make sure steps.json and images exist.** If `SESSION_DIR/steps.json` or
   `SESSION_DIR/images/` is missing, run:
   ```bash
   stepcap build SESSION_DIR
   ```
2. **Read `SESSION_DIR/steps.json`.** Relevant fields per step:
   `id`, `kind` (click / type / drag / scroll / key / manual), `click_type`,
   `title`, `description`, `rendered` (annotated image, e.g. `images/step-003.webp`),
   `window_title`, `app_name`, `keys`, `direction`. Top level: `title`, `lang`.
3. **Look at every step image** (`rendered`; if it is null, use `image` and the
   pixel position `point.img_x` / `point.img_y`). A numbered frame surrounds the clicked
   element (`box` in steps.json); a numbered ring marks the click when no element was
   detected; an arrow marks a drag or scroll; a key-cap label marks a shortcut.
   Identify the UI element (button label, menu item, field name) and what happens.
4. **Write the text** for each step:
   - `title`: imperative, one line, at most ~70 characters, names the element:
     `Click "New project"`, `Enter the project name`, `Drag the card to "In progress"`.
     Plain text only: no Markdown, no step number (stepcap adds "Step N —").
   - `description`: 1-2 sentences: where the element is and/or what the reader
     should see next. Use `""` when the title says it all.
   - Also set a meaningful top-level `title` for the whole guide.
   - Language: keep `lang` from steps.json (`en` or `ja`) unless the user asks
     otherwise. Japanese style: 「新規プロジェクト」をクリックします。
5. **Save steps.json** as UTF-8, valid JSON, 2-space indent. Validate:
   ```bash
   python -c "import json,sys;json.load(open(sys.argv[1],encoding='utf-8'))" SESSION_DIR/steps.json
   ```
6. **Rebuild** and check the summary says `steps.json kept`:
   ```bash
   stepcap build SESSION_DIR
   ```
   Open `SESSION_DIR/guide.md` and skim it. Tell the user where `guide.html` is
   (single file, can be printed to PDF from a browser).

## Procedure B: Agent Skill from the recording

1. Write the deterministic draft (no network, secrets already masked):
   ```bash
   stepcap skill SESSION_DIR -o OUT_DIR --agent none
   ```
   It prints the skill folder (`OUT_DIR/<name>/`: `SKILL.md` + `references/step-NN.png`).
   Use `--name kebab-case-name` if the user gave a name.
2. Read the draft `SKILL.md`, the step images in `references/`, and
   `SESSION_DIR/steps.json` / `SESSION_DIR/events.jsonl` (app switches, URLs, clipboard and
   terminal events are there when they were recorded).
3. Rewrite `SKILL.md` into a reusable skill:
   - **Generalise**: the recording is one example; describe the procedure for the whole family
     of similar tasks. Keep example values only as examples.
   - **Tools before clicks**: if a CLI, an API or a file edit can do a step, describe that
     first and keep the UI steps as the fallback. Do not invent commands you are not sure of.
   - **Inputs**: everything that changes next time is `{{snake_case_name}}` under `## Inputs`.
   - **Confirmations**: deleting, sending, publishing, paying or changing permissions ->
     "Ask the user to confirm before ...".
   - Sections: `## Goal`, `## Inputs`, `## Steps`, `## Checks`, `## Notes for the agent`.
   - Keep `name` unchanged (it must equal the folder name); `description` <= 1024 characters
     saying what the skill does and when to use it; under 500 lines.
4. Validate your edit and fix every reported problem:
   ```bash
   stepcap check-skill OUT_DIR/<name>
   ```
   It checks the frontmatter, the 500-line / ~5000-token limits, every `references/...` link
   and secret patterns. Also make sure no e-mail address or customer name is in the text.
5. Tell the user where the skill folder is. To install it: copy the folder to
   `.claude/skills/` (Claude Code) or `.agents/skills/` (Codex), or regenerate with
   `--install claude|codex --scope project|user`.

The user can also let their own agent do step 3 in one go:
`stepcap skill SESSION_DIR -o OUT_DIR --agent claude` (or `codex`). stepcap shows the files the
agent will read and asks before running it.

## Rules

- Only change `title`, `description` and the top-level `title`. Never change `id`,
  `kind`, `screenshot`, `point`, `from`, `to`, `auto`, `image`, `rendered`, `box`,
  `box_source` or `arrows`, nor the guide-wide `marker`, `spotlight` and `auto_arrows`
  (the user sets those in `stepcap edit`).
- You may delete a step that is clearly accidental (e.g. a stray click on the desktop)
  or merge its meaning into a neighbour's description, and you may reorder steps only
  when the recording order is obviously wrong. Mention every deletion/reorder to the user.
- Typed text is usually **not recorded** (`Typed 12 characters (content not recorded)`).
  Describe the intent ("Enter your employee ID") - never guess or invent the value,
  and never write passwords, tokens or personal data into the guide even if visible.
- If a screenshot shows sensitive data (passwords, customer names, tokens, e-mail
  addresses), tell the user and suggest `stepcap edit SESSION_DIR` → "Blur area".
  Do not upload screenshots or guides anywhere; everything stays local.
- Do not edit `guide.md`, `guide.html` or files under `raw/`: they are regenerated or
  immutable. `stepcap build --reset` discards all text edits - only use it if asked.

## Example

Before (automatic):
```json
{"id": "s0002", "kind": "click", "title": "Click in \"New project - Acme Tasks\"",
 "description": "", "rendered": "images/step-002.webp"}
```
After:
```json
{"id": "s0002", "kind": "click", "title": "Click the \"Project name\" field",
 "description": "It is the first field in the New project dialog.",
 "rendered": "images/step-002.webp"}
```
