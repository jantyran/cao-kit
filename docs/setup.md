# セットアップ詳細

README の「はじめかた」で足りないときの詳しい説明です。

## install.sh がすること

`./install.sh --dry-run` で、実行せずに内容だけ表示できます。

1. **リンクを張る**（リポジトリを編集すると、すぐ反映されます）

   | リポジトリ | リンク先 |
   |---|---|
   | `agents/{team,claude,codex,agy}` | `$CAO_HOME_DIR/agents/…` |
   | `skills/{ponytail,ponytail-audit,ponytail-review}` | `$CAO_HOME_DIR/skills/…` |
   | `bin/{cao-dev,cao-doctor,cao-trace,cao-models}` | `~/.local/bin/…` |
   | `codex/cao.config.toml`、`codex/cao-ro.config.toml` | `~/.codex/…` |

   リンク先にすでにファイルがあれば `.bak-YYYYmmddHHMMSS` に退避します（上書きしません）。リンクは絶対パスなので、リポジトリを移動したら再実行してください。

2. **CAO の設定を保存する**（`cao config set`）

   | 項目 | 値 |
   |---|---|
   | `agents.extra_dirs` | 上でリンクした 4 つの agents フォルダ |
   | `agents.disabled_dirs` | `~/.kiro/agents`、`$CAO_HOME_DIR/agent-store`、`$CAO_HOME_DIR/agent-context` |
   | `memory.learning_enabled` | `true` |
   | `terminal.spawn_mode` | `pane` |

   古い CAO で失敗したら、`uv tool upgrade cli-agent-orchestrator` してから再実行してください。

3. **systemd のユーザーサービスを用意する**
   `~/.config/systemd/user/cao-server.service` がなければテンプレートから作り、`enable` までします（起動はしません）。すでにあれば触りません。cao-server は `127.0.0.1:9889` だけで待ち受けます。

4. **AppArmor の案内を表示する**（sudo は実行しません。下の「AppArmor」参照）

## 状態ディレクトリを変える

既定は `~/.aws/cli-agent-orchestrator` です（CAO の既定）。変える場合は絶対パスで指定し、以後の CAO コマンドでも同じ値を使ってください。

```bash
export CAO_HOME_DIR="$HOME/.cao"
./install.sh
```

新しく作る systemd ユニットにはこの値が埋め込まれます。既存のユニットを使う場合は `systemctl --user edit cao-server.service` で `Environment="CAO_HOME_DIR=…"` を足してください。

## systemd と Node.js

サービスの PATH は `%h/.local/bin:/usr/local/bin:/usr/bin:/bin` です。nvm などで入れた node や、各 AI の CLI がこの PATH にない場合は、場所を確認して drop-in で足します。

```bash
command -v node claude codex agy
systemctl --user edit cao-server.service
```

```ini
[Service]
Environment="PATH=%h/.local/bin:/nodeがあるディレクトリ:/usr/local/bin:/usr/bin:/bin"
```

```bash
systemctl --user daemon-reload
systemctl --user restart cao-server.service
systemctl --user status cao-server.service
```

## AppArmor（Ubuntu 23.10 以降など）

Codex のサンドボックス（bubblewrap）が user namespace を使えない環境では、Codex の担当者がコマンドを実行できません。その場合だけ、リポジトリのルートで実行します。

```bash
sudo cp system/apparmor-bwrap /etc/apparmor.d/bwrap
sudo apparmor_parser -r /etc/apparmor.d/bwrap
```

## herdr を使う

既定の端末は tmux です。herdr に切り替える場合は、実行中の CAO セッションをすべて終了してから設定します（tmux 側のセッションは管理外になります）。

```bash
cao shutdown --all
cao config set terminal.backend herdr
systemctl --user restart cao-server.service
```

herdr では、CAO のセッション 1 つがワークスペース `cao-<セッション名>` に、担当者 1 人がその中のタブになります。`cao-dev` には jq も必要です。

## 元に戻す

1. 対象のシンボリックリンクを削除する（例: `rm ~/.local/bin/cao-dev`）
2. 退避された `.bak-*` があれば元の名前に戻す
3. `cao config set` した項目は、必要なら元の値に戻す

## 外部公開について

このリポジトリには、nginx・Basic 認証・CORS などの外部公開設定、IP アドレス、認証情報を含めていません。cao-server をネットワークに公開する場合は、マシンごとに別で管理してください。
