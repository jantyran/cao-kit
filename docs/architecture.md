# 構成とデータの流れ

このページで分かること: `cao-trio` と CAO 本体の構成要素、セッションとペインの階層、タスク委譲とメッセージ配送の仕組み、サンドボックス、`install.sh` とパッチの動作。

## 全体構成

```
ユーザー
  │
  ├─ cao-dev / cao-trace / cao-doctor / cao-patch / cao-models / cao-recap
  │
  ▼
cao-server（systemd ユーザーサービス: localhost:9889）
  ├── 状態保存: <CAO_HOME_DIR>/db/cli-agent-orchestrator.db（SQLite: terminals, inbox, handoff_results 等）
  ├── 画面ログ: <CAO_HOME_DIR>/logs/terminal/*.{snapshot.json,log,scrollback}
  └── 端末バックエンド（herdr セッション "cao" または tmux）
        └── ワークスペース / セッション: cao-<プロジェクト名>
              ├── リーダー（claude_code / antigravity_cli / codex）
              │     └── stdio 経由で cao-mcp-server に接続（handoff / assign / report_outcome 等）
              └── ワーカー（codex / antigravity_cli / claude_code）
                    └── stdio 経由で cao-mcp-server に接続（send_message / memory_store 等）
```

### 構成要素

| 要素 | 役割 |
|---|---|
| CAO 本体 | `cli-agent-orchestrator`（2.5.4）。`uv tool install cli-agent-orchestrator` で `~/.local/share/uv/tools/cli-agent-orchestrator/` に入る |
| `cao-server` | セッション管理・状態監視（`status_monitor`）・inbox 配送を行う常駐サーバー。`system/cao-server.service` を元に systemd ユーザーサービスとして起動 |
| 端末バックエンド | `herdr` または `tmux`（`cao config get terminal.backend`）。各エージェントの CLI プロセスをペイン／ウィンドウ内で動かす |
| 3 つの CLI | Claude Code（`claude`）、Codex CLI（`codex`）、Antigravity CLI（`agy`） |
| `cao-mcp-server` | 各エージェントから stdio で呼ばれる MCP サーバー。`handoff`、`assign`、`send_message`、`delete_terminal`、`load_skill`、メモリ・学習系ツールを提供 |
| メモリと学習 | `memory_store` / `memory_recall` で教訓や決定を保持。リーダーが作業単位ごとに `report_outcome` で成否を記録し、`*_retrospector` に振り返りを handoff して教訓を抽出する（`memory.learning_enabled = true`） |

## セッションとペインの形

`cao-dev <project>` を実行すると、プロジェクト名から作られた CAO セッション `cao-<プロジェクト名>`（予備リーダー指定時は末尾に `-agy` や `-codex`）が起動する。

```
cao-dev <project>
  └── CAO セッション: cao-<project>
        └── herdr ワークスペース（label = "cao-<project>"）
              ├── タブ 1（label = リーダーの tmux_window、例: "claude_opus_lead-xxxx"）
              │     ┌──────────────────────┬──────────────────────┐
              │     │ ペイン 1: リーダー   │ ペイン 2: ワーカー 1 │
              │     │ (label = 空)         │ (label = window_name)│
              │     ├──────────────────────┼──────────────────────┤
              │     │ ペイン 3: ワーカー 2 │ ペイン 4: ワーカー 3 │
              │     │ (label = window_name)│ (label = window_name)│
              │     └──────────────────────┴──────────────────────┘
              └── タブ 2 以降（5 体目以降のワーカーは新しいタブとして作成）
```

- **herdr バックエンド（`terminal.spawn_mode = pane` パッチ適用時）**:
  - ワークスペースの最初のタブにリーダーが配置される（リーダーのペインは `label` が空、タブの `label` が CAO の `tmux_window` 名）。
  - ワーカーを起動すると、最初のタブの空き領域を分割して最大 4 ペイン（2×2 グリッド）に並ぶ。各ワーカーのペインには `window_name` がラベルとして付く。
  - 最初のタブに 4 ペインある状態でさらにワーカーを起動すると、5 体目以降は同じワークスペース内の新しいタブに作られる。
