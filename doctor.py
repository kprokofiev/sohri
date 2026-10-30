"""Dependency checks without reading credentials, contacting models or starting a bot."""
import importlib.util
import json
import shutil
import sys

import agent


def inspect():
    command = agent.codex_command()
    checks = {'python_3_11_or_newer': sys.version_info >= (3, 11),
              'git': bool(shutil.which('git')), 'codex': bool(shutil.which(command[0])),
              'requests': importlib.util.find_spec('requests') is not None,
              'beautifulsoup4': importlib.util.find_spec('bs4') is not None}
    optional = {'ffmpeg': bool(shutil.which('ffmpeg'))}
    for module in ['yt_dlp', 'faster_whisper', 'pypdf', 'docx']:
        optional[module] = importlib.util.find_spec(module) is not None
    return {'ready_for_text': all(checks.values()), 'required': checks, 'optional_media': optional}


if __name__ == '__main__':
    report = inspect()
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['ready_for_text'] else 1)
