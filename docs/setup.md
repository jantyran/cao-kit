# セットアップ詳細

このページで分かること: `install.sh` の詳細な処理内容、パッチの適用と `cao-server` 再起動手順、`local.env`・systemd・AppArmor・herdr・`cao-doctor --save` の設定方法。

基本の導入手順は [README.md](../README.md) を参照。

## `install.sh` がすること

`./install.sh --dry-run` で、変更を加えずに実行内容だけを確認できる。Codex の通知抑止設定だけを適用する場合は `./install.sh --apply-codex-notice-only` を使う。

1. **シンボリックリンクを張る**（リポジトリの編集がすぐリンク先に反映される）

   | リポジトリ内パス | リンク先 |
   |---|---|
   | `agents/{team,claude,codex,agy}` | `<CAO_HOME_DIR>/agents/{team,claude,codex,agy}` |
   | `local/agents`（git 管理外、なければ作成） | `<CAO_HOME_DIR>/agents/local`（最優先で探索される） |
   | `skills/{ponytail,ponytail-audit,ponytail-review}` | `<CAO_HOME_DIR>/skills/…` |
   | `bin/{cao-dev,cao-recap,cao-doctor,cao-models,cao-trace,cao-patch}` | `~/.local/bin/…` |
   | `codex/cao.config.toml`、`codex/cao-ro.config.toml` | `~/.codex/…` |

   リンク先に既存ファイルや別リンクがある場合は `.bak-YYYYmmddHHMMSS`（重複時は連番付き）に退避し、上書きしない。リンクは絶対パスのため、リポジトリを移動した場合は `./install.sh` を再実行する。

2. **Codex のモデル切替ダイアログを抑止する**
   `~/.codex/config.toml` が存在する場合、`[notice]` テーブルに `hide_rate_limit_model_nudge = true` を冪等で追加し、`tomllib` で構文を検証する（失敗時は自動ロールバック）。

3. **CAO の設定を保存する**（`cao config set`）

   | 項目 | 値 |
   |---|---|
   | `agents.extra_dirs` | リンクした agents ディレクトリ配列（`local` が先頭） |
   | `agents.disabled_dirs` | `~/.kiro/agents`、`<CAO_HOME_DIR>/agent-store`、`<CAO_HOME_DIR>/agent-context` |
   | `memory.learning_enabled` | `true` |
   | `terminal.spawn_mode` | `pane` |

4. **systemd ユーザーサービスを用意する**
   `~/.config/systemd/user/cao-server.service` がなければ `system/cao-server.service` から生成し、`daemon-reload` と `enable` を行う（起動はしない）。既存ユニットがある場合は変更しない。`cao-server` はループバックアドレスのポート `9889`（`localhost:9889`）のみで待ち受ける。

5. **AppArmor の案内を表示する**
   `/etc/apparmor.d/bwrap` がない環境では、手動コピー用のコマンドを表示する（`sudo` は自動実行しない）。

## パッチの適用と `cao-server` の再起動

herdr バックエンドでの 2×2 ペイン表示（`cao-2.5.4-herdr-pane-spawn.patch`）、Codex が `processing` のまま固まる問題の解消（`cao-2.5.4-herdr-codex-status.patch`）、handoff の結果を codex の会話記録（rollout）から読む対応（`cao-2.5.4-codex-rollout-output.patch`。読めなければ画面から切り出す）には、CAO 2.5.4 本体へのパッチ適用が必要（仕組みは [docs/architecture.md](architecture.md) を参照）。

```bash
# 1. 適用状態を確認（未適用があれば終了コード 1）
cao-patch --check

# 2. パッチを適用（名前順に site-packages へ適用）
cao-patch

# 3. 逆適用して原本に戻す場合
cao-patch --reverse
```

### `cao-server` 再起動時の注意と手順

パッチを適用・逆適用したあとは、`cao-server` を再起動するまで稼働中のサーバーには反映されない。
**注意: `cao-server` を再起動すると、子プロセスの herdr `cao` セッションごと稼働中の全セッション・全エージェントが停止する。**

