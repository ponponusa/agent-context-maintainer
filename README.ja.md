# Agent Context Maintainer

`agent-context-maintainer` は、AI coding agent 向けの repo-local な指示ファイルを作成・保守するための、ポータブルなツールキット兼 agent skill です。

対象リポジトリを調査し、将来のエージェントが安全に参照・更新できるように、小さく階層化されたコンテキスト構造を生成します。Codex、Claude Code、Gemini、Copilot、Cursor、その他のエージェント、あるいはターミナルの人間、どこから使っても同じように動きます。

## 適用条件

このツールが提供するのは、構造・更新の安全性・機密情報の取り扱い境界であって、リポジトリ固有の内容そのものではありません。価値は、同じ指示を共有するツール数・リポジトリ数・人数に比例して大きくなります。次のいずれかに当てはまるとき、導入コストに見合います。

- **同じリポジトリで複数の AI ツールを使っている。** Codex、Claude Code、Gemini CLI、Copilot、Cursor のうち 2 つ以上が別々のファイル名から指示を読んでおり、手動で同期したコピーではなく単一の source of truth が欲しい。
- **複数のリポジトリを保守しており**、どのリポジトリでも同じコンテキスト構造と同じ scaffold/check コマンドを使いたい。
- **エージェントやチームメイトが指示ファイルを再生成する**環境で、手書きのルールが更新後も必ず残ることを仕組みとして保証したい。
- **指示ファイルとコードの実態が乖離しがち**で、inventory 由来のセクションを記憶ではなくコマンドで更新したい。

どれにも当てはまらない場合は、導入しないでください。

- **単一ツール × 単一リポジトリ**なら、手書きの `CLAUDE.md` か `AGENTS.md` が 1 枚あれば十分です。階層構造は使われない間接参照を増やすだけで、7 つの provider profile の大半は死蔵ファイルになります。
- **本当に重要な指示がリポジトリ固有の判断**(アーキテクチャルール、ワークフローの慣習、レビュー方針)である場合、このツールはその内容を書いてはくれません。手書きセクションを埋める人がいないなら、足場だけあってもほとんど価値はありません。
- **利用中のプラットフォームがすべて `AGENTS.md` を直接読み**、provider ごとの差分もないなら、素の `AGENTS.md` だけで足りる可能性があります。bridge ファイル群は現時点のバラバラな読み込み仕様のために存在するもので、標準への収束が進むほど価値は下がります。

## 作成するもの

```text
AGENTS.md
CLAUDE.md
GEMINI.md
.github/
  copilot-instructions.md
.gemini/
  settings.json
.agents/
  core.md
  routing.md
  provider-registry.yaml
  profiles/
    codex.md
    claude.md
    gemini.md
    cursor.md
    copilot.md
    antigravity.md
    generic.md
  skills/
```

`AGENTS.md` は短い入口に留めます。`CLAUDE.md`、`GEMINI.md`、`.github/copilot-instructions.md` は provider bridge として働き、各ツールが同じ source of truth を参照できるようにします。共通ポリシーは `.agents/core.md`、タスクごとの参照先は `.agents/routing.md`、各社エージェントやモデルごとの差分は `.agents/profiles/`、bridge file と source URL の一覧は `.agents/provider-registry.yaml` に置きます。

生成物の完全な実例は [examples/sample-output/](examples/sample-output/) にあります。このリポジトリ自体のルートに `AGENTS.md` や `.agents/` が意図的に置かれていないのは、このリポジトリ自体が配布物(skill)であり、生成物をパッケージに混ぜないことで skill のインストールを清潔に保つためです。

## インストール

コアは依存ゼロの単一 Python スクリプト(`scripts/agent_context.py`、Python 3.9+)なので、どの統合方法も「このフォルダをどこかに置いてスクリプトを実行する」だけです。

