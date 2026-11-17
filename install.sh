#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
dry_run=false
notice_only=false
case "${1:-}" in
  '') ;;
  --dry-run) dry_run=true; shift ;;
  --apply-codex-notice-only) notice_only=true; shift ;;
  *) echo '使い方: ./install.sh [--dry-run]'; exit 1 ;;
esac
if $notice_only; then
  [[ $# -eq 0 ]] || { echo '使い方: ./install.sh --apply-codex-notice-only'; exit 1; }
else
  [[ $# -eq 0 ]] || { echo '使い方: ./install.sh [--dry-run]'; exit 1; }
fi
if ! $notice_only && ! command -v cao >/dev/null 2>&1; then
  echo 'cao がありません。uv tool install cli-agent-orchestrator を実行してください。'
  exit 1
fi
export CAO_HOME_DIR="${CAO_HOME_DIR:-$HOME/.aws/cli-agent-orchestrator}"
[[ "$CAO_HOME_DIR" = /* ]] || { echo 'CAO_HOME_DIR は絶対パスで指定してください。' >&2; exit 1; }

apply_codex_notice() {
  local config="$HOME/.codex/config.toml" tmp
  if [[ ! -e "$config" ]]; then
    echo "Codex 設定なし、維持: $config"
    return
  fi
  if python3 -c 'import sys,tomllib; sys.exit(0 if tomllib.load(open(sys.argv[1], "rb")).get("notice", {}).get("hide_rate_limit_model_nudge") is not None else 1)' "$config"; then
    echo "Codex 通知設定済み: $config"
    return
  fi
  printf '%s ' "$($dry_run && echo '[dry-run]' || echo '[実行]')"
  printf 'notice.hide_rate_limit_model_nudge = true → %q\n' "$config"
  $dry_run && return
  tmp=$(mktemp "${config}.XXXXXX")
  cp -p -- "$config" "$tmp"
  if python3 - "$config" <<'PY'
import pathlib, sys, tomllib

path = pathlib.Path(sys.argv[1])
lines = path.read_text().splitlines(keepends=True)
start = next((i for i, line in enumerate(lines) if line.lstrip().startswith("[notice]")), None)
if start is None:
    first_table = next((i for i, line in enumerate(lines) if line.lstrip().startswith("[")), len(lines))
    lines[first_table:first_table] = ["[notice]\n", "hide_rate_limit_model_nudge = true\n"]
else:
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    lines[end:end] = ["hide_rate_limit_model_nudge = true\n"]
path.write_text("".join(lines))
tomllib.loads(path.read_text())
PY
  then
    rm -f -- "$tmp"
  else
    cp -p -- "$tmp" "$config"
    rm -f -- "$tmp"
    echo "Codex 設定の TOML 検証に失敗、元に戻しました: $config" >&2
    return 1
  fi
}
if $notice_only; then apply_codex_notice; exit; fi

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
# local/agents（git 管理外）は自分用の上書き置き場。同じ名前のプロファイルがあれば、こちらが優先される
[[ -d "$repo/local/agents" ]] || run mkdir -p -- "$repo/local/agents"
for dir in team claude codex agy; do link "$repo/agents/$dir" "$CAO_HOME_DIR/agents/$dir"; done
link "$repo/local/agents" "$CAO_HOME_DIR/agents/local"
for skill in ponytail ponytail-audit ponytail-review; do link "$repo/skills/$skill" "$CAO_HOME_DIR/skills/$skill"; done
for cmd in cao-dev cao-doctor cao-models cao-trace cao-patch; do link "$repo/bin/$cmd" "$HOME/.local/bin/$cmd"; done
link "$repo/codex/cao.config.toml" "$HOME/.codex/cao.config.toml"
link "$repo/codex/cao-ro.config.toml" "$HOME/.codex/cao-ro.config.toml"
apply_codex_notice
run cao config set agents.extra_dirs "$(json_array "$CAO_HOME_DIR/agents/local" "$CAO_HOME_DIR/agents/claude" "$CAO_HOME_DIR/agents/codex" "$CAO_HOME_DIR/agents/agy" "$CAO_HOME_DIR/agents/team")"
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
