# cao-kit

自作 CAO 設定の正本です。別マシンでは clone 後に `./install.sh` を実行し、プロファイル・共有スキル・起動コマンドをこのリポジトリへリンクします。

- `agents/{team,claude,codex,agy}/`: チームと各 provider の汎用プロファイル（廃止済みは除外）
- `skills/{ponytail,ponytail-audit,ponytail-review}/`: 追加した共有スキル。CAO 同梱スキルは含みません。
- `bin/cao-dev`: プロジェクト別セッションの起動
- `codex/cao.config.toml`: workspace-write と自動承認レビューの設定
- `codex/cao-ro.config.toml`: レビュー・調査・振り返り用の読み取り専用設定
- `system/`: AppArmor 設定と systemd ユニットのテンプレート
- `test/install.test.sh`: 一時 HOME とスタブを使うインストール検証
- `test/profiles.test.sh`: プロファイルのメタデータと読み取り専用設定の検証
- `docs/roles.md`: ロール設計・標準の流れ・レビュー担当の選び方

## チーム構成

| 担当 | 主担当 | provider | 用途 | 予備 |
|---|---|---|---|---|
| lead | claude_opus_lead | claude_code | 要件整理・設計・委譲・最終確認 | agy_opus_lead → codex_sol_lead |
| coder（軽量） | codex_luna_coder | codex | 小さい定型修正 | agy_flash_coder |
| coder（標準） | codex_sol_coder | codex | 実装・テスト | agy_sonnet_coder |
| coder（難問） | codex_astra_coder | codex | 標準担当で解けない不具合・大規模修正 | agy_sonnet_coder |
| tester | claude_sonnet_tester | claude_code | 重要変更のみ、実装前にテスト作成 | codex_sol_tester |
| reviewer | claude_sonnet_reviewer | claude_code | 差分レビュー | codex_sol_reviewer |
| researcher（軽量） | agy_flash_researcher | antigravity_cli | API・エラー等の調査 | codex_luna_researcher |
| researcher（深掘り） | agy_hydrogen_researcher | antigravity_cli | 技術選定・比較 | codex_luna_researcher |
| writer | agy_argon_writer | antigravity_cli | README・設計書・記事 | claude_sonnet_writer |
| designer | claude_sonnet_designer | claude_code | UI/UX 設計・文言・a11y | agy_argon_designer |
| frontend | codex_sol_frontend | codex | UI 実装・表示確認 | agy_sonnet_frontend |
| security | codex_sol_security | codex | セキュリティ診断（読み取り） | claude_sonnet_security |
| docmaker | claude_sonnet_docmaker | claude_code | スライド・文書・表・図 | agy_argon_docmaker |
| retrospector | claude_sonnet_retrospector | claude_code | 作業結果の振り返り・教訓 | codex_luna_retrospector |

読み取り専用は Claude の `role: reviewer` によるツール制限、Codex の `codexProfile: cao-ro` によるサンドボックス（`read-only`、承認待ちなし）で強制します。agy はプロンプトのみなので、読み取り専用が必須の役には使いません。原則・標準の流れ・レビュー担当の選び方は [ロール設計](docs/roles.md) を参照してください。

汎用の `claude` / `codex` / `agy` も同梱しています。モデル名・スキル・プラグインの利用可否は各 provider の環境に依存します。CAO 自体、各 provider の CLI・認証、provider 側のスキルやプラグインは別途準備してください。

## 新規マシンのセットアップ

Linux、bash、coreutils、systemd ユーザーサービスを前提にします。インストーラーに追加ライブラリ、jq、Python は不要です。CAO の導入には uv を使います。

1. `uv tool install cli-agent-orchestrator` を実行します。CAO が導入済みなら不要です。
2. Claude Code / Codex / agy の使用する CLI を導入し、認証を済ませます。`cao-dev` には tmux（または herdr + jq）、curl、通常の Unix コマンドも必要です。herdr を使う場合は `cao config set terminal.backend herdr` 後に `systemctl --user restart cao-server`（実行中の tmux セッションは管理外になるので、先に終了させる）。
3. このリポジトリを任意の場所に clone し、そのディレクトリで実行します。

```bash
export PATH="$HOME/.local/bin:$PATH"
./install.sh --dry-run
./install.sh
```

インストーラーは各リンク先に実体や別リンクがあれば `.bak-YYYYmmddHHMMSS` に退避します。同名の退避先があれば連番を追加し、上書きしません。正しいリンクは維持します。リンク先は絶対パスなので、リポジトリを移動した場合は再実行してください。

設定は `cao config set` で次の4項目を保存します。配列は JSON を単一引数として渡します（現行 CLI で確認済み）。未対応の項目を手作業へ回す処理はありません。古い CAO で失敗した場合は CAO を更新して再実行してください。

