# cao-trio

[CLI Agent Orchestrator（CAO）](https://github.com/awslabs/cli-agent-orchestrator) で、**Claude Code・Codex・agy（Antigravity CLI）を役割分担させて開発するための設定一式**です。

> **English summary:** A ready-to-use team of CAO agent profiles. A lead (Claude Opus) plans and delegates; Codex writes code, a different model family reviews it, Gemini-based agents research and write. Includes a launcher (`cao-dev`), read-only sandboxes for reviewers, and an installer that symlinks everything into place. Docs are in Japanese.

## どう動くか

```
あなた ──依頼──> リーダー（Claude Opus）
                  │  設計して、仕事を振り分ける
                  ├─> 調査（agy）        … 調べて要約だけ返す
                  ├─> 実装（Codex）      … コードとテストを書く（サンドボックス内）
                  ├─> レビュー（Codex）  … 実装より上の格が独立して確認（読み取り専用）
                  └─> 文章・資料（agy / Claude）
                  │
                  └─ diff とテスト結果を自分で確かめてから、あなたに報告
```

- **足りる中で一番安いモデルを使う**：小さな修正は軽いモデル、難しい不具合だけ上位モデル。
- **書く役と確かめる役を分ける**：レビュー担当は実装より上の格のモデル（terra の実装を sol が、sol の実装を astra が）で、ファイルを書けない設定で動きます。Claude のトークンを節約するため、Claude のレビュー担当は予備です。
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
git clone https://github.com/jantyran/cao-trio.git
cd cao-trio
./install.sh --dry-run
./install.sh

# 3. cao-server を起動
systemctl --user start cao-server.service

# 4. 自分用の設定（プロジェクトの置き場など。既定は ~/projects）
cp local.env.example local.env     # 中の CAO_DEV_ROOT="$HOME/code" などを書き換える

# 5. 作業したいプロジェクトで起動
cao-dev myapp                      # ~/code/myapp でリーダーと対話を始める
```

`install.sh` はファイルをコピーせず、シンボリックリンクを張ります。既存のファイルは `.bak-日時` に退避し、上書きしません。何をするかの詳細、systemd・Node.js・AppArmor の設定、元に戻す方法は [docs/setup.md](docs/setup.md) にあります。

## 使い方

```bash
cao-dev --list                            # プロジェクト一覧
cao-dev myapp                             # 対話で始める（既存セッションがあれば接続）
cao-dev myapp "ログイン画面のバグを直して"  # 依頼だけ投げてバックグラウンドで実行
cao-dev                                   # 置き場の中か git リポジトリの中なら名前を省略できる
cao-dev ~/work/other                      # 置き場の外はパスで指定（~/other なら名前だけでも可）
cao-dev --lead agy_opus_lead myapp        # Claude が利用上限のとき、予備のリーダーで起動
```

| やりたいこと | コマンド（`~/code/myapp` の場合） |
|---|---|
| 進み具合を見る | `cao session status cao-code-myapp --workers` |
| 追加で依頼する | `cao-dev myapp "続けてテストも足して"` |
| セッションを終える | `cao shutdown --session cao-code-myapp` |

セッション名は `cao-<置き場のフォルダ名>-<プロジェクト名>` です。

### 困ったとき・後から調べたいとき

| コマンド | 用途 |
|---|---|
| `cao-doctor` | cao-server と各 CLI の状態を確認。前回うまく動いたときから CLI のバージョンが変わっていれば知らせる |
| `cao-doctor --save` | 問題なく動いたときに、今のバージョンの組み合わせを記録する |
| `cao-trace myapp` | 誰が誰に何を頼み、何を返したかを一覧表示（終了して消えた担当者も含む） |
| `cao-trace <terminal_id>` | その担当者の画面の記録を表示 |
| `cao-models` | どのプロファイルがどのモデルを使っているかの一覧 |
| `cao-models replace --local 古い名前 新しい名前` | モデル名を一括で置き換える（`local/agents` に書くので git pull で衝突しない） |

CAO は各 CLI の画面を読んで動いているため、CLI の更新で急に動かなくなることがあります。`cao-dev` は起動のたびに `cao-doctor --brief` を実行し、記録時からバージョンが変わった CLI があれば表示します。cao-server が止まっていれば、systemd で自動的に起動します。

`cao-dev` は起動時に次のことも自動で行います。

- Codex の「このフォルダを信頼しますか」で止まらないよう、`~/.codex/config.toml` にプロジェクトを trusted として追加
- リーダーの指示書置き場 `.cao/` を、そのプロジェクトの `.git/info/exclude` に追加（コミットされません）

## 自分用に変える

自分用の変更は、git 管理外の 2 か所だけに書きます。cao-trio のファイルには触らないので、`git pull` で更新しても衝突しません。

| 置き場 | 書くもの |
|---|---|
| `local.env` | プロジェクトの置き場（`CAO_DEV_ROOT`）、既定のリーダー（`CAO_DEV_LEAD`） |
| `local/agents/` | 変えたいプロファイルのコピー。同じ名前なら、こちらが優先して使われる |

### 設定（local.env）

```bash
cp local.env.example local.env
```

`cao-dev` と定期実行（`flows/`）の両方がこのファイルを読みます。環境変数で指定した値はこちらより優先され、1 回だけリーダーを変えるなら `--lead` を使います。

### プロファイルを変える（local/agents）

変えたいプロファイルを `local/agents/` にコピーして編集します。

```bash
cp agents/team/codex_terra_coder.md local/agents/
vi local/agents/codex_terra_coder.md        # モデル・指示などを自由に変える
```

元に戻すときは、そのファイルを消すだけです。動いているセッションには、起動し直すと反映されます。

**モデルを一斉に変える**ときは、次のコマンドが該当するプロファイルを `local/agents/` にコピーして書き換えます。使えるモデル名は、契約しているプランと各 CLI のバージョンで変わります。

```bash
cao-models                                         # 今のモデルの一覧（* は local の上書き）
cao-models replace --local gpt-6.1-sol 新しい名前
```

**使わない AI がある**場合は、リーダー（`claude_opus_lead.md`）を `local/agents/` にコピーし、本文の「チームと使い分け」の表で、その AI の担当を別の担当に置き換えます。たとえば agy を使わないなら、調査は `codex_luna_researcher`、文章は `claude_sonnet_writer` にします。

**担当を増やす**ときは、既存のプロファイルを `local/agents/` にコピーして `name:`・`description:`・本文を書き換え、リーダーの表に 1 行足します。守るべき決まりは次のとおりです。`bash test/profiles.test.sh` は `local/agents/` も確認します。

- `provider` は `claude_code` / `codex` / `antigravity_cli` のどれか
- Claude Code は `permissionMode: auto`
- Codex は `codexProfile: cao`（読み取り専用の役なら `cao-ro`）
- `allowedTools` に `"*"` を入れない

### まずは少ない担当で始める

担当は 29 体いますが、全部を使う必要はありません。リーダーは仕事に合わせて選ぶので、最初は次の 4 役が動けば十分です。ほかの担当は、必要な場面でだけ使われます。

| 役 | 担当 | 使う CLI |
|---|---|---|
| リーダー | `claude_opus_lead` | Claude Code |
| 実装 | `codex_terra_coder` | Codex |
| レビュー | `codex_sol_reviewer` | Codex |
| 調査 | `agy_flash_researcher`（agy がなければ `codex_luna_researcher`） | agy / Codex |

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
| `agents/team/` | チームのプロファイル（リーダー 3 体＋担当 26 体） |
| `agents/{claude,codex,agy}/` | 役割を決めない汎用プロファイル |
| `skills/` | 共有スキル（ponytail：最小の変更で解くための指針） |
| `bin/cao-dev` | プロジェクトごとのセッション起動コマンド |
| `bin/cao-doctor`、`bin/cao-trace`、`bin/cao-models` | 状態確認、作業の追跡、モデル名の管理 |
| `codex/` | Codex のサンドボックス設定（書き込み用・読み取り専用） |
| `system/` | systemd ユニットと AppArmor 設定のテンプレート |
| `flows/` | 定期実行のサンプル（毎週、未コミットのリポジトリを要約） |
| `workflows/` | ワークフローのサンプル（差分の要約 → レビュー） |
| `docs/` | [ロール設計](docs/roles.md)、[セットアップ詳細](docs/setup.md) |
| `local.env.example` | 自分用の設定のひな形（コピーした `local.env` と `local/` は git 管理外） |
| `test/` | インストーラーとプロファイルの検証 |

## 更新とテスト

リンクなので、ファイルを編集するとすぐ反映されます。ただし動いているセッションは起動時の設定のままなので、`cao shutdown --session …` してから起動し直してください。

```bash
bash test/install.test.sh    # 一時 HOME で install.sh を検証（本物の HOME は変更しない）
bash test/profiles.test.sh   # プロファイルの決まりと、リーダー 3 体の本文のずれを検証
bash test/tools.test.sh      # cao-doctor / cao-trace / cao-models を一時コピーで検証
```

CLI を更新したら、`cao-doctor` で確認し、問題なく動いたら `cao-doctor --save` で記録し直してください。

## 注意

- プロファイルの本文は日本語です。リーダーも日本語で報告します。
- 一部のプロファイルは、Claude Code の [superpowers](https://github.com/obra/superpowers) プラグインのスキルを使うよう書かれています。入っていなくても動きますが、該当の手順は飛ばされます。
- 個人の環境に合わせて作ったものです。CAO や各 CLI の更新で動かなくなることがあります。

## ライセンス

`skills/ponytail*` は [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail)（MIT）を元にしています。詳細は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。
