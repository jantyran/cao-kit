"""Run with the CAO uv-tool Python; mock only the external herdr process."""
import atexit
import json
import os
import tempfile
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

STATE = tempfile.TemporaryDirectory(prefix="herdr-unit-")
atexit.register(STATE.cleanup)
os.environ["CAO_HOME_DIR"] = STATE.name

from cli_agent_orchestrator.backends.base import TerminalBackendError, TerminalNotFoundError
from cli_agent_orchestrator.backends.herdr_backend import HerdrBackend, _sanitize_herdr_args
from cli_agent_orchestrator.backends.factory import BackendFactory


class PaneSpawnTest(unittest.TestCase):
    def setUp(self):
        self.tabs = [dict(tab_id='w1:t1', workspace_id='w1', label='leader')]
        self.panes = [dict(pane_id='w1:p1', tab_id='w1:t1', workspace_id='w1')]
        self.calls = []
        self.next_pane = 2
        self.area = dict(x=0, y=0, width=100, height=40)
        self.rects = {'w1:p1': dict(self.area)}
        self.startup = patch.object(HerdrBackend, '_ensure_session_running').start()
        self.addCleanup(patch.stopall)
        self.run = patch.object(HerdrBackend, '_run_herdr', side_effect=self.herdr).start()
        patch('cli_agent_orchestrator.backends.herdr_backend.time.sleep').start()

    def herdr(self, args, check=True):
        # Keep the real validation in the mock boundary, including new flags.
        _sanitize_herdr_args(args)
        self.calls.append(args)
        action = args[:2]
        if action == ['workspace', 'list']:
            data = dict(workspaces=[dict(workspace_id='w1', label='test')])
        elif action == ['tab', 'list']:
            data = dict(tabs=self.tabs)
        elif action == ['pane', 'list']:
            data = dict(panes=self.panes)
        elif action in (['pane', 'split'], ['tab', 'create']):
            tab_id = 'w1:t1' if action[0] == 'pane' else f'w1:t{len(self.tabs)+1}'
            if action[0] == 'tab':
                self.tabs.append(dict(tab_id=tab_id, workspace_id='w1', label=args[args.index('--label')+1]))
            pane = dict(pane_id=f'w1:p{self.next_pane}', tab_id=tab_id, workspace_id='w1')
            self.next_pane += 1
            if action[0] == 'pane':
                rect = self.rects[args[2]]
                other = dict(rect)
                if args[args.index('--direction')+1] == 'right':
                    rect['width'] //= 2
                    other['width'] -= rect['width']
                    other['x'] += rect['width']
                else:
                    rect['height'] //= 2
                    other['height'] -= rect['height']
                    other['y'] += rect['height']
                self.rects[pane['pane_id']] = other
            self.panes.append(pane)
            data = {'pane' if action[0] == 'pane' else 'root_pane': pane}
        elif action == ['pane', 'rename']:
            next(p for p in self.panes if p['pane_id'] == args[2])['label'] = args[3]
            data = {}
        elif action == ['api', 'snapshot']:
            # Native herdr terminal ids need not be CAO ids; exercise fallback.
            data = dict(snapshot=dict(panes=self.panes, layouts=[dict(tab_id='w1:t1', area=self.area, panes=[dict(pane_id=p['pane_id'], rect=self.rects[p['pane_id']]) for p in self.panes if p['pane_id'] in self.rects])]))
        elif action == ['pane', 'close']:
            self.panes[:] = [p for p in self.panes if p['pane_id'] != args[2]]
            data = {}
        else:
            data = {}
        return subprocess.CompletedProcess(args, 0, json.dumps(dict(result=data)), '')

    def backend(self, mode='pane'):
        return HerdrBackend(herdr_session='cao-pane-test', spawn_mode=mode)

    def test_default_creates_tab(self):
        b = HerdrBackend(herdr_session='cao-pane-test')
        b.create_window('test', 'worker', 'id')
        self.assertEqual(len(self.tabs), 2)
        self.assertFalse(any(c[:2] == ['pane', 'split'] for c in self.calls))

    def test_three_splits_then_tabs_with_env_cwd_shell(self):
        b = self.backend()
        for i in range(1, 6):
            self.assertEqual(b.create_window('test', f'worker{i}', f'id{i}', '/tmp', 'echo ready', {'DEMO':'yes'}), f'worker{i}')
        splits = [c for c in self.calls if c[:2] == ['pane', 'split']]
        self.assertEqual([c[2] for c in splits], ['w1:p1', 'w1:p1', 'w1:p2'])
        self.assertEqual([c[c.index('--direction')+1] for c in splits], ['right', 'down', 'down'])
        self.assertEqual(len(self.tabs), 3)
        for i, c in enumerate(splits, 1):
            self.assertIn('--no-focus', c)
            self.assertEqual(c[c.index('--cwd')+1], '/tmp')
            self.assertIn(f'CAO_TERMINAL_ID=id{i}', c)
            self.assertIn('CAO_SESSION_NAME=test', c)
            self.assertIn('DEMO=yes', c)
            self.assertIn(['pane', 'rename', f'w1:p{i+1}', f'worker{i}'], self.calls)
            self.assertIn(['pane', 'run', f'w1:p{i+1}', 'echo ready'], self.calls)

    def test_label_fallback_routes_io_and_close_to_worker(self):
        b = self.backend()
        b.create_window('test', 'worker', 'id')
        b._pane_cache.clear()
        # An identically labeled pane in another workspace must never match.
        self.panes.insert(0, dict(pane_id='w2:p1', tab_id='w2:t1', workspace_id='w2', label='worker'))
        self.assertEqual(b.get_pane_id('id', 'test', 'worker'), 'w1:p2')
        b.send_keys('test', 'worker', 'hello')
        b.get_history('test', 'worker')
        self.assertIn(['pane', 'send-text', 'w1:p2', 'hello'], self.calls)
        self.assertTrue(any(c[:3] == ['pane', 'read', 'w1:p2'] for c in self.calls))
        self.assertTrue(b.kill_window('test', 'worker'))
        self.assertIn(['pane', 'close', 'w1:p2'], self.calls)
        with self.assertRaises(TerminalNotFoundError):
            b._resolve_pane_id_from_window('test', 'worker')

    def test_tab_label_has_priority_over_pane_label(self):
        b = self.backend('window')
        self.panes.append(dict(pane_id='w1:p2', tab_id='w1:t2', workspace_id='w1', label='leader'))
        self.assertEqual(b._resolve_pane_id_from_window('test', 'leader'), 'w1:p1')

    def test_each_closed_worker_slot_is_filled_from_live_geometry(self):
        for closed, target in [('worker1', 'w1:p4'), ('worker2', 'w1:p1'), ('worker3', 'w1:p2')]:
            with self.subTest(closed=closed):
                self.panes = [dict(pane_id='w1:p1', tab_id='w1:t1', workspace_id='w1')]
                self.next_pane = 2
                self.rects = {'w1:p1':dict(x=0,y=0,width=100,height=40)}
                b = self.backend()
                for i in range(1, 4):
                    b.create_window('test', f'worker{i}', f'id{i}')
                b.kill_window('test', closed)
                # Closing either sibling expands the remaining pane in its column.
                self.rects[target]['y'] = 0
                self.rects[target]['height'] = 40
                b.create_window('test', 'replacement', 'new')
                split = [c for c in self.calls if c[:2] == ['pane', 'split']][-1]
                self.assertEqual(split[2], target)
                self.assertEqual(split[split.index('--direction')+1], 'down')
                self.assertEqual(len(self.tabs), 1)

    def test_grid_assertions_reject_old_layout_and_undersized_rects(self):
        from herdr_pane_live import assert_grid
        area = dict(x=0, y=0, width=100, height=40)
        old_rects = [dict(x=0,y=0,width=50,height=40),
                     dict(x=50,y=0,width=50,height=20),
                     dict(x=50,y=20,width=50,height=10),
                     dict(x=50,y=30,width=50,height=10)]
        undersized = [dict(x=x,y=y,width=10,height=10) for x in [0,50] for y in [0,20]]
        for rects in [old_rects, undersized]:
            with self.subTest(rects=rects), self.assertRaises(AssertionError):
                assert_grid(dict(area=area, panes=[dict(rect=r) for r in rects]))

    def test_no_tab_falls_back_to_tab_create(self):
        self.tabs.clear()
        self.panes.clear()
        self.backend().create_window('test', 'worker', 'id')
        self.assertTrue(any(c[:2] == ['tab', 'create'] for c in self.calls))

    def test_factory_passes_spawn_mode_and_defaults_invalid_value(self):
        for mode, expected in [('pane','pane'), ('window','window'), ('invalid','window')]:
            def config(key, default=None, **kwargs):
                return {'terminal.backend':'herdr', 'terminal.spawn_mode':mode, 'terminal.herdr_session':'cao-pane-test'}.get(key, default)
            with patch('cli_agent_orchestrator.backends.factory.ConfigService.get', side_effect=config), patch('cli_agent_orchestrator.backends.herdr_backend.HerdrBackend') as cls:
                BackendFactory.create()
                cls.assert_called_once_with(herdr_session='cao-pane-test', spawn_mode=expected)

    def test_concurrent_instances_serialize_layout_through_rename(self):
        first_listing = threading.Event()
        release = threading.Event()
        second_listing = threading.Event()
        renamed = threading.Event()
        listings = []

        def delayed(args, check=True):
            result = self.herdr(args, check)
            if args[:2] == ['pane', 'rename']:
                renamed.set()
            if args[:2] == ['pane', 'list']:
                listings.append(renamed.is_set())
                if len(listings) == 1:
                    first_listing.set()
                    if not release.wait(3):
                        raise AssertionError('first spawn was not released')
                else:
                    second_listing.set()
            return result

        backends = [self.backend() for _ in range(5)]
        with patch.object(HerdrBackend, '_run_herdr', side_effect=delayed):
            with ThreadPoolExecutor(max_workers=5) as pool:
                first = pool.submit(backends[0].create_window, 'test', 'worker1', 'id1')
                try:
                    self.assertTrue(first_listing.wait(3))
                    rest = [pool.submit(b.create_window, 'test', f'worker{i}', f'id{i}')
                            for i, b in enumerate(backends[1:], 2)]
                    raced = second_listing.wait(0.2)
                finally:
                    release.set()
                self.assertEqual(first.result(), 'worker1')
                for future in rest:
                    future.result()
        self.assertFalse(raced, 'another instance read layout before split/rename completed')
        self.assertTrue(all(listings[1:]), 'lock released before rename')
        splits = [c for c in self.calls if c[:2] == ['pane', 'split']]
        self.assertEqual([c[2] for c in splits], ['w1:p1', 'w1:p1', 'w1:p2'])
        self.assertEqual(len(self.tabs), 3)

    def test_layout_errors_fall_back_to_tab(self):
        for error in (KeyError('rect'), TypeError('area'), TerminalBackendError('snapshot failed')):
            with self.subTest(error=type(error).__name__):
                self.panes = [dict(pane_id='w1:p1', tab_id='w1:t1', workspace_id='w1'),
                              dict(pane_id='w1:p2', tab_id='w1:t1', workspace_id='w1', label='existing')]
                def broken(args, check=True):
                    if args[:2] == ['api', 'snapshot']:
                        raise error
                    return self.herdr(args, check)
                with patch.object(HerdrBackend, '_run_herdr', side_effect=broken):
                    self.backend().create_window('test', 'fallback', 'fallback-id')
                self.assertEqual(self.calls[-1][:2], ['tab', 'create'])

    def test_malformed_geometry_falls_back_to_tab(self):
        b = self.backend()
        b.create_window('test', 'worker1', 'id1')
        for rect in ({'width': 50}, {'width': None, 'height': 40, 'x': 0, 'y': 0}):
            with self.subTest(rect=rect):
                self.rects['w1:p1'] = rect
                b.create_window('test', 'fallback', 'fallback-id')
                self.assertEqual(self.calls[-1][:2], ['tab', 'create'])

    def test_rename_failure_closes_new_pane_and_preserves_error(self):
        b = self.backend()
        failure = TerminalBackendError('rename failed')
        def broken(args, check=True):
            if args[:2] == ['pane', 'rename']:
                raise failure
            return self.herdr(args, check)
        with patch.object(HerdrBackend, '_run_herdr', side_effect=broken):
            with self.assertRaises(TerminalBackendError) as raised:
                b.create_window('test', 'worker', 'id')
        self.assertIs(raised.exception, failure)
        self.assertEqual([p['pane_id'] for p in self.panes], ['w1:p1'])
        self.assertNotIn('id', b._pane_cache)

    def test_leader_routes_io_and_close_when_workers_precede_it(self):
        b = self.backend()
        for i in range(1, 4):
            b.create_window('test', f'worker{i}', f'id{i}')
        self.panes[:] = self.panes[1:] + self.panes[:1]
        for pane in self.panes:
            pane['terminal_id'] = 'term_native_' + pane['pane_id']
        b._pane_cache.clear()
        self.assertEqual(b.get_pane_id('leader-id', 'test', 'leader'), 'w1:p1')
        b.send_keys('test', 'leader', 'LEADER_ONLY')
        b.get_history('test', 'leader')
        self.assertIn(['pane', 'send-text', 'w1:p1', 'LEADER_ONLY'], self.calls)
        self.assertTrue(any(c[:3] == ['pane', 'read', 'w1:p1'] for c in self.calls))
        self.assertTrue(b.kill_window('test', 'leader'))
        self.assertEqual({p['label'] for p in self.panes}, {'worker1', 'worker2', 'worker3'})

    def test_multi_pane_tab_prefers_matching_label_over_first_pane(self):
        self.panes[0]['label'] = 'worker'
        self.panes.append(dict(pane_id='w1:p2', tab_id='w1:t1', workspace_id='w1', label='leader'))
        self.assertEqual(self.backend()._resolve_pane_id_from_window('test', 'leader'), 'w1:p2')

    def test_duplicate_labels_refuse_resolution_and_close(self):
        self.panes.extend(dict(pane_id=f'w1:p{i}', tab_id='w1:t1', workspace_id='w1', label='worker')
                          for i in (2, 3))
        b = self.backend()
        with self.assertRaises(TerminalNotFoundError):
            b._resolve_pane_id_from_window('test', 'worker')
        self.assertFalse(b.kill_window('test', 'worker'))
        self.assertFalse(any(c[:2] == ['pane', 'close'] for c in self.calls))

    def test_closed_leader_never_resolves_to_last_worker(self):
        b = self.backend()
        b.create_window('test', 'worker1', 'worker-id')
        self.assertTrue(b.kill_window('test', 'leader'))
        self.assertEqual([p['label'] for p in self.panes], ['worker1'])
        self.calls.clear()
        b._pane_cache.clear()
        for action in (lambda: b.get_pane_id('leader-id', 'test', 'leader'),
                       lambda: b.send_keys('test', 'leader', 'LEADER_ONLY'),
                       lambda: b.get_history('test', 'leader')):
            with self.subTest(action=action), self.assertRaises(TerminalNotFoundError):
                action()
        self.assertFalse(b.kill_window('test', 'leader'))
        self.assertFalse(any(c[:2] in (['pane', 'close'], ['pane', 'send-text'], ['pane', 'read'])
                             for c in self.calls))
        self.assertEqual([p['label'] for p in self.panes], ['worker1'])

    def test_odd_geometry_keeps_worker2_left_and_worker3_right(self):
        for left_width, right_width, height in ((50, 51, 40), (50, 51, 41),
                                               (51, 50, 41), (49, 50, 39), (50, 50, 41)):
            with self.subTest(left=left_width, right=right_width, height=height):
                self.panes = [dict(pane_id='w1:p1', tab_id='w1:t1', workspace_id='w1')]
                self.next_pane = 2
                self.calls.clear()
                self.area = dict(x=7, y=3, width=left_width + right_width, height=height)
                self.rects = {'w1:p1': dict(self.area)}
                b = self.backend()
                b.create_window('test', 'worker1', 'id1')
                self.rects['w1:p1']['width'] = left_width
                self.rects['w1:p2'].update(x=7 + left_width, width=right_width)
                b.create_window('test', 'worker2', 'id2')
                b.create_window('test', 'worker3', 'id3')
                splits = [c for c in self.calls if c[:2] == ['pane', 'split']]
                self.assertEqual([c[2] for c in splits], ['w1:p1', 'w1:p1', 'w1:p2'])
                self.assertEqual([c[c.index('--direction') + 1] for c in splits],
                                 ['right', 'down', 'down'])
                from herdr_pane_live import assert_grid
                assert_grid(dict(area=self.area, panes=[dict(rect=r) for r in self.rects.values()]))
                self.assertEqual(self.rects['w1:p3']['x'], 7)
                self.assertEqual(self.rects['w1:p4']['x'], 7 + left_width)


if __name__ == '__main__':
    unittest.main(verbosity=2)

