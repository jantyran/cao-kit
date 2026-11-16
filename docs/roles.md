# チームのロール設計（2026-11-13 改訂）

使う AI は Claude（`claude_code`）・agy（`antigravity_cli`）・Codex（`codex`）の 3 系統だけ。Kiro は使わない。

## 設計原則（根拠つき）

| # | 原則 | 根拠 |
|---|---|---|
| P1 | **書く役と確かめる役を分け、確かめる役は本当に書けないようにする** | 自己レビューは生成時の正当化を引きずる。読み取り専用のレビュー担当が一般的（Anthropic: Building effective agents、Claude Code subagents） |
| P2 | **レビューは実装より上の格で、独立して** | 同系モデル同士は上流の誤りを追認しやすい（同調バイアス）。2026-11-16 からは Claude のトークン節約のため Codex 同士で行い、格の差・独立した CLI・受け入れ条件の ○/× 判定で補う。Claude は予備 |
| P3 | **常時動かすのは 3〜4 役**（リーダー・実装・レビュー、必要時に調査） | 役を増やすほど調整コストとコンテキスト断片化（Silent Divergence）が増える |
| P4 | **上位で考え、中位で書き、下位で調べる** | モデル段階分けでコストを抑える。調査は要約と根拠パスだけ返す |
| P5 | **テストを書く役の分離は重要変更だけ** | テスト改ざん（アサーションを弱める）を防げるが、遅延とコストが増える |
| P6 | **設計判断は指示書に書いて全員で共有** | 暗黙の判断の食い違い（Silent Divergence）を防ぐ |
| P7 | **差し戻しは 2 回まで**。超えたら上位の担当かユーザーへ | 無限ループ（MAST の仕様不備）を防ぐ |

## 書ける／書けないの強制方法（P1）

| provider | 強制の仕組み | 読み取り専用にする方法 |
|---|---|---|
| claude_code | Claude Code のツール禁止で**強制される** | `role: reviewer`（Read/Glob/Grep のみ） |
| codex | ツール制限は強制されない。**サンドボックスで強制** | `codexProfile: cao-ro`（`~/.codex/cao-ro.config.toml` で `sandbox_mode = "read-only"`） |
| antigravity_cli | 強制されない（プロンプトだけ） | 読み取り専用が必須の役には使わない。調査・文章など「書いても実害が小さい」役に限る |

書く役の Codex は従来どおり `codexProfile: cao`（workspace-write、ネット遮断）。Claude Code の全プロファイルは `permissionMode: auto`（CAO 既定の `--dangerously-skip-permissions` の代わりに、危険な操作を分類器が止める）。agy は CAO が常に `--dangerously-skip-permissions` で起動し、サンドボックスを指定する手段がないため無制限で動く（未対策）。

## 標準の流れ（P3）

```
リーダー ──(必要時)──> 調査（要約と根拠パスだけ返す・読み取り専用）
   │
   ├─> 実装（Codex terra）──> レビュー（Codex sol・読み取り専用）──> リーダーが diff とテストを再確認
   │        ↑                     │要修正（2 回まで）
   │        └─────────────────────┘
   └─(重要変更のみ)─> テスト作成（実装とは別担当、先に書く）
```

## handoff と assign の選び方

迷ったら `handoff`。`assign` は下の条件に当てはまるときだけ使う。

| 使う | 場面 |
|---|---|
| `handoff`（既定） | 結果を受けてすぐ次に進む 1 件（調査・レビュー・小さな実装・テスト作成）。終わると worker の画面は自動で消える |
| `assign` | (1) 互いに独立した仕事を並列に進める (2) 長い作業（目安 10 分超）で、待つ間にリーダーが別の作業を進めたい (3) ユーザーが「作業を画面で見たい」「worker を残して」と言ったとき |

