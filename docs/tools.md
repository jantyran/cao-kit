# ツールリファレンス（`bin/`）

このページで分かること: `bin/` 配下の全 6 コマンド（`cao-dev`, `cao-recap`, `cao-doctor`, `cao-patch`, `cao-trace`, `cao-models`）の書式、オプション、内部の判定ロジック。

`./install.sh` を実行すると、すべて `~/.local/bin/` にシンボリックリンクされる。

## `cao-dev` — セッションの起動・接続・自動復旧

プロジェクト単位で CAO セッションを起動、または既存セッションへ接続・送信する。

### 書式

```bash
cao-dev                                    # 場所に応じてプロジェクト起動または既存セッション画面に入る
cao-dev <project>                          # 対話モードで起動（既存セッションがあれば接続）
cao-dev <パス>                              # パス（. や ~/foo、/path/to/foo）を指定して起動
cao-dev <project> "<依頼内容>"              # ヘッドレスで依頼を投げて非同期実行
cao-dev --lead <profile> [project] [...]   # リーダーを予備（例: agy_opus_lead）に差し替えて起動
cao-dev -l | --list                        # プロジェクト置き場（CAO_DEV_ROOT）直下のフォルダ一覧
cao-dev -h | --help                        # ヘルプを表示
```

設定値の優先順位は「環境変数（`CAO_DEV_ROOT`, `CAO_DEV_LEAD`）＞ `local.env` ＞ 既定値（`~/projects`, `claude_opus_lead`）」。

### 引数なしで実行したときの動作

引数なしで `cao-dev` を実行すると、カレントディレクトリ（`$PWD`）を次の順に判定する。

1. **プロジェクト置き場（`CAO_DEV_ROOT`）の配下**にいる場合: その直下のプロジェクト名（`$ROOT/<project>/...` の `<project>`）で起動する。
2. **ホーム（`$HOME`）や `/` 以外の git リポジトリ内**にいる場合: `git rev-parse --show-toplevel` のディレクトリで起動する（ホーム自体が git リポジトリになっている環境でも誤ってホーム全体で起動しない）。
3. **それ以外の場所**にいる場合: **既存のセッション画面に入る**。
   - `cao-server` が停止していれば起動し、`cao session list` から `cao-` で始まるセッション一覧を取得する。
   - セッションが 1 つもなければ使い方を表示して終了コード `0` で終わる。
   - セッションがあればセッション名一覧を表示し、端末の外にいれば `herdr --session <herdr_session>`（既定 `cao`）または `tmux attach` に `exec` する。すでに `herdr`（`HERDR_PANE_ID` あり）や `tmux`（`TMUX` あり）の中にいる場合は、ワークスペース／セッション一覧から選ぶよう案内して終了コード `0` で終わる。

### 起動前の自動処理

プロジェクトが決まると、セッション起動前に次を行う。

- `~/.codex/config.toml` が存在し対象フォルダが未登録なら、`[projects."<dir>"] trust_level = "trusted"` を追記する（「Trust this folder?」ダイアログでタスク配送が止まるのを防ぐ）。
- `git -C <dir> rev-parse --path-format=absolute --git-path info/exclude` で `.cao/` をローカル除外に追加する（通常の git リポジトリと linked worktree の両方に対応）。
- `cao-server` が応答しなければ `systemctl --user start cao-server.service` で起動し、最大 15 秒待つ。
- 端末バックエンドが herdr で、herdr のサーバーが止まっていれば、起動してから立ち上げる（前のセッションを閉じたときに herdr ごと止まり、cao-server を再起動するまで立ち上げられなくなるのを防ぐ）。
- `cao-doctor --brief` を実行し、CLI バージョン変化やパッチ未適用があれば標準エラーに表示する（起動は止めない）。
- セッション名はプロジェクト名を小文字・ハイフン化した `cao-<project>`（すでに `cao-` で始まるプロジェクト名でも `cao-cao-...` にはならない）。既定以外のリーダー指定時は `-agy` や `-codex` などの接尾辞が付く。
- 同名の既存セッションが**別のフォルダ**で動いている場合は、取り違えを防ぐためエラーで停止する。

### リーダーが終了したセッションの判定・片付け・再起動

既存セッションがある場合、リーダーがすでに終了してシェルに戻っていないかを判定する（`leader_exited`）。

