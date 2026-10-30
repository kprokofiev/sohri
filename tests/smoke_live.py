"""Explicit live smoke test: real Codex editing only an isolated generated fixture."""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
from storage import Store


def main():
    root = Path(__file__).resolve().parents[1] / 'data' / f'live-smoke-{int(time.time())}'
    repo = root / 'fixture'
    repo.mkdir(parents=True)
    (repo / 'README.md').write_text('# Smoke fixture\n', encoding='utf-8')
    agent.run_process(['git', 'init', str(repo)])
    agent.run_process(['git', '-C', str(repo), 'add', 'README.md'])
    agent.run_process(['git', '-C', str(repo), '-c', 'user.name=Sohri Test', '-c', 'user.email=test@localhost', 'commit', '-m', 'Fixture baseline'])
    config = {'execution_enabled': True, 'projects': {'fixture': {'path': str(repo), 'description': 'Disposable test repository'}}}
    store = Store(root / 'state.db')
    iid = store.new_item(1, {'text': 'Internal isolated smoke test'})
    analysis_job = store.claim()
    store.finish(analysis_job['id'])
    plan = {'project': 'fixture', 'task': 'Add the exact line Smoke test passed. to README.md. Do not change anything else.',
            'acceptance': ['README.md contains the exact line Smoke test passed.'], 'reason': 'Test an isolated generated fixture only.'}
    plan = agent.prepare_execution(plan, config)
    store.set(iid, analysis=json.dumps(plan), status='review')
    assert store.decide(iid, 'execute')
    assert not store.decide(iid, 'execute')
    job = store.claim()
    assert job['kind'] == 'execute'
    result = agent.execute(iid, plan, config, root, lambda path: store.set(iid, worktree=path))
    assert result['status'] == 'completed', result
    wt = Path(result['path'])
    assert 'Smoke test passed.' in (wt / 'README.md').read_text(encoding='utf-8')
    assert (repo / 'README.md').read_text(encoding='utf-8') == '# Smoke fixture\n'
    changed = agent.run_process(['git', '-C', str(wt), 'diff', '--name-only']).splitlines()
    assert changed == ['README.md'], changed
    store.set(iid, status='done', result=json.dumps(result, ensure_ascii=False))
    store.finish(job['id'])
    assert store.claim() is None
    report = {'passed': True, 'branch': result['branch'], 'fixture_unchanged': True,
              'changed_files': changed, 'double_approval_blocked': True, 'result': result}
    (root / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'report': str(root / 'report.json')}, ensure_ascii=True))


if __name__ == '__main__':
    main()
