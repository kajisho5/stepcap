---
name: "create-project-move-card"
description: "Create a new project and move a card to a different column (e.g. \"In progress\") on its board in Acme Tasks. Use when the user asks to create a project in Acme Tasks, set up a new Kanban board, or move/update the status of a task card, e.g. \"create a project called X and move the Y card to In progress\"."
metadata:
  generator: "stepcap 0.1.3"
  recorded: "2026-09-24"
  status: "refined by claude"
---

> **Sample output** of `stepcap skill demo -o skills --name create-project-move-card --agent claude`:
> one real Claude Code run on the synthetic demo recording (2026-09-24), kept as is.
> Compare with the [draft it started from](skill/create-project-move-card/SKILL.md).
> `demos/build.py` does not regenerate this file.

# Create a project and move a card in Acme Tasks

## Goal

Create a new project in Acme Tasks and move one of its cards into a different
column on the resulting board (e.g. from "To do" to "In progress"), so the
card's status is visible to the team.

## Inputs

- `{{project_name}}` - name for the new project (e.g. "Q3 launch plan").
- `{{template}}` - board template to use, e.g. "Kanban board" (optional; the "Create" button defaults to "Kanban board" if left unset).
- `{{is_private}}` - whether the project should be marked private, true/false (optional; defaults to unchecked/public).
- `{{card_name}}` - name of the card to move (e.g. "Draft brief").
- `{{source_column}}` - the column the card currently sits in, e.g. "To do" (helps you find it; not otherwise needed).
- `{{target_column}}` - the column to move the card into, e.g. "In progress".

## Steps

Check first whether Acme Tasks exposes a CLI or API for creating projects and
moving cards (e.g. from its Settings or developer docs) - if so, prefer that
over the UI steps below. Otherwise, use the UI:

1. **Open Projects and start a new project.** In the Acme Tasks sidebar, click
   "Projects", then click "+ New project" (top right).
   [step 1](skill/create-project-move-card/references/step-01.png)
   - Check: a "New project" dialog opens with a "Project name" field, a
     "Template" dropdown, and a "Private project" checkbox.
2. **Fill in the new-project form.** Click the "Project name" field and type
   `{{project_name}}`. If `{{template}}` was given, open the "Template"
   dropdown and select it (otherwise leave the default). If `{{is_private}}`
   is true, check "Private project".
   [step 2](skill/create-project-move-card/references/step-02.png) · [step 3](skill/create-project-move-card/references/step-03.png) · [step 4](skill/create-project-move-card/references/step-04.png)
   - Marking a project private changes who can see it - ask the user to
     confirm before checking "Private project" if they didn't explicitly ask
     for a private project.
3. **Create the project.** Click "Create".
   [step 5](skill/create-project-move-card/references/step-05.png)
   - Check: the dialog closes and Acme Tasks opens the new board, titled
     `{{project_name}}`, with columns from the chosen template (e.g. "To do",
     "In progress", "Done").
4. **Find the card.** On the board, locate the card named `{{card_name}}`,
   normally in the `{{source_column}}` column.
   [step 6](skill/create-project-move-card/references/step-06.png)
   - Check: the card is visible with its current column shown as a small
     label under its title.
5. **Move the card to the target column.** Either:
   - **Drag and drop** the card from its current column and drop it inside
     the `{{target_column}}` column, at the vertical position (row) you want
     it to land; or
   - **Right-click** the card to open its menu (Rename / Move to… / Duplicate
     / Delete), choose "Move to…", then pick `{{target_column}}`. If you open
     this menu but decide not to use it, press `Esc` to close it without
     picking an option - other entries in the menu (Rename, Duplicate,
     Delete) are unrelated and shouldn't be clicked.
   [step 7](skill/create-project-move-card/references/step-07.png) · [step 8](skill/create-project-move-card/references/step-08.png) · [step 9](skill/create-project-move-card/references/step-09.png)
   - Moving the card notifies the team, so ask the user to confirm before
     doing this move if it wasn't explicit which card and column they meant.
6. **Save if needed.** Scroll the board into view and, if Acme Tasks doesn't
   autosave, press `Ctrl+S` (or `Cmd+S` on Mac).
   [step 10](skill/create-project-move-card/references/step-10.png) · [step 11](skill/create-project-move-card/references/step-11.png)
   - Check: no "unsaved changes" indicator remains on the board.

## Checks

- The board for `{{project_name}}` exists and shows the columns from its
  template.
- The card `{{card_name}}` now appears under the `{{target_column}}` column
  header (its status label matches `{{target_column}}`), and no longer
  appears under `{{source_column}}`.
- [step 12](skill/create-project-move-card/references/step-12.png) shows the expected end state: card moved,
  team notified.

## Notes for the agent

- Prefer tools over replaying clicks: if a CLI, an API or a file edit gives
  the same result, use it. The screenshots show the intent of each step, not
  the only way to do it.
- Ask the user to confirm before marking a project private or moving a card
  (it notifies the team) if those specifics weren't clearly requested.
- Values written as `{{name}}` are inputs. Use the ones the user gave you;
  ask for missing ones (at minimum `{{project_name}}`, `{{card_name}}`, and
  `{{target_column}}`) instead of reusing the examples above.
- The recording is one run with one project/template/card layout. Names,
  columns, and templates will differ next time - match elements by meaning
  (e.g. "the column named after the target status"), and stop and ask when
  the screen doesn't look like what's described here.

<!-- generated by stepcap 0.1.3 (en); screenshots are annotated: a numbered frame or ring marks the clicked element -->