`assign` の依頼文には `send_message` での完了報告先（自分の terminal_id、環境変数 `CAO_TERMINAL_ID` の値）を必ず書く。結果を受けて diff とテストを確認したら `delete_terminal` で片付けるが、ユーザーが残すよう指定した worker は指示まで残す。報告の最後に残っている worker の terminal_id 一覧を書く（なければ「なし」）。worker の画面は herdr ならワークスペース `cao-<セッション名>` 内のタブ、tmux なら `cao-agents` ウィンドウ（Ctrl-b 1）で見られる。

## 分割して並列に進めるか

大きな依頼では設計・指示書作成の前に並列化を検討し、迷ったら分けない。

- 分けるのは、互いの結果を待たず、担当ファイルが重ならず、各部分が単独で 10 分以上かかる場合だけ。共有の設定・型定義・lock ファイルは 1 担当にまとめる。小さな修正や順番に依存する作業は分けず、設計が未確定なら先に決めて指示書の「設計判断」に書く。
- 同時実行は調査・レビューが 2〜4 体、実装担当（coder / frontend）は 3 体まで。部分ごとに指示書を 1 枚作り、目的・担当範囲（触ってよいファイル）・担当外・報告形式・共通の設計判断を書く。
- `assign` で起動し、実装担当は worktree 手順に従う。統合は 1 つずつ行い、そのつどテストを再実行する。衝突や設計の食い違いが出たら残りは順番に進める。
- 分けた／分けなかった理由を 1 行で報告する。

## レビュー担当の選び方（P2）

| 実装した担当 | レビュー担当（主） | 予備 |
|---|---|---|
| `codex_luna_coder`、`codex_terra_coder`、`codex_sol_frontend` | `codex_sol_reviewer`（effort high） | `claude_sonnet_reviewer` |
| `codex_sol_coder`、`codex_astra_coder`、重要変更 | `codex_astra_reviewer` | `claude_sonnet_reviewer` |
| agy 経由（`agy_*_coder`, `agy_sonnet_frontend`） | `codex_sol_reviewer` | `claude_sonnet_reviewer` |

標準の実装は `codex_terra_coder`（GPT-6.1 Terra）。差し戻しが 2 回を超えたら terra → sol → astra → ユーザーの順に格上げする。terra の実力は運用で確かめ、差し戻しが増えるようなら標準を sol に戻す。

セキュリティ診断も同じ考え方（主 `codex_sol_security`、Codex が実装した変更では `claude_sonnet_security` を優先）。

## 変更点の一覧

1. 新規 `codex/cao-ro.config.toml`（読み取り専用サンドボックス）。install.sh で `~/.codex/cao-ro.config.toml` にリンク。
2. 読み取り専用の Codex 4 体を `codexProfile: cao-ro` に: `codex_sol_reviewer`, `codex_sol_security`, `codex_luna_researcher`, `codex_luna_retrospector`。
3. 新規 `claude_sonnet_tester`（テスト作成担当、予備 `codex_sol_tester`）。重要変更のときだけ使う。実装コードは書かない、テストだけ書く。
4. リーダー 3 体（`claude_opus_lead`, `agy_opus_lead`, `codex_sol_lead`）のチーム表と手順を改訂: 標準の流れ、レビュー担当の選び方表、テスト担当、差し戻し上限、指示書の「設計判断」欄。
5. 実装担当（coder/frontend 全員）に「テストを弱めない・消さない。テスト担当が書いたテストは変更しない」を追記。
6. レビュー担当（reviewer/security 全員）に「受け入れ条件を 1 項目ずつ ○/× で判定し根拠を書く」「結論は APPROVE / REQUEST_CHANGES」を追記。
7. 調査担当（researcher 全員）に「要約は 20 行以内＋根拠のパス/URL」を追記。
8. テスト `test/profiles.test.sh`: 全プロファイルの provider が 3 系統のどれか／Codex は codexProfile 必須／role が reviewer の Codex は cao-ro／allowedTools に `*` が無い。
