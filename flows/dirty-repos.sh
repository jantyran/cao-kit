#!/usr/bin/env bash
# 定期実行の事前チェック: プロジェクト置き場（CAO_DEV_ROOT、既定 ~/projects）配下で未コミットの変更があるリポジトリを JSON で返す。
# 該当なしなら execute=false でエージェントを起動しない（料金ゼロ）。
set -euo pipefail
# cao-server から動くので、置き場は cao-trio の local.env から読む（環境変数があれば優先）
env_root=${CAO_DEV_ROOT:-}
kit=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/.." && pwd -P)
[[ -f "$kit/local.env" ]] && . "$kit/local.env"
root="${env_root:-${CAO_DEV_ROOT:-$HOME/projects}}"
list=""
for d in "$root"/*/; do
  [[ -d "$d/.git" ]] || continue
  n=$(git -C "$d" status --porcelain 2>/dev/null | wc -l)
  (( n > 0 )) && list+="$(basename "$d") ($n files), "
done
if [[ -z "$list" ]]; then
  echo '{"execute": false, "output": {}}'
else
  list=${list%, }; list=${list//\\/\\\\}; list=${list//\"/\\\"}
  printf '{"execute": true, "output": {"repos": "%s", "root": "%s"}}\n' "$list" "$root"
fi
