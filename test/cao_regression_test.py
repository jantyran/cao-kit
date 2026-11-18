import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RegressionTest(unittest.TestCase):
    def test_missing_leader_requires_unknown_and_delayed_recheck(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, script in {
                'curl': '''#!/bin/sh
printf '{"terminals":[{"tmux_window":"claude_opus_lead-3cc6","status":"%s"}]}' "$STATUS"
''',
                'herdr': '''#!/bin/sh
case "$*" in
  *'workspace list') kind=workspace ;;
  *'tab list') kind=tab ;;
  *) exit 1 ;;
esac
echo "$kind" >> "$CALLS"
if [ "$kind" = "$MISSING" ] && { [ "$RECOVERS" = no ] || [ ! -f "$DELAYED" ]; }; then
  printf '{"result":{"%ss":[]}}\n' "$kind"
elif [ "$kind" = workspace ]; then
  echo '{"result":{"workspaces":[{"workspace_id":"w1","label":"cao-app"}]}}'
else
  echo '{"result":{"tabs":[{"workspace_id":"w1","tab_id":"w1:t1","label":"claude_opus_lead-3cc6"}]}}'
fi
''',
                # Record the requested delay without making the suite wait.
                'sleep': '''#!/bin/sh
echo "sleep $*" >> "$CALLS"
touch "$DELAYED"
''',
            }.items():
                path = root / name
                path.write_text(script)
                path.chmod(0o755)
            shell = 'source <(sed -n "/^leader_exited() {/,/^}/p" "$DEV"); if leader_exited; then echo dead; else echo live; fi'
            calls = root / 'calls'
            delayed = root / 'delayed'
            env = dict(os.environ, PATH=f'{d}:/usr/bin:/bin', DEV=str(ROOT/'bin/cao-dev'), sess='cao-app', HERDR_SESSION='cao', BACKEND='herdr', CALLS=str(calls), DELAYED=str(delayed))
            for missing in ('workspace', 'tab'):
                for status, recovers, expected in [
                    ('processing', 'no', 'live'),
                    ('idle', 'no', 'live'),
                    ('completed', 'no', 'live'),
                    ('unknown', 'no', 'dead'),
                    ('unknown', 'yes', 'live'),
                ]:
                    with self.subTest(missing=missing, status=status, recovers=recovers):
                        calls.write_text('')
                        delayed.unlink(missing_ok=True)
                        result = subprocess.run(['bash', '-c', shell], env=dict(env, STATUS=status, MISSING=missing, RECOVERS=recovers), capture_output=True, text=True, check=True)
                        self.assertEqual(result.stdout.strip(), expected, result.stderr)
                        prefix = ['workspace'] if missing == 'tab' else []
                        expected_calls = prefix + [missing]
                        if status == 'unknown':
                            # Retry the full lookup, starting with the workspace.
                            expected_calls += ['sleep 1', 'workspace']
                            if missing == 'tab' or recovers == 'yes':
                                expected_calls += ['tab']
                        self.assertEqual(calls.read_text().splitlines(), expected_calls)


class RecapRegressionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.project = self.home / 'project'
        self.project.mkdir()
        self.logs = self.home / '.claude/projects' / re.sub(r'[^a-zA-Z0-9-]', '-', str(self.project))
        self.logs.mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.home))

    @staticmethod
    def row(content):
        return json.dumps({'type': 'user', 'message': {'content': content}}).encode() + b'\n'

    def recap(self, data):
        (self.logs / 'session.jsonl').write_bytes(data)
        result = subprocess.run([str(ROOT/'bin/cao-recap'), str(self.project)], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return (self.project / '.cao/last-session.md').read_text()

    def test_non_string_text_is_ignored_and_invalid_utf8_is_replaced(self):
        content = self.recap(
            self.row([{'type': 'text', 'text': None}, {'type': 'text', 'text': 12}, {'type': 'text', 'text': 'valid'}])
            + self.row(None) + self.row(12)
            + b'{"type":"user","message":{"content":"truncated-\xe3\x81"}}\n'
            + self.row('after-invalid')
        )
        self.assertIn('\nvalid\n', content)
        self.assertIn('truncated-\ufffd', content)
        self.assertIn('after-invalid', content)
        self.assertNotIn('None', content)
        self.assertNotIn('\n12\n', content)
        self.assertEqual(content.count('## user\n'), 3)

    def test_lines_over_256k_are_skipped(self):
        # Exact byte lengths, including JSON overhead and the newline.
        limit = 256 * 1024
        overhead = len(self.row(''))
        boundary = self.row('boundary-marker' + 'x' * (limit - overhead - len('boundary-marker')))
        oversized = self.row('oversized-marker' + 'x' * (limit + 1 - overhead - len('oversized-marker')))
        self.assertEqual(len(boundary), limit)
        self.assertEqual(len(oversized), limit + 1)
        content = self.recap(boundary + oversized + self.row('after-large'))
        self.assertIn('boundary-marker', content)
        self.assertNotIn('oversized-marker', content)
        self.assertIn('after-large', content)

    def test_only_last_4mb_are_read_and_partial_first_line_is_discarded(self):
        # Fewer than 30 messages: the message-count cap cannot hide a missing byte cap.
        prefix = self.row('before-tail-marker')
        crossing = self.row('crossing-marker' + 'x' * 100)
        padding = b' ' * 200000 + b'\n'
        tail = padding * 20 + self.row('tail-marker')
        data = prefix + crossing + tail
        # Put the seek position at the start of valid JSON inside a partial line.
        seek = len(prefix) + len(crossing) - len(b'"}}\n')
        embedded = self.row('partial-line-marker')
        data = data[:seek] + embedded + data[seek:]
        data += b' ' * (4 * 1024 * 1024 - (len(data) - seek))
        self.assertEqual(len(data) - 4 * 1024 * 1024, seek)
        content = self.recap(data)
        self.assertIn('tail-marker', content)
        self.assertNotIn('before-tail-marker', content)
        self.assertNotIn('crossing-marker', content)
        self.assertNotIn('partial-line-marker', content)

    def test_linked_worktree_excluded_by_recap_and_dev(self):
        repo = self.home / 'repo'
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        subprocess.run(['git', '-C', str(repo), '-c', 'user.name=T', '-c', 'user.email=t@example.com', 'commit', '--allow-empty', '-qm', 'init'], check=True, capture_output=True)
        self.project.rmdir()
        subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '-q', str(self.project)], check=True)
        self.assertTrue((self.project / '.git').is_file())
        exclude = Path(subprocess.check_output(['git', '-C', str(self.project), 'rev-parse', '--path-format=absolute', '--git-path', 'info/exclude'], text=True).strip())
        fake = self.home / 'bin'
        fake.mkdir()
        for name, script in {
            'curl': '#!/bin/sh\necho \'{"terminals":[]}\'\n',
            'cao': '''#!/bin/sh
case "$1 $2" in
  'session list') echo cao-project ;;
  'session send') echo "SEND $3" ;;
esac
''',
        }.items():
            path = fake / name
            path.write_text(script)
            path.chmod(0o755)
        for command in ('recap', 'dev'):
            with self.subTest(command=command):
                exclude.write_text('# preserved\n')
                if command == 'recap':
                    self.recap(self.row('worktree-message'))
                    self.recap(self.row('worktree-message'))
                else:
                    for _ in range(2):
                        result = subprocess.run([str(ROOT/'bin/cao-dev'), str(self.project), 'task'], env=dict(self.env, PATH=f'{fake}:/usr/bin:/bin', TMUX='', HERDR_PANE_ID=''), capture_output=True, text=True, check=True)
                        self.assertIn('SEND cao-project', result.stdout)
                lines = exclude.read_text().splitlines()
                self.assertIn('# preserved', lines)
                self.assertEqual(lines.count('.cao/'), 1)
                ignored = subprocess.run(['git', '-C', str(self.project), 'check-ignore', '.cao/last-session.md'], capture_output=True, text=True)
                self.assertEqual(ignored.returncode, 0, ignored.stderr)


if __name__ == '__main__':
    unittest.main()
