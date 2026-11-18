# cao-trio

このページで分かること: `cao-trio` の全体像、導入手順、基本コマンド、自分用にカスタマイズする方法。AI エージェント向けの要点は [AGENTS.md](AGENTS.md) を参照。

[CLI Agent Orchestrator（CAO）](https://github.com/awslabs/cli-agent-orchestrator) で、**Claude Code・Codex・agy（Antigravity CLI）を役割分担させて開発するための設定・補助ツール・パッチ一式**。

> **English summary:** A ready-to-use team of CAO agent profiles. A lead (Claude Opus) plans and delegates; Codex writes code, a read-only reviewer checks it independently, and Gemini-based agents research and write. Includes a session launcher (`cao-dev`), previous-session recap (`cao-recap`), CAO patches (`cao-patch`), read-only sandboxes for reviewers, and an installer that symlinks everything into place. Docs are in Japanese.

## どう動くか

```
あなた ──依頼──> リーダー（Claude Opus）
                  │  設計して、仕事を振り分ける
                  ├─> 調査（agy）        … 調べて要約と根拠パスだけ返す
                  ├─> 実装（Codex）      … コードとテストを書く（workspace-write）
                  ├─> レビュー（Codex）  … 独立して確認（read-only）
                  └─> 文章・資料（agy / Claude）
                  │
                  └─ diff とテスト結果を自分で確かめてから報告
```

- **足りる中で一番安いモデルを使う**: 定型・小修正は `codex_luna_coder`、標準の実装は `codex_terra_coder` から始め、2 回差し戻されたときだけ `sol` → `astra` へ段階的に格上げする。
- **書く役と確かめる役を分ける**: レビューは原則 `codex_sol_reviewer`（読み取り専用サンドボックス）が独立して担当し、`codex_astra_reviewer` は 2 回まとまらないときの最後の手段とする。Claude のトークンを節約するため Claude のレビュー担当は予備。
- **利用上限への備え**: 主な役割ごとに別系統 AI の予備を持つ（リーダーは Claude → agy → Codex）。
- **herdr での 2×2 ペイン表示**: パッチ適用により、ワーカーはリーダーと同じタブ内のペイン（最大 4 ペイン・2×2 グリッド、5 体目以降は別タブ）に並んで表示される。

ロール設計とルーティングの詳細は [docs/roles.md](docs/roles.md)、内部構成とデータの流れは [docs/architecture.md](docs/architecture.md) を参照。

## 必要なもの

- Linux（Ubuntu で確認）、bash、systemd ユーザーサービス、`patch`、Python 3
- [uv](https://docs.astral.sh/uv/)（CAO のインストールに使用）
- tmux（または herdr + jq）、curl
- 使う AI の CLI とログイン
  - [Claude Code](https://docs.claude.com/en/docs/claude-code)（`claude`）
  - Codex CLI（`codex`）
  - Antigravity CLI（`agy`）

3 つすべてが揃っていなくても動作する。使わない AI がある場合は「[自分用に変える](#自分用に変える)」を参照。

## はじめかた

```bash
# 1. CAO（2.5.4）を入れる
uv tool install cli-agent-orchestrator
export PATH="$HOME/.local/bin:$PATH"

# 2. リポジトリを取得し、内容を確認してからリンクを張る
git clone https://github.com/jantyran/cao-trio.git
cd cao-trio
./install.sh --dry-run
./install.sh

# 3. herdr を使う場合は CAO 2.5.4 用パッチを当てる
cao-patch --check
cao-patch

# 4. cao-server を起動し、正常動作時の CLI バージョンを記録
systemctl --user start cao-server.service
cao-doctor --save

# 5. 自分用の設定（プロジェクトの置き場など。既定は ~/projects）
cp local.env.example local.env     # CAO_DEV_ROOT="$HOME/code" などを設定

# 6. 作業したいプロジェクトで起動
cao-dev myapp                      # ~/code/myapp でリーダーと対話を開始
```

`install.sh` はファイルをコピーせずシンボリックリンクを張る（既存ファイルは `.bak-日時` に退避）。インストール処理・パッチ適用・systemd / Node.js / AppArmor / herdr の設定手順は [docs/setup.md](docs/setup.md) を参照。

## 使い方

```bash
cao-dev --list                            # プロジェクト置き場の一覧
cao-dev myapp                             # 対話で開始（既存セッションがあれば接続）
cao-dev myapp "ログイン画面のバグを直して"  # 依頼だけ投げてバックグラウンドで非同期実行
cao-dev                                   # 置き場配下や git リポジトリ内ならそのプロジェクトで起動
                                          # それ以外の場所では、開いているセッションの画面に入る
cao-dev ~/work/other                      # 置き場の外はパスで指定（~/other なら名前だけでも可）
cao-dev --lead agy_opus_lead myapp        # Claude が利用上限のとき、予備リーダーで起動
```

| やりたいこと | コマンド（`~/code/myapp` の場合） |
|---|---|
| 進み具合を見る | `cao session status cao-myapp --workers` |
| 追加で依頼する | `cao-dev myapp "続けてテストも足して"` |
| セッションを終える | `cao shutdown --session cao-myapp` |

`cao-dev` は起動時に次の処理を自動で行う（詳細は [docs/tools.md](docs/tools.md)）。

- `cao-server` が停止していれば systemd で自動起動
- `cao-doctor --brief` で CLI バージョン変化やパッチ未適用を通知
- リーダーが終了してシェルに戻っている既存セッションを検出したら、`cao shutdown` で片付けてから再起動
- `cao-recap` で前回の Claude 会話の要約を `<project>/.cao/last-session.md` に書き出し（リーダーに「前回の続き」と伝えると参照される）
- `~/.codex/config.toml` にプロジェクトの trusted 設定を追加し、`.git/info/exclude` に `.cao/` を追加

### 補助コマンド一覧

各コマンドの詳しいオプションと動作は [docs/tools.md](docs/tools.md) を参照。

| コマンド | 用途 |
|---|---|
| `cao-dev` | プロジェクト別セッションの起動・再接続・終了済みリーダーの片付けと再起動 |
| `cao-recap` | 直近の Claude 会話履歴から要約 `<project>/.cao/last-session.md` を生成 |
| `cao-doctor` | `cao-server`・各 CLI・パッチ適用状態の確認と、正常動作時のバージョン記録（`--save`） |
| `cao-patch` | CAO 2.5.4 本体へのパッチ適用・状態確認（`--check`）・逆適用（`--reverse`） |
| `cao-trace` | セッション内の委譲ツリー・結果・各ターミナルの画面ログを表示 |
| `cao-models` | プロファイルのモデル一覧表示と一括置換（`replace --local`） |

## 自分用に変える

自分用の変更は git 管理外の 2 か所に置くため、`git pull` で衝突しない。

| 置き場 | 書くもの |
|---|---|
| `local.env` | プロジェクトの置き場（`CAO_DEV_ROOT`）、既定のリーダー（`CAO_DEV_LEAD`） |
| `local/agents/` | 上書き・追加したいプロファイル（同名ならこちらが優先） |

- **モデルを一括変更する**: `cao-models replace --local <古いモデル名> <新しいモデル名>` で対象プロファイルを `local/agents/` にコピーして書き換える。
- **使わない AI がある**: リーダー（`claude_opus_lead.md`）を `local/agents/` にコピーし、「チームと使い分け」の表を別 AI の担当に差し替える（例: agy を使わないなら調査は `codex_luna_researcher`、文章は `claude_sonnet_writer`）。
- **少ない担当で始める**: 30 体すべてを使う必要はなく、リーダー（`claude_opus_lead`）・実装（`codex_terra_coder`）・レビュー（`codex_sol_reviewer`）・調査（`agy_flash_researcher` または `codex_luna_researcher`）の 4 役があれば基本サイクルが回る。

## 安全のための設定

| AI | 起動設定 | 制限 |
|---|---|---|
| Codex（実装） | `codexProfile: cao` | 作業フォルダ内のみ書き込み可（`workspace-write`）、ネット遮断、承認は `auto_review` |
| Codex（レビュー・調査・振り返り） | `codexProfile: cao-ro` | 読み取り専用（`read-only`） |
| Claude Code | `permissionMode: auto` | 危険な操作を分類器が阻止。`role: reviewer` は書き込みツール禁止 |
| agy | CAO が常時自動許可で起動 | **制限なし**（プロンプトの指示のみ） |

サンドボックスと MCP 承認設定の詳細は [docs/architecture.md](docs/architecture.md) を参照。

## ドキュメント一覧

| ドキュメント | 内容 |
|---|---|
| [AGENTS.md](AGENTS.md) | AI エージェント向けの入口（ディレクトリ地図・テスト・変更ルール） |
| [docs/architecture.md](docs/architecture.md) | 構成要素、セッションとペインの構造、委譲とメッセージ配送、サンドボックス、パッチの仕組み |
| [docs/roles.md](docs/roles.md) | チームのロール設計原則、担当一覧、予備ロール、レビューと並列化の規約 |
| [docs/setup.md](docs/setup.md) | `install.sh` の処理、パッチ適用と再起動、systemd・AppArmor・herdr 設定 |
| [docs/tools.md](docs/tools.md) | `bin/` の全 6 コマンドの詳しい使い方と内部動作 |
| [docs/status.md](docs/status.md) | プロジェクトの目標、達成状況、既知の課題と回避策、主な変更履歴 |

## テスト

```bash
bash test/install.test.sh
bash test/profiles.test.sh
bash test/tools.test.sh
PY=~/.local/share/uv/tools/cli-agent-orchestrator/bin/python
for t in test/*_test.py; do PYTHONDONTWRITEBYTECODE=1 $PY "$t"; done
# 実機の herdr を使う確認（別名の herdr セッションで動く）: test/herdr_pane_live.py
```

## ライセンス

`skills/ponytail*` は [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail)（MIT）を元にしている。詳細は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照。