**Codex** — このフォルダを skills ディレクトリに置きます。Codex は `.agents/skills` を repo スコープ(`<repo>/.agents/skills/agent-context-maintainer/`)または user スコープ(`~/.agents/skills/agent-context-maintainer/`)から発見します。本ツール自身が対象リポジトリに `.agents/skills/` を生成するため、そこに自己ホストすることもできます。推奨は user スコープです: repo スコープに置くと、skill に同梱されたファイル(`examples/`、`tests/`)がそのリポジトリ自身の inventory に docs/tests として現れます。

**Claude Code** — このフォルダを `~/.claude/skills/agent-context-maintainer/`(個人用)または `<repo>/.claude/skills/agent-context-maintainer/`(プロジェクト用)に置きます。

**Skill 機構を持たないエージェント** — フォルダを任意の場所に checkout し、リポジトリの指示ファイルからスクリプトを案内します。例:「agent context ファイルを保守するには `python3 <path>/scripts/agent_context.py scaffold . --agent <name>` と `check .` を実行する」。

**人間** — CLI を直接実行します。クイックスタートを参照してください。

インストールパスは 2026-07-02 に各プラットフォームのドキュメントで検証済みです。出典は `reports/provider-review-2026-07.md` に記録されています。

## クイックスタート

このフォルダから実行します。

```bash
python3 scripts/agent_context.py providers
python3 scripts/agent_context.py inventory /path/to/repo
python3 scripts/agent_context.py inventory /path/to/repo --json --explain-skips
python3 scripts/agent_context.py scaffold /path/to/repo --agent auto
python3 scripts/agent_context.py check /path/to/repo
python3 scripts/agent_context.py skills inventory /path/to/repo --json
python3 scripts/agent_context.py skills check /path/to/repo
python3 scripts/agent_context.py skills sync /path/to/repo
```

`providers` は、対応 provider・bridge ファイル・自動検出の可否を一覧表示します。`--agent codex`、`--agent claude`、`--agent gemini`、`--agent cursor`、`--agent copilot`、`--agent antigravity`、`--agent generic` を指定すると、対応するプロファイルを active profile として生成します。

`--agent auto` は、一次情報で確認済みの環境変数(`reports/provider-review-2026-07.md` 参照)から runtime を検出し、検出結果を表示します。検出は意図的に保守的です: 未知の環境は `generic` にフォールバックし、一部の provider は明示指定でのみ選択できます。特に Codex は sandbox 動作時のみ変数を設定するため、検出がフォールバックした場合は `--agent codex` を指定してください。

`scaffold` には 3 つの安全制御があります。

- `--dry-run`: ファイルを変更せず、予定される書き込みを表示します。
- `--append-generated-block`: 既存の marker なし Markdown を維持し、managed block を追記します。
- `--force-recreate`: generated marker のない scaffold 対象を明示的に置き換えます。

## SkillOps

ネストされた `skills` コマンド群は、`.agents/skills/` 以下の repository-local Agent Skills を監査・保守します。

```bash
python3 scripts/agent_context.py skills inventory /path/to/repo
python3 scripts/agent_context.py skills inventory /path/to/repo --json
python3 scripts/agent_context.py skills check /path/to/repo
python3 scripts/agent_context.py skills report /path/to/repo
python3 scripts/agent_context.py skills sync /path/to/repo
python3 scripts/agent_context.py skills routes /path/to/repo
python3 scripts/agent_context.py skills eval /path/to/repo --skill code-review --plan
python3 scripts/agent_context.py skills eval /path/to/repo --skill code-review --init-workspace
```

`skills inventory` は `ROOT/.agents/skills/` 直下の skill directory だけを列挙し、それぞれの中にある `SKILL.md` を検証します。依存ゼロの安全な frontmatter サブセットを parse し、Agent Skills の必須フィールド、安全な local reference、存在する場合は `evals/evals.json` を検証します。symlink された skill directory は追跡せず warning として報告します。eval 不在は warning のみで、valid skill の既定 lifecycle は `active` です。

