#!/usr/bin/env bash
# cao-models / cao-trace / cao-doctor / cao-dev を一時コピーと偽の状態ディレクトリで検証（本物は変更しない）
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/tools-test.XXXXXX")
trap 'rm -r -- "$tmp"' EXIT
checks=0
check() { if "$@"; then checks=$((checks + 1)); else printf 'FAIL: %s\n' "$*" >&2; exit 1; fi; }

# --- cao-models: frontmatter の model: だけを、引用符の形を保って置き換える
mkdir -p "$tmp/kit/bin" "$tmp/kit/agents/team"
cp "$repo/bin/cao-models" "$tmp/kit/bin/"
printf -- '---\nname: a\nprovider: codex\nmodel: "old-1"\n---\nmodel: old-1 は本文なので変えない\n' > "$tmp/kit/agents/team/a.md"
printf -- '---\nname: b\nprovider: codex\nmodel: old-1\n---\n' > "$tmp/kit/agents/team/b.md"
printf -- '---\nname: c\nprovider: codex\nmodel: other\n---\n' > "$tmp/kit/agents/team/c.md"
check grep -q 'old-1 .* 2  a, b' <("$tmp/kit/bin/cao-models")
"$tmp/kit/bin/cao-models" replace old-1 new-2 > /dev/null
check grep -qx 'model: "new-2"' "$tmp/kit/agents/team/a.md"
check grep -qx 'model: old-1 は本文なので変えない' "$tmp/kit/agents/team/a.md"
check grep -qx 'model: new-2' "$tmp/kit/agents/team/b.md"
check grep -qx 'model: other' "$tmp/kit/agents/team/c.md"
if "$tmp/kit/bin/cao-models" replace missing x > /dev/null 2>&1; then echo 'FAIL: unknown model accepted' >&2; exit 1; fi
# --local: 元のファイルは変えず、local/agents のコピーを書き換え、一覧では * で示す
"$tmp/kit/bin/cao-models" replace --local other local-3 > /dev/null
check grep -qx 'model: other' "$tmp/kit/agents/team/c.md"
check grep -qx 'model: local-3' "$tmp/kit/local/agents/c.md"
check grep -q 'local-3 .* 1  c\*' <("$tmp/kit/bin/cao-models")

# --- cao-trace: 依頼元ごとの字下げ、handoff 結果、画面の記録
export CAO_HOME_DIR="$tmp/state" CAO_SERVER_URL=http://127.0.0.1:9  # 閉じたポート = サーバー停止
logs="$CAO_HOME_DIR/logs/terminal"; mkdir -p "$logs" "$CAO_HOME_DIR/db"
printf '{"terminal_id":"lead1","session_name":"cao-root-app","agent_profile":"claude_opus_lead","caller_id":null}' > "$logs/lead1.snapshot.json"
printf '{"terminal_id":"work1","session_name":"cao-root-app","agent_profile":"codex_sol_coder","caller_id":"lead1"}' > "$logs/work1.snapshot.json"
printf 'worker screen\n' > "$logs/work1.scrollback"
python3 - "$CAO_HOME_DIR/db/cli-agent-orchestrator.db" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
c.execute("create table handoff_results (job_id, state, terminal_id, last_message, error_message, created_at, updated_at)")
c.execute("create table inbox (id integer primary key, sender_id, receiver_id, message, status, created_at)")
c.execute("insert into handoff_results values ('j', 'completed', 'work1', '\n実装しました', '', '', '')")
c.commit()
PY
out=$("$repo/bin/cao-trace" app)
check grep -q '^[0-9-]* [0-9:]*  lead1  claude_opus_lead$' <<< "$out"
check grep -q '    work1  codex_sol_coder  \[完了\] 実装しました' <<< "$out"
check test "$("$repo/bin/cao-trace" work1)" = 'worker screen'
check grep -q 'cao-root-app' <("$repo/bin/cao-trace")
if "$repo/bin/cao-trace" nothing > /dev/null 2>&1; then echo 'FAIL: unknown session accepted' >&2; exit 1; fi

