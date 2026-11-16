#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/install-test.XXXXXX")
trap 'rm -r -- "$tmp"' EXIT
export HOME="$tmp/home with spaces" CAO_HOME_DIR="$tmp/state" CALLS="$tmp/calls"
mkdir -p "$HOME" "$tmp/bin" "$CAO_HOME_DIR/agents/team" "$HOME/.local/bin" "$HOME/.codex"
printf 'original\n' > "$CAO_HOME_DIR/agents/team/keep"
printf 'old launcher\n' > "$HOME/.local/bin/cao-dev"
ln -s "$tmp/missing" "$HOME/.codex/cao.config.toml"
printf 'old read-only config\n' > "$HOME/.codex/cao-ro.config.toml"
cat > "$tmp/bin/cao" <<'STUB'
#!/usr/bin/env bash
printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >> "$CALLS"
STUB
cat > "$tmp/bin/systemctl" <<'STUB'
#!/usr/bin/env bash
printf 'systemctl %s\n' "$*" >> "$CALLS"
STUB
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:/usr/bin:/bin"
checks=0
check() { if "$@"; then checks=$((checks + 1)); else printf 'FAIL: %s\n' "$*" >&2; exit 1; fi; }
run() { bash "$repo/install.sh" "$@" > "$tmp/output"; }
# Missing installer must fail before any assertions can pass.
check test -f "$repo/install.sh"
run --dry-run
check test ! -e "$CALLS"
check test ! -L "$CAO_HOME_DIR/agents/team"
check test ! -d "$HOME/.config"
check test -f "$CAO_HOME_DIR/agents/team/keep"
run
for dir in team claude codex agy; do check test "$(readlink "$CAO_HOME_DIR/agents/$dir")" = "$repo/agents/$dir"; done
check test "$(readlink "$CAO_HOME_DIR/agents/local")" = "$repo/local/agents"
for skill in ponytail ponytail-audit ponytail-review; do check test "$(readlink "$CAO_HOME_DIR/skills/$skill")" = "$repo/skills/$skill"; done
for cmd in cao-dev cao-doctor cao-models cao-trace; do check test "$(readlink "$HOME/.local/bin/$cmd")" = "$repo/bin/$cmd"; done
check test "$(readlink "$HOME/.codex/cao.config.toml")" = "$repo/codex/cao.config.toml"
check test "$(readlink "$HOME/.codex/cao-ro.config.toml")" = "$repo/codex/cao-ro.config.toml"
check test -f "$HOME/.codex/cao-ro.config.toml"
backups=("$HOME/.codex/"cao-ro.config.toml.bak-*)
check test "$(cat "${backups[0]}")" = 'old read-only config'
backups=("$CAO_HOME_DIR/agents/"team.bak-*)
check test "${#backups[@]}" -eq 1
check test "$(cat "${backups[0]}/keep")" = original
backups=("$HOME/.local/bin/"cao-dev.bak-*)
check test "$(cat "${backups[0]}")" = 'old launcher'
backups=("$HOME/.codex/"cao.config.toml.bak-*)
check test -L "${backups[0]}"
check test "$(grep -c $'^config\tset\t' "$CALLS")" -eq 4
check grep -Fq "[\"$CAO_HOME_DIR/agents/local\",\"$CAO_HOME_DIR/agents/claude\",\"$CAO_HOME_DIR/agents/codex\",\"$CAO_HOME_DIR/agents/agy\",\"$CAO_HOME_DIR/agents/team\"]" "$CALLS"
check grep -Fq "[\"$HOME/.kiro/agents\",\"$CAO_HOME_DIR/agent-store\",\"$CAO_HOME_DIR/agent-context\"]" "$CALLS"
check grep -Fq $'memory.learning_enabled\ttrue' "$CALLS"
check grep -Fq $'terminal.spawn_mode\tpane' "$CALLS"
unit="$HOME/.config/systemd/user/cao-server.service"
loopback=$(printf '%d.%d.%d.%d' 127 0 0 1)
check grep -Fq -- "--host $loopback" "$unit"
check test "$(grep -c '^systemctl ' "$CALLS")" -eq 2
check grep -Fxq 'systemctl --user daemon-reload' "$CALLS"
check grep -Fxq 'systemctl --user enable cao-server.service' "$CALLS"
check test "$(grep -Ec 'restart|start ' "$CALLS" || :)" -eq 0
printf '\n# preserve existing\n' >> "$unit"
cp "$unit" "$tmp/unit-before"
run
check cmp -s "$unit" "$tmp/unit-before"
check grep -q '既存ユニットを維持' "$tmp/output"
check test "$(find "$HOME" "$CAO_HOME_DIR" -name '*.bak-*' | wc -l)" -eq 4
check test "$(grep -c '^systemctl ' "$CALLS")" -eq 2
cp "$CALLS" "$tmp/calls-before"
run --dry-run
check cmp -s "$CALLS" "$tmp/calls-before"
check cmp -s "$unit" "$tmp/unit-before"
# Default state path, and a backup name collision must preserve both originals.
export HOME="$tmp/default-home"
unset CAO_HOME_DIR
mkdir -p "$HOME/.aws/cli-agent-orchestrator/agents/team"
cat > "$tmp/bin/date" <<'STUB'
#!/usr/bin/env bash
printf '20000101000000\n'
STUB
chmod +x "$tmp/bin/date"
mkdir -p "$HOME/.aws/cli-agent-orchestrator/agents/team.bak-20000101000000"
printf 'keep\n' > "$HOME/.aws/cli-agent-orchestrator/agents/team.bak-20000101000000/keep"
run
check test -L "$HOME/.aws/cli-agent-orchestrator/agents/team"
check test -f "$HOME/.aws/cli-agent-orchestrator/agents/team.bak-20000101000000/keep"
check test -d "$HOME/.aws/cli-agent-orchestrator/agents/team.bak-20000101000000-1"
# A replacement metacharacter in the state path must survive unit rendering.
export HOME="$tmp/odd-home" CAO_HOME_DIR="$tmp/state&dir"
run
check grep -Fxq "Environment=\"CAO_HOME_DIR=$CAO_HOME_DIR\"" "$HOME/.config/systemd/user/cao-server.service"
# Missing cao and unknown arguments must fail without creating HOME.
export HOME="$tmp/unused-home" PATH=/usr/bin:/bin
if run; then echo 'FAIL: missing cao accepted' >&2; exit 1; fi
check grep -q 'uv tool install cli-agent-orchestrator' "$tmp/output"
check test ! -e "$HOME"
if run --invalid; then echo 'FAIL: invalid option accepted' >&2; exit 1; fi
check test ! -e "$HOME"
printf 'PASS: %s checks\n' "$checks"
