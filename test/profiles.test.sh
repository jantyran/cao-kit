#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
shopt -s globstar nullglob dotglob extglob

fail() { printf 'FAIL: %s: %s\n' "$1" "$2" >&2; }
# shortcut: frontmatter の単純な YAML スカラーとブロック/インラインのツール一覧だけを簡易解析する, 複数行値・アンカーなどを使う場合は YAML パーサーに替える
# Only frontmatter counts; prompt-body examples must not grant permissions.
check_profiles() {
  local root=$1 file line key value provider profile role name tools wildcard in_header
  local -a tool_tokens
  local mode
  local count=0 errors=0
  for file in "$root"/**/*.md; do
    mode= provider= profile= role= name= tools=false wildcard=false in_header=false
    while IFS= read -r line || [[ -n "$line" ]]; do
      if [[ "$line" = --- ]]; then
        if $in_header; then break; fi
        in_header=true
        continue
      fi
      $in_header || break
      line=${line%%#*}
      # A bare '*' is forbidden, but scoped patterns such as fs_* are valid.
      if [[ "$line" = [![:space:]]*:* ]]; then
        key=${line%%:*}
        value=${line#*:}
        tools=false
        [[ "$key" != allowedTools ]] || tools=true
        value=${value//\"/}; value=${value//\'/}
        value=${value##+([[:space:]])}; value=${value%%+([[:space:]])}
        case "$key" in
          provider) provider=$value ;;
          codexProfile) profile=$value ;;
          role) role=$value ;;
          name) name=$value ;;
          permissionMode) mode=$value ;;
        esac
      elif $tools; then
        value=${line//\"/}; value=${value//\'/}
      else
        continue
      fi
      if $tools; then
        value=${value//\[/ }; value=${value//\]/ }; value=${value//,/ }
        value=${value##+([[:space:]])}; value=${value#-}
        local tool
        read -ra tool_tokens <<< "$value"
        for tool in "${tool_tokens[@]}"; do [[ "$tool" != '*' ]] || wildcard=true; done
      fi
    done < "$file"
    count=$((count + 1))
    case "$provider" in
      claude_code|codex|antigravity_cli) ;;
      *) fail "$file" 'provider must be claude_code / codex / antigravity_cli'; errors=$((errors + 1)) ;;
    esac
    if [[ "$provider" = codex ]]; then
      if [[ -z "$profile" ]]; then
        fail "$file" 'codex requires codexProfile'; errors=$((errors + 1))
      fi
      if [[ "$role" = reviewer && "$profile" != cao-ro ]]; then
        fail "$file" 'codex reviewer requires codexProfile: cao-ro'; errors=$((errors + 1))
      fi
    fi
    # 既定の --dangerously-skip-permissions を避け、危険な操作を auto モードの分類器に止めさせる
    if [[ "$provider" = claude_code && "$mode" != auto ]]; then
      fail "$file" 'claude_code requires permissionMode: auto'; errors=$((errors + 1))
    fi
    if $wildcard; then
      fail "$file" 'allowedTools must not contain "*"'; errors=$((errors + 1))
    fi
    # Retrospectors are identified by name; their CAO permission role may vary.
    if [[ "$profile" = cao-ro && "$role" != reviewer && "$name" != *_retrospector ]]; then
      fail "$file" 'cao-ro is only for reviewer or names matching *_retrospector'; errors=$((errors + 1))
    fi
  done
  if [[ "$count" -eq 0 ]]; then fail "$root" 'no profiles found'; return 1; fi
  [[ "$errors" -eq 0 ]] || return 1
  printf 'PASS: %s profiles\n' "$count"
}

