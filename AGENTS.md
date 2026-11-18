# AGENTS.md

このページで分かること: AI エージェントがこのリポジトリを理解・変更・検証するための要点と、詳細ドキュメントへの案内。

## このリポジトリは何か

- [CLI Agent Orchestrator（CAO）](https://github.com/awslabs/cli-agent-orchestrator) 上で、Claude Code・Codex・agy（Antigravity CLI）の 3 系統を役割分担させて開発するためのプロファイル・補助コマンド・パッチ一式。
- リーダー（Claude Opus 等）が設計・タスク分解・最終確認を担い、実装（Codex）・レビュー（Codex 読み取り専用）・調査や文章作成（agy / Claude）を委譲する。
- `install.sh` で `<CAO_HOME_DIR>`（既定 `~/.aws/cli-agent-orchestrator`）や `~/.local/bin`、`~/.codex` にシンボリックリンクを張って使う。

## ディレクトリの地図

- `agents/team/`: 役割分担チームのプロファイル（リーダー 3 体＋ワーカー 27 体の計 30 体）
- `agents/{claude,codex,agy}/`: 役割を固定しない汎用プロファイル
- `bin/`: 運用コマンド（`cao-dev`, `cao-doctor`, `cao-models`, `cao-patch`, `cao-recap`, `cao-trace`）
- `codex/`: Codex 用サンドボックス設定（書き込み可 `cao.config.toml`、読み取り専用 `cao-ro.config.toml`）
- `patches/`: CAO 2.5.4 本体に対するパッチ（`bin/cao-patch` で適用・確認・逆適用）
- `skills/`: CAO 共有スキル（`ponytail`, `ponytail-review`, `ponytail-audit`）
- `system/`: systemd ユーザーサービス（`cao-server.service`）と AppArmor 設定（`apparmor-bwrap`）のテンプレート
- `flows/`: 定期実行用の定義とスクリプト（未コミットリポジトリの週次要約）
- `workflows/`: ワークフロー定義サンプル（`review_changes.py`）
- `docs/`: 構成・ロール・セットアップ・ツール・現状のドキュメント
- `test/`: インストーラー・プロファイル・各コマンド・パッチの自動テスト
- `local/`・`local.env`: 個人設定とプロファイル上書き置き場（git 管理外）

## テスト

変更後は次のコマンドをすべて実行して通ることを確かめる。

```bash
bash test/install.test.sh
bash test/profiles.test.sh
bash test/tools.test.sh
PY=~/.local/share/uv/tools/cli-agent-orchestrator/bin/python
for t in test/*_test.py; do PYTHONDONTWRITEBYTECODE=1 $PY "$t"; done
# 実機の herdr を使う確認（別名の herdr セッションで動く）: test/herdr_pane_live.py
```

- `test/herdr_pane_live.py` は実機の herdr を操作するため、通常のテストでは実行しない。

## 変更するときの決まり

- **シンボリックリンク方式**: `install.sh` はファイルをコピーせずリンクを張る。リポジトリ内のファイルを編集すると即座にリンク先に反映される（稼働中セッションには再起動後に反映）。
- **リーダー規約 3 ファイルの同期**: `agents/team/{claude_opus,agy_opus,codex_sol}_lead.md` の本文（最初の `## ` 以降）はスキル呼び出しの 1 行を除き同一にする。全チームプロファイルの共通節（`## Security Constraints`、`## CAO での受け答え`、`## 学習（cao-learning）`）も一致させる。`bash test/profiles.test.sh` が検査する。
- **プロファイルの制約**: `provider` は `claude_code` / `codex` / `antigravity_cli` のいずれか。Claude Code は `permissionMode: auto`、Codex は `codexProfile: cao`（reviewer と `*_retrospector` は `cao-ro`）が必須。`allowedTools` に `"*"` は禁止。
- **CAO 本体への変更はパッチで管理**: インストール済みの `site-packages` を直接書き換えない。パッチは `patches/cao-<version>-*.patch` に置き、`bin/cao-patch` で適用する。テストは一時コピー上で行う。
- **`cao-server` を無断で再起動しない**: 再起動すると子プロセスの herdr `cao` セッションごと稼働中の全エージェントが停止する。再起動が必要な場合はユーザーに手順を案内する。
- **公開リポジトリの制約**: IP アドレス、ホスト名、メールアドレス、個人名、秘密情報、他プロジェクト名をコミット対象ファイルに書かない。環境固有の情報は git 管理外の `local/` や `local.env` に置く。

## 詳しいドキュメント

- [README.md](README.md): 全体概要・クイックスタート・カスタマイズ方法
- [docs/architecture.md](docs/architecture.md): 構成要素・セッション構造・委譲とメッセージ配送・サンドボックス・パッチの仕組み
- [docs/roles.md](docs/roles.md): チームのロール設計・モデル選択・ルーティング規約
- [docs/setup.md](docs/setup.md): インストール詳細・パッチ適用・systemd / AppArmor / herdr 設定
- [docs/tools.md](docs/tools.md): `bin/` 配下の各コマンドの仕様と使い方
- [docs/status.md](docs/status.md): 目標・到達点・既知の課題・変更履歴
