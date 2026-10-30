"""Source-only privacy gate. Does not read ignored local credentials or private data."""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT_FILES = {
    '.env.example', '.gitignore', 'AGENTS.md', 'README.md', 'SEND_TO_FRIEND.md',
    'LICENSE', 'SECURITY.md', 'THIRD_PARTY.md', 'CONTRIBUTING.md', 'RELEASE_CHECKS.md',
    'agent.py', 'bot.py', 'doctor.py', 'media.py', 'onboarding.py', 'setup.py',
    'storage.py', 'supervisor.py', 'install-autostart.ps1', 'stop.ps1',
    'config.example.json', 'schema.json', 'execution.schema.json',
    'requirements.txt', 'requirements-media.txt',
}
EXTRA_FILES = {'tests/test_core.py', 'tests/test_personal.py', 'tests/test_release.py',
               'tests/smoke_live.py', '.github/workflows/tests.yml',
               'tools/check_release.py', 'tools/build_release.py'}


def source_files(root):
    return [name for name in sorted(ROOT_FILES | EXTRA_FILES) if (root / name).is_file()]


def check(root, strict=False):
    failures = []
    for name in source_files(root):
        content = (root / name).read_text(encoding='utf-8-sig')
        if re.search(r'\b\d{8,12}:[A-Za-z0-9_-]{30,}\b|\bsk-[A-Za-z0-9_-]{20,}', content):
            failures.append(f'credential pattern in {name}')
        if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', content):
            failures.append(f'private key in {name}')
        if re.search(r'(?i)C:[/\\]Users[/\\]', content):
            failures.append(f'personal absolute path in {name}')
    required = ROOT_FILES | EXTRA_FILES
    failures += [f'missing source file: {p}' for p in sorted(required) if not (root / p).is_file()]
    if (root / 'config.example.json').exists():
        config = json.loads((root / 'config.example.json').read_text(encoding='utf-8-sig'))
        if config.get('owner_id') != 0 or config.get('execution_enabled') is not False or config.get('projects') != {}:
            failures.append('example config is not neutral and execution-disabled')
        if config.get('profile', {}).get('completed'):
            failures.append('example config contains a completed personal profile')
    if strict:
        for path in root.rglob('*'):
            rel = path.relative_to(root)
            if '.git' in rel.parts or '__pycache__' in rel.parts:
                continue
            if path.is_file() and rel.as_posix() not in required:
                failures.append(f'unexpected file in clean export: {rel.as_posix()}')
    return failures


def check_tracked(root):
    result = subprocess.run(['git', '-C', str(root), 'ls-files'], capture_output=True, text=True)
    if result.returncode:
        return []
    return [f'private path tracked: {p}' for p in result.stdout.splitlines()
            if p == '.env' or (p.startswith('.env.') and p != '.env.example')
            or p.startswith('config.local.') or p.startswith('data/') or p.startswith('.venv/')]


if __name__ == '__main__':
    target = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
    issues = check(target, '--strict' in sys.argv) + check_tracked(target)
    print(json.dumps({'passed': not issues, 'issues': issues}, indent=2))
    raise SystemExit(1 if issues else 0)
