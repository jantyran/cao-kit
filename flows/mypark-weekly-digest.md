---
name: mypark-weekly-digest
schedule: "0 9 * * 1"
agent_profile: codex_luna_researcher
provider: codex
script: ./mypark-dirty-repos.sh
---
あなたは読み取り専用の調査担当です。ファイルは変更しないでください。

[[root]] 配下で、未コミットの変更が残っているリポジトリがあります: [[repos]]

各リポジトリについて `git -C <path> status --short` と `git -C <path> diff --stat` を確認し、
日本語で次の形式の一覧を返してください:
- リポジトリ名: 変更の要約（1〜2 行）/ コミットしてよさそうか、作業途中に見えるか
最後に「今週まず片付けるべきもの」を 1 つ挙げてください。