- **tmux バックエンド**:
  - tmux セッション `cao-<プロジェクト名>` 内にウィンドウが作られる。

## 委譲とメッセージ配送の流れ

リーダーからワーカーへの委譲には `handoff` と `assign` の 2 通りがある（使い分け基準は [docs/roles.md](roles.md) を参照）。

```
【handoff（同期委譲）】
リーダー ──handoff(agent_profile, message)──> cao-server
  1. ワーカーのペインを起動し、message を入力
  2. ワーカーの完了（IDLE / COMPLETED）まで待機
  3. 画面から最終出力を取得して handoff_results に保存し、ワーカーのペインを削除
  4. リーダーに結果を返す

【assign（非同期委譲）＋ send_message】
リーダー ──assign(agent_profile, message)──> cao-server
  1. ワーカーのペインを起動し、message を入力して即座に terminal_id を返す
  2. ワーカーが作業完了後、send_message(receiver_id=リーダーの terminal_id, message=報告) を呼ぶ
  3. inbox テーブルに status=pending で保存される
  4. リーダーが待機中（IDLE / COMPLETED）になった時点で cao-server がリーダーのペインへ入力・Enter を送る
  5. リーダーが結果を確認し、delete_terminal でワーカーのペインを片付ける
```

### inbox と状態判定の注意点

- **待機中になるまで配送されない**: `inbox_service` は受信側ターミナルの状態が待機中（IDLE / COMPLETED）のときだけメッセージを配送する。リーダーが別の作業中（PROCESSING）のあいだは、ワーカーが `send_message` を呼んでも `pending` のまま保持され、リーダーが入力待ちに戻ってから届く。
- **`delivered` の意味**: inbox の状態 `delivered` は「`cao-server` が受信側ペインへのテキスト送信処理を実行した（送信前に状態を `DELIVERED` に更新した）」ことを意味する。受信側の CLI が実際に入力を受け取って処理したかまでは検証していない。

## サンドボックスと権限

各プロバイダの権限制御は仕組みが異なる（設計原則は [docs/roles.md](roles.md) を参照）。

| 設定ファイル / 指定 | 対象 | 設定内容 |
|---|---|---|
| `codex/cao.config.toml`（`codexProfile: cao`） | 実装系の Codex ワーカー | `sandbox_mode = "workspace-write"`、`approval_policy = "on-request"`、`approvals_reviewer = "auto_review"`。ワーカーはリーダーの作業フォルダで起動するため、**そのフォルダの外には書き込めない** |
| `codex/cao-ro.config.toml`（`codexProfile: cao-ro`） | レビュー・調査・振り返りの Codex ワーカー | `sandbox_mode = "read-only"`、`approval_policy = "never"`。ファイルの変更・作成はサンドボックスで拒否される |
| `[mcp_servers.cao-mcp-server]` | `cao.config.toml` と `cao-ro.config.toml` の両方 | `default_tools_approval_mode = "approve"`。`approval_policy = "never"` の `cao-ro` ワーカーでも、`send_message` 等の CAO MCP ツール呼び出しが承認エラーにならず実行できる |
| `permissionMode: auto` | Claude Code 全プロファイル | 危険な操作を分類器が阻止。さらに `role: reviewer` は Read/Glob/Grep のみに制限 |
| `antigravity_cli` | agy 全プロファイル | CAO が常に自動許可で起動するため、サンドボックスによる強制はない |

## `install.sh` が行うこと

`install.sh` は次の処理を順番に行う（`--dry-run` で事前確認、`--apply-codex-notice-only` で 3 のみ実行）。既存ファイルがある場合は `.bak-YYYYmmddHHMMSS`（重複時は連番付き）に退避してから処理する。

