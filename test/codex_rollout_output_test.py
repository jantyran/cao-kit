"""Rollout extraction runs only against an isolated CAO package and fake /proc."""
import functools
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = Path(importlib.util.find_spec('cli_agent_orchestrator').origin).parent
(ROOT / '.cao/tmp').mkdir(parents=True, exist_ok=True)
TMP = tempfile.TemporaryDirectory(dir=ROOT / '.cao/tmp')
os.environ['CAO_HOME_DIR'] = TMP.name
PKG = Path(TMP.name) / 'cli_agent_orchestrator'
shutil.copytree(ORIGINAL, PKG)
PATCHES = sorted((ROOT / 'patches').glob('cao-2.5.4-*.patch'))
for file in reversed(PATCHES):
    cmd = ['patch', '--batch', '--silent', '-F0', '-p1', '-R', '--forward', '-i', str(file)]
    if subprocess.run(cmd + ['--dry-run'], cwd=PKG, capture_output=True).returncode == 0:
        subprocess.run(cmd, cwd=PKG, check=True)
    else:
        subprocess.run(['patch', '--batch', '--silent', '-F0', '-p1', '--forward', '--dry-run', '-i', str(file)], cwd=PKG, check=True, capture_output=True)
for file in PATCHES:
    subprocess.run(['patch', '--batch', '--silent', '-F0', '-p1', '-i', str(file)], cwd=PKG, check=True)
sys.path.insert(0, TMP.name)
from cli_agent_orchestrator.providers import codex
from cli_agent_orchestrator.backends.herdr_backend import HerdrBackend

SCREEN = '› task\n• Screen fallback\n›\nGPT-6.1 Sol medium · ~/project · main · Workspace · Approve f…'


def message(text, second=2, role='assistant', phase='final_answer'):
    return json.dumps({'timestamp': f'2026-11-18T00:00:{second:02d}Z', 'type': 'response_item',
                       'payload': {'type': 'message', 'role': role, 'phase': phase,
                                   'content': [{'type': 'output_text' if role == 'assistant' else 'input_text', 'text': text}]}}) + '\n'


def session_meta(thread='main', session='main', **extra):
    return json.dumps({'type': 'session_meta', 'payload': {
        'id': thread, 'session_id': session, **extra}}) + '\n'


def write_rollout(path, data):
    path.write_text(session_meta() + data)


class RolloutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / '.cao/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.proc = self.root / 'proc'
        self.sessions = self.root / 'sessions'
        self.sessions.mkdir()
        self.file = self.sessions / '2026/11/18/rollout-worker.jsonl'
        self.file.parent.mkdir(parents=True)
        write_rollout(self.file, '')
        self.process(10, [11], 'bash')
        self.process(11, [], 'codex')
        self.link(11, self.file)
        self.provider = codex.CodexProvider('id', 'session', 'window')
        self.provider._last_dispatch_time = 1794960001.0  # 2026-11-18T00:00:01Z
        self.pid_patch = patch.object(self.provider, '_rollout_shell_pid', return_value=10, create=True)
        self.pid_patch.start()
        self.addCleanup(patch.stopall)
        if hasattr(codex, '_codex_rollout_paths'):
            patch.object(codex, '_codex_rollout_paths', functools.partial(codex._codex_rollout_paths, proc_root=self.proc, sessions_root=self.sessions)).start()
        self.provider.record_dispatched_message('task')
        self.append(message('Old answer', 0) + message('task', role='user') + message('Rollout answer'))

    def process(self, pid, children, name):
        path = self.proc / str(pid)
        (path / 'task' / str(pid)).mkdir(parents=True)
        (path / 'task' / str(pid) / 'children').write_text(' '.join(map(str, children)))
        (path / 'fd').mkdir()
        (path / 'exe').symlink_to('/usr/bin/' + name)

    def link(self, pid, target, fd='7'):
        (self.proc / str(pid) / 'fd' / fd).symlink_to(target)

    def dispatch(self, text):
        write_rollout(self.file, '')
        self.provider.record_dispatched_message(text)

    def append(self, data):
        with self.file.open('a') as stream:
            stream.write(data)

    def output(self):
        return self.provider.extract_last_message_from_script(SCREEN)

    def test_prefers_last_final_answer_and_concatenates_text(self):
        row = json.loads(message('last', 4))
        row['payload']['content'] = [{'type': 'output_text', 'text': 'Last\n'}, {'type': 'output_text', 'text': 'answer'}]
        write_rollout(self.file, message('Old answer', 0) + message('task', role='user') + message('First answer') + message('progress', 3, phase='commentary') + json.dumps(row) + '\n' + message('late progress', 5, phase='commentary'))
        self.assertEqual(self.output(), 'Last\nanswer')

    def test_delayed_old_answer_without_matching_user_falls_back(self):
        self.dispatch('current task')
        write_rollout(self.file, message('previous task', 0, role='user') + message('Delayed previous answer', 9))
        self.assertIn('Screen fallback', self.output())

    def test_clock_rollback_cannot_return_old_answer(self):
        self.dispatch('current task')
        self.provider._last_dispatch_time = 1
        write_rollout(self.file, message('previous task', 0, role='user') + message('Old answer', 2))
        self.assertIn('Screen fallback', self.output())

    def test_unknown_dispatch_text_falls_back(self):
        self.provider.mark_input_received()
        write_rollout(self.file, message('task', role='user') + message('Unattributed answer'))
        self.assertIn('Screen fallback', self.output())

    def test_matching_user_returns_answer_regardless_of_clock(self):
        self.dispatch('current task')
        self.provider._last_dispatch_time = 9999999999
        write_rollout(self.file, message('Old answer', 9) + message('current task', 0, role='user') + message('Current answer', 0))
        self.assertEqual(self.output(), 'Current answer')

    def test_last_matching_user_discards_earlier_answer(self):
        self.dispatch('current task')
        write_rollout(self.file, message('current task', role='user') + message('Previous answer') + message('current task', role='user'))
        self.assertIn('Screen fallback', self.output())

    def test_different_later_user_cannot_claim_its_answer(self):
        self.dispatch('current task')
        write_rollout(self.file, message('current task', role='user') + message('Current answer') + message('different task', role='user') + message('Wrong answer'))
        self.assertIn('Screen fallback', self.output())

    def test_normalized_complete_text_matches_with_assignment_suffix(self):
        self.dispatch('Review  this\nchange')
        row = json.loads(message('', role='user'))
        row['payload']['content'] = [
            {'type': 'input_text', 'text': 'Review this\n'},
            {'type': 'input_text', 'text': 'change\n\n[Assigned by terminal worker]'}]
        write_rollout(self.file, json.dumps(row) + '\n' + message('Current answer'))
        self.assertEqual(self.output(), 'Current answer')

    def test_shared_long_prefix_does_not_match_different_request(self):
        prefix = 'same instructions ' * 20
        self.dispatch(prefix + 'task A')
        write_rollout(self.file, message(prefix + 'task B', role='user') + message('Wrong answer'))
        self.assertIn('Screen fallback', self.output())

    def test_dispatch_recording_does_not_require_footer_or_screen(self):
        for footer in (False, True):
            with self.subTest(footer=footer):
                self.provider._ends_turns_with_footer = footer
                with patch.object(codex, 'get_backend', side_effect=RuntimeError('no screen')):
                    self.dispatch('current task')
                self.provider._ends_turns_with_footer = False
                write_rollout(self.file, message('current task', role='user') + message('Current answer'))
                self.assertEqual(self.output(), 'Current answer')

    def test_empty_dispatch_text_falls_back(self):
        for text in ('', ' \n '):
            with self.subTest(text=text):
                self.dispatch(text)
                self.assertIn('Screen fallback', self.output())

    def test_last_matching_user_selects_only_its_final_answer(self):
        write_rollout(self.file, message('task', role='user') + message('Previous answer') +
                      message('task', role='user') + message('Current answer'))
        self.assertEqual(self.output(), 'Current answer')

    def test_new_dispatch_during_read_invalidates_answer_even_with_same_text(self):
        paths = codex._codex_rollout_paths
        def scan(pid):
            self.provider.mark_input_received()
            with patch.object(codex, '_codex_rollout_paths', paths):
                self.dispatch('task')
            return paths(pid)
        with patch.object(codex, '_codex_rollout_paths', side_effect=scan):
            self.assertIn('Screen fallback', self.output())

    def test_dispatch_invalidation_does_not_reuse_previous_text(self):
        for reset in (self.provider.mark_input_received,
                      self.provider.mark_redelivery_received,
                      lambda: self.provider.notify_status_buffer_reset(7),
                      self.provider.cleanup):
            with self.subTest(reset=reset):
                self.dispatch('task')
                self.append(message('task', role='user') + message('Rollout answer'))
                self.assertEqual(self.output(), 'Rollout answer')
                reset()
                self.assertIn('Screen fallback', self.output())

    def test_matching_user_outside_read_tail_falls_back(self):
        self.file.write_bytes(session_meta().encode() + message('task', role='user').encode() +
                              b'x' * (5 * 1024 * 1024) + b'\n' + message('Unattributed answer').encode())
        self.assertIn('Screen fallback', self.output())

    def test_duplicate_fds_are_one_candidate(self):
        self.link(11, self.file, '8')
        self.assertEqual(self.output(), 'Rollout answer')

    def test_ambiguous_candidates_fall_back(self):
        other = self.file.with_name('rollout-other.jsonl')
        write_rollout(other, message('Wrong answer'))
        self.link(11, other, '8')
        self.assertIn('Screen fallback', self.output())

    def test_main_and_approval_child_returns_main_answer(self):
        child = self.file.with_name('rollout-approval.jsonl')
        child.write_text(session_meta('child', parent_thread_id='main') +
                         message('{"risk_level":"low","outcome":"allow"}'))
        self.link(11, child, '8')
        self.assertEqual(self.output(), 'Rollout answer')

    def test_child_identifiers_each_exclude_approval_rollout(self):
        for metadata in (session_meta(parent_thread_id='main'), session_meta('child')):
            with self.subTest(metadata=metadata):
                self.file.write_text(metadata + message('{"outcome":"allow"}'))
                self.assertIn('Screen fallback', self.output())

    def test_invalid_session_metadata_falls_back(self):
        for metadata in ('broken\n', '{}\n', '[]\n',
                         '{"type":"session_meta","payload":null}\n',
                         '{"type":"session_meta","payload":{}}\n'):
            with self.subTest(metadata=metadata):
                self.file.write_text(metadata + message('Unattributed answer'))
                self.assertIn('Screen fallback', self.output())

    def test_missing_unreadable_or_corrupt_file_falls_back(self):
        for data in (None, 'broken\n', 'null\n[]\n{"payload":null}\n'):
            with self.subTest(data=data):
                if data is None:
                    self.file.unlink(missing_ok=True)
                else:
                    write_rollout(self.file, data)
                self.assertIn('Screen fallback', self.output())
        write_rollout(self.file, message('answer'))
        with patch.object(Path, 'open', side_effect=PermissionError):
            self.assertIn('Screen fallback', self.output())

    def test_stale_unknown_dispatch_and_commentary_fall_back(self):
        for data in (message('Old answer', 0), message('Equal timestamp', 1), message('progress', phase='commentary')):
            write_rollout(self.file, data)
            self.assertIn('Screen fallback', self.output())
        write_rollout(self.file, message('answer'))
        self.provider._last_dispatch_time = 0
        self.assertIn('Screen fallback', self.output())

    def test_corrupt_lines_are_skipped(self):
        write_rollout(self.file, 'broken\nnull\n[]\n' + message('task', role='user') + message('Rollout answer') + '{partial')
        self.assertEqual(self.output(), 'Rollout answer')

    def test_only_codex_descendants_and_session_paths_are_used(self):
        outside = self.root / 'rollout-unrelated.jsonl'
        outside.write_text(message('Wrong answer'))
        self.link(11, outside, '8')
        self.process(99, [], 'codex')
        self.link(99, self.file.with_name('rollout-unrelated.jsonl'))
        self.process(12, [], 'bash')
        (self.proc / '10/task/10/children').write_text('11 12')
        self.link(12, outside)
        self.assertEqual(self.output(), 'Rollout answer')

    def test_tail_read_is_bounded_and_ignores_cut_first_line(self):
        self.file.write_bytes(session_meta().encode() + b'x' * (5 * 1024 * 1024) + b'\n')
        self.provider.record_dispatched_message('task')
        self.append(message('task', role='user') + message('Rollout answer'))
        original_open = Path.open
        sizes = []
        class Reader:
            def __enter__(inner):
                inner.stream = original_open(self.file, 'rb')
                return inner
            def __exit__(inner, *args):
                inner.stream.close()
            def fileno(inner):
                return inner.stream.fileno()
            def seek(inner, *args):
                return inner.stream.seek(*args)
            def readline(inner, size=-1):
                sizes.append(size)
                return inner.stream.readline(size)
            def tell(inner):
                return inner.stream.tell()
            def read(inner, size=-1):
                sizes.append(size)
                return inner.stream.read(size)
        def open_file(path, *args, **kwargs):
            return Reader() if path == self.file else original_open(path, *args, **kwargs)
        with patch.object(Path, 'open', open_file):
            self.assertEqual(self.output(), 'Rollout answer')
        self.assertTrue(sizes)
        self.assertTrue(all(0 < size <= 4 * 1024 * 1024 for size in sizes), sizes)

    def test_new_user_turn_cannot_return_previous_answer(self):
        write_rollout(self.file, message('previous answer') + message('new task', 3, role='user') + message('working', 4, phase='commentary'))
        self.assertIn('Screen fallback', self.output())

    def test_unreadable_process_scan_falls_back(self):
        (self.proc / '11/task/11/children').unlink()
        self.assertIn('Screen fallback', self.output())

    def test_resend_without_new_user_never_reuses_old_answer(self):
        for clock in (1, 9999999999):
            with self.subTest(clock=clock):
                self.provider.record_dispatched_message('task')
                self.provider._last_dispatch_time = clock
                self.append(message('Delayed previous answer', 9))
                self.assertIn('Screen fallback', self.output())

    def test_resend_returns_only_answer_after_boundary(self):
        self.provider.record_dispatched_message('task')
        self.append(message('Delayed previous answer', 9))
        self.assertIn('Screen fallback', self.output())
        self.append(message('task', 0, role='user') + message('Current answer', 0))
        self.assertEqual(self.output(), 'Current answer')

    def test_missing_boundary_does_not_recover_at_read_time(self):
        for pid in (None, 10):
            with self.subTest(pid=pid):
                if pid == 10:
                    self.file.unlink(missing_ok=True)
                with patch.object(self.provider, '_rollout_shell_pid', return_value=pid):
                    self.provider.record_dispatched_message('task')
                write_rollout(self.file, message('task', role='user') + message('Unattributed answer'))
                self.assertIn('Screen fallback', self.output())

    def test_ambiguous_boundary_does_not_recover_at_read_time(self):
        other = self.file.with_name('rollout-other.jsonl')
        write_rollout(other, '')
        self.link(11, other, '8')
        self.provider.record_dispatched_message('task')
        (self.proc / '11/fd/8').unlink()
        self.append(message('task', role='user') + message('Unattributed answer'))
        self.assertIn('Screen fallback', self.output())

    def test_replaced_inode_falls_back_even_with_matching_new_records(self):
        self.provider.record_dispatched_message('task')
        old_inode = self.file.stat().st_ino
        self.file.rename(self.file.with_suffix('.old'))
        write_rollout(self.file, message('task', role='user') + message('Old answer') +
                      message('task', role='user') + message('Wrong answer'))
        self.assertNotEqual(self.file.stat().st_ino, old_inode)
        self.assertIn('Screen fallback', self.output())

    def test_truncated_file_falls_back(self):
        self.append('x' * 1024 + '\n')
        self.provider.record_dispatched_message('task')
        write_rollout(self.file, message('task', role='user') + message('Wrong answer'))
        self.assertIn('Screen fallback', self.output())

    def test_boundary_outside_tail_falls_back_even_with_recent_match(self):
        self.append('x' * (4 * 1024 * 1024) + '\n' +
                    message('task', role='user') + message('Wrong answer'))
        self.assertIn('Screen fallback', self.output())

    def test_partial_user_before_boundary_cannot_be_completed_into_match(self):
        write_rollout(self.file, message('task', role='user').rstrip()[:-2])
        self.provider.record_dispatched_message('task')
        self.append('}}\n' + message('Wrong answer'))
        self.assertIn('Screen fallback', self.output())

    def test_partial_final_record_waits_for_newline(self):
        self.append(message('Incomplete final').rstrip())
        self.assertEqual(self.output(), 'Rollout answer')
        self.append('\n')
        self.assertEqual(self.output(), 'Incomplete final')

    def test_tmux_shell_pid_uses_terminal_pane(self):
        from cli_agent_orchestrator.backends.tmux_backend import TmuxBackend
        from cli_agent_orchestrator.clients.tmux import TmuxClient
        backend = TmuxBackend(client=TmuxClient())
        result = subprocess.CompletedProcess([], 0,
            'other\t%1\t1\t99\nwindow\t%2\t0\t98\nwindow\t%3\t1\t10\n', '')
        def run(cmd, **kwargs):
            self.assertEqual(cmd[:6], ['tmux', 'list-panes', '-s', '-t', '=session', '-F'])
            self.assertGreater(kwargs['timeout'], 0)
            self.assertLessEqual(kwargs['timeout'], 2)
            return result
        with patch.object(codex, 'get_backend', return_value=backend), patch.object(subprocess, 'run', side_effect=run):
            self.pid_patch.stop()
            self.assertEqual(self.provider._rollout_shell_pid(), 10)

    def test_get_output_last_prefers_rollout_then_preserves_screen_fallback(self):
        from cli_agent_orchestrator.services import terminal_service as service
        backend = SimpleNamespace(get_history=lambda *args, **kwargs: SCREEN)
        with patch.object(service, 'get_terminal_metadata', return_value={'tmux_session': 'session', 'tmux_window': 'window'}), patch.object(service.status_monitor, 'get_buffer', return_value=SCREEN), patch.object(service.provider_manager, 'get_provider', return_value=self.provider), patch.object(service, 'get_backend', return_value=backend):
            self.assertEqual(service.get_output('id', service.OutputMode.LAST), 'Rollout answer')
            self.file.unlink()
            self.assertIn('Screen fallback', service.get_output('id', service.OutputMode.LAST))

    def test_herdr_shell_pid_uses_process_info_envelope(self):
        backend = HerdrBackend.__new__(HerdrBackend)
        backend._herdr_session = 'test-session'
        result = subprocess.CompletedProcess([], 0, json.dumps({'result': {'process_info': {'shell_pid': 10}}}), '')
        with patch.object(codex, 'get_backend', return_value=backend), patch.object(backend, '_resolve_pane_id_from_window', return_value='w1:p1'), patch.object(subprocess, 'run', return_value=result):
            self.pid_patch.stop()
            self.assertEqual(self.provider._rollout_shell_pid(), 10)


