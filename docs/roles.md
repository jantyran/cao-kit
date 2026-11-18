# チームのロール設計とルーティング

このページで分かること: 30 体のプロファイルの役割分担、モデル選択と格上げの規則、予備ロール、レビューと並列化のルール。

使用する AI は Claude（`claude_code`）・agy（`antigravity_cli`）・Codex（`codex`）の 3 系統のみ（Kiro は不使用）。リーダー規約の正本は `agents/team/claude_opus_lead.md`（および同期される `agy_opus_lead.md`、`codex_sol_lead.md`）。

## 設計原則

| # | 原則 | 根拠 |
|---|---|---|
| P1 | **書く役と確かめる役を分け、確かめる役は書けないようにする** | 自己レビューは生成時の正当化を引きずる。読み取り専用のレビュー担当で独立性を担保する |
| P2 | **レビューは原則 `codex_sol_reviewer` が独立して担当** | Claude のトークンを節約するため Codex の読み取り専用プロファイルで行い、受け入れ条件の ○/× 判定で検証する。Claude は予備、`codex_astra_reviewer` は最後の手段 |
| P3 | **常時動かすのは 3〜4 役**（リーダー・実装・レビュー、必要時に調査） | 役を増やすほど調整コストと認識のずれ（Silent Divergence）が増える |
| P4 | **上位で考え、中位で書き、下位で調べる** | 足りる中で一番安いモデルを選びコストを抑える。調査担当は 20 行以内の要約と根拠パス／URL だけ返す |
| P5 | **テスト作成の分離は重要変更のみ** | テスト改ざん（アサーションの弱体化）を防ぐため、重要変更では実装前に別担当がテストを書く |
| P6 | **設計判断は指示書に書いて全員で共有** | 暗黙の判断の食い違いを防ぎ、ワーカーには指示書の絶対パスを渡す |
| P7 | **差し戻しは luna が 1 回、他は 2 回まで** | 無限ループを防ぎ、上限に達した luna は terra へ、他は 2 回で収まらなければ 1 つ上の格の担当かユーザーへ引き継ぐ |

## リーダーとチームの使い分け

### リーダー（3 体）

| プロファイル | プロバイダ / モデル | 用途 |
|---|---|---|
| `claude_opus_lead` | `claude_code` / `claude-opus-5-5` | 既定のリーダー。要件整理・設計・タスク分解・委譲・最終確認 |
| `agy_opus_lead` | `antigravity_cli` / `claude-opus-4-6-thinking` | `claude_opus_lead` が利用上限に達したときの第 1 予備（`cao-dev --lead agy_opus_lead`） |
| `codex_sol_lead` | `codex` / `gpt-6.1-sol` | 第 2 予備（`cao-dev --lead codex_sol_lead`） |

リーダー自身はアプリのコードやテストを書かず、`.cao/tasks/<YYYYMMDD-HHMM>-<slug>.md` の指示書作成と最終確認（`git diff`・テスト再実行）に専念する。また、前回セッションの話題（「前回の続き」など）が出たときだけ `.cao/last-session.md` を読む。

### ワーカーの使い分け（足りる中で一番安いものを選ぶ）

