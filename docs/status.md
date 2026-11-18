# 現状と既知の課題（2026-11-18 時点）

このページで分かること: `cao-trio` が目指していること、現在できていること、既知の課題と回避策、今後の候補、主な変更履歴。

## 何を目指しているか

- Claude Code・Codex・agy の 3 系統の CLI エージェントを、コスト・得意分野・権限制御に応じて組み合わせ、1 つのプロジェクト上で安全かつ継続的に協調動作させること。
- 特定の AI が利用上限（レート制限）に達しても、別系統の AI の予備プロファイルへシームレスに切り替えて開発を止めないこと。
- 個人環境の設定（`local.env`, `local/agents/`）と公開リポジトリ本体を分離し、CLI や CAO 本体の不整合に対しても診断ツール（`cao-doctor`）とパッチ管理（`cao-patch`）で再現可能に維持すること。

## できていること（2026-11-18 時点）

- **3 系統 30 体のプロファイルと自動検証**: リーダー 3 体＋ワーカー 27 体の構成。実装（`workspace-write`）とレビュー・調査（`read-only`）の権限分離、および `test/profiles.test.sh` による frontmatter・リーダー規約本文・共通節の自動検証。
- **トークン節約重視のモデルルーティング**: 実装は `codex_luna_coder` / `codex_terra_coder` を優先し、レビューは原則 `codex_sol_reviewer`（effort medium）、重要変更は `codex_sol_deep_reviewer`（effort high）が担当。luna は 1 回、他は 2 回差し戻された場合のみ上位モデル（`terra` / `sol` / `astra`）へ段階的に格上げ。
- **herdr バックエンドでの 2×2 ペイン分割と状態復帰パッチ**:
  - `cao-2.5.4-herdr-pane-spawn.patch`: ワーカーをリーダーと同じタブ内の 2×2 ペインに配置。
  - `cao-2.5.4-herdr-codex-status.patch`: herdr で Codex ワーカーが `processing` のまま戻らなくなる問題を、300 秒経過後の画面再確認（30 秒間隔）で解消。
  - `cao-2.5.4-codex-rollout-output.patch`: handoff の結果を、codex の会話記録（rollout）から読む。読めなければ画面から切り出す。
- **Codex ワーカーの停止原因の解消**:
  - 利用上限接近時のモデル切替ダイアログを `~/.codex/config.toml` の `hide_rate_limit_model_nudge = true` で抑止。
  - 読み取り専用プロファイル（`cao-ro`）でも `[mcp_servers.cao-mcp-server] default_tools_approval_mode = "approve"` により `send_message` 等の CAO MCP ツールを承認待ちなしで実行可能に。
- **`cao-dev` のセッション管理と会話引き継ぎ**:
  - リーダーが終了してシェルに戻ったセッションを自動判定し、`cao shutdown` で片付けてから再起動。
  - 起動時に直近の Claude 会話要約を `.cao/last-session.md` に書き出し（`cao-recap`）、「前回の続き」で引き継ぎ可能に。
  - プロジェクトの外で引数なし実行したときに、開いているセッションの画面（herdr / tmux）へ直接接続。

## 既知の課題と回避策