# Mutate temporary copies to prove each guard rejects bad metadata (including
# inline lists), reports the filename/reason, and ignores prompt-body examples.
self_check() {
  local source mutated expected checks=0 variant
  profiles_tmp=$(mktemp -d "${TMPDIR:-/tmp}/profiles-test.XXXXXX")
  trap 'rm -r -- "$profiles_tmp"' EXIT
  mkdir -p "$profiles_tmp/agents/nested"
  source=$(< "$repo/agents/codex/codex.md")
  for variant in valid scoped body provider missing reviewer wildcard inline writer retrospector other_retrospector named_reviewer role_only near_suffix claude_mode; do
    mutated=$source
    expected=''
    case "$variant" in
      scoped) mutated=${source/codexProfile: cao/$'codexProfile: "cao"\nallowedTools: ["fs_*", "@builtin"]'} ;;
      body) mutated=$source$'\nprovider: kiro\nallowedTools: ["*"]\nrole: reviewer' ;;
      claude_mode) mutated=${source/provider: codex/provider: claude_code}; expected='claude_code requires permissionMode' ;;
      provider) mutated=${source/provider: codex/provider: kiro}; expected='provider must be' ;;
      missing) mutated=${source/codexProfile: cao/}; expected='codex requires codexProfile' ;;
      reviewer) mutated=${source/role: developer/role: reviewer}; expected='codex reviewer requires' ;;
      wildcard) mutated=${source/codexProfile: cao/$'codexProfile: cao\nallowedTools:\n  - "*"'}; expected='allowedTools must not' ;;
      inline) mutated=${source/codexProfile: cao/$'codexProfile: cao\nallowedTools: ["fs_*", "*"]'}; expected='allowedTools must not' ;;
      writer) mutated=${source/codexProfile: cao/codexProfile: cao-ro}; expected='cao-ro is only for' ;;
      # Any *_retrospector name may use cao-ro, regardless of filename/role.
      retrospector|other_retrospector)
        mutated=${source/name: codex/name: ${variant}_retrospector}
        mutated=${mutated/codexProfile: cao/codexProfile: cao-ro}
        mutated=${mutated/role: developer/role: supervisor}
        ;;
      named_reviewer)
        mutated=${source/codexProfile: cao/codexProfile: cao-ro}
        mutated=${mutated/role: developer/role: reviewer}
        ;;
      # A role label or a similar-looking name must not grant the exception.
      role_only)
        mutated=${source/codexProfile: cao/codexProfile: cao-ro}
        mutated=${mutated/role: developer/role: retrospector}
        expected='cao-ro is only for'
        ;;
      near_suffix)
        mutated=${source/name: codex/name: codex_retrospector_coder}
        mutated=${mutated/codexProfile: cao/codexProfile: cao-ro}
        expected='cao-ro is only for'
        ;;
    esac
    printf '%s\n' "$mutated" > "$profiles_tmp/agents/nested/profile.md"
    if [[ -n "$expected" ]]; then
      if check_profiles "$profiles_tmp/agents" > "$profiles_tmp/output" 2>&1; then
        fail "$variant" 'invalid copy accepted'; return 1
      fi
      local output
      output=$(< "$profiles_tmp/output")
      [[ "$output" = *"$profiles_tmp/agents/nested/profile.md: $expected"* ]] || { fail "$variant" 'missing diagnostic'; return 1; }
    else
      check_profiles "$profiles_tmp/agents" > "$profiles_tmp/output"
    fi
    checks=$((checks + 1))
  done
  printf 'PASS: %s validator self-checks\n' "$checks"
}

if [[ "${1:-}" = --check && $# -eq 2 ]]; then
  check_profiles "$2"
else
  [[ $# -eq 0 ]] || { echo 'Usage: profiles.test.sh [--check agents-directory]' >&2; exit 1; }
  self_check
  check_profiles "$repo/agents"
  # 予備リーダーは主担当の手作業コピー。本文（最初の ## 以降）はスキルの使い方の 1 行以外そろえる
  lead_body() { sed -n '/^## /,$p' "$1" | grep -v 'load_skill'; }
  for f in "$repo"/agents/team/{agy_opus,codex_sol}_lead.md; do
    diff <(lead_body "$repo/agents/team/claude_opus_lead.md") <(lead_body "$f") >&2 || { fail "$f" 'lead body differs from claude_opus_lead.md'; exit 1; }
  done
  echo 'PASS: lead bodies in sync'
  # 全員にコピーしている共通の節は、1 か所だけ違う文にならないよう一致を確かめる（空行の違いは無視）
  section() { awk -v h="$1" '$0==h{f=1;next} f&&/^## /{exit} f&&NF' "$2"; }
  check_same() {  # $1=見出し, 残り=対象ファイル。その節を持つファイル同士で比べる
    local heading=$1 first='' f; shift
    for f in "$@"; do
      [[ -n "$(section "$heading" "$f")" ]] || continue
      if [[ -z "$first" ]]; then first=$f; continue; fi
      diff <(section "$heading" "$first") <(section "$heading" "$f") >&2 || { fail "$f" "「$heading」が $(basename "$first") と違う"; exit 1; }
    done
  }
  team=("$repo"/agents/team/*.md)
  check_same '## Security Constraints' "${team[@]}"
  check_same '## CAO での受け答え' "${team[@]}"
  check_same '## 学習（cao-learning）' "$repo"/agents/team/*_lead.md
  check_same '## 学習（cao-learning）' $(printf '%s\n' "${team[@]}" | grep -v '_lead.md$')
  echo 'PASS: shared sections in sync'
  # 自分用の上書き（local/agents）も同じ決まりで確認する
  if compgen -G "$repo/local/agents/*.md" > /dev/null; then check_profiles "$repo/local/agents"; fi
fi
