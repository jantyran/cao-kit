import os
from pathlib import Path
import subprocess
import tempfile
import unittest

DEV = Path(__file__).resolve().parents[1] / 'bin/cao-dev'


class NoArgAttachTest(unittest.TestCase):
    def run_dev(self, cwd, home, root, **extra):
        fake = home / 'bin'
        fake.mkdir(exist_ok=True)
        log = home / 'log'
        for name, body in {
            'cao': '''#!/bin/sh
echo "cao $*" >> "$LOG"
case "$1 $2 $3" in
  'config get terminal.backend') echo "${BACKEND:-herdr}" ;;
  'config get terminal.herdr_session') echo cao ;;
  'session list '*) printf '%s\\n' "$SESSIONS" ;;
  'launch '* ) echo launch ;;
esac
''',
            'herdr': '#!/bin/sh\ncase "$*" in *"status server") echo "status: running"; exit 0 ;; esac\necho "herdr $*" >> "$LOG"\n',
            'tmux': '#!/bin/sh\necho "tmux $*" >> "$LOG"\n',
            'curl': '#!/bin/sh\nexit 0\n',
            'cao-doctor': '#!/bin/sh\nexit 0\n',
            'git': '#!/bin/sh\n[ "$1" = rev-parse ] && [ "$2" = --show-toplevel ] || exit 1\nprintf "%s\\n" "$FAKE_TOP"\n',
        }.items():
            path = fake / name
            path.write_text(body)
            path.chmod(0o755)
        env = dict(os.environ)
        env.update(HOME=str(home), CAO_DEV_ROOT=str(root), PATH=f'{fake}:/usr/bin:/bin',
                   LOG=str(log), SESSIONS='cao-trio x', TMUX='', HERDR_PANE_ID='')
        env.update(extra)
        env['FAKE_TOP'] = str(home)
        result = subprocess.run([str(DEV)], cwd=cwd, env=env, text=True, capture_output=True)
        return result, log.read_text().splitlines() if log.exists() else []

    def test_outside_root_attaches_herdr(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); home = base / 'home'; home.mkdir()
            cwd = base / 'outside'; cwd.mkdir()
            result, log = self.run_dev(cwd, home, base / 'project-root')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('herdr --session cao', log)
            self.assertIn('cao-trio', result.stdout)

    def test_herdr_inside_lists_without_attaching(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); home = base / 'home'; home.mkdir()
            cwd = base / 'outside'; cwd.mkdir()
            result, log = self.run_dev(cwd, home, base / 'project-root', HERDR_PANE_ID='w1:p1')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('herdr --session cao', log)
            self.assertEqual(log.count('cao session list'), 1)
            self.assertIn('すでに herdr の中です', result.stdout)
            self.assertIn('cao-trio', result.stdout)

    def test_tmux_inside_lists_without_attaching(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); home = base / 'home'; home.mkdir()
            cwd = base / 'outside'; cwd.mkdir()
            result, log = self.run_dev(cwd, home, base / 'project-root', BACKEND='tmux', TMUX='/tmp/tmux,1,0')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('tmux attach', log)
            self.assertEqual(log.count('cao session list'), 1)
            self.assertIn('すでに tmux の中です。tmux のセッション一覧（Ctrl-b s）から選んでください。', result.stdout)
            self.assertIn('cao-trio', result.stdout)

    def test_no_sessions_prints_usage(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); home = base / 'home'; home.mkdir()
            cwd = base / 'outside'; cwd.mkdir()
            result, log = self.run_dev(cwd, home, base / 'project-root', SESSIONS='')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(log, ['cao session list'])
            self.assertIn('cao-dev（プロジェクトの外）', result.stdout)

    def test_tmux_outside_attaches(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); home = base / 'home'; home.mkdir()
            cwd = base / 'outside'; cwd.mkdir()
            result, log = self.run_dev(cwd, home, base / 'project-root', BACKEND='tmux')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(log[-1], 'tmux attach')

    def test_project_directory_and_other_repo_launch(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); home = base / 'home'; home.mkdir()
            root = base / 'projects'; project = root / 'inside'; project.mkdir(parents=True)
            other = base / 'other'; other.mkdir()
            subprocess.run(['git', 'init', '-q', str(other)], check=True)
            for cwd, dev_root in ((project, root), (other, root)):
                result, log = self.run_dev(cwd, home, dev_root, FAKE_TOP=str(cwd))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(any(x.startswith('cao launch ') for x in log))


if __name__ == '__main__':
    unittest.main()
