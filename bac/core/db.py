from contextlib import contextmanager
from pathlib import Path
import json, sqlite3, time, uuid

ROOT = Path(__file__).resolve().parents[2]


def uid(prefix):
    return prefix + "_" + uuid.uuid4().hex


def js(x):
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


class DB:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def connect(self):
        c = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=15000")
        c.execute("PRAGMA synchronous=FULL")
        return c

    @contextmanager
    def tx(self):
        c = self.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def migrate(self):
        c = self.connect()
        try:
            c.execute(
                "CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY,applied_at REAL NOT NULL)"
            )
            scripts = sorted((ROOT / "migrations").glob("*.sql"))
            known = {int(p.name.split("_")[0]) for p in scripts}
            applied = {r[0] for r in c.execute("SELECT version FROM migrations")}
            if applied - known:
                raise RuntimeError("Database requires a newer application version")
            for p in scripts:
                version = int(p.name.split("_")[0])
                if c.execute(
                    "SELECT 1 FROM migrations WHERE version=?", (version,)
                ).fetchone():
                    continue
                # Executescript commits; keep the migration and version marker in one explicit transaction.
                c.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + p.read_text()
                    + f"\nINSERT INTO migrations VALUES({version},{time.time()});\nCOMMIT;"
                )
        finally:
            c.close()

    def rows(self, sql, args=()):
        c = self.connect()
        try:
            return [dict(r) for r in c.execute(sql, args)]
        finally:
            c.close()

    def one(self, sql, args=()):
        rows = self.rows(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()):
        with self.tx() as c:
            c.execute(sql, args)

    def audit(self, actor, action, target=None, details=None):
        self.execute(
            "INSERT INTO audit(actor_id,action,target,details,created_at) VALUES(?,?,?,?,?)",
            (actor, action, target, js(details or {}), time.time()),
        )

    def event(self, run, type, payload, lease=None):
        with self.tx() as c:
            if (
                lease
                and not c.execute(
                    "SELECT 1 FROM agent_runs WHERE id=? AND lease_token=? AND status='RUNNING' AND lease_until>?",
                    (run, lease, time.time()),
                ).fetchone()
            ):
                raise RuntimeError("LEASE_LOST")
            c.execute(
                "INSERT INTO run_events(run_id,type,payload,created_at) VALUES(?,?,?,?)",
                (run, type, js(payload), time.time()),
            )

    def rate(self, key, limit, seconds):
        now = time.time()
        with self.tx() as c:
            row = c.execute("SELECT * FROM rate_limits WHERE key=?", (key,)).fetchone()
            if not row or row["window"] + seconds <= now:
                c.execute(
                    "INSERT OR REPLACE INTO rate_limits VALUES(?,?,?)", (key, now, 1)
                )
                return True
            if row["amount"] >= limit:
                return False
            c.execute("UPDATE rate_limits SET amount=amount+1 WHERE key=?", (key,))
            return True