1. CAO API `http://localhost:9889/sessions/<sess>` の `terminals` が 0 件なら、リーダーのいない残骸（同じ名前のワークスペースだけが残っている状態）として「終了」と判定する。
2. CAO API `http://localhost:9889/sessions/<sess>` からリーダーのターミナル（`agent_profile` が `*_lead`、なければ先頭）の `tmux_window` と `status` を取得する。
3. **herdr バックエンドの場合**:
   - ワークスペース（`label == <sess>`）とリーダーのタブ（`label == <tmux_window>`）を探す。
   - ワークスペースまたはタブが見つからない場合:
     - CAO の `status` が `unknown` 以外なら「生きている」とみなす。
     - `status` が `unknown` なら **1 秒待ってから判定全体（CAO API の取得からワークスペース・タブ・ペインの検索まで）を最初から 1 回だけやり直す**。2 回目も見つからず `status` が `unknown` のときだけ「終了」と判定する。
   - タブが見つかった場合:
     - そのタブ内のラベルなしペイン（`label == ""`）を調べる。
     - 1 つでも `agent` フィールドが付いていれば「生きている」とみなす（同じタブにユーザーが自分で開いたシェルペインが同居していても誤判定しない）。
     - すべてのラベルなしペインの `terminal_title` がシェルのプロンプト形式（`user@host:`）で、**かつ** CAO の `status` が `unknown` のときだけ「終了」と判定する（`codex` や `agy` のリーダーには herdr の `agent` が付かないことがあるため、`status` が `idle` / `processing` / `completed` なら生きているとみなす）。
4. **tmux バックエンドの場合**:
   - CAO の `status` が `unknown` で、かつ `tmux list-panes -t "$sess:$window" -F '#{pane_current_command}'` の**すべてのペイン**がシェル（`bash` / `zsh` / `sh`）のときだけ「終了」と判定する。
5. **安全側の原則**: API やコマンドの失敗、複数ヒットなど、確実に判定できない場合はすべて「生きている」とみなす。
6. **片付けと再起動**:
   - 「終了」と判定された場合、`cao shutdown --session <sess>` で古いセッションを片付け、`cao-recap` を実行してから新しいセッションを起動して画面を切り替える。
   - `herdr` や `tmux` の内部から実行された場合は、`shutdown` で自分自身のペインが閉じても再起動処理が止まらないよう、`CAO_DEV_RESTART=1 setsid nohup` で切り離して実行する（ログは `<project>/.cao/tmp/cao-dev-restart.log`）。

---

## `cao-recap` — 前回の Claude 会話の要約生成

対象プロジェクトの最新の Claude Code 会話履歴からテキスト発言だけを抜き出し、`<project>/.cao/last-session.md` に書き出す。`cao-dev` が新規セッション起動の直前に自動で呼び出す。

### 書式

```bash
cao-recap <project_dir> [--exclude <session-id>]
```

### 動作仕様

- 参照元: `~/.claude/projects/<絶対パスの英数字とハイフン以外を - に置換した名前>/*.jsonl` のうち、`--exclude` で指定されたセッション ID を除く最新（更新時刻が最も新しい）ファイル。
- 巨大ファイル対策: ファイル末尾から最大 4MB だけを読み込み、1 行が 256KB を超える行は読み飛ばす。壊れた UTF-8（`errors='replace'`）や不正な JSON 行、文字列以外のテキスト要素は無視する。
- 抽出内容: `type` が `user` または `assistant` のメッセージからテキスト部分だけを抽出し（ツール呼び出しや結果は除外）、最後の 30 件・1 件あたり 800 文字までを残す。
- 出力先: `<project_dir>/.cao/last-session.md`（先頭に会話 ID・最終更新時刻・元ファイルのパスを記録）。書き出し前に `git rev-parse --git-path info/exclude` に `.cao/` を追加する。
- 会話記録が存在しない場合は何もせず終了コード `0` で終了する。
- **リーダー側の扱い**: リーダーは `.cao/last-session.md` を毎回自動では読まず、ユーザーから「前回の続き」「さっきの件」など前のセッションへの言及があったときだけ読む（トークン節約のため）。

---

## `cao-doctor` — 環境・バージョン変化・パッチ状態の診断

`cao-server`、各 CLI、端末バックエンド、パッチの適用状態を確認し、「前回正常に動いたときのバージョン組み合わせ」との差分を表示する。

