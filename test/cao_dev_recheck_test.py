import os
from pathlib import Path
import subprocess
import tempfile
import unittest

DEV = Path(__file__).resolve().parents[1] / 'bin/cao-dev'


class RecheckTest(unittest.TestCase):
    def check_recovery(self, missing, recovery):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            scripts = {
                'curl': '''#!/bin/sh
status=unknown
if [ -f "$DELAYED" ]; then
  case "$RECOVERY" in
    processing) status=processing ;;
    failure) exit 1 ;;
  esac
fi
printf '{"terminals":[{"agent_profile":"claude_opus_lead","tmux_window":"claude_opus_lead-3cc6","status":"%s"}]}' "$status"
''',
                'herdr': '''#!/bin/sh
ws=w1
[ ! -f "$DELAYED" ] || ws=w2
case "$*" in
  *'workspace list')
    if [ "$MISSING" = workspace ] && { [ ! -f "$DELAYED" ] || [ "$RECOVERY" != workspace ]; }; then
      echo '{"result":{"workspaces":[]}}'
    else
      printf '{"result":{"workspaces":[{"workspace_id":"%s","label":"cao-app"}]}}' "$ws"
    fi ;;
  *'tab list')
    if [ "$MISSING" = tab ] && [ ! -f "$DELAYED" ] || [ "$RECOVERY" != workspace ]; then
      echo '{"result":{"tabs":[]}}'
    else
      printf '{"result":{"tabs":[{"workspace_id":"%s","tab_id":"%s:t1","label":"claude_opus_lead-3cc6"}]}}' "$ws" "$ws"
    fi ;;
  *'pane list')
    printf '{"result":{"panes":[{"workspace_id":"%s","tab_id":"%s:t1","label":null,"agent":"claude","terminal_title":"working"}]}}' "$ws" "$ws" ;;
  *) exit 1 ;;
esac
''',
                'sleep': '''#!/bin/sh
[ "$1" = 1 ] || exit 1
echo delay >> "$DELAYS"
touch "$DELAYED"
''',
            }
            for name, script in scripts.items():
                path = root / name
                path.write_text(script)
                path.chmod(0o755)
            env = dict(os.environ, PATH=f'{d}:/usr/bin:/bin', DEV=str(DEV),
                       sess='cao-app', HERDR_SESSION='cao', BACKEND='herdr',
                       MISSING=missing, RECOVERY=recovery,
                       DELAYED=str(root / 'delayed'), DELAYS=str(root / 'delays'))
            shell = 'source <(sed -n "/^leader_exited() {/,/^}/p" "$DEV"); if leader_exited; then echo dead; else echo live; fi'
            result = subprocess.run(['bash', '-c', shell], env=env,
                                    capture_output=True, text=True, check=True, timeout=5)
            self.assertEqual(result.stdout.strip(), 'live', result.stderr)
            self.assertEqual((root / 'delays').read_text().splitlines(), ['delay'])

    def test_recheck_refreshes_unknown_status_to_processing(self):
        for missing in ('workspace', 'tab'):
            with self.subTest(missing=missing):
                self.check_recovery(missing, 'processing')

    def test_recheck_finds_live_workspace_with_new_id(self):
        for missing in ('workspace', 'tab'):
            with self.subTest(missing=missing):
                self.check_recovery(missing, 'workspace')

    def test_failed_api_recheck_preserves_session(self):
        for missing in ('workspace', 'tab'):
            with self.subTest(missing=missing):
                self.check_recovery(missing, 'failure')


if __name__ == '__main__':
    unittest.main()