1. 作業中のセッションがないことを確認する（`cao session list`）。
2. **herdr の外の通常ターミナル**から次を実行する。
   ```bash
   systemctl --user restart cao-server.service
   systemctl --user status cao-server.service
   ```
3. `cao-dev <project>` でセッションを起動し直す。

## CLI バージョンの記録（`cao-doctor --save`）

CAO は各 CLI の画面出力を解析して状態を判定するため、CLI のバージョン更新で挙動が変わることがある。正常に動作している状態でバージョン組み合わせを記録しておく。

```bash
cao-doctor          # cao-server・各 CLI・パッチ状態と前回記録からの変化を表示
cao-doctor --save   # 問題がなければ現在のバージョン組み合わせを <CAO_HOME_DIR>/cao-trio-known-good.json に保存
```

CLI を更新したあと問題なく動くことを確認したら、再度 `cao-doctor --save` を実行して記録を更新する。

## プロジェクト置き場と個人設定（`local.env`）

リポジトリ直下の `local.env`（git 管理外）で、プロジェクトの置き場（`CAO_DEV_ROOT`）と既定のリーダー（`CAO_DEV_LEAD`）を設定する。`cao-dev` と定期実行（`flows/dirty-repos.sh`）の両方がこのファイルを読み込む。

```bash
cp local.env.example local.env
```

```bash
# プロジェクトの置き場（既定 ~/projects）
CAO_DEV_ROOT="$HOME/code"

# 既定のリーダー（既定 claude_opus_lead）
#CAO_DEV_LEAD=agy_opus_lead
```

環境変数で `CAO_DEV_ROOT` や `CAO_DEV_LEAD` が指定されている場合は環境変数が優先される。

## 状態ディレクトリ（`CAO_HOME_DIR`）を変える

既定は `~/.aws/cli-agent-orchestrator`。変更する場合は絶対パスを指定して `./install.sh` を実行し、以後のコマンドでも同じ環境変数を使う。

```bash
export CAO_HOME_DIR="$HOME/.cao"
./install.sh
```

既存の systemd ユニットがある場合は `systemctl --user edit cao-server.service` で `Environment="CAO_HOME_DIR=..."` を追加する。

## systemd と Node.js

`cao-server.service` の既定 `PATH` は `%h/.local/bin:/usr/local/bin:/usr/bin:/bin`。nvm 等で入れた `node` や各 AI の CLI が別パスにある場合は drop-in で追加する。

```bash
command -v node claude codex agy
systemctl --user edit cao-server.service
```

```ini
[Service]
Environment="PATH=%h/.local/bin:/path/to/node/bin:/usr/local/bin:/usr/bin:/bin"
```

```bash
systemctl --user daemon-reload
systemctl --user restart cao-server.service
```

## AppArmor（Ubuntu 23.10 以降など）

Codex のサンドボックス（bubblewrap）が非特権 user namespace を使えずコマンド実行に失敗する環境では、次を実行する。

```bash
sudo cp system/apparmor-bwrap /etc/apparmor.d/bwrap
sudo apparmor_parser -r /etc/apparmor.d/bwrap
```

## herdr バックエンドへの切り替え

既定の端末バックエンドは `tmux`。`herdr` に切り替える場合は、全セッションを終了してから設定・パッチ適用・再起動を行う。`cao-dev` には `jq` も必要。

```bash
cao shutdown --all
cao config set terminal.backend herdr
cao config set terminal.spawn_mode pane
cao-patch
systemctl --user restart cao-server.service
```

## アンインストール（元に戻す）

1. パッチを当てている場合は `cao-patch --reverse` で外す。
2. `install.sh` が作成したシンボリックリンクを削除する（例: `rm ~/.local/bin/cao-{dev,recap,doctor,models,trace,patch}`）。
3. 退避された `.bak-*` ファイルがあれば元の名前に戻す。
4. `cao config set` した項目を必要に応じて戻し、`cao-server` を再起動する。

## 外部公開について

このリポジトリには、リバースプロキシ・認証・CORS などの外部公開設定や IP アドレス・認証情報を含めていない。`cao-server` をネットワーク経由で利用する場合はマシンごとに別途管理する。
