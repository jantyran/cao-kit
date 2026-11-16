#!/usr/bin/env bash
# 定期実行の事前チェック: プロジェクト置き場（CAO_DEV_ROOT、既定 ~/mypark）配下で未コミットの変更があるリポジトリを JSON で返す。
# 該当なしなら execute=false でエージェントを起動しない（料金ゼロ）。
set -euo pipefail
root="${CAO_DEV_ROOT:-${MYPARK_DIR:-$HOME/mypark}}"
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