1. **ディレクトリの用意**: `local/agents`（git 管理外の上書き用ディレクトリ）がなければ作成する。
2. **シンボリックリンクの作成**:
   - `agents/{team,claude,codex,agy}` → `<CAO_HOME_DIR>/agents/{team,claude,codex,agy}`
   - `local/agents` → `<CAO_HOME_DIR>/agents/local`
   - `skills/{ponytail,ponytail-audit,ponytail-review}` → `<CAO_HOME_DIR>/skills/…`
   - `bin/{cao-dev,cao-recap,cao-doctor,cao-models,cao-trace,cao-patch}` → `~/.local/bin/…`
   - `codex/{cao,cao-ro}.config.toml` → `~/.codex/{cao,cao-ro}.config.toml`
3. **Codex のモデル切替ダイアログ抑止**: `~/.codex/config.toml` が存在し、`[notice]` の `hide_rate_limit_model_nudge` が未設定なら、`hide_rate_limit_model_nudge = true` を追記して `tomllib` で構文検証する（利用上限接近時のモデル切替確認ダイアログでワーカーが停止・誤判定するのを防ぐ）。
4. **`cao config` の設定**:
   - `agents.extra_dirs`: `local` を先頭に、`claude`、`codex`、`agy`、`team` の順で登録
   - `agents.disabled_dirs`: `~/.kiro/agents`、`<CAO_HOME_DIR>/agent-store`、`<CAO_HOME_DIR>/agent-context`
   - `memory.learning_enabled`: `true`
   - `terminal.spawn_mode`: `pane`
5. **systemd ユニットの生成**: `~/.config/systemd/user/cao-server.service` が存在しない場合のみ、`system/cao-server.service` からループバックアドレス（ポート 9889）と `CAO_HOME_DIR` を埋め込んで生成し、`daemon-reload` と `enable` を行う。
6. **AppArmor の案内**: `/etc/apparmor.d/bwrap` がなければ手動コピーの手順を表示する。

詳細は [docs/setup.md](setup.md) を参照。

## パッチの仕組み（`patches/` と `bin/cao-patch`）

CAO 本体（2.5.4）の `site-packages/cli_agent_orchestrator` に対する修正は、直接書き換えず `patches/cao-2.5.4-*.patch` として管理し、`bin/cao-patch` で適用する（コマンドの詳細は [docs/tools.md](tools.md)）。

- `bin/cao-patch` はインストール済みの CAO バージョンが `2.5.4` であることを確かめ、`patches/cao-2.5.4-*.patch` を**ファイル名の辞書順**に `patch -p1` で適用する。
- `bin/cao-patch --check` は全パッチの適用状態を確認し、1 つでも未適用があれば終了コード `1` を返す。`cao-doctor`（`terminal.backend = herdr` のとき）も内部で `--check` を呼び、未適用なら警告を出す。
- `bin/cao-patch --reverse` は逆順にパッチを外す。
- パッチは Python コードを変更するため、**適用後に `cao-server` を再起動するまで稼働中のサーバーには反映されない**。

### 同梱パッチ一覧

| パッチファイル | 対象ファイル | 内容 |
|---|---|---|
| `cao-2.5.4-herdr-codex-status.patch` | `providers/codex.py` | herdr バックエンドで Codex のネイティブ状態が `working`（`PROCESSING`）のまま戻らなくなる問題への対策。`PROCESSING` が 300 秒続いた場合、30 秒ごとに画面バッファ（`_resolve_buffer`）を読み直してフッターや入力欄プロンプトから実際の状態を判定し、入力待ちなら `IDLE` / `COMPLETED` に戻す |
| `cao-2.5.4-herdr-pane-spawn.patch` | `backends/herdr_backend.py`, `backends/factory.py` | `terminal.spawn_mode = pane` のとき、ワーカーを新規タブではなく最初のタブ（リーダーのタブ）内のペイン分割（最大 4 ペイン・2×2 グリッド）で起動し、ペインラベルで識別できるようにする |
| `cao-2.5.4-codex-rollout-output.patch` | `providers/codex.py` | handoff の結果を、codex の会話記録（rollout）から読む。読めなければ画面から切り出す |
