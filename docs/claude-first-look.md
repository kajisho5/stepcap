# Claude 向け実装指示（stepcap の第一印象）

対象: `kajisho5/stepcap` `main`（v0.1.6、`e9321b1`）
このファイルをそのまま Claude Code に渡す。

目的はスターを増やす機能追加ではない。公開ページを開いた人が「壊れている」「デモが嘘」と思わずに、何をする道具か 10 秒で分かること。

検証: 既存のテストが通ること。新しい機能のテストは足さない。

---

## やってはいけないこと

- RM-013 から RM-069 のどれも実装するな。PDF、DOCX、Wayland、署名、Homebrew、MCP、音声、PowerShell、OCR を作るな。
- 署名証明書は無い。バイナリに署名するな。SmartScreen の説明は README にあるので残す。
- 合成デモを、実在のアプリの画面に見せかけるな。`demos/build.py` の「synthetic / 合成」という注記は残す。
- クラウド送信、アカウント、Copilot 連携を足すな。
- README を短くするために、比較表・コマンド一覧・制限（Wayland、Linux はウィンドウ名だけ）を消すな。上に短い導入を足すだけ。
- Issue を消したあと、`scripts/roadmap_to_issues.py` が同じ Issue を作り直さないようにすること。スクリプトを消すな。既定の動作を「作らない」に変える。

---

## 1. 開いている 45 件はバグではない。閉じる

全部ラベル `roadmap` の予定表である。GitHub の「Open 45」は、通りがかりには未修正のバグに見える。

- 開いている `roadmap` Issue を、コメント 1 行で閉じる。「バグではない。予定は ROADMAP.md。議論が始まったら開き直す。」
- `scripts/roadmap_to_issues.py` は、引数なしでは何も作らない。`--create` を付けたときだけ今までどおり作る。`--dry-run` は残す。
- ROADMAP.md の先頭の「Every planned item has a GitHub issue」を、「予定はこの表。Issue は議論が始まったものだけ」に直す。
- 閉じたあと `gh issue list --state open` が 0 件であることを確かめる。

---

## 2. README の最初の画面

今の見出し（Record once…）は残す。その直下、バッジより前に、次の 4 行だけ足す。英語 README と README.ja.md の両方。

- デスクトップアプリもブラウザも、1 回操作すると、人向けの手順（guide.html）とエージェント向けの SKILL.md が出る。
- 手元だけ。アカウント不要。Scribe / Tango の無料枠はブラウザだけで、デスクトップ取り込みは有料。
- デモ画像は合成である（`demos/build.py`）。実データは含まない。
- 開いている Issue は置かない。予定は ROADMAP.md。

バッジ列は、この 4 行とデモ GIF のあとに移す。

---

## 3. 公開用の文章を 1 枚

`docs/announce.md` を新規に作る。実装はしない。ユーザーが自分で投稿するための下書き。

- 日本語と英語を同じファイルに。Show HN 用（英語、タイトル 1 行と本文 12 行以内）と、X 用（日本語、280 字以内、URL は https://github.com/kajisho5/stepcap）。
- 書いてよい事実だけ。ローカル、アカウント無し、Windows / macOS / Linux（X11）、guide.html と SKILL.md、合成デモ、バイナリは未署名。
- スター数、ダウンロード数、他社の価格の数字は書くな。価格は変わる。
- 「Scribe の代わり」とは書くな。「ブラウザ専用の無料枠ではデスクトップアプリが録れない人向け」と書く。

---

## 4. リポジトリの説明

`gh repo edit` で description を次にする。

`Record once. Local guide for people and a SKILL.md for any agent. No account.`

topics を足す: `cli` `documentation` `screenshot` `agent-skills` `windows` `macos` `linux`

既存の topics は消すな。足すだけ。
