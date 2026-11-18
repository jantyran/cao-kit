"""Exercise the patch against an isolated copy of the original CAO package."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
import importlib.util
ORIGINAL = Path(importlib.util.find_spec('cli_agent_orchestrator').origin).parent
(ROOT / '.cao/tmp').mkdir(parents=True, exist_ok=True)
TMP = tempfile.TemporaryDirectory(dir=ROOT / '.cao/tmp')
os.environ['CAO_HOME_DIR'] = TMP.name
shutil.copytree(ORIGINAL, Path(TMP.name) / 'cli_agent_orchestrator')
pkg = Path(TMP.name) / 'cli_agent_orchestrator'
for applied_patch in reversed(sorted((ROOT / 'patches').glob('cao-2.5.4-*.patch'))):
    command = ['patch', '--batch', '--silent', '-F0', '-p1', '-R', '--forward', '-i', str(applied_patch)]
    if subprocess.run(command + ['--dry-run'], cwd=pkg, capture_output=True).returncode == 0:
        subprocess.run(command, cwd=pkg, check=True)
    else:
        subprocess.run(['patch', '--batch', '--silent', '-F0', '-p1', '--forward', '--dry-run', '-i', str(applied_patch)], cwd=pkg, check=True, capture_output=True)
patchfile = ROOT / 'patches/cao-2.5.4-herdr-codex-status.patch'
if patchfile.exists():
    subprocess.run(['patch', '--batch', '--silent', '-F0', '-p1', '-i', str(patchfile)], cwd=Path(TMP.name) / 'cli_agent_orchestrator', check=True)
sys.path.insert(0, TMP.name)
from cli_agent_orchestrator.providers.codex import CodexProvider
from cli_agent_orchestrator.models.terminal import TerminalStatus as S


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.provider = CodexProvider('id', 'session', 'window')
        self.clock = patch('cli_agent_orchestrator.providers.codex.time.monotonic', return_value=1000).start()
        self.addCleanup(patch.stopall)
        self.native = patch.object(self.provider, '_resolve_native_status', return_value=S.PROCESSING).start()
        self.screen = patch.object(self.provider, '_resolve_buffer', return_value='›').start()

    def at(self, seconds):
        self.clock.return_value = 1000 + seconds
        return self.provider.get_status('')

    def test_idle_and_dispatched_completion(self):
        self.assertEqual(self.at(0), S.PROCESSING)
        self.assertEqual(self.at(300), S.IDLE)
        self.provider.mark_input_received()
        self.assertEqual(self.at(301), S.PROCESSING)
        self.assertEqual(self.at(601), S.COMPLETED)

    def test_throttle_and_unresolved_frames(self):
        self.assertEqual(self.at(0), S.PROCESSING)
        self.assertEqual(self.at(299), S.PROCESSING)
        self.screen.assert_not_called()
        self.screen.return_value = ''
        self.assertEqual(self.at(300), S.PROCESSING)
        self.assertEqual(self.at(329), S.PROCESSING)
        self.assertEqual(self.screen.call_count, 1)
        self.screen.return_value = 'Working (esc to interrupt)'
        self.assertEqual(self.at(330), S.PROCESSING)
        self.assertEqual(self.screen.call_count, 2)
        self.screen.return_value = '›'
        self.assertEqual(self.at(360), S.IDLE)
        self.assertEqual(self.at(361), S.IDLE)
        self.assertEqual(self.screen.call_count, 3)

    def test_reconnected_active_frames_stay_processing(self):
        frames = [
            '› do work\n• Working (10s • esc to interrupt)\n›\n? for shortcuts',
            '› do work\n• Answer still streaming\n›\n? for shortcuts',
            '› do work\n• Called shell.exec()\n  output\n›\n? for shortcuts',
        ]
        for frame in frames:
            with self.subTest(frame=frame):
                self.provider = CodexProvider('id', 'session', 'window')
                with patch.object(self.provider, '_resolve_native_status', return_value=S.PROCESSING), patch.object(self.provider, '_resolve_buffer', return_value=frame):
                    self.assertEqual(self.at(0), S.PROCESSING)
                    self.assertEqual(self.at(300), S.PROCESSING)

    def test_reconnected_banner_restores_footer_mode(self):
        self.screen.return_value = 'OpenAI Codex (v0.160.0)\n› do work\n• Answer still streaming\n›\n? for shortcuts'
        self.at(0)
        self.assertEqual(self.at(300), S.PROCESSING)
        self.assertTrue(self.provider._ends_turns_with_footer)
        self.assertEqual(self.provider._codex_version, (0, 160, 0))
        self.screen.return_value = 'OpenAI Codex (v0.160.0)\n› do work\n• Finished\nWorked for 3s • 12:34\n›\n? for shortcuts'
        self.assertEqual(self.at(330), S.IDLE)

    def test_native_change_restarts_window(self):
        self.at(0)
        self.native.return_value = S.IDLE
        self.assertEqual(self.at(299), S.IDLE)
        self.native.return_value = S.PROCESSING
        self.assertEqual(self.at(300), S.PROCESSING)
        self.assertEqual(self.at(599), S.PROCESSING)
        self.screen.assert_not_called()
        self.assertEqual(self.at(600), S.IDLE)

    def test_reconnected_finished_frame_with_trailing_blank_lines(self):
        self.screen.return_value = 'OpenAI Codex (v0.160.0)\n› do work\n• Finished\nWorked for 3s • 12:34\n›\n? for shortcuts' + '\n' * 8
        self.at(0)
        self.assertEqual(self.at(300), S.IDLE)

    def test_reconnected_footer_is_retried_after_version_is_known(self):
        self.screen.return_value = 'OpenAI Codex (v0.160.0)\n› do work\n• Answer still streaming\n›' + '\n' * 8
        self.at(0)
        self.assertEqual(self.at(300), S.PROCESSING)
        self.screen.return_value = 'OpenAI Codex (v0.160.0)\n› do work\n• Finished\nWorked for 3s • 12:34\n›\n? for shortcuts'
        self.assertEqual(self.at(330), S.IDLE)


if __name__ == '__main__':
    unittest.main(verbosity=2)