`skills sync` は `.agents/skill-registry.yaml` と `.agents/skill-reports/skill-health.md` を deterministic な generated marker 付きファイルとして書きます。marker 外の手書き内容は維持し、marker のない既存ファイルはデフォルトで拒否します。`skills routes` は active/watch skill への短い route を `.agents/routing.md` に追加し、skill body はコピーしません。`skills eval --init-workspace` は `.agents/skill-workspaces/` に local planning workspace を作ります。`--runner codex` と prompt/output path を明示しない限り Codex は実行しません。

Codex eval execution は `codex exec --json --sandbox ...` を使い、JSONL trace output は `.agents/skill-workspaces/` 以下にだけ保存します。通常は `--sandbox read-only` または `--sandbox workspace-write` を使ってください。`--sandbox danger-full-access` は追加で `--i-understand-danger` が必要で、隔離された CI/container 環境でのみ適しています。`--full-auto` は deprecated legacy alias であり、新しい automation では使わないでください。

## 安全性

inventory は、一般的な secret、鍵、依存キャッシュ、ビルド成果物、ローカル DB、生ログをスキップします。生成されるコンテキストには安全境界を記述し、機密値そのものはコピーしません。

生成 Markdown セクションは次のマーカーで囲まれます。

```md
<!-- agent-context-maintainer:begin -->
...
<!-- agent-context-maintainer:end -->
```

両方のマーカーが存在する場合、updater はマーカー内だけを置き換えます。マーカー外の手書き内容は維持します。

marker は Markdown code fence の外にある単独行だけを認識します。

`scaffold` 実行時、既存の marker 付きファイルは marker-first に更新されます。つまり generated block だけを置き換え、marker 外の手書き内容は維持します。marker のない既存 Markdown はデフォルトで拒否されます。維持して managed block を足す場合は `--append-generated-block`、置き換える場合は `--force-recreate` を使います。git から復元できない generated-block changes は、上書き前に `.agents/snapshots/agent-context-maintainer/` に snapshot されます。既存の `.gemini/settings.json` は、他の設定を維持したまま必要な bridge key を追加します。

inventory は sensitive directory component、symlink、binary file、巨大ファイル、archive、依存キャッシュ、ビルド成果物、ローカル DB、生ログをスキップします。`inventory --explain-skips` で bounded な skip 理由を確認できます。

## リポジトリ構成

- `SKILL.md`: skill 互換エージェント(Codex、Claude Code、その他の Agent Skills 対応ツール)が実行時に読む指示。
- `agents/openai.yaml`: Codex 固有のアダプタメタデータ(表示名とデフォルトプロンプト)。他のプラットフォームはこのファイルを無視します。Codex を使わない場合は削除して構いません。
- `scripts/agent_context.py`: プラットフォーム中立のコア CLI。依存ゼロの単一ファイル。
- `examples/sample-output/`: `scaffold` の生成物のコミット済み実例(再生成手順は `examples/HOWTO.md`)。
- `tests/`: ユニットテストと、生成物を固定するゴールデンファイル。
- `references/`: skill 自体の保守・拡張のための契約とガイド。
- `reports/`: 検証済みプラットフォーム事実(インストールパス、検出変数)の日付つき記録。

## 開発

```bash
scripts/run_checks.sh
```

は CI と同じステップを実行します: バイトコンパイル、ユニットテストスイート、sample-output のラウンドトリップ(再生成、check、冪等性、`examples/sample-output/` との diff)。

生成物の変更履歴は [CHANGELOG.md](CHANGELOG.md) に記録します。

## ドキュメント

- `references/context-file-contract.md`: 生成ファイルの役割と更新境界。
- `references/provider-profiles.md`: provider/model profile の考え方。
- `references/inventory-heuristics.md`: 安全な inventory のルール。
- `references/extension-guide.md`: 企画意図、拡張ルール、この skill 自体の配布方法。

日本語版は `README.ja.md` と `references/*.ja.md` です。正は英語版ドキュメントであり、日本語版は同一コミットで追随します。

## ライセンス

MIT — [LICENSE](LICENSE) を参照してください。