# --- cao-doctor: 足りない CLI、バージョン変化の通知、問題があるときは記録しない
mkdir -p "$tmp/bin" "$CAO_HOME_DIR/agents/team"
printf -- '---\nname: x\nprovider: codex\n---\n' > "$CAO_HOME_DIR/agents/team/x.md"
for cmd in cao codex tmux; do printf '#!/bin/sh\necho "%s $VER"\n' "$cmd" > "$tmp/bin/$cmd"; done
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:/usr/bin:/bin"
# cao-server は無いので NG になり、記録されない
if VER=1 "$repo/bin/cao-doctor" --save > "$tmp/out"; then echo 'FAIL: saved despite problems' >&2; exit 1; fi
check grep -q 'cao-server が応答しません' "$tmp/out"
check test ! -e "$CAO_HOME_DIR/cao-trio-known-good.json"
printf '{"cao": "cao 1", "codex": "codex 1"}' > "$CAO_HOME_DIR/cao-trio-known-good.json"
VER=2 "$repo/bin/cao-doctor" --brief > "$tmp/out" || true
check grep -q 'codex が変わりました: codex 1 → codex 2' "$tmp/out"
rm "$tmp/bin/codex"
VER=1 "$repo/bin/cao-doctor" --brief > "$tmp/out" || true
check grep -q 'codex が見つかりません' "$tmp/out"

# --- cao-dev: 置き場の外（ホーム直下・パス指定）でも起動し、セッション名は cao-<プロジェクト名>
mkdir -p "$tmp/dev/bin" "$tmp/home/projects/app" "$tmp/home/side" "$tmp/home/x/deep" "$tmp/home/x/app"
# 偽の cao: launch は引数を表示、session list は DEV_SESSIONS を表示
printf '#!/bin/sh\n[ "$1" = launch ] && echo "LAUNCH $*"\n[ "$1 $2" = "session list" ] && printf "%%s\\n" "$DEV_SESSIONS"\n[ "$1 $2" = "session send" ] && echo "SEND $3"\nexit 0\n' > "$tmp/dev/bin/cao"
# 偽の curl: /sessions/ では、既存セッションの作業フォルダとして DEV_WD を返す
printf '#!/bin/sh\ncase "$*" in *sessions/*) printf "{\\"terminals\\":[{\\"working_directory\\":\\"%%s\\"}]}" "$DEV_WD" ;; esac\nexit 0\n' > "$tmp/dev/bin/curl"
chmod +x "$tmp/dev/bin/"*
dev() { HOME="$tmp/home" CAO_DEV_ROOT="$tmp/home/projects" PATH="$tmp/dev/bin:/usr/bin:/bin" TMUX= HERDR_PANE_ID= "$repo/bin/cao-dev" "$@"; }
check grep -q -- "--session-name app --working-directory $tmp/home/projects/app " <(dev app 'do')
check grep -q -- "--session-name side --working-directory $tmp/home/side " <(dev side 'do')
check grep -q -- "--session-name deep --working-directory $tmp/home/x/deep " <(dev "$tmp/home/x/deep" 'do')
check grep -q -- "--session-name deep " <(cd "$tmp/home/x" && dev ./deep 'do')
if dev nothing 'do' > /dev/null 2>&1; then echo 'FAIL: unknown project accepted' >&2; exit 1; fi
if dev "$tmp/home" 'do' > /dev/null 2>&1; then echo 'FAIL: home accepted' >&2; exit 1; fi
# 同じ名前のセッションがあれば、同じフォルダなら追記、別のフォルダならエラー
check grep -q 'SEND cao-app' <(DEV_SESSIONS='cao-app  x' DEV_WD="$tmp/home/projects/app" dev app 'more' 2>/dev/null)
if DEV_SESSIONS='cao-app  x' DEV_WD="$tmp/home/projects/app" dev "$tmp/home/x/app" 'more' > /dev/null 2>&1; then echo 'FAIL: name clash accepted' >&2; exit 1; fi

printf 'PASS: %s checks\n' "$checks"