| `agent_profile` | 用途 | コスト |
|---|---|---|
| `codex_luna_coder` | 指示書に「どのファイルの・何を・どう変えるか」まで書かれ、合否を確かめるテストが既にあるか不要な作業（文言・設定値の変更、決まった形の追加、既存パターンの複製）。境界条件やテストの設計を自分で決める必要がある、複数ファイルの整合が要る、実環境を確かめながら進める作業は terra。迷ったら terra | 低 |
| `codex_terra_coder` | **標準の実装担当。実装は原則ここから始める**。機能追加・バグ修正・テスト作成・複数ファイルの変更 | 中 |
| `codex_sol_coder` | `terra` で 2 回差し戻された作業のみ（最初から選ばない） | 中〜高 |
| `codex_astra_coder` | `sol` で 2 回差し戻された作業のみ（最後の手段） | 高 |
| `claude_sonnet_tester` / `codex_sol_tester`（予備） | 重要変更のみ、受け入れ条件から実装前にテストを作成（実装コードは書かない） | 中 |
| `codex_sol_reviewer` | **標準のレビュー担当**（通常レビュー・再レビュー）。数行の修正では省略可 | 中 |
| `codex_sol_deep_reviewer` | 重要変更、または `sol_reviewer` で 2 回まとまらない時 | 中〜高 |
| `codex_astra_reviewer` | `deep_reviewer` のレビューで 2 回まとまらない時のみ（最後の手段） | 高 |
| `agy_flash_researcher` | ちょっとした調べもの（API の使い方、エラーメッセージの意味など） | 低 |
| `agy_hydrogen_researcher` | 深い調査（技術選定、比較、設計に影響する調査） | 中 |
| `agy_argon_writer` | README・設計書・記事・リリースノートなどの文章（コードは変更しない） | 中 |
| `claude_sonnet_designer` | UI/UX デザイン（画面設計・デザイン方針・デザインシステム・a11y・UI 文言。コードは書かない） | 中 |
| `codex_sol_frontend` | UI の実装（デザイン仕様から実装・ブラウザで表示確認） | 中 |
| `codex_sol_security` | セキュリティ診断（認証・入力検証・依存・秘密情報。読むだけ）。認証/決済/外部公開に関わる変更で使用。Codex 実装時は別系統の `claude_sonnet_security` を優先 | 中 |
| `claude_sonnet_docmaker` | 体裁のある資料（スライド pptx/Marp、docx、xlsx、PDF、図）。リポジトリ内の文章は writer | 中 |
| `claude_sonnet_retrospector` | 機能・修正の 1 単位完了時に振り返りを行い、教訓を抽出 | 中 |

### 予備ロール（利用上限への備え）

ワーカーが利用上限・レート制限（429 等）で停止した場合は、同じ指示書で別系統 AI の予備に振り直す。

| 主担当 | 予備（別 AI） |
|---|---|
| `codex_luna_coder` | `agy_flash_coder` |
| `codex_terra_coder` / `codex_sol_coder` / `codex_astra_coder` | `agy_sonnet_coder` |
| `codex_sol_reviewer` / `codex_sol_deep_reviewer` / `codex_astra_reviewer` | `claude_sonnet_reviewer` |
| `claude_sonnet_tester` | `codex_sol_tester` |
| `agy_flash_researcher` / `agy_hydrogen_researcher` | `codex_luna_researcher` |
| `agy_argon_writer` | `claude_sonnet_writer` |
| `claude_sonnet_docmaker` | `agy_argon_docmaker` |
| `claude_sonnet_designer` | `agy_argon_designer` |
| `codex_sol_frontend` | `agy_sonnet_frontend` |
| `codex_sol_security` | `claude_sonnet_security` |
| `claude_sonnet_retrospector` | `codex_luna_retrospector` |

## 標準の流れと格上げ規則

「重要変更」とは、認証・権限・決済、データの削除や移行、公開 API や外部との契約の変更、過去に回帰したバグの修正を指す。

```
リーダー ──(必要時)──> 調査（要約と根拠パスだけ返す・読み取り専用）
   │
   ├─> 実装（Codex terra）──> レビュー（Codex sol・読み取り専用）──> リーダーが diff とテストを再確認
   │        ↑                     │要修正（2 回まで）
   │        └─────────────────────┘
   └─(重要変更のみ)─> テスト作成（実装とは別担当、先に書く）
```

- **実装の格上げ順**: luna は差し戻し 1 回で terra へ移す。他の担当は同じ担当につき 2 回までで、超えたら `codex_terra_coder` → `codex_sol_coder` → `codex_astra_coder` → ユーザーの順に格上げする。
- **原因不明の不具合**: 最初から上位モデルで書き換えず、まず `codex_terra_coder`（または `codex_sol_reviewer`）に読むだけの調査として依頼する。
- **実装担当のテスト規律**: 実装担当（coder / frontend）は既存のテストを弱めたり消したりしてはならず、tester が先に書いたテストも変更しない。