| 項目 | 値 |
|---|---|
| agents.extra_dirs | 状態ディレクトリの agents/{claude,codex,agy,team} |
| agents.disabled_dirs | HOME の .kiro/agents、状態ディレクトリの agent-store と agent-context |
| memory.learning_enabled | true |
| terminal.spawn_mode | pane |

状態ディレクトリの既定は `$HOME/.aws/cli-agent-orchestrator` です。変更するときは絶対パスで `export CAO_HOME_DIR="$HOME/別の状態ディレクトリ"` を指定してください。以後の CAO コマンドにも同じ環境変数を指定します。新しく生成する systemd ユニットにもこの値を埋め込みます。既存ユニットを使う場合は、必要に応じて `systemctl --user edit cao-server.service` で同じ値を設定してください。

### systemd と Node.js

`~/.config/systemd/user/cao-server.service` がなければテンプレートから生成し、daemon-reload と enable のみを実行します。起動・再起動は自動実行しません。既存ユニットがあれば内容も有効化状態も維持します。

テンプレートの `@LOOPBACK@` は生成時に IPv4 ループバックへ置換され、`--host` は常にその値に固定されます。`@CAO_HOME_DIR@` も生成時に置換されるため、テンプレートをそのままコピーしないでください。CAO の実行ファイルは uv 標準の `~/.local/bin/cao-server` を前提にしています。

PATH は `%h/.local/bin:/usr/local/bin:/usr/bin:/bin` です。nvm 等の node がこの PATH にない場合は、以下で実体を確認し、表示されたパスを使って drop-in を設定してください（nvm の版を更新した際も見直します）。各 provider CLI もサービスの PATH から実行できる必要があります。

```bash
command -v node
systemctl --user edit cao-server.service
```

```ini
[Service]
Environment="PATH=%h/.local/bin:/nodeがあるディレクトリ:/usr/local/bin:/usr/bin:/bin"
```

編集後は `systemctl --user daemon-reload` を実行します。新規マシンで起動する場合、または全セッションを終了して設定を反映する場合に手動で実行します。

```bash
systemctl --user restart cao-server.service
systemctl --user status cao-server.service
```

### AppArmor

Codex の workspace-write で bwrap の user namespace 許可が必要な環境向けです。インストーラーは sudo を実行しません。`/etc/apparmor.d/bwrap` がない場合だけ手順を表示します。必要に応じてリポジトリのルートで実行してください。

```bash
sudo cp system/apparmor-bwrap /etc/apparmor.d/bwrap
sudo apparmor_parser -r /etc/apparmor.d/bwrap
```

## このマシンへの適用

先に `./install.sh --dry-run` で退避とリンクを確認してから `./install.sh` を実行します。既存の systemd ユニットを維持するため、現状の外部公開設定もそのままです。動作中のセッションは自動終了・再起動されません。退避した設定へ戻す場合は対象のシンボリックリンクを外し、対応する `.bak-*` を元の名前へ戻してください。

## cao-dev の使い方

プロジェクトの置き場は既定で `~/mypark`、`MYPARK_DIR` で変更できます。

```bash
cao-dev --list
cao-dev project
cao-dev project "テスト失敗を調査して修正してください"
cao-dev --lead agy_opus_lead project
cao-dev --lead codex_sol_lead project
```

プロジェクト配下での引数なし実行はそのプロジェクトを使います。通常は tmux（`terminal.backend` が herdr なら herdr）に接続し、依頼文を渡した場合はヘッドレスで非同期実行します。既存セッションがあれば接続または依頼送信します。既定リーダーは `claude_opus_lead`、`CAO_DEV_LEAD` または `--lead` で変更できます。

`cao-dev` はローカルの cao-server の稼働を確認します。既存の Codex `config.toml` にプロジェクトの trust 設定を追加し、通常の Git checkout では `.git/info/exclude` に `.cao/` を追加します。`--auto-approve` を指定する起動コマンドなので、信頼するプロジェクトで使用してください。

## 更新と検証

リポジトリを編集 → テスト → 差分確認 → commit の順で更新します。リンクのためファイル編集は直ちにリンク先へ反映されますが、動作中のエージェントが読み込み済みの設定はセッションを再起動して反映します。別マシンでは pull 後、必要に応じてインストーラーを再実行します。systemd のテンプレート更新は既存ユニットへ自動反映されません。

```bash
bash test/install.test.sh
bash test/profiles.test.sh
bash -n install.sh
bash -n bin/cao-dev
```

テストは一時 HOME / CAO_HOME_DIR、cao と systemctl のスタブを使い、本物の HOME を変更しません。

nginx・Basic 認証・ホスト許可・CORS・WebSocket の外部公開設定、IP アドレス、認証情報はこのリポジトリに含めません。マシン固有の公開設定は別管理してください。`.cao/`（指示書・一時検証）や実行環境が配置する隠しディレクトリも Git 管理対象外です。
