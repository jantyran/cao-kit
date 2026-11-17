"""Explicit live check: touches only the dedicated cao-pane-test session."""
import json
import subprocess
import time

from cli_agent_orchestrator.backends.herdr_backend import HerdrBackend


def assert_grid(layout):
    rects = [pane['rect'] for pane in layout['panes']]
    assert len(rects) == 4
    area = layout['area']
    for rect in rects:
        assert abs(2 * rect['width'] - area['width']) <= 1
        assert abs(2 * rect['height'] - area['height']) <= 1
    xs = sorted({r['x'] for r in rects})
    ys = sorted({r['y'] for r in rects})
    assert len(xs) == len(ys) == 2
    assert {(r['x'], r['y']) for r in rects} == {(x, y) for x in xs for y in ys}
    assert max(r['width'] for r in rects) - min(r['width'] for r in rects) <= 1
    assert max(r['height'] for r in rects) - min(r['height'] for r in rects) <= 1


def main():
    backend = HerdrBackend(herdr_session='cao-pane-test', spawn_mode='pane')
    session = 'pane-spawn-test'
    try:
        backend.create_session(session, 'leader', 'pane-test-lead', working_directory='/tmp')
        print('BEFORE:', backend._run_herdr(['pane', 'list']).stdout.strip())
        leader = backend._resolve_pane_id_from_window(session, 'leader')
        for i in range(1, 6):
            backend.create_window(
                session, f'worker{i}', f'pane-test-{i}', working_directory='/tmp',
                window_shell='printf \'READY:%s:%s:%s\\n\' "$CAO_TERMINAL_ID" "$CAO_SESSION_NAME" "$PWD"',
            )
        print('CREATED:', backend._run_herdr(['pane', 'list']).stdout.strip())
        panes = backend._parse_herdr_json(backend._run_herdr(['pane', 'list']).stdout)['panes']
        assert backend._resolve_pane_id_from_window(session, 'leader') == leader
        first = next(p['tab_id'] for p in panes if p['pane_id'] == leader)
        assert sum(p['tab_id'] == first for p in panes) == 4
        assert len({p['tab_id'] for p in panes}) == 3
        snapshot = backend._parse_herdr_json(backend._run_herdr(['api', 'snapshot']).stdout)['snapshot']
        layout = next(item for item in snapshot['layouts'] if item['tab_id'] == first)
        rects = {p['pane_id']:p['rect'] for p in layout['panes']}
        print('LAYOUT:', json.dumps(layout))
        worker_ids = [backend._resolve_pane_id_from_window(session, f'worker{i}') for i in range(1, 6)]
        assert_grid(layout)
        right_top, left_bottom, right_bottom = [rects[p] for p in worker_ids[:3]]
        assert rects[leader]['x'] == left_bottom['x'] < right_top['x'] == right_bottom['x']
        assert rects[leader]['y'] == right_top['y'] < left_bottom['y'] == right_bottom['y']
        print('GRID ROLES:', json.dumps({'leader':rects[leader], 'worker1':right_top, 'worker2':left_bottom, 'worker3':right_bottom}))
        backend._pane_cache.clear()
        assert backend.get_pane_id('pane-test-lead', session, 'leader') == leader
        # Build the marker in the shell so command echo alone cannot pass.
        backend.send_keys(session, 'leader', "printf 'LEADER_%s\\n' 'ROUTED'")
        deadline = time.monotonic() + 5
        while 'LEADER_ROUTED' not in backend.get_history(session, 'leader'):
            assert time.monotonic() < deadline, 'leader send_keys/get_history failed with three workers'
            time.sleep(0.1)
        for i in range(1, 6):
            assert 'LEADER_ROUTED' not in backend.get_history(session, f'worker{i}')
        print(f'LEADER: get_pane_id={leader}, send_keys/get_history isolated with three workers OK')
        for i, pane in enumerate(worker_ids, 1):
            assert backend.get_pane_id(f'pane-test-{i}', session, f'worker{i}') == pane
            deadline = time.monotonic() + 5
            marker = f'READY:pane-test-{i}:{session}:/tmp'
            while marker not in backend.get_history(session, f'worker{i}'):
                assert time.monotonic() < deadline, f'cwd/env/window_shell failed: worker{i}'
                time.sleep(0.1)
            backend.send_keys(session, f'worker{i}', f'echo ROUTED_{i}')
            deadline = time.monotonic() + 5
            while f'ROUTED_{i}' not in backend.get_history(session, f'worker{i}'):
                assert time.monotonic() < deadline, f'send_keys failed: worker{i}'
                time.sleep(0.1)
            print(f'worker{i}: get_pane_id={pane}, cwd/env/window_shell/send_keys/get_history OK')
        for i in range(1, 4):
            assert backend.kill_window(session, f'worker{i}')
            backend.create_window(session, f'worker{i}', f'pane-refill-{i}', working_directory='/tmp')
            snapshot = backend._parse_herdr_json(backend._run_herdr(['api', 'snapshot']).stdout)['snapshot']
            layout = next(item for item in snapshot['layouts'] if item['tab_id'] == first)
            assert_grid(layout)
            print(f'REFILLED worker{i}: 2x2 OK', json.dumps(layout))
        for i in range(1, 6):
            assert backend.kill_window(session, f'worker{i}')
        print('AFTER:', backend._run_herdr(['pane', 'list']).stdout.strip())
        remaining = backend._parse_herdr_json(backend._run_herdr(['pane', 'list']).stdout)['panes']
        assert [p['pane_id'] for p in remaining] == [leader]
        print('PASS: 2x2 grid, three vacancies refilled, two fallback tabs; five workers removed; leader retained')
    finally:
        cleanup_errors = []
        for action in ['stop', 'delete']:
            result = subprocess.run(['herdr', 'session', action, 'cao-pane-test'], text=True, capture_output=True)
            print(f'CLEANUP {action}:', result.returncode, result.stdout.strip(), result.stderr.strip())
            if result.returncode:
                cleanup_errors.append(f'session {action} failed')
        if cleanup_errors:
            raise RuntimeError('; '.join(cleanup_errors))


if __name__ == '__main__':
    main()