## レビュー担当の選び方（P2）

レビューは原則 `codex_sol_reviewer`（effort medium）が担当し、受け入れ条件を 1 項目ずつ ○/× で判定して `APPROVE` または `REQUEST_CHANGES` を返す。

| 場面 | レビュー担当（主） | 予備 |
|---|---|---|
| 通常レビュー・再レビュー | `codex_sol_reviewer`（effort medium） | `claude_sonnet_reviewer` |
| 重要変更、または `sol_reviewer` で 2 回まとまらない時 | `codex_sol_deep_reviewer`（effort high） | `claude_sonnet_reviewer` |
| `deep_reviewer` で 2 回まとまらない時 | `codex_astra_reviewer`（effort high） | `claude_sonnet_reviewer` |

再レビューでは「前回の指摘が直ったかと、その差分だけを見る」と範囲を指定する。reviewer はテストを実行せず、coder の報告とコードを突き合わせる。テストの再実行はリーダーが 1 回だけ行う。

重要変更のうち認証・権限・決済・外部公開に関わるものは、別系統の `claude_sonnet_security` にもセキュリティ診断を依頼する。

## 書ける／書けないの強制方法（P1）

| provider | 強制の仕組み | 読み取り専用にする方法 |
|---|---|---|
| `claude_code` | Claude Code のツール制限で強制 | `role: reviewer`（Read/Glob/Grep のみ許可） |
| `codex` | サンドボックス（bubblewrap）で強制 | `codexProfile: cao-ro`（`~/.codex/cao-ro.config.toml` で `sandbox_mode = "read-only"`） |
| `antigravity_cli` | 強制されない（プロンプトのみ） | 読み取り専用が必須の役には使わず、調査・文章など影響が限定される役に限る |

書く役の Codex は `codexProfile: cao`（`workspace-write`、ネット遮断）。ただしワーカーはリーダーの作業フォルダで起動するため、リーダーと別プロジェクトのファイルを変更する作業は委譲できない（そのプロジェクトで `cao-dev` を起動し直す）。サンドボックス設定の詳細は [docs/architecture.md](architecture.md) を参照。

## `handoff` と `assign` の選び方

迷ったら `handoff` を使う。

| 手段 | 場面 |
|---|---|
| `handoff`（既定） | 結果を受けてすぐ次に進む 1 件（調査・レビュー・小さな実装・テスト作成）。完了するとワーカーのペインは自動で消える |
| `assign` | (1) 独立した仕事を並列に進める (2) 長い作業（目安 10 分超）で待つ間にリーダーが別作業を進める (3) ユーザーが「作業を画面で見たい」「worker を残して」と指定したとき |

- `assign` 時は依頼文に `send_message` の送信先（リーダー自身の `CAO_TERMINAL_ID`）を明記し、結果確認後に `delete_terminal` で片付ける（残す指示がある場合を除く）。

## 分割して並列に進めるか（fan-out と worktree）

- **分ける条件（すべて満たす場合のみ）**: 部分同士が互いの結果を待たない／触るファイルが重ならない（共有設定・型定義・lock ファイルは 1 担当に集約）／各部分が単独で 10 分以上かかる。
- **同時実行数の上限**: 調査・レビューは 2〜4 体、実装担当（coder / frontend）は 3 体まで。
- **worktree の使用**: 実装系ワーカーを 2 体以上同時に動かす場合は `use_worktree=true` を付け、各ワーカーに自分のブランチへ commit（push はしない）させた上で、リーダーが `git merge --no-ff <ブランチ>` で 1 つずつ取り込みテストを実行してから `delete_terminal` する。

## プロファイルの検証

`bash test/profiles.test.sh` が全プロファイル（`agents/` および `local/agents/`）の frontmatter 制約、リーダー 3 体の本文一致、全チームプロファイルの共通節一致を検証する（詳細は [AGENTS.md](../AGENTS.md)）。
