"""Regressions for rewritten rollout boundaries and bounded pane discovery."""
import subprocess
import time
import unittest
from unittest.mock import patch

import codex_rollout_output_test as base


class BoundaryTest(unittest.TestCase):
    setUp = base.RolloutTest.setUp
    process = base.RolloutTest.process
    link = base.RolloutTest.link
    append = base.RolloutTest.append
    output = base.RolloutTest.output

    def test_truncate_and_regrow_same_inode_rejects_old_answer(self):
        self.provider.record_dispatched_message('task')
        before = self.file.stat()
        # Keep valid JSONL and the old byte offset, but change pre-send content.
        old = self.file.read_text()
        self.file.write_text(old.replace('Old answer', 'Bad answer'))
        self.append(base.message('task', role='user') + base.message('Wrong old answer'))
        self.assertEqual(self.file.stat().st_ino, before.st_ino)
        self.assertGreater(self.file.stat().st_size, before.st_size)
        self.assertIn('Screen fallback', self.output())

    def test_long_boundary_checks_its_tail_and_accepts_append(self):
        self.append(base.message('padding ' * 1024))
        self.provider.record_dispatched_message('task')
        self.append(base.message('task', role='user') + base.message('Current answer'))
        self.assertEqual(self.output(), 'Current answer')
        data = self.file.read_text()
        self.file.write_text(data.replace('padding ', 'changed '))
        self.assertIn('Screen fallback', self.output())

    def test_slow_herdr_or_tmux_discovery_does_not_block_dispatch(self):
        from cli_agent_orchestrator.backends.tmux_backend import TmuxBackend
        from cli_agent_orchestrator.clients.tmux import TmuxClient

        herdr = base.HerdrBackend.__new__(base.HerdrBackend)
        herdr._herdr_session = 'test-session'
        herdr._workspace_cache = {}
        backends = (herdr, TmuxBackend(client=TmuxClient()))
        self.pid_patch.stop()
        real_popen = subprocess.Popen
        for backend in backends:
            with self.subTest(backend=type(backend).__name__):
                # Sleep in a real subprocess: a missing timeout actually stalls.
                children = []
                def slow_cli(cmd, **kwargs):
                    child = real_popen([base.sys.executable, '-c', 'import time; time.sleep(3)'],
                                       **kwargs)
                    children.append(child)
                    return child
                with patch.object(base.codex, 'get_backend', return_value=backend), \
                     patch.object(subprocess, 'Popen', side_effect=slow_cli):
                    start = time.monotonic()
                    self.provider.record_dispatched_message('task')
                    elapsed = time.monotonic() - start
                self.assertTrue(children, 'exercise the real CLI process boundary')
                self.assertTrue(all(child.poll() is not None for child in children))
                self.assertLess(elapsed, 2.8, 'optional discovery must not delay sending')
                self.assertIsNone(self.provider._rollout_dispatch_boundary)
                with patch.object(self.provider, '_rollout_shell_pid', return_value=10):
                    self.append(base.message('task', role='user') + base.message('Late answer'))
                    self.assertIn('Screen fallback', self.output())

    def test_herdr_resolution_shares_one_deadline_and_preserves_backend(self):
        backend = base.HerdrBackend.__new__(base.HerdrBackend)
        backend._herdr_session = 'test-session'
        backend._workspace_cache = {}
        clock = [100.0]
        remaining = []
        def run(cmd, **kwargs):
            remaining.append(kwargs['timeout'])
            clock[0] += 0.8
            data = {
                'workspace': {'workspaces': [{'workspace_id': 'w1', 'label': 'session'}]},
                'tab': {'tabs': [{'workspace_id': 'w1', 'tab_id': 't1', 'label': 'window'}]},
                'pane': {'panes': [{'workspace_id': 'w1', 'tab_id': 't1',
                                    'pane_id': 'p1', 'label': 'window'}]},
            }[cmd[3]]
            return subprocess.CompletedProcess(cmd, 0, base.json.dumps({'result': data}), '')
        self.pid_patch.stop()
        with patch.object(base.codex, 'get_backend', return_value=backend), \
             patch.object(subprocess, 'run', side_effect=run), \
             patch.object(base.codex.time, 'monotonic', side_effect=lambda: clock[0]):
            self.provider.record_dispatched_message('task')
        self.assertEqual(len(remaining), 3)
        for actual, expected in zip(remaining, (2.0, 1.2, 0.4)):
            self.assertAlmostEqual(actual, expected)
        self.assertIsNone(self.provider._rollout_dispatch_boundary)
        self.assertNotIn('_run_herdr', backend.__dict__)

    def test_tmux_own_marks_select_one_pane_and_reject_duplicates(self):
        from cli_agent_orchestrator.backends.tmux_backend import TmuxBackend
        from cli_agent_orchestrator.clients.tmux import TmuxClient
        backend = TmuxBackend(client=TmuxClient())
        backend._client.server.socket_name = 'test-socket'
        self.pid_patch.stop()
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                def run(cmd, **kwargs):
                    self.assertEqual(cmd[:3], ['tmux', '-L', 'test-socket'])
                    self.assertGreater(kwargs['timeout'], 0)
                    self.assertLessEqual(kwargs['timeout'], 2)
                    if cmd[3] == 'list-panes':
                        self.assertEqual(cmd[4:7], ['-s', '-t', '=session'])
                        output = 'host\t%1\t1\t99\nhost\t%2\t0\t10\n'
                    else:
                        self.assertEqual(cmd[3:6], ['show-options', '-p', '-t'])
                        output = '@cao_terminal window\n' if duplicate or cmd[6] == '%2' else ''
                    return subprocess.CompletedProcess(cmd, 0, output, '')
                with patch.object(base.codex, 'get_backend', return_value=backend), \
                     patch.object(subprocess, 'run', side_effect=run):
                    self.assertEqual(self.provider._rollout_shell_pid(), None if duplicate else 10)


if __name__ == '__main__':
    unittest.main(verbosity=2)
