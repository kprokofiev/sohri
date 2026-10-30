"""Durable intake, jobs, audit trail and Telegram delivery outbox."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS updates(id INTEGER PRIMARY KEY, payload TEXT NOT NULL, handled INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS items(
                id INTEGER PRIMARY KEY, update_id INTEGER UNIQUE, created TEXT NOT NULL,
                status TEXT NOT NULL, raw TEXT NOT NULL, content TEXT, analysis TEXT,
                error TEXT, worktree TEXT, result TEXT);
              CREATE TABLE IF NOT EXISTS jobs(
                id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, kind TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'queued', UNIQUE(item_id,kind));
              CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, item_id INTEGER, at TEXT, event TEXT);
              CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, payload TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, updates):
        with self.connect() as db:
            for u in updates:
                db.execute('INSERT OR IGNORE INTO updates(id,payload) VALUES (?,?)', (u['update_id'], json.dumps(u, ensure_ascii=False)))
            if updates:
                db.execute('INSERT OR REPLACE INTO meta VALUES (\'offset\',?)', (str(max(u['update_id'] for u in updates) + 1),))

    def offset(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key='offset'").fetchone()
            return int(row[0]) if row else 0

    def meta(self, key, default=None):
        with self.connect() as db:
            row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def put_meta(self, key, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(value, ensure_ascii=False)))

    def pending_updates(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM updates WHERE handled=0 ORDER BY id')]

    def handled(self, uid):
        with self.connect() as db:
            db.execute('UPDATE updates SET handled=1 WHERE id=?', (uid,))

    def new_item(self, uid, message):
        with self.connect() as db:
            cur = db.execute('INSERT OR IGNORE INTO items(update_id,created,status,raw) VALUES (?,?,?,?)', (uid, now(), 'queued', json.dumps(message, ensure_ascii=False)))
            if not cur.rowcount:
                return None
            iid = cur.lastrowid
            db.execute("INSERT INTO jobs(item_id,kind) VALUES (?,'analyze')", (iid,))
            self._event(db, iid, 'received')
            return iid

    def get(self, iid):
        with self.connect() as db:
            row = db.execute('SELECT * FROM items WHERE id=?', (iid,)).fetchone()
            return dict(row) if row else None

    def set(self, iid, **fields):
        allowed = {'status', 'content', 'analysis', 'error', 'worktree', 'result'}
        if not fields.keys() <= allowed:
            raise ValueError('invalid item fields')
        with self.connect() as db:
            db.execute('UPDATE items SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?', (*fields.values(), iid))
            if 'status' in fields:
                self._event(db, iid, fields['status'])

    def decide(self, iid, action):
        """Atomic compare-and-swap: one click can queue at most one execution."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM items WHERE id=?', (iid,)).fetchone()
            if not row or row['status'] != 'review':
                return False
            if action == 'execute':
                plan = json.loads(row['analysis'])
                if not plan.get('project') or not plan.get('task') or not plan.get('execution'):
                    return False
                db.execute("UPDATE items SET status='approved' WHERE id=?", (iid,))
                db.execute("INSERT OR IGNORE INTO jobs(item_id,kind) VALUES (?,'execute')", (iid,))
            elif action == 'plan':
                plan = json.loads(row['analysis'])
                if not plan.get('task') or plan.get('project'):
                    return False
                db.execute("UPDATE items SET status='planned' WHERE id=?", (iid,))
            elif action == 'archive':
                db.execute("UPDATE items SET status='archived' WHERE id=?", (iid,))
            else:
                return False
            self._event(db, iid, action)
            return True

    def retry(self, iid):
        # Failed executions are never automatically replayed: require new explicit approval.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status FROM items WHERE id=?', (iid,)).fetchone()
            if not row or row[0] != 'error':
                return False
            db.execute("UPDATE items SET status='queued',error=NULL WHERE id=?", (iid,))
            db.execute("UPDATE jobs SET state='queued' WHERE item_id=? AND kind='analyze'", (iid,))
            self._event(db, iid, 'retry-analysis')
            return True

    def complete_personal(self, iid):
        with self.connect() as db:
            cursor = db.execute("UPDATE items SET status='applied' WHERE id=? AND status='planned'", (iid,))
            if cursor.rowcount:
                self._event(db, iid, 'personal-step-completed')
            return bool(cursor.rowcount)

    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET state='running' WHERE id=?", (row['id'],))
            db.execute('UPDATE items SET status=? WHERE id=?', ('analyzing' if row['kind'] == 'analyze' else 'executing', row['item_id']))
            return dict(row)

    def finish(self, jid):
        with self.connect() as db:
            db.execute("UPDATE jobs SET state='done' WHERE id=?", (jid,))

    def recover(self):
        interrupted = []
        with self.connect() as db:
            for row in db.execute("SELECT * FROM jobs WHERE state='running'").fetchall():
                if row['kind'] == 'analyze':
                    db.execute("UPDATE jobs SET state='queued' WHERE id=?", (row['id'],))
                    db.execute("UPDATE items SET status='queued' WHERE id=?", (row['item_id'],))
                else:
                    interrupted.append(row['item_id'])
                    db.execute("UPDATE jobs SET state='interrupted' WHERE id=?", (row['id'],))
                    db.execute("UPDATE items SET status='interrupted',error='Исполнение прервано. Проверьте рабочую ветку; автоматический повтор запрещён.' WHERE id=?", (row['item_id'],))
        return interrupted

    def notify(self, text, keyboard=None):
        payload = {'text': text}
        if keyboard:
            payload['reply_markup'] = keyboard
        with self.connect() as db:
            db.execute('INSERT INTO outbox(payload) VALUES (?)', (json.dumps(payload, ensure_ascii=False),))

    def deliveries(self):
        with self.connect() as db:
            return [(r['id'], json.loads(r['payload'])) for r in db.execute('SELECT * FROM outbox WHERE sent=0 ORDER BY id LIMIT 20')]

    def delivered(self, oid, failed=False):
        # sent=-1 keeps a rejected notification for diagnosis without retrying it.
        with self.connect() as db:
            db.execute('UPDATE outbox SET sent=? WHERE id=?', (-1 if failed else 1, oid))

    def recent(self, limit=15):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM items ORDER BY id DESC LIMIT ?', (limit,))]

    def listed(self, status, limit=15):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM items WHERE status=? ORDER BY id DESC LIMIT ?', (status, limit))]

    def _event(self, db, iid, event):
        db.execute('INSERT INTO events(item_id,at,event) VALUES (?,?,?)', (iid, now(), event))
