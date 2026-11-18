import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

DEV = Path(__file__).resolve().parents[1] / 'bin/cao-dev'

class RestartTest(unittest.TestCase):
    def test_real_herdr_layouts(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixtures = {
                'workspaces': [{'workspace_id': w, 'label': name} for w, name in [('w7', 'cao-app-a'), ('w8', 'cao-app-b'), ('wC', 'cao-trio')]],
                'tabs': [{'workspace_id': w, 'tab_id': w + ':t1', 'label': label} for w, label in [('w7', 'claude_opus_lead-3cc6'), ('w8', 'claude_opus_lead-eca2'), ('wC', 'claude_opus_lead-d269')]],
                'panes': [
                    {'workspace_id': w, 'tab_id': w + ':t1', 'pane_id': w + ':' + p, 'label': None, 'agent': agent, 'terminal_title': title}
                    for w, p, agent, title in [
                        ('w7', 'p1', None, 'user@host: ~/projects/app-a'),
                        ('w7', 'p2', None, 'user@host: ~/projects/app-a'),
                        ('w8', 'p1', 'claude', '✳ サイト・アプリ開発の続き'),
                        ('w8', 'p2', None, 'user@host: ~/projects/app-b'),
                        ('wC', 'p1', 'claude', '◑ 過去のログの閲覧方法'),
                    ]],
            }
            for kind, data in fixtures.items():
                (root / kind).write_text(json.dumps({'result': {kind: data}}, ensure_ascii=False))
            herdr = root / 'herdr'
            herdr.write_text('#!/bin/sh\ncase "$*" in *"workspace list") cat "$FIXTURES/workspaces";; *"tab list") cat "$FIXTURES/tabs";; *"pane list") cat "$FIXTURES/panes";; esac\n')
            herdr.chmod(0o755)
            curl = root / 'curl'
            curl.write_text("#!/bin/sh\nprintf '{\"terminals\":[{\"agent_profile\":\"claude_opus_lead\",\"tmux_window\":\"%s\",\"status\":\"unknown\"}]}' \"$WINDOW\"\n")
            curl.chmod(0o755)
            shell = 'source <(sed -n "/^leader_exited() {/,/^}/p" "$DEV"); if leader_exited; then echo dead; else echo live; fi'
            for session, window, expected in [('cao-app-a', 'claude_opus_lead-3cc6', 'dead'), ('cao-app-b', 'claude_opus_lead-eca2', 'live'), ('cao-trio', 'claude_opus_lead-d269', 'live')]:
                env = dict(os.environ, DEV=str(DEV), FIXTURES=d, PATH=f'{d}:/usr/bin:/bin', BACKEND='herdr', HERDR_SESSION='cao', sess=session, WINDOW=window)
                result = subprocess.run(['bash', '-c', shell], env=env, text=True, capture_output=True, check=True)
                self.assertEqual(result.stdout.strip(), expected, result.stderr)

    def test_leader_states(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            project = root / 'projects/cao-app'
            project.mkdir(parents=True)
            fake = root / 'bin'
            fake.mkdir()
            scripts = {
                'cao': '''#!/bin/sh
case "$1 $2 $3" in
  'config get terminal.backend') echo "${BACKEND:-herdr}" ;;
  'config get terminal.herdr_session') echo cao ;;
  'session list '*) echo 'cao-app x' ;;
  'session send '*) echo "SEND $3" ;;
  'shutdown --session '*) echo "SHUTDOWN $3" ;;
  'launch --agents '*) echo "LAUNCH $*" ;;
esac
''',
                'curl': f'''#!/bin/sh
[ -n "$SESSION_JSON" ] && {{ echo "$SESSION_JSON"; exit 0; }}
case "$*" in *sessions/*) printf '{{"terminals":[{{"working_directory":"{project}","agent_profile":"claude_opus_lead","tmux_window":"claude_opus_lead-3cc6","status":"%s"}}]}}' "$STATUS" ;; esac
''',
                'tmux': '''#!/bin/sh
case "$1" in list-panes) [ "$2" = -t ] && [ "$3" = "cao-app:claude_opus_lead-3cc6" ] && [ "$4" = -F ] && [ "$5" = '#{pane_current_command}' ] || exit 1; printf '%s\\n' "$TMUX_COMMAND" ;; *) exit 0 ;; esac
''',
                'herdr': '''#!/bin/sh
case "$*" in
  *'workspace list') echo '{"result":{"workspaces":[{"workspace_id":"w1","label":"cao-app"}]}}' ;;
  *'tab list') echo '{"result":{"tabs":[{"workspace_id":"w1","tab_id":"w1:t1","label":"claude_opus_lead-3cc6"}]}}' ;;
  *'pane list') printf '%s\\n' "$PANES" ;;
  *'status server') echo 'status: running' ;;
esac
''',
            }
            for name, body in scripts.items():
                path = fake / name
                path.write_text(body)
                path.chmod(0o755)
            env = dict(os.environ, HOME=d, CAO_DEV_ROOT=str(root/'projects'), PATH=f'{fake}:/usr/bin:/bin', TMUX='', HERDR_PANE_ID='', STATUS='unknown')
            def run(panes):
                return subprocess.run([str(DEV), 'cao-app', 'task'], env=dict(env, PANES=panes), text=True, capture_output=True, check=True).stdout
            live = '{"result":{"panes":[{"workspace_id":"w1","tab_id":"w1:t1","agent":"claude","terminal_title":"✳ working"}]}}'
            dead = '{"result":{"panes":[{"workspace_id":"w1","tab_id":"w1:t1","terminal_title":"ubuntu@host: ~/app"}]}}'
            live_with_shell = '{"result":{"panes":[{"workspace_id":"w1","tab_id":"w1:t1","label":null,"agent":"claude","terminal_title":"✳ サイト・アプリ開発の続き"},{"workspace_id":"w1","tab_id":"w1:t1","label":null,"agent":null,"terminal_title":"user@host: ~/projects/app-b"}]}}'
            self.assertIn('SEND cao-app', run(live_with_shell))
            self.assertIn('SEND cao-app', run(live))
            self.assertIn('SEND cao-app', run('{}'))
            for status in ('idle', 'processing', 'completed'):
                result = subprocess.run([str(DEV), 'cao-app', 'task'], env=dict(env, PANES=dead, STATUS=status), text=True, capture_output=True, check=True)
                self.assertIn('SEND cao-app', result.stdout)
            output = run(dead)
            self.assertLess(output.index('SHUTDOWN cao-app'), output.index('LAUNCH '))
            self.assertIn('--session-name cao-app', output)
            for command, expected in [('bash', 'SHUTDOWN cao-app'), ('bash\nzsh\nsh', 'SHUTDOWN cao-app'), ('codex', 'SEND cao-app'), ('bash\nclaude', 'SEND cao-app'), ('bash\ncodex', 'SEND cao-app'), ('', 'SEND cao-app')]:
                result = subprocess.run([str(DEV), 'cao-app', 'task'], env=dict(env, BACKEND='tmux', TMUX_COMMAND=command), text=True, capture_output=True, check=True)
                self.assertIn(expected, result.stdout)
            result = subprocess.run([str(DEV), 'cao-app', 'task'], env=dict(env, BACKEND='tmux', TMUX_COMMAND='bash', STATUS='idle'), text=True, capture_output=True, check=True)
            self.assertIn('SEND cao-app', result.stdout)
            result = subprocess.run([str(DEV), 'cao-app', 'task'], env=dict(env, PANES=dead, HERDR_PANE_ID='w1:p1'), text=True, capture_output=True, check=True)
            log = project / '.cao/tmp/cao-dev-restart.log'
            for _ in range(100):
                if log.exists() and 'LAUNCH ' in log.read_text():
                    break
                time.sleep(0.02)
            output = log.read_text()
            self.assertLess(output.index('SHUTDOWN cao-app'), output.index('LAUNCH '))
            output = subprocess.run([str(DEV), 'cao-app'], env=dict(env, SESSION_JSON='{"terminals":[]}'), text=True, capture_output=True, check=True).stdout
            self.assertLess(output.index('SHUTDOWN cao-app'), output.index('LAUNCH '))
            missing = subprocess.run([str(DEV), 'missing'], env=dict(env, CAO_DEV_ROOT=str(root/'absent')), capture_output=True, text=True)
            self.assertNotIn('No such file', missing.stderr)

if __name__ == '__main__': unittest.main()
