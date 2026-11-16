# cao-kit

[CLI Agent Orchestrator（CAO）](https://github.com/awslabs/cli-agent-orchestrator) で、**Claude Code・Codex・agy（Antigravity CLI）を役割分担させて開発するための設定一式**です。

> **English summary:** A ready-to-use team of CAO agent profiles. A lead (Claude Opus) plans and delegates; Codex writes code, a different model family reviews it, Gemini-based agents research and write. Includes a launcher (`cao-dev`), read-only sandboxes for reviewers, and an installer that symlinks everything into place. Docs are in Japanese.

## どう動くか

```
あなた ──依頼──> リーダー（Claude Opus）
                  │  設計して、仕事を振り分ける
                  ├─> 調査（agy）        … 調べて要約だけ返す
                  ├─> 実装（Codex）      … コードとテストを書く（サンドボックス内）
                  ├─> レビュー（Claude） … 実装とは別の AI が確認（読み取り専用）
                  └─> 文章・資料（agy / Claude）
                  │
                  └─ diff とテスト結果を自分で確かめてから、あなたに報告
```

- **足りる中で一番安いモデルを使う**：小さな修正は軽いモデル、難しい不具合だけ上位モデル。
- **書く役と確かめる役を分ける**：レビュー担当は実装と別系統の AI で、ファイルを書けない設定で動きます。
- **利用上限への備え**：主な役割ごとに別の AI の予備があります（リーダーは Claude → agy → Codex）。

ロールの詳しい設計と根拠は [docs/roles.md](docs/roles.md) にあります。

## 必要なもの

- Linux（Ubuntu で確認）、bash、systemd のユーザーサービス
- [uv](https://docs.astral.sh/uv/)（CAO のインストールに使用）
- tmux（または herdr + jq）、curl
- 使う AI の CLI と、それぞれのログイン
  - [Claude Code](https://docs.claude.com/en/docs/claude-code)（`claude`）
  - Codex CLI（`codex`）
  - Antigravity CLI（`agy`）

3 つすべてなくても動きます。使わない AI がある場合は「[自分用に変える](#自分用に変える)」を見てください。

## はじめかた

```bash
# 1. CAO を入れる
uv tool install cli-agent-orchestrator
export PATH="$HOME/.local/bin:$PATH"

# 2. このリポジトリを取ってきて、インストール内容を確認してから実行
git clone https://github.com/jantyran/cao-kit.git
cd cao-kit
./install.sh --dry-run
./install.sh

# 3. cao-server を起動
systemctl --user start cao-server.service

# 4. 作業したいプロジェクトで起動（既定のプロジェクト置き場は ~/mypark）
export CAO_DEV_ROOT="$HOME/code"   # 置き場を変えるなら。~/.bashrc などに書いておく
cao-dev myapp                      # ~/code/myapp でリーダーと対話を始める
```

`install.sh` はファイルをコピーせず、シンボリックリンクを張ります。既存のファイルは `.bak-日時` に退避し、上書きしません。何をするかの詳細、systemd・Node.js・AppArmor の設定、元に戻す方法は [docs/setup.md](docs/setup.md) にあります。

## 使い方

```bash
cao-dev --list                            # プロジェクト一覧
cao-dev myapp                             # 対話で始める（既存セッションがあれば接続）
cao-dev myapp "ログイン画面のバグを直して"  # 依頼だけ投げてバックグラウンドで実行
cao-dev                                   # プロジェクトのフォルダ内なら名前を省略できる
cao-dev --lead agy_opus_lead myapp        # Claude が利用上限のとき、予備のリーダーで起動
```

| やりたいこと | コマンド（`~/code/myapp` の場合） |
|---|---|
| 進み具合を見る | `cao session status cao-code-myapp --workers` |
| 追加で依頼する | `cao-dev myapp "続けてテストも足して"` |
| セッションを終える | `cao shutdown --session cao-code-myapp` |

セッション名は `cao-<置き場のフォルダ名>-<プロジェクト名>` です。

`cao-dev` は起動時に次のことも自動で行います。

- Codex の「このフォルダを信頼しますか」で止まらないよう、`~/.codex/config.toml` にプロジェクトを trusted として追加
- リーダーの指示書置き場 `.cao/` を、そのプロジェクトの `.git/info/exclude` に追加（コミットされません）

## 自分用に変える

### プロジェクトの置き場

環境変数 `CAO_DEV_ROOT` で変えます（既定 `~/mypark`。旧名の `MYPARK_DIR` も使えます）。

### モデル

各プロファイル（`agents/team/*.md`）の先頭にある `model:` を書き換えます。使えるモデル名は、契約しているプランと各 CLI のバージョンで変わります。

```yaml
---
name: codex_sol_coder
provider: codex
model: "gpt-6.1-sol"     # ← ここ
---
```

### 使わない AI がある

リーダーは、プロファイル本文の「チームと使い分け」の表を見て仕事を振ります。たとえば agy を使わないなら、`agents/team/claude_opus_lead.md` の表で agy の担当を予備の担当（`codex_luna_researcher`、`claude_sonnet_writer` など）に置き換えてください。予備のリーダー（`agy_opus_lead.md`、`codex_sol_lead.md`）も同じ本文にしておく必要があります。ずれていると `test/profiles.test.sh` が失敗して教えてくれます。

### 既定のリーダー

`CAO_DEV_LEAD=agy_opus_lead` のように環境変数で変えられます。1 回だけなら `--lead` を使います。

### 担当を増やす

既存のプロファイルをコピーして `name:`・`description:`・本文を書き換え、リーダーの表に 1 行足します。守るべき決まりは次のとおりです（テストで確認されます）。

- `provider` は `claude_code` / `codex` / `antigravity_cli` のどれか
- Claude Code は `permissionMode: auto`
- Codex は `codexProfile: cao`（読み取り専用の役なら `cao-ro`）
- `allowedTools` に `"*"` を入れない

## 安全のための設定

| AI | 起動のしかた | 制限 |
|---|---|---|
| Codex | `codexProfile: cao` | 作業フォルダ内だけ書き込める。ネットワークは遮断。承認は自動レビューが判断 |
| Codex（レビュー・調査） | `codexProfile: cao-ro` | 読み取り専用 |
| Claude Code | `permissionMode: auto` | 危険な操作を分類器が止める。レビュー担当はファイルを書けない |
| agy | CAO が常に全自動許可で起動 | **制限なし**（プロンプトでの指示だけ） |

`cao-dev` は `--auto-approve` 付きで起動します。信頼できるプロジェクトだけで使ってください。agy の担当者は Web の内容を読みつつコマンドも実行できるため、気になる場合は agy を使わない構成にしてください。

## リポジトリの中身

| パス | 内容 |
|---|---|
| `agents/team/` | チームのプロファイル（リーダー 3 体＋担当 24 体） |
| `agents/{claude,codex,agy}/` | 役割を決めない汎用プロファイル |
| `skills/` | 共有スキル（ponytail：最小の変更で解くための指針） |
| `bin/cao-dev` | プロジェクトごとのセッション起動コマンド |
| `codex/` | Codex のサンドボックス設定（書き込み用・読み取り専用） |
| `system/` | systemd ユニットと AppArmor 設定のテンプレート |
| `flows/` | 定期実行のサンプル（毎週、未コミットのリポジトリを要約） |
| `workflows/` | ワークフローのサンプル（差分の要約 → レビュー） |
| `docs/` | [ロール設計](docs/roles.md)、[セットアップ詳細](docs/setup.md) |
| `test/` | インストーラーとプロファイルの検証 |

## 更新とテスト

リンクなので、ファイルを編集するとすぐ反映されます。ただし動いているセッションは起動時の設定のままなので、`cao shutdown --session …` してから起動し直してください。

```bash
bash test/install.test.sh    # 一時 HOME で install.sh を検証（本物の HOME は変更しない）
bash test/profiles.test.sh   # プロファイルの決まりと、リーダー 3 体の本文のずれを検証
```

## 注意

- プロファイルの本文は日本語です。リーダーも日本語で報告します。
- 一部のプロファイルは、Claude Code の [superpowers](https://github.com/obra/superpowers) プラグインのスキルを使うよう書かれています。入っていなくても動きますが、該当の手順は飛ばされます。
- 個人の環境に合わせて作ったものです。CAO や各 CLI の更新で動かなくなることがあります。

## ライセンス

`skills/ponytail*` は [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail)（MIT）を元にしています。詳細は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。
