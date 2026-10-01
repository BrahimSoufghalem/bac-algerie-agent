from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
import time
import uuid

SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1), workers INTEGER NOT NULL, next_request REAL NOT NULL DEFAULT 0, cooldown_until REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS engine_heartbeats(id TEXT PRIMARY KEY, last_seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, config_json TEXT NOT NULL, encrypted_key TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS books(id TEXT PRIMARY KEY, filename TEXT NOT NULL, title TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE, size INTEGER NOT NULL, page_count INTEGER NOT NULL, source_file TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'UPLOADED', run_id TEXT REFERENCES runs(id), structure_dir TEXT, created_at REAL NOT NULL, completed_at REAL);
CREATE TABLE IF NOT EXISTS pages(id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books(id), pdf_page INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', printed_page TEXT, languages TEXT NOT NULL DEFAULT '[]', quality TEXT NOT NULL DEFAULT '[]', artifact_dir TEXT, elapsed REAL, completed_at REAL, error TEXT, UNIQUE(book_id,pdf_page));
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('page','structure')), target_id TEXT NOT NULL, book_id TEXT NOT NULL REFERENCES books(id), status TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0, lease_token TEXT, lease_until REAL, last_error TEXT, generation INTEGER NOT NULL DEFAULT 0, raw_file TEXT, UNIQUE(kind,target_id));
CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(status,available_at);
CREATE TABLE IF NOT EXISTS elements(id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books(id), page_id TEXT NOT NULL REFERENCES pages(id), element_id TEXT NOT NULL, type TEXT NOT NULL, ordinal INTEGER NOT NULL, payload TEXT NOT NULL, asset_file TEXT);
CREATE INDEX IF NOT EXISTS elements_book ON elements(book_id,ordinal);
CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books(id), parent_id TEXT, kind TEXT NOT NULL, title TEXT NOT NULL, label TEXT, start_order INTEGER NOT NULL, end_order INTEGER NOT NULL, start_page INTEGER NOT NULL, end_page INTEGER NOT NULL, content_file TEXT NOT NULL, metadata_file TEXT NOT NULL, evidence TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS relationships(source TEXT NOT NULL, target TEXT NOT NULL, relation TEXT NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY(source,target,relation));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, book_id TEXT, page_id TEXT, level TEXT NOT NULL, message TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(entity_id UNINDEXED,book_id UNINDEXED,page_id UNINDEXED,kind UNINDEXED,title,body,tokenize='unicode61 remove_diacritics 2');
'''


class Database:
    def __init__(self, path: Path, workers: int = 4):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        c=self.connect()
        try:
            c.executescript(SCHEMA)
            versions=[r[0] for r in c.execute('SELECT version FROM schema_version')]
            if versions != [1]: raise RuntimeError('Unsupported database schema version; restore/upgrade explicitly')
            c.execute('INSERT OR IGNORE INTO settings(id,workers) VALUES(1,?)', (workers,))
        finally:
            c.close()

    def connect(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA synchronous=FULL')
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA busy_timeout=30000')
        return c

    @contextmanager
    def transaction(self):
        c = self.connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def rows(self, query, params=()):
        c = self.connect()
        try:
            return [dict(r) for r in c.execute(query, params)]
        finally:
            c.close()

    def one(self, query, params=()):
        rows = self.rows(query, params)
        return rows[0] if rows else None

    def execute(self, query, params=()):
        with self.transaction() as c:
            c.execute(query, params)

    def event(self, message, book_id=None, page_id=None, level='INFO'):
        self.execute('INSERT INTO events(ts,book_id,page_id,level,message) VALUES(?,?,?,?,?)',
                     (time.time(), book_id, page_id, level, message))


def new_id(prefix):
    return prefix + '_' + uuid.uuid4().hex


def dumps(data):
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))