### 書式

```bash
cao-doctor          # すべての状態と、前回記録からの変化を表示
cao-doctor --save   # 問題がなければ現在のバージョン組み合わせを記録
cao-doctor --brief  # 問題と変化だけを表示（cao-dev が起動時に呼ぶ）
cao-doctor -h | --help
```

### 動作仕様

- `<CAO_HOME_DIR>/agents/*/*.md` の frontmatter から実際に使われている `provider` を調べ、`cao`・該当 CLI（`claude`, `codex`, `agy`）・端末バックエンド（`herdr` または `tmux`）のバージョンを取得する。
- `terminal.backend` が `herdr` の場合は `cao-patch --check` を実行し、未適用のパッチがあれば「注意」として表示する。
- `http://localhost:9889/health`（環境変数 `CAO_SERVER_URL` で変更可）で `cao-server` の死活を確認する。
- `--save` を指定すると、問題（`NG`）がない場合のみ `<CAO_HOME_DIR>/cao-trio-known-good.json` にバージョン一覧を保存する。

---

## `cao-patch` — CAO 本体へのパッチ管理

インストール済みの CAO 2.5.4（`site-packages/cli_agent_orchestrator`）に対して、`patches/cao-2.5.4-*.patch` をファイル名順に適用・確認・逆適用する（各パッチの内容は [docs/architecture.md](architecture.md) を参照）。
複数パッチの適用途中で失敗した場合は、その回に当てたパッチを自動で逆順に元に戻す。

### 書式

```bash
cao-patch            # 未適用のパッチを名前順に適用（cao-server の再起動は行わない）
cao-patch --check    # 各パッチの適用状態を表示（未適用があれば終了コード 1）
cao-patch --reverse  # 適用済みのパッチを逆順に外す
cao-patch -h | --help
```

### 終了コード

| コード | 意味 |
|---|---|
| `0` | 適用完了、`--check` で全パッチ適用済み、または `--reverse` で逆適用完了 |
| `1` | `--check` で 1 つ以上のパッチが未適用 |
| `2` | `cao` / `patch` コマンド不在、CAO バージョンが `2.5.4` 以外、またはパッチがファイルと一致しない |

---

## `cao-trace` — 委譲履歴と画面ログの追跡

終了して消えたワーカーも含め、誰が誰に何を依頼し何を返したかを一覧表示する。ファイルを一切書き換えない読み取り専用コマンド。

### 書式

```bash
cao-trace                    # 記録が残っているセッション一覧（最終更新時刻・担当数）
cao-trace <session|project>  # セッション内の担当者を呼び出し順・親子関係（字下げ）で表示
cao-trace <terminal_id>      # 指定ターミナルの画面ログ（.log または .scrollback）を表示
cao-trace -h | --help
```

### 動作仕様

- `<CAO_HOME_DIR>/logs/terminal/*.snapshot.json` からターミナル一覧と親子関係（`caller_id`）を復元する。
- `<CAO_HOME_DIR>/db/cli-agent-orchestrator.db` を読み取り専用（`mode=ro`）で開き、`handoff_results` テーブルの結果と、`inbox` テーブルに届いた `send_message`（`assign` されたワーカーからの報告）の両方を結合して各担当の `[完了]` / `[失敗]` / `[報告]` と先頭行を表示する。
- セッション指定は、`cao-myapp`、`myapp`、または末尾が `-myapp` のいずれでも一致する。

---

## `cao-models` — モデルの一覧と一括置換

全プロファイルが指定しているモデルを一覧表示し、指定したモデル名を一括で置き換える。

### 書式

```bash
cao-models                           # プロバイダ・モデルごとにプロファイル名を表示（* は local/agents の上書き）
cao-models replace <OLD> <NEW>       # model: <OLD> のプロファイルを直接 <NEW> に書き換える
cao-models replace --local <OLD> <NEW>  # 元のファイルは変えず、local/agents/ にコピーして書き換える
cao-models -h | --help
```

### 動作仕様

- `agents/*/*.md` と `local/agents/*.md` の YAML frontmatter 内の `model:` 行だけを対象にする（本文は書き換えない）。
- `--local` を付けると、対象プロファイルを git 管理外の `local/agents/` にコピーした上で `model:` を書き換えるため、`git pull` で競合しない。