class LifecycleTest(unittest.TestCase):
    def test_all_patches_check_apply_and_reverse_without_changing_originals(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.cao/tmp') as directory:
            root = Path(directory)
            pkg = root / 'pkg'
            shutil.copytree(PKG / 'providers', pkg / 'providers')
            shutil.copytree(PKG / 'backends', pkg / 'backends')
            (pkg / 'services').mkdir()
            shutil.copy2(PKG / 'services/agent_step.py', pkg / 'services/agent_step.py')
            for file in reversed(PATCHES):
                command = ['patch', '--batch', '--silent', '-F0', '-p1', '-R', '-i', str(file)]
                if subprocess.run(command + ['--dry-run'], cwd=pkg, capture_output=True).returncode == 0:  # not applied yet on a fresh install
                    subprocess.run(command, cwd=pkg, check=True)
            baseline = {path.relative_to(pkg): path.read_bytes() for path in pkg.rglob('*.py')}
            fakebin = root / 'bin'
            fakebin.mkdir()
            (fakebin / 'cao').write_text('#!/bin/sh\nexit 0\n')
            (fakebin / 'cao').chmod(0o755)
            (fakebin / 'python').write_text(f'#!{sys.executable}\nprint({json.dumps([str(pkg), "2.5.4"])!r})\n')
            (fakebin / 'python').chmod(0o755)
            def check():
                return subprocess.run([sys.executable, str(ROOT / 'bin/cao-patch'), '--check'], env={**os.environ, 'PATH': f'{fakebin}:/usr/bin:/bin'}, capture_output=True, text=True)
            self.assertEqual(check().returncode, 1)
            for file in PATCHES:
                subprocess.run(['patch', '--batch', '--silent', '-F0', '-p1', '-i', str(file)], cwd=pkg, check=True)
            result = check()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('適用済み: cao-2.5.4-codex-rollout-output', result.stdout)
            for file in reversed(PATCHES):
                subprocess.run(['patch', '--batch', '--silent', '-F0', '-p1', '-R', '-i', str(file)], cwd=pkg, check=True)
            self.assertEqual({path.relative_to(pkg): path.read_bytes() for path in pkg.rglob('*.py')}, baseline)


if __name__ == '__main__':
    unittest.main(verbosity=2)
