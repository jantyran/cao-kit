"""review_changes — プロジェクトの未コミット差分を「要約 → レビュー」の 2 段で確認するサンプル。

どちらのステップも読み取り専用で、ファイルを書き換えない（だから recovery="idempotent" が正直な宣言）。
実行例:
  cao workflow run review_changes --input project=$HOME/projects/myapp --run-id rc-myapp-1
"""
from cao_workflow import emit_output, get_inputs, step

INPUTS = {
    "project": {"type": "path", "required": True},
}

project = get_inputs()["project"]

# 1. 安い担当で差分を要約（Codex Luna）
summary = step(
    provider="codex",
    agent="codex_luna_researcher",
    prompt=(
        f"{project} の git リポジトリで `git status --short` と `git diff` を読み、"
        "変更内容をファイルごとに日本語で 1〜2 行ずつ要約して返してください。ファイルは変更しないこと。"
    ),
    step_id="summarize",
    recovery="idempotent",
)

# 2. 要約を踏まえてレビュー（Codex Sol、読み取り専用のサンドボックス）
review = step(
    provider="codex",
    agent="codex_sol_reviewer",
    prompt=(
        f"{project} の未コミット差分をレビューしてください。`git diff` を自分でも読むこと。\n"
        f"参考: 別担当の要約\n{summary.output}\n\n"
        "バグ・セキュリティ・テスト不足を重要度順に日本語で返してください。ファイルは変更しないこと。"
    ),
    step_id="review",
    recovery="idempotent",
)

emit_output({"project": project, "summary": summary.output, "review": review.output})
