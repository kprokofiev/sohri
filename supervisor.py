"""Hidden per-user watchdog; survives UI closing and restarts the bot on failure."""
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
lock = (DATA / 'supervisor.lock').open('a+b')
if os.name == 'nt':
    import msvcrt
    lock.seek(0)
    if not lock.read(1):
        lock.write(b'0')
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        sys.exit(0)
else:
    import fcntl
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)
(DATA / 'supervisor.pid').write_text(str(os.getpid()), encoding='ascii')
python = Path(sys.executable)
if python.name.lower() == 'pythonw.exe':
    python = python.with_name('python.exe')
while not (DATA / 'STOP').exists():
    with (DATA / 'supervisor.log').open('ab') as out:
        proc = subprocess.Popen([str(python), str(ROOT / 'bot.py')], cwd=ROOT, stdout=out, stderr=out,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        proc.wait()
        out.write(f'\n{time.ctime()}: bot exited {proc.returncode}; restart in 10s\n'.encode())
    time.sleep(10)
