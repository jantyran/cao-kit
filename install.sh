#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
dry_run=false
case "${1:-}" in
  '') ;;
  --dry-run) dry_run=true; shift ;;
  *) echo '使い方: ./install.sh [--dry-run]'; exit 1 ;;
esac
[[ $# -eq 0 ]] || { echo '使い方: ./install.sh [--dry-run]'; exit 1; }
if ! command -v cao >/dev/null 2>&1; then
  echo 'cao がありません。uv tool install cli-agent-orchestrator を実行してください。'
  exit 1
fi
export CAO_HOME_DIR="${CAO_HOME_DIR:-$HOME/.aws/cli-agent-orchestrator}"
[[ "$CAO_HOME_DIR" = /* ]] || { echo 'CAO_HOME_DIR は絶対パスで指定してください。' >&2; exit 1; }

run() {
  printf '%s ' "$($dry_run && echo '[dry-run]' || echo '[実行]')"
  printf '%q ' "$@"
  printf '\n'
  if ! $dry_run; then "$@"; fi
}
link() {
  local source=$1 target=$2 backup suffix=0
  if [[ -L "$target" && "$(readlink -- "$target")" = "$source" ]]; then
    printf 'リンク設定済み: %s\n' "$target"
    return
  fi
  run mkdir -p -- "$(dirname -- "$target")"
  if [[ -e "$target" || -L "$target" ]]; then
    backup="$target.bak-$(date +%Y%m%d%H%M%S)"
    while [[ -e "$backup" || -L "$backup" ]]; do
      suffix=$((suffix + 1))
      backup="$target.bak-$(date +%Y%m%d%H%M%S)-$suffix"
    done
    run mv -T -- "$target" "$backup"
  fi
  run ln -sT -- "$source" "$target"
}
# JSON 配列を単一引数で渡す。HOME 内の引用符や改行もエスケープする。
json_array() {
  local value separator=''
  printf '['
  for value in "$@"; do
    value=${value//\\/\\\\}; value=${value//\"/\\\"}
    value=${value//$'\n'/\\n}; value=${value//$'\r'/\\r}; value=${value//$'\t'/\\t}
    value=${value//$'\b'/\\b}; value=${value//$'\f'/\\f}
    printf '%s"%s"' "$separator" "$value"
    separator=,
  done
  printf ']'
}
for dir in team claude codex agy; do link "$repo/agents/$dir" "$CAO_HOME_DIR/agents/$dir"; done
for skill in ponytail ponytail-audit ponytail-review; do link "$repo/skills/$skill" "$CAO_HOME_DIR/skills/$skill"; done
for cmd in cao-dev cao-doctor cao-models cao-trace; do link "$repo/bin/$cmd" "$HOME/.local/bin/$cmd"; done
link "$repo/codex/cao.config.toml" "$HOME/.codex/cao.config.toml"
link "$repo/codex/cao-ro.config.toml" "$HOME/.codex/cao-ro.config.toml"
run cao config set agents.extra_dirs "$(json_array "$CAO_HOME_DIR/agents/claude" "$CAO_HOME_DIR/agents/codex" "$CAO_HOME_DIR/agents/agy" "$CAO_HOME_DIR/agents/team")"
run cao config set agents.disabled_dirs "$(json_array "$HOME/.kiro/agents" "$CAO_HOME_DIR/agent-store" "$CAO_HOME_DIR/agent-context")"
run cao config set memory.learning_enabled true
run cao config set terminal.spawn_mode pane

unit="$HOME/.config/systemd/user/cao-server.service"
if [[ -e "$unit" || -L "$unit" ]]; then
  echo "既存ユニットを維持: $unit"
else
  run mkdir -p -- "$(dirname -- "$unit")"
  echo "systemd ユニットを生成: $unit（ローカル接続のみ）"
  if ! $dry_run; then
    template=$(< "$repo/system/cao-server.service")
    loopback=$(printf '%d.%d.%d.%d' 127 0 0 1)
    state=${CAO_HOME_DIR//\\/\\\\}; state=${state//\"/\\\"}; state=${state//%/%%}
    template=${template//@LOOPBACK@/$loopback}
    template=${template//@CAO_HOME_DIR@/"$state"}
    printf '%s\n' "$template" > "$unit"
  fi
  run systemctl --user daemon-reload
  run systemctl --user enable cao-server.service
fi
if [[ ! -e /etc/apparmor.d/bwrap ]]; then
  echo 'AppArmor が必要な環境では次を手動実行してください:'
  printf 'sudo cp -- %q /etc/apparmor.d/bwrap\n' "$repo/system/apparmor-bwrap"
  echo 'sudo apparmor_parser -r /etc/apparmor.d/bwrap'
fi
echo 'セッション終了後、必要に応じて実行: systemctl --user restart cao-server.service'
echo 'node が systemd の PATH にない場合は docs/setup.md の手順を実施してください。'
