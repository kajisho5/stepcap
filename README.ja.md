# stepcap

**1 回の記録から、人向けの手順書と、どのエージェントでも使える SKILL.md の両方を。ローカル完結・アカウント不要・Copilot 不要。**

*Record once. Get a how-to guide for humans and a SKILL.md for any agent. Local, no account, no Copilot.*

`完全ローカル · オフライン動作 · アカウント不要 · ブラウザもデスクトップアプリも記録 · Windows / macOS / Linux`

[![tests](https://github.com/kajisho5/stepcap/actions/workflows/tests.yml/badge.svg)](https://github.com/kajisho5/stepcap/actions/workflows/tests.yml)
[![CodeQL](https://github.com/kajisho5/stepcap/actions/workflows/codeql.yml/badge.svg)](https://github.com/kajisho5/stepcap/actions/workflows/codeql.yml)
[![PyPI](https://img.shields.io/pypi/v/stepcap)](https://pypi.org/project/stepcap/)
[![Downloads](https://img.shields.io/pypi/dm/stepcap)](https://pypistats.org/packages/stepcap)
[![Stars](https://img.shields.io/github/stars/kajisho5/stepcap)](https://github.com/kajisho5/stepcap/stargazers)
[![Last commit](https://img.shields.io/github/last-commit/kajisho5/stepcap)](https://github.com/kajisho5/stepcap/commits/main)
[![Python 3.11 | 3.13 tested](https://img.shields.io/badge/python-3.11%20%7C%203.13%20tested-blue)](.github/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

作業を 1 回やって F9 を押すと、stepcap は記録から **2 つ** を作ります。

- **人向けの手順書**: `guide.md`、1 ファイルの `guide.html`、印刷用チェックリスト（番号付きの枠・矢印・ぼかし付き）
- **エージェント用の Agent Skill**: [Agent Skills](https://agentskills.io/specification) 形式の `SKILL.md` と注釈付きスクリーンショット。Claude Code や Codex など、スキルを読めるエージェントが同じ作業を繰り返せます。入力した値は `{{変数}}` になります

情シス、ヘルプデスク、総務、講師など「操作マニュアル」を作る人と、「次からはこの作業をエージェントにやらせたい」人向けです。

- **完全ローカル**: データは PC の外に出ません。クラウド・会員登録は不要で、ネットワークを抜いた状態でも動きます
- **ブラウザもデスクトップアプリも 1 本で記録**: Chrome / Edge / Firefox の Web アプリと、Excel・Zoom・OBS・機器の制御ソフトなどのデスクトップアプリを区別なく記録します（ブラウザ拡張型ツールの無料プランはブラウザ内のみ）
- **手順書はブラウザで開くだけ**: `guide.html` は画像込みの 1 ファイルで、専用ビューアもログインも不要です。編集 UI（`stepcap edit`）もブラウザで動きます（127.0.0.1 で待ち受け）
- **エージェントを選ばない**: スキルの下書きは LLM なしで作れます。一般化させたい場合は、読ませるファイルを表示して確認したうえで、**あなた自身の** `claude` / `codex` CLI を実行します。stepcap 自体は何も送信しません

[English README](README.md)

## クイックスタート

```bash
pipx install stepcap          # または pip install stepcap（Python 3.11 以上）
stepcap doctor                # 権限・フックを確認し、足りない設定の手順を表示
stepcap record -o my-guide    # 操作する → 終わったら F9
stepcap export my-guide --format both -o dist --lang ja
#   -> dist/guide/  guide.md, guide.html, checklist.html, images/
#   -> dist/skill/<名前>/  SKILL.md, references/step-NN.png
```

セッションフォルダの中に手順書だけ作る場合は `stepcap build my-guide --lang ja`、スキルを作って Claude Code にインストールまでする場合は `stepcap skill my-guide -o skills --install claude` です（[エージェント用](#エージェント用-stepcap-skill) を参照）。

`my-guide/checklist.html` は同じ手順を A4 に収めた印刷用チェックリストで、現場で紙に印を付けながら使えます。`my-guide/guide.html` は画像込みの 1 ファイルなので、そのままメール添付できます。Ctrl+P →「PDF に保存」で PDF にもなります。`guide.md` と `images/` は GitHub / Notion / Confluence に貼り付けられます。

記録中のキー: **F9** 停止 · **F8** 一時停止 / 再開 · **F7** メモ付きの手動ステップ（`--hotkey-stop ctrl+alt+s` のように変更可能）

Python を入れたくない場合は、[Releases](https://github.com/kajisho5/stepcap/releases) から Windows / macOS / Linux 用の単体実行ファイル（PyInstaller 製）を使えます。

### ターミナルを使わない場合: ウィンドウで操作

```bash
stepcap app          # または Releases の単体実行ファイルをダブルクリック
```

保存先を選んで **記録開始** を押し、作業をして、常に前面に出る小さなバーの **停止** を押します（F9 / F8 / F7 も使えます）。バー自体のクリックはステップになりません。停止すると、2 種類の成果物を選べます。

- **AI エージェント向け：スキル（SKILL.md）**: **Claude Code に追加**（`~/.claude/skills/<名前>/` にコピー。Claude Code で `/<名前>` と入力するか、作業をそのまま頼む）、**Codex に追加**（`~/.agents/skills/<名前>/`。`$<名前>` または `/skills`）、または **SKILL.md を作る** だけ。`claude` / `codex` CLI が入っていれば「先に一般化する」にチェックすると、1 回分の記録から汎用的な手順に書き直させられます（実行前に確認します）。同じ名前のスキルが既にある場合は、確認してから置き換えます。
- **人向け：手順書**: **手順書を開く**・**印刷用チェックリスト**・**手順を編集**。

**手順書とスキルを書き出す（共有用）** は両方を記録の隣（`<名前>-export/`）に出力します。表示言語はシステムの言語（日本語 / English）に合わせます。

![stepcap app: 開始画面・記録バー・完了画面](https://raw.githubusercontent.com/kajisho5/stepcap/main/docs/demo/app.png)

Releases の実行ファイルにはまだコード署名がありません。Windows では「Windows によって PC が保護されました」が出ることがあります（**詳細情報 → 実行**）。macOS ではダウンロードしたファイルがブロックされることがあります（システム設定 → プライバシーとセキュリティ → **このまま開く**）。記録バーはスクリーンショットに写るので、必要なら `stepcap edit` でぼかしてください。

## デモ

**1 回の記録 → 人向けの手順書（左）とエージェント用の SKILL.md（右）:**

![1 回の記録から、左に guide.html、右に入力変数と参照画像付きの SKILL.md](https://raw.githubusercontent.com/kajisho5/stepcap/main/docs/demo/guide-and-skill.png)

### 出力サンプル（GitHub 上でそのまま開けます）

同じ合成記録から作ったものです（[`demos/build.py`](demos/build.py) で再生成できます）。

| | 開く | 作り方 |
|---|---|---|
| 人向けの手順書 | [guide.md](docs/demo/sample/guide/guide.md) · [guide.html](docs/demo/sample/guide/guide.html) · [checklist.html](docs/demo/sample/guide/checklist.html) | `stepcap export --format both` → `guide/` |
| スキルの下書き（LLM なし） | [SKILL.md](docs/demo/sample/skill/create-project-move-card/SKILL.md) + [references/](docs/demo/sample/skill/create-project-move-card/references) | `stepcap skill`（`--agent none`、既定） |
| Claude Code が清書したスキル | [SKILL.refined-by-claude.md](docs/demo/sample/SKILL.refined-by-claude.md) | 実際に `stepcap skill --agent claude` を 1 回実行した結果 |

GitHub は `.html` をソースとして表示します。`guide.html` / `checklist.html` はダウンロードしてブラウザで開いてください。

<details>
<summary>清書後のスキルの抜粋: 入力した値は変数に、CLI / API の確認が先に、各手順に確認ポイント</summary>

```markdown
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
   [step 1](references/step-01.png)
   - Check: a "New project" dialog opens with a "Project name" field, a
     "Template" dropdown, and a "Private project" checkbox.
```

</details>

実行例（出力は実際のもの。長い一覧は省略、プロンプトとパスは短縮）:

```console
$ stepcap export demo --format both -o dist --name create-project-move-card
Guide dist/guide: 15 files
Skill 'create-project-move-card': 12 steps -> dist/skill/create-project-move-card (62 lines, ~698 tokens)
  valid (Agent Skills spec + no secrets)

$ stepcap skill demo -o skills --name create-project-move-card --agent claude
claude will be able to read these files (secrets already masked):
  skills/create-project-move-card/SKILL.md
  skills/create-project-move-card/_context/INSTRUCTIONS.md
  skills/create-project-move-card/_context/events.jsonl
  skills/create-project-move-card/_context/steps.json
  skills/create-project-move-card/references/step-01.png ...
Command: claude -p '...' --permission-mode acceptEdits --allowedTools Read,Edit,Write
Run it? [y/N] y
Skill 'create-project-move-card': 12 steps -> skills/create-project-move-card (98 lines, ~1223 tokens)
  valid (Agent Skills spec + no secrets)

$ stepcap shell demo          # 別のターミナルで（stepcap record -o demo の記録中に）
stepcap: commands in this bash are added to demo (secrets masked, output not recorded). Type `exit` to finish.
[stepcap] ~/work$ git status --short
fatal: not a git repository (or any of the parent directories): .git
[stepcap] ~/work$ export GITHUB_TOKEN=ghp_Q1w2...
[stepcap] ~/work$ exit
stepcap: 2 command(s) recorded in demo/terminal.jsonl

$ cat demo/terminal.jsonl
{"kind":"terminal","time":1790262966.16,"command":"git status --short","cwd":"/home/you/work","exit":128}
{"kind":"terminal","time":1790262966.162,"command":"export GITHUB_TOKEN=[REDACTED:github-token]","cwd":"/home/you/work","exit":0}
```

![stepcap: 記録して、生成された手順書をページ送り](https://raw.githubusercontent.com/kajisho5/stepcap/main/docs/demo/demo.gif)

| 生成された `guide.html`（ライト / ダーク、目次、印刷用 CSS） | `stepcap edit`（並べ替え・改名・ぼかし） |
|---|---|
| ![guide.html](https://raw.githubusercontent.com/kajisho5/stepcap/main/docs/demo/guide-html.png) | ![編集 UI](https://raw.githubusercontent.com/kajisho5/stepcap/main/docs/demo/edit-ui.png) |

クリックしたボタン・入力欄・カードは、番号付きの枠で囲みます。部品の範囲はスクリーンショットから検出するので、OCR や OS のアクセシビリティ API は使いません。判定に自信がないとき（無地の画面上の文字、グラデーションなど）は、クリック位置に番号付きの丸を描きます。枠は `stepcap edit` で描き直したり消したりできます（常に丸にしたい場合は `--marker ring`）。チェックボックスのような小さい部品には、自動で矢印も付きます。`--spotlight` を付けると対象以外を暗くします。矢印は `stepcap edit` で手描きで追加することもできます。ドラッグには矢印、スクロールには方向矢印、ショートカットにはキーラベルが付きます。`--zoom 640` を指定するとクリック周辺の切り抜きがメイン画像になり、全画面のサムネイルが添えられます。

| ボタンを枠で囲む | ドラッグ | `--zoom 640` |
|---|---|---|
| ![クリック](https://raw.githubusercontent.com/kajisho5/stepcap/main/docs/demo/step-click.png) | ![ドラッグ](https://raw.githubusercontent.com/kajisho5/stepcap/main/docs/demo/step-drag.png) | ![ズーム](https://raw.githubusercontent.com/kajisho5/stepcap/main/docs/demo/step-zoom.png) |

| `--spotlight` + 小さいチェックボックスへの自動矢印 | 印刷用 `checklist.html` |
|---|---|
| ![スポットライト](https://raw.githubusercontent.com/kajisho5/stepcap/main/docs/demo/step-spotlight.png) | ![チェックリスト](https://raw.githubusercontent.com/kajisho5/stepcap/main/docs/demo/checklist.png) |

上の画像はすべて [`demos/build.py`](demos/build.py) が合成セッション（`stepcap simulate`）から生成しています。実データは含まれず、いつでも再生成できます。

## できること

- **デスクトップ全体を記録**（ブラウザに限定されません）: クリック（シングル / ダブル / 右）、ドラッグ、スクロール（連続操作は 1 ステップに集約）、文字入力、Enter / Esc、Ctrl+S などのショートカット、F7 の手動メモ。マルチモニタと HiDPI / Retina に対応
- **ステップごとにスクリーンショット**: カーソルのあるモニタを撮影（`--monitor all` で全画面）。撮影は押下時なので、クリックで画面が変わる前の状態が残ります。保存は別スレッドで行い、クリック→保存の遅延を計測・記録します（目標 < 300 ms）
- **クリックした部品名から自動タイトル**: Windows（UI Automation）と macOS（アクセシビリティ）では `ボタン「保存」をクリック`、`入力欄「プロジェクト名」に入力`、`メニュー「名前の変更」を選択` のように付け、部品の正確な位置で枠を描きます。Linux、部品名を公開しないアプリ、`--no-element-names` 指定時はウィンドウ名（`「設定」でクリック`）になります。パスワード欄は名前を取得せず、入力は常に伏せ字です（`--lang ja` / `en`）
- **同じ画面は画像を再利用**: 連続するステップの画面が 98% 以上同じなら 1 枚を共有するので、ぼかしも 1 回で全ステップに反映されます
- **出力**: `guide.md` + `images/`、単一ファイルの `guide.html`（目次・ライト / ダーク・印刷 CSS）、印刷用の A4 チェックリスト `checklist.html`（チェック欄・対象周辺の縮小画像・備考欄・実施日 / 実施者 / 確認者の記入欄）、編集用の正本 `steps.json`
- **再ビルドしても編集を上書きしない**: 人・`stepcap edit`・AI エージェントが `steps.json` に加えた編集は保持されます（最初から作り直すときは `--reset`）
- **クリックした部品を枠で囲む**: ボタン・入力欄・チェックボックス・カードをスクリーンショットから検出して囲みます。自信がないときは丸にします
- **矢印とスポットライト**: 小さい部品には自動で矢印を付けます。`--spotlight` で対象以外を暗くでき、編集 UI では矢印を手描きで追加できます
- **ローカル編集 UI**（`stepcap edit`）: ドラッグで並べ替え、削除、タイトル / 説明の編集、枠の描き直し / 削除、矢印の追加、枠・自動矢印・スポットライトの切り替え、矩形ぼかし（`work/` のコピーに適用し、原本 `raw/` は変更しません）、再ビルド
- **エージェント向けの文脈**: アプリ / ウィンドウの切り替えは常に記録します。`--record-urls` で前面のブラウザタブの URL（macOS: Safari・Chrome・Edge・Arc。`--keep-query` なしではクエリ文字列を除去）、`--record-clipboard` でコピーした文字列（文字数と先頭 80 文字）も記録します。これらはステップにはならず、`stepcap skill` が「Browser at …」「Then: copied …」として使います
- **プライバシー重視の初期設定**: `--record-typing` を付けない限り入力内容は保存しません。パスワード / ログイン画面では常にマスクします。`--exclude-app` を指定したアプリが前面の間は記録もスクショもしません。通信は一切行いません

### できないこと（v0.1）

- **Wayland**（Linux）には非対応で、X11 のみです。Wayland では理由を表示して停止します
- **OCR / AI による命名**はしません。部品名は OS のアクセシビリティ API（Windows / macOS）から取得し、画面の文字は読み取りません。文章として整えたい場合は同梱のエージェント用スキルか、`stepcap skill --agent claude|codex` を使ってください。Linux（AT-SPI）は未対応です
- **動画**、ナレーション、クラウド共有、チーム管理
- PDF の直接出力（`guide.html` をブラウザで印刷 → PDF）

## なぜ作ったか

- Windows 標準の**ステップ記録ツール**（psr.exe）は Microsoft が非推奨化しています（2024 年 2 月の更新から予告表示。2026-09 時点ではまだ起動し、削除日は未発表）。Microsoft が案内する代替（Snipping Tool・Game Bar・Clipchamp）は動画の録画で、手順の記録ではありません
- Microsoft の **skill-recorder** は「1 回の記録 → エージェント用スキル」の有用性を示しましたが、Copilot を利用できる GitHub アカウントが必要で、分析（Analyze）時にイベント記録と画面画像を GitHub のクラウドへ送り、対応先は Microsoft Scout / Copilot Cowork / Copilot Studio です

stepcap はこの 2 つの空白を埋めます。1 回のローカル記録から手順書とスキルの両方を、どの OS でも、どのエージェント向けにも作れます。

## 他ツールとの比較

各プロジェクトの公開情報に基づきます（2026-09-24 時点で確認、Claude の行は 2026-09-25。詳細は各リンクを参照してください）。

| | 動作環境 | 人向け手順書 | エージェント用 SKILL.md | アカウント | 外部送信 |
|---|---|---|---|---|---|
| **stepcap** | Windows / macOS / Linux(X11) | ✅ MD・HTML・チェックリスト | ✅ どのエージェントでも（Claude Code、Codex など） | 不要 | なし（任意のエージェント連携は利用者自身の CLI） |
| [skill-recorder](https://github.com/microsoft/skill-recorder) | macOS / Windows 11 / Ubuntu | —（スキルと自動化のみ） | ✅ Microsoft Scout / Copilot Cowork / Copilot Studio 向け | Copilot を使える GitHub アカウント | Analyze 時にイベントと画面画像を GitHub のクラウドへ |
| [Claude の「Record a skill」](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills) | Claude for Mac（Cowork）。Windows 非対応 | — | ✅ Claude 向け（Claude のスキルに保存） | Pro / Max / Team プラン | 記録（画面・操作・音声）を Claude が確認。動画と音声は保持されず、スクリーンショットが保存される |
| [OpenSteps](https://github.com/ebanez8/openstep) | Windows 10 以降 | ✅ MD・HTML | — | 不要 | なし（ローカル） |
| [BetterStepsRecorder](https://github.com/Mentaleak/BetterStepsRecorder) | Windows | ✅ HTML・RTF・ODT | — | 不要 | 記載なし |
| [Scribe](https://scribe.com/pricing) | ブラウザ（Pro はデスクトップアプリも） | ✅（PDF / HTML / Markdown 書き出しは Pro） | — | 必要 | クラウド |
| [Tango](https://www.tango.ai/pricing) | ブラウザ（Pro はデスクトップも） | ✅（書き出しは Pro） | — | 必要 | クラウド |
| [Windows ステップ記録ツール](https://support.microsoft.com/en-us/windows/apps/steps-recorder-deprecation) | Windows | ✅ .zip 内の .mht（既定では最後の 25 枚のみ） | — | 不要 | なし。**非推奨化** |

Scribe（Basic）と Tango の無料プランはブラウザ内の Web アプリのみ記録・書き出し不可で、有料プランは 1 ユーザーあたり月 $25 / $22（年払い）からです。

## コマンド

```text
stepcap record [-o SESSION_DIR] [--monitor all|active] [--record-typing]
               [--exclude-app NAME ...] [--hotkey-stop F9] [--hotkey-pause F8]
               [--hotkey-manual F7] [--note-prompt auto|gui|terminal|none]
               [--record-urls] [--keep-query] [--record-clipboard] [--dry-run] [--json]
stepcap build SESSION_DIR [-f md,html,checklist] [--zoom 800] [--width 1600] [--lang en|ja]
              [--title "..."] [--marker box|ring] [--[no-]spotlight] [--[no-]auto-arrows]
              [--image-format webp|jpeg|png] [--quality 85] [--reset]
              [--dry-run] [--json]
stepcap edit SESSION_DIR [--port 8765] [--host 127.0.0.1] [--no-browser]
stepcap skill SESSION_DIR -o OUT_DIR [--name NAME] [--agent none|claude|codex]
              [--install none|claude|codex] [--scope user|project] [--yes] [--force]
              [--dry-run] [--json]
stepcap export SESSION_DIR --format guide|skill|both -o OUT_DIR [--name NAME]
               [--agent none|claude|codex] [--lang en|ja] [--yes] [--force] [--dry-run] [--json]
stepcap check-skill SKILL_DIR [--json]
stepcap shell SESSION_DIR [--shell bash|zsh] [--json]      # macOS / Linux
stepcap simulate EVENTS.json -o SESSION_DIR [--record-typing] [--json]
stepcap app [--lang en|ja]                                 # ウィンドウ: 開始 / 停止 / 編集 / 書き出し
stepcap doctor [--json]
```

失敗時はすべて非ゼロで終了します。`--json` で機械可読な出力になります。既存の空でないセッションフォルダは上書きせず、`build` は `raw/` に一切触れません。

## 権限

足りない設定は `stepcap doctor` が具体的に表示します。概要は次のとおりです。

- **macOS**: ターミナルアプリに「アクセシビリティ」「入力監視」「画面収録」を許可し、アプリを再起動
- **Windows**: 許可操作は不要です。ただし管理者として実行したウィンドウの操作は、stepcap も管理者として起動しないと記録できません
- **Linux**: X11 セッションが必要です（Wayland 不可）。`xdotool` を入れるとウィンドウ名の取得が安定します（任意）

詳細: [docs/permissions.md](docs/permissions.md)

## エージェント用: `stepcap skill`

```bash
stepcap skill my-guide -o skills                     # 下書き（LLM 不要）: skills/<名前>/SKILL.md
stepcap skill my-guide -o skills --agent claude      # 手元の Claude Code CLI に一般化させる
stepcap skill my-guide -o skills --install claude --scope project   # .claude/skills/<名前>/ にも配置
stepcap check-skill skills/<名前>                     # 手で直した後の検証
```

- **下書き（`--agent none`、既定）**: 決まった手順で作り、オフラインで動きます。frontmatter（`name`・`description`）、`## Goal`（F7 のメモ。なければ `TODO`）、`## Inputs`（入力した値は入力欄の名前から `{{project_name}}` のような変数に。名前が取れない場合は `{{input_N}}`。名前の変更や「固定値」への切り替えは `stepcap edit` で）、番号付きの `## Steps`（アプリ・ウィンドウ名・`references/step-NN.png`。注釈付きでぼかし適用済み）、`## Notes for the agent`（クリックより CLI / API を優先、削除・送信・支払いの前は確認）
- **清書（`--agent claude|codex`）**: スキルフォルダで `claude -p` または `codex exec` を実行し、[`prompts/skill_refine.md`](src/stepcap/prompts/skill_refine.md) の指示で一般化させます。実行前に、エージェントが読めるファイルを一覧表示して `y/N` を確認します（`--yes` で省略、`--dry-run` は一覧表示のみ）。stepcap 自体は通信しません。エージェントがどこへ送るかはエージェント側の設定次第です
- **配置（`--install claude|codex`）**: `~/.claude/skills/` または `./.claude/skills/`（Claude Code）、`~/.agents/skills/` または `./.agents/skills/`（Codex）にコピーします。同名のスキルがあれば `--force` なしでは上書きしません
- **必ず検証**: Agent Skills の frontmatter 規則、名前 = フォルダ名、500 行未満、約 5000 トークン以内、`references/` のリンク切れなし、秘密情報のパターン（GitHub / AWS / OpenAI / Anthropic のキー、JWT、URL 内のパスワード、カード番号）なし。満たさなければ終了コード 1
- **ターミナルでの操作**: 記録中に別のターミナルで `stepcap shell my-guide` を開くと、そこで打ったコマンド（出力は含まない）が終了コード付き・秘密情報マスク済みで追加され、スキルに「Ran in a terminal: `...`」として載ります。macOS / Linux の bash と zsh に対応し、Windows の PowerShell は未対応です。先頭にスペースを付けたコマンドは記録されません（シェルが履歴から除外する設定の場合）
- **記録中に F7 で「なぜ」をメモ**してください。スキルの Goal になり、エージェントにとって最も役立つ情報です

## 手順書の文章をコーディングエージェントに書かせる

自動タイトルはテンプレートベースです（`「設定」でクリック`）。Claude Code / Codex / Cursor にセッションフォルダを渡すと、エージェントが注釈付きスクリーンショットを見て各ステップのタイトルと 1〜2 文の説明を `steps.json` に書き、`stepcap build` まで実行します。手順は [`skills/stepcap/SKILL.md`](skills/stepcap/SKILL.md) にあります。

```bash
# Claude Code: ユーザー単位でスキルをインストール
mkdir -p ~/.claude/skills && cp -r skills/stepcap ~/.claude/skills/
# 依頼例:「./my-guide に stepcap スキルを使って日本語で手順を書いて」
```

エージェントが画像を直接読むため、OCR も API キーも不要です。

## FAQ

**どこかにアップロードされますか？** されません。stepcap は通信を一切行いません（`--agent claude|codex` は確認後に利用者自身のエージェント CLI を実行するだけです）。編集 UI は 127.0.0.1 のみで待ち受け、Host / Origin も検査します。

**パスワードは記録されますか？** 既定では入力内容を保存せず、「12 文字入力」とだけ記録します。ただし画面に表示されている内容はスクリーンショットに写るので、`stepcap edit` でぼかすか、パスワードマネージャーを `--exclude-app` で除外してください。

**秘密情報はマスクされますか？** テキストはされます。入力内容（`--record-typing` 時）、ウィンドウ名、メモ、スキルの全文から、GitHub / AWS / OpenAI / Anthropic のキー、JWT、URL 内のパスワード、カード番号を検出して `[REDACTED:種類]` として保存します。画像のピクセルは検査しないため、画面に写った秘密情報は `stepcap edit` でぼかしてください。

**インストールせずにブラウザだけで使えますか？** 編集 UI と手順書はブラウザで動きますが、記録部分はできません。Web ページは自分のタブの中のクリックしか検知できないため、デスクトップ全体を記録するには小さなローカルプログラム（`pipx install stepcap` または Releases の単体実行ファイル）が必要です。Web アプリはほかのウィンドウと同じように記録できます。

**録画せずに試せますか？** 試せます: `python tests/fixtures/make_events.py > ev.json && stepcap simulate ev.json -o demo && stepcap build demo --lang ja`

**タイトルが「クリック」だけになります。** ウィンドウ名を取得できていません（`stepcap doctor` を実行してください。macOS では「画面収録」の許可が必要です）。`stepcap edit` で直すか、エージェントに書かせてください。

## ロードマップ

[ROADMAP.md](ROADMAP.md) を参照してください（OCR による命名、PDF 出力、portal 経由の Wayland 対応、マスキングプリセット、多言語化など）。予定の項目は `roadmap` ラベル付きの GitHub Issue で管理しています。

## クレジット

「1 回記録してエージェント用スキルを作る」という考え方は Microsoft の [skill-recorder](https://github.com/microsoft/skill-recorder) で広まったものです。stepcap はコードを共有していません（言語も設計も別です）。考え方の出典として記載しています。

## ライセンス

[MIT](LICENSE)。実行時の依存は Pillow（MIT-CMU）、mss（MIT）、pynput（LGPL-3.0、無改変のライブラリとして利用）です。詳しくは [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md) を参照してください。
