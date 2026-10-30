"""Create a NEW neutral source repo and a ZIP, never copying the live working folder."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import zipfile

from check_release import check, source_files

SOURCE = Path(__file__).resolve().parents[1]


def build(source, target):
    source, target = source.resolve(), target.resolve()
    if target.exists():
        raise ValueError('Output already exists. Choose a new directory; no existing files are overwritten.')
    problems = check(source)
    if problems:
        raise ValueError('; '.join(problems))
    target.mkdir(parents=True)
    for name in source_files(source):
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, destination)
    problems = check(target, strict=True)
    if problems:
        raise ValueError('; '.join(problems))
    # Fixed neutral release author. The private repo's history, email and refs are never copied.
    for args in [
        ['init', '-b', 'main'], ['add', '.'],
        ['-c', 'user.name=Sohri contributors', '-c', 'user.email=contributors@example.invalid',
         'commit', '-m', 'Initial open source release: personal saved-materials prioritisation'],
        ['tag', 'v0.1.0']
    ]:
        subprocess.run(['git', '-C', str(target), *args], check=True, capture_output=True)
    archive = target.with_suffix('.zip')
    if archive.exists():
        raise ValueError('Archive already exists; choose a different output name')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as output:
        for name in source_files(target):
            output.write(target / name, arcname=target.name + '/' + name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(digest + '  ' + archive.name + '\n', encoding='ascii')
    return archive, digest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path, help='New output directory for the clean repo')
    args = parser.parse_args()
    archive, digest = build(SOURCE, args.output)
    print('Clean source repo: ' + str(args.output.resolve()))
    print('Send this ZIP: ' + str(archive))
    print('SHA256: ' + digest)
