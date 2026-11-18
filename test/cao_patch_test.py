"""Patch lifecycle tests use a temporary CAO installation, never the real one."""
import importlib.machinery
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]


class PatchTest(unittest.TestCase):
    def setUp(self):
        (REPO / '.cao/tmp').mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=REPO / '.cao/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pkg = self.root / 'pkg'
        self.pkg.mkdir()
        original = Path(importlib.util.find_spec('cli_agent_orchestrator').origin).parent
        shutil.copytree(original / 'backends', self.pkg / 'backends')
        shutil.copytree(original / 'providers', self.pkg / 'providers')
        (self.pkg / 'services').mkdir()
        shutil.copy2(original / 'services/agent_step.py', self.pkg / 'services/agent_step.py')
        for applied_patch in reversed(sorted((REPO / 'patches').glob('cao-2.5.4-*.patch'))):
            command = ['patch', '--batch', '--silent', '--no-backup-if-mismatch', '-F0', '-p1', '-R', '--forward', '-i', str(applied_patch)]
            if subprocess.run(command + ['--dry-run'], cwd=self.pkg, capture_output=True).returncode == 0:
                subprocess.run(command, cwd=self.pkg, check=True)
            else:
                subprocess.run(['patch', '--batch', '--silent', '-F0', '-p1', '--forward', '--dry-run', '-i', str(applied_patch)], cwd=self.pkg, check=True, capture_output=True)
        # Execute a verbatim temporary copy, never the repository CLI without args.
        tool_root = self.root / 'tool'
        (tool_root / 'bin').mkdir(parents=True)
        self.patch_cli = tool_root / 'bin/cao-patch'
        shutil.copy2(REPO / 'bin/cao-patch', self.patch_cli)
        shutil.copytree(REPO / 'patches', tool_root / 'patches')
        self.patchfile = REPO / 'patches/cao-2.5.4-herdr-pane-spawn.patch'
        self.statusfile = REPO / 'patches/cao-2.5.4-herdr-codex-status.patch'
        self.fakebin = self.root / 'bin'
        self.fakebin.mkdir()
        cao = self.fakebin / 'cao'
        cao.write_text('#!/bin/sh\nexit 0\n'); cao.chmod(0o755)
        python = self.fakebin / 'python'
        self.version_file = self.root / 'version'
        self.version_file.write_text('2.5.4')
        python.write_text(f'#!{sys.executable}\nimport json\nfrom pathlib import Path\n'
                          f'print(json.dumps([{str(self.pkg)!r}, Path({str(self.version_file)!r}).read_text()]))\n')
        python.chmod(0o755)

    def run_patch(self, *args):
        import os
        return subprocess.run([sys.executable, str(self.patch_cli), *args], env={**os.environ, 'PATH':f'{self.fakebin}:/usr/bin:/bin'}, text=True, capture_output=True)

    def test_check_apply_repeat_and_reverse(self):
        before = (self.pkg / 'backends/herdr_backend.py').read_bytes()
        status_before = (self.pkg / 'providers/codex.py').read_bytes()
        check = self.run_patch('--check')
        self.assertEqual(check.returncode, 1, check.stderr)
        self.assertIn('未適用', check.stdout)
        self.assertEqual((self.pkg / 'backends/herdr_backend.py').read_bytes(), before)
        first = self.run_patch()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        after = (self.pkg / 'backends/herdr_backend.py').read_bytes()
        self.assertNotEqual(after, before)
        self.assertNotEqual((self.pkg / 'providers/codex.py').read_bytes(), status_before)
        self.assertLess(first.stdout.index(self.statusfile.stem), first.stdout.index(self.patchfile.stem))
        for args in [(), ('--check',)]:
            again = self.run_patch(*args)
            self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
            self.assertIn('適用済み', again.stdout)
            self.assertEqual((self.pkg / 'backends/herdr_backend.py').read_bytes(), after)
        self.assertFalse(list(self.pkg.rglob('*.orig')))
        reverse = subprocess.run(['patch','--batch','-p1','-R','--forward','-i',str(self.patchfile)],cwd=self.pkg,capture_output=True)
        self.assertEqual(reverse.returncode, 0)
        self.assertEqual((self.pkg / 'backends/herdr_backend.py').read_bytes(), before)
        self.assertEqual(self.run_patch('--check').returncode, 1)

    def test_reverse_cli_restores_baseline_and_allows_reapply(self):
        before = (self.pkg / 'backends/herdr_backend.py').read_bytes()
        status_before = (self.pkg / 'providers/codex.py').read_bytes()
        self.assertEqual(self.run_patch().returncode, 0)
        reverse = self.run_patch('--reverse')
        self.assertEqual(reverse.returncode, 0, reverse.stdout + reverse.stderr)
        self.assertIn('逆適用', reverse.stdout)
        self.assertLess(reverse.stdout.index(self.patchfile.stem), reverse.stdout.index(self.statusfile.stem))
        self.assertEqual((self.pkg / 'providers/codex.py').read_bytes(), status_before)
        self.assertEqual((self.pkg / 'backends/herdr_backend.py').read_bytes(), before)
        self.assertEqual(self.run_patch('--check').returncode, 1)
        self.assertEqual(self.run_patch('--reverse').returncode, 0)
        self.assertEqual(self.run_patch().returncode, 0)
        self.assertEqual(self.run_patch('--check').returncode, 0)

    def test_check_fails_when_only_status_patch_is_missing(self):
        self.assertEqual(self.run_patch().returncode, 0)
        subprocess.run(['patch', '--batch', '--silent', '-p1', '-R', '--forward', '-i', str(self.statusfile)], cwd=self.pkg, check=True)
        result = self.run_patch('--check')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('未適用: ' + self.statusfile.stem, result.stdout)
        self.assertIn('適用済み: ' + self.patchfile.stem, result.stdout)

    def test_rollback_when_subsequent_patch_fails_during_apply(self):
        before = {p: p.read_bytes() for p in self.pkg.rglob('*.py')}
        fake_patch = self.fakebin / 'patch'
        fake_patch.write_text(f"""#!{sys.executable}
import sys, subprocess
args = sys.argv[1:]
if '--dry-run' not in args and '--reverse' not in args and any('herdr-codex-status' in a for a in args):
    sys.stderr.write('simulated patch failure\\n')
    sys.exit(1)
sys.exit(subprocess.run(['/usr/bin/patch', *args]).returncode)
""")
        fake_patch.chmod(0o755)
        result = self.run_patch()
        self.assertEqual(result.returncode, 2)
        self.assertIn('適用できません', result.stderr)
        self.assertIn('元に戻しました: cao-2.5.4-codex-rollout-output', result.stderr)
        self.assertEqual({p: p.read_bytes() for p in self.pkg.rglob('*.py')}, before)

    def test_incompatible_installation_fails_without_mutating(self):
        file = self.pkg / 'backends/herdr_backend.py'
        file.write_text('incompatible\n')
        factory_before = (self.pkg / 'backends/factory.py').read_bytes()
        result = self.run_patch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('適用できません', result.stdout + result.stderr)
        self.assertEqual(file.read_text(), 'incompatible\n')
        self.assertEqual((self.pkg / 'backends/factory.py').read_bytes(), factory_before)

    def test_other_versions_are_rejected_without_mutating(self):
        before = {p: p.read_bytes() for p in (self.pkg / 'backends').glob('*.py')}
        for version in ('2.5.3', '2.5.5', '2.5.4.dev1'):
            self.version_file.write_text(version)
            for args in ((), ('--check',), ('--reverse',)):
                with self.subTest(version=version, args=args):
                    result = self.run_patch(*args)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(version, result.stderr)
                    self.assertIn('2.5.4', result.stderr)
                    self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_context_drift_is_rejected_without_fuzzy_apply(self):
        file = self.pkg / 'backends/herdr_backend.py'
        file.write_text(file.read_text().replace('import os\n', 'import os  # context drift\n', 1))
        before = {p: p.read_bytes() for p in (self.pkg / 'backends').glob('*.py')}
        result = self.run_patch()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('一致しません', result.stderr)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_doctor_brief_warns_when_patch_missing(self):
        loader = importlib.machinery.SourceFileLoader('doctor', str(REPO / 'bin/cao-doctor'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        doctor = importlib.util.module_from_spec(spec)
        loader.exec_module(doctor)
        def run(cmd, **kwargs):
            if cmd[0].endswith('cao-patch'):
                return subprocess.CompletedProcess(cmd, 1, '未適用\n', '')
            return subprocess.CompletedProcess(cmd, 0, 'herdr\n', '')
        import io
        stream = io.StringIO()
        with patch.object(doctor, 'version', return_value='1'), patch.object(doctor, 'providers_in_use', return_value=[]), patch.object(doctor, 'server_ok', return_value=True), patch.object(doctor, 'known_file', self.root / 'missing'), patch.object(doctor.subprocess, 'run', side_effect=run), patch('sys.stdout', stream):
            self.assertEqual(doctor.main(['--brief']), 0)
        self.assertIn('パッチ未適用', stream.getvalue())
        self.assertIn('cao-patch', stream.getvalue())


if __name__ == '__main__':
    unittest.main(verbosity=2)