| 課題 | 原因・詳細 | 回避策・扱い |
|---|---|---|
| inbox の `delivered` が受信を保証しない | CAO の `inbox_service` はペインへの送信処理を行う前に状態を `DELIVERED` に更新するため、受信側 CLI が実際にテキストを受け取ったかは確かめていない | 応答がない場合は `cao-trace <terminal_id>` やワーカーのペイン画面を確認する |
| Codex ワーカーの `handoff` 結果の本文が切れることがある | Codex ワーカーに対する `handoff` の戻り値が、画面末尾のステータス行だけを拾い、報告の本文が欠ける場合がある | パッチ cao-2.5.4-codex-rollout-output で対応済み。cao-server の再起動後に有効。境界を記録できないときは、今までどおり画面から切り出す |
| Codex が利用上限で止まっても `handoff` が成功を返す | 利用上限の画面（`■` のエラーセル）を「完了」とみなし、結果が空になる | パッチ cao-2.5.4-codex-error-cell で対応（未適用なら `cao-patch` を実行し、cao-server の再起動後に有効）。`handoff` は失敗となり、メッセージに上限の文が入る |
| リーダーが作業中のあいだは `send_message` が届かない | CAO の inbox 配送は受信側が待機中（IDLE / COMPLETED）のときだけ行われる（仕様どおりの動作） | リーダーのターンが終わって入力待ちに戻ると自動で配送される |
| `cao-recap` の対象が Claude のリーダーのみ | `~/.claude/projects/` の JSONL 履歴を読む実装のため、予備リーダー（`agy_opus_lead` / `codex_sol_lead`）の会話は要約されない | 予備リーダー使用時は `.cao/tasks/` の指示書で文脈を引き継ぐ |
| agy ワーカーにはサンドボックス強制がない | CAO が `antigravity_cli` を常に自動許可で起動し、サンドボックス指定手段がない | 読み取り専用が必須の役には使わず、調査や文章作成に限定する（気になる場合は `local/agents/` で別系統に差し替える） |

## 今後の候補

- CAO 本体のバージョン更新（2.5.4 以降）に応じたパッチの追従または不要化の確認。
- `cao-patch` で途中失敗した際の案内表示やロールバックの補助。
- Codex ワーカーの `handoff` 出力切り詰めに対する CAO 側の改善確認。
- 予備リーダー（Codex / agy）使用時の会話要約（`cao-recap`）対応の検討。

## 主な変更履歴（git log より）

| 日付 | コミット | 内容 |
|---|---|---|
| 2026-11-18 | - | レビューの effort を重要度に応じて分け、luna の選定・格上げ基準を明確化 |
| 2026-11-18 | - | Codex の利用上限（`■` のエラーセル）を ERROR にし、`handoff` の失敗メッセージに本文を入れるパッチ（codex-error-cell）を追加 |
| 2026-11-18 | - | `cao-patch`: 途中で失敗したらその回に当てたパッチを自動で元に戻す |
| 2026-11-18 | `8092505` | `cao-dev`: プロジェクトの外で引数なしなら、開いているセッションの画面に入る |
| 2026-11-18 | `7d44852` | `cao-dev`: リーダーが終了したセッションを片付けて起動し直し、前回の会話の要約（`cao-recap`）を残す |
| 2026-11-18 | `638b88e` | `herdr`: Codex が `processing` のまま戻らない件を画面の再確認で直すパッチを追加 |
| 2026-11-17 | `fc1008a` | ルーティング: Codex は `luna` / `terra` を優先し、`astra` を最後の手段にする |
| 2026-11-17 | `e59a382` | `codex`: モデル切替ダイアログを抑止し、`cao-ro` ワーカーの `send_message` を許可 |
| 2026-11-17 | `bf8b3bf` | `herdr`: ワーカーをリーダーと同じタブのペインに出すパッチと `cao-patch` を追加 |
| 2026-11-16 | `da959e0` | `cao-dev`: セッション名を `cao-<プロジェクト名>` にし、同名の別フォルダとの取り違えを止める |
| 2026-11-16 | `b1df227` | `cao-dev`: 置き場の外のプロジェクトもパスやホーム直下の名前で起動できるようにする |
| 2026-11-16 | `e602cf8` | 標準の実装を `codex_terra_coder` に、レビューの主担当を Codex に変更 |
| 2026-11-16 | `a0539de` | 自分用の設定を `local.env` と `local/agents` に集約 |
| 2026-11-16 | `7d74e58` | `cao-doctor` / `cao-trace` / `cao-models` を追加、`cao-dev` が `cao-server` を自動起動 |
| 2026-11-16 | `d6bef7e` | CAO 自作環境の初期構築（チーム構成・`ponytail` スキル・`cao-dev`・Codex サンドボックス設定） |
