"""A Codex error cell (usage limit) must end the turn as ERROR, not COMPLETED."""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = Path(importlib.util.find_spec('cli_agent_orchestrator').origin).parent
(ROOT / '.cao/tmp').mkdir(parents=True, exist_ok=True)
TMP = tempfile.TemporaryDirectory(dir=ROOT / '.cao/tmp')
os.environ['CAO_HOME_DIR'] = TMP.name
pkg = Path(TMP.name) / 'cli_agent_orchestrator'
shutil.copytree(ORIGINAL, pkg)
patches = sorted((ROOT / 'patches').glob('cao-2.5.4-*.patch'))
run = ['patch', '--batch', '--silent', '--no-backup-if-mismatch', '-F0', '-p1', '--forward']
for p in reversed(patches):  # back to the unpatched package, whatever is installed
    if subprocess.run(run + ['-R', '--dry-run', '-i', str(p)], cwd=pkg, capture_output=True).returncode == 0:
        subprocess.run(run + ['-R', '-i', str(p)], cwd=pkg, check=True)
for p in patches:
    subprocess.run(run + ['-i', str(p)], cwd=pkg, check=True)
sys.path.insert(0, TMP.name)
from cli_agent_orchestrator.providers.codex import CodexProvider
from cli_agent_orchestrator.models.terminal import TerminalStatus as S

STATUS_BAR = 'GPT-6-Luna low · ~/work · Approve for me'
LIMIT = (
    '■ You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro),\n'
    '  visit https://chatgpt.com/settings/usage to purchase more credits or try again at\n'
    '  4:19 PM.'
)
WRAPPED = (
    '■ You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro),\n'
    'visit https://chatgpt.com/settings/usage to purchase more credits or try again at\n'
    '4:19 PM.'
)
USER = '› [CAO Handoff] do the task'
SCREENS = {
    'limit': f'{USER}\n\n{LIMIT}\n\n› Ask Codex\n{STATUS_BAR}',
    'limit_no_hint': f'{USER}\n\n{LIMIT}\n\n›\n{STATUS_BAR}',
    'done': f'{USER}\n\n• All done.\n\n─ Worked for 3s ─\n\n› Ask Codex\n{STATUS_BAR}',
    'past_error_then_done': f'› old task\n\n{LIMIT}\n\n{USER}\n\n• All done.\n\n─ Worked for 3s ─\n\n›\n{STATUS_BAR}',
    'quoted_in_reply': f'{USER}\n\n• The error looked like:\n■ boom\n  more\n\n─ Worked for 3s ─\n\n›\n{STATUS_BAR}',
    'working': f'{USER}\n\n• Working (3s • esc to interrupt)\n\n› Ask Codex\n{STATUS_BAR}',
}


class ErrorCellTest(unittest.TestCase):
    def provider(self, screen, native):
        p = CodexProvider('id', 'session', 'window')
        p._initialized = True
        p._task_dispatched = True
        for target, value in (('_resolve_native_status', native), ('_resolve_buffer', screen)):
            patcher = patch.object(p, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return p

    def test_usage_limit_is_error(self):
        for name in ('limit', 'limit_no_hint'):
            for native in (S.COMPLETED, None):  # herdr "done" / buffer parsing
                with self.subTest(screen=name, native=native):
                    self.assertEqual(self.provider(SCREENS[name], native).get_status(''), S.ERROR)

    def test_other_screens_are_not_error(self):
        for name in ('done', 'past_error_then_done', 'quoted_in_reply'):
            with self.subTest(screen=name):
                self.assertEqual(self.provider(SCREENS[name], S.COMPLETED).get_status(''), S.COMPLETED)
        self.assertNotEqual(self.provider(SCREENS['working'], None).get_status(''), S.ERROR)

    def test_handoff_error_carries_the_error_cell(self):
        from cli_agent_orchestrator.services import agent_step
        with patch.object(agent_step.terminal_service, 'get_output_context', return_value=SCREENS['limit']):
            detail = agent_step._error_cell_text('t')
        self.assertIn('usage limit', detail)
        self.assertIn('4:19 PM.', detail)
        self.assertNotIn('Ask Codex', detail)

    def test_wrapped_cell_is_whole_and_this_turn_only(self):
        from cli_agent_orchestrator.services import agent_step
        def detail(screen):
            with patch.object(agent_step.terminal_service, 'get_output_context', return_value=screen):
                return agent_step._error_cell_text('t')
        d = detail(f'{USER}\n\n{WRAPPED}\n\n› Ask Codex\n{STATUS_BAR}')
        self.assertIn('4:19 PM.', d)
        self.assertNotIn('Ask Codex', d)
        self.assertEqual(detail(SCREENS['past_error_then_done']), '')
        self.assertLessEqual(len(detail(f'{USER}\n\n■ ' + 'x' * 900)), 502)

    def test_no_screen_keeps_plain_message(self):
        from cli_agent_orchestrator.services import agent_step
        with patch.object(agent_step.terminal_service, 'get_output_context', return_value=None):
            self.assertEqual(agent_step._error_cell_text('t'), '')

    def test_screen_read_once_per_turn(self):
        p = self.provider(SCREENS['done'], S.COMPLETED)
        for _ in range(3):
            self.assertEqual(p.get_status(''), S.COMPLETED)
        self.assertEqual(p._resolve_buffer.call_count, 1)
        p.mark_input_received()  # next turn is read again
        p.get_status('')
        self.assertEqual(p._resolve_buffer.call_count, 2)

    def test_error_stays_error_for_the_turn(self):
        p = self.provider(SCREENS['limit'], S.COMPLETED)
        for _ in range(3):
            self.assertEqual(p.get_status(''), S.ERROR)
        self.assertEqual(p._resolve_buffer.call_count, 1)
        p.mark_input_received()
        p.get_status('')
        self.assertEqual(p._resolve_buffer.call_count, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
