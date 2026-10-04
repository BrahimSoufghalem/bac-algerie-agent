import json
import random
import time
import uuid
from bac.vendor.bookforge.database.db import dumps, new_id


class LeaseLost(Exception):
    pass


class Queue:
    """SQLite single-host transactional queue. Fenced leases prevent duplicate commits."""

    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def start(self, book_ids, config, key, vault, workers):
        if not 1 <= workers <= self.settings.worker_ceiling:
            raise ValueError("Worker count outside configured limits")
        run_id = new_id("run")
        now = time.time()
        with self.db.transaction() as c:
            books = []
            for book_id in dict.fromkeys(book_ids):
                book = c.execute(
                    "SELECT * FROM books WHERE id=?", (book_id,)
                ).fetchone()
                if not book:
                    raise ValueError("Unknown book")
                if book["status"] == "PROCESSING":
                    raise ValueError("Book already processing")
                books.append(book)
            if not books:
                raise ValueError("Select at least one book")
            c.execute(
                "INSERT INTO runs VALUES(?,?,?,?)",
                (run_id, dumps(config), vault.encrypt(key), now),
            )
            c.execute("UPDATE settings SET workers=? WHERE id=1", (workers,))
            for b in books:
                c.execute(
                    "DELETE FROM jobs WHERE kind='structure' AND book_id=?", (b["id"],)
                )
                c.execute(
                    "UPDATE books SET run_id=?,status='PROCESSING',completed_at=NULL WHERE id=?",
                    (run_id, b["id"]),
                )
                for p in c.execute(
                    "SELECT * FROM pages WHERE book_id=? AND status='PENDING'",
                    (b["id"],),
                ).fetchall():
                    c.execute(
                        "INSERT OR IGNORE INTO jobs(id,kind,target_id,book_id,available_at) VALUES(?,?,?,?,?)",
                        (new_id("job"), "page", p["id"], b["id"], now),
                    )
        for b in books:
            self.db.event("Book started", b["id"])
        return run_id

    def recover(self, c, now):
        expired = c.execute(
            "SELECT * FROM jobs WHERE status='RUNNING' AND (lease_until IS NULL OR lease_until<=?)",
            (now,),
        ).fetchall()
        for j in expired:
            status = (
                "FAILED"
                if j["attempts"] >= self.settings.max_retries + 1
                else "PENDING"
            )
            c.execute(
                "UPDATE jobs SET status=?,lease_token=NULL,lease_until=NULL,last_error=? WHERE id=?",
                (status, "WORKER_LEASE_EXPIRED", j["id"]),
            )
            if j["kind"] == "page":
                c.execute(
                    "UPDATE pages SET status=?,error=? WHERE id=?",
                    (status, "WORKER_LEASE_EXPIRED", j["target_id"]),
                )
            else:
                c.execute(
                    "UPDATE books SET status='STRUCTURE_FAILED' WHERE id=? AND ?='FAILED'",
                    (j["book_id"], status),
                )

    def schedule_structure(self, c, now):
        ready = c.execute(
            "SELECT * FROM books b WHERE b.status='PROCESSING' AND NOT EXISTS(SELECT 1 FROM jobs j WHERE j.book_id=b.id AND j.kind='page' AND j.status IN ('PENDING','RUNNING'))"
        ).fetchall()
        for b in ready:
            c.execute(
                "INSERT OR IGNORE INTO jobs(id,kind,target_id,book_id,available_at) VALUES(?,?,?,?,?)",
                (new_id("job"), "structure", b["id"], b["id"], now),
            )

    def claim(self):
        now = time.time()
        with self.db.transaction() as c:
            self.recover(c, now)
            self.schedule_structure(c, now)
            # A restored database may retain a higher cap from an older deployment.
            workers = min(
                c.execute("SELECT workers FROM settings WHERE id=1").fetchone()[0],
                self.settings.max_workers,
            )
            active = c.execute(
                "SELECT count(*) FROM jobs WHERE status='RUNNING'"
            ).fetchone()[0]
            if active >= workers:
                return None
            j = c.execute(
                "SELECT * FROM jobs WHERE status='PENDING' AND available_at<=? ORDER BY CASE kind WHEN 'page' THEN 0 ELSE 1 END,available_at,target_id LIMIT 1",
                (now,),
            ).fetchone()
            if not j:
                return None
            token = uuid.uuid4().hex
            c.execute(
                "UPDATE jobs SET status='RUNNING',attempts=attempts+1,lease_token=?,lease_until=? WHERE id=?",
                (token, now + self.settings.lease_seconds, j["id"]),
            )
            if j["kind"] == "page":
                c.execute(
                    "UPDATE pages SET status='PROCESSING',error=NULL WHERE id=?",
                    (j["target_id"],),
                )
            c.execute(
                "INSERT INTO events(ts,book_id,page_id,level,message) VALUES(?,?,?,?,?)",
                (
                    now,
                    j["book_id"],
                    j["target_id"] if j["kind"] == "page" else None,
                    "INFO",
                    "EXTRACTION_STAGE:claimed",
                ),
            )
            return dict(
                c.execute("SELECT * FROM jobs WHERE id=?", (j["id"],)).fetchone()
            )

    def assert_owned(self, c, job):
        row = c.execute(
            "SELECT 1 FROM jobs WHERE id=? AND lease_token=? AND status='RUNNING' AND lease_until>?",
            (job["id"], job["lease_token"], time.time()),
        ).fetchone()
        if not row:
            raise LeaseLost()

    def heartbeat(self, job):
        with self.db.transaction() as c:
            changed = c.execute(
                "UPDATE jobs SET lease_until=? WHERE id=? AND lease_token=? AND status='RUNNING' AND lease_until>?",
                (
                    time.time() + self.settings.lease_seconds,
                    job["id"],
                    job["lease_token"],
                    time.time(),
                ),
            ).rowcount
            return bool(changed)

    def save_raw(self, job, raw_file):
        with self.db.transaction() as c:
            self.assert_owned(c, job)
            c.execute("UPDATE jobs SET raw_file=? WHERE id=?", (raw_file, job["id"]))

    def finish(self, c, job):
        self.assert_owned(c, job)
        c.execute(
            "UPDATE jobs SET status='DONE',lease_token=NULL,lease_until=NULL,last_error=NULL WHERE id=?",
            (job["id"],),
        )

    def fail(self, job, code, retryable=True, retry_after=0):
        with self.db.transaction() as c:
            self.assert_owned(c, job)
            retry = retryable and job["attempts"] <= self.settings.max_retries
            delay = max(
                retry_after, min(300, 2 ** job["attempts"] + random.uniform(0, 1))
            )
            status = "PENDING" if retry else "FAILED"
            c.execute(
                "UPDATE jobs SET status=?,available_at=?,lease_token=NULL,lease_until=NULL,last_error=? WHERE id=?",
                (status, time.time() + delay, code, job["id"]),
            )
            if code == "HTTP_429":
                c.execute(
                    "UPDATE settings SET cooldown_until=max(cooldown_until,?) WHERE id=1",
                    (time.time() + delay,),
                )
            if job["kind"] == "page":
                c.execute(
                    "UPDATE pages SET status=?,error=? WHERE id=?",
                    (status, code, job["target_id"]),
                )
            elif not retry:
                c.execute(
                    "UPDATE books SET status='STRUCTURE_FAILED' WHERE id=?",
                    (job["book_id"],),
                )
        self.db.event(
            ("Retry scheduled: " if retry else "Job failed: ") + code,
            job["book_id"],
            job["target_id"] if job["kind"] == "page" else None,
            "ERROR",
        )

    def release(self, job):
        try:
            with self.db.transaction() as c:
                self.assert_owned(c, job)
                c.execute(
                    "UPDATE jobs SET status='PENDING',attempts=max(0,attempts-1),lease_token=NULL,lease_until=NULL WHERE id=?",
                    (job["id"],),
                )
                if job["kind"] == "page":
                    c.execute(
                        "UPDATE pages SET status='PENDING' WHERE id=?",
                        (job["target_id"],),
                    )
        except LeaseLost:
            pass

    def retry_pages(self, book_id, status):
        if status not in ("FAILED", "NEEDS_REVIEW"):
            raise ValueError("Invalid retry status")
        with self.db.transaction() as c:
            b = c.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
            if not b or not b["run_id"]:
                raise ValueError("Start/configure this book first")
            if c.execute(
                "SELECT 1 FROM jobs WHERE book_id=? AND kind='structure' AND status='RUNNING'",
                (book_id,),
            ).fetchone():
                raise ValueError("Wait for the current structure pass before retrying")
            pages = c.execute(
                "SELECT id FROM pages WHERE book_id=? AND status=?", (book_id, status)
            ).fetchall()
            for p in pages:
                c.execute(
                    "UPDATE pages SET status='PENDING',error=NULL,completed_at=NULL WHERE id=?",
                    (p["id"],),
                )
                c.execute(
                    "UPDATE jobs SET status='PENDING',attempts=0,generation=generation+1,raw_file=NULL,available_at=0,lease_token=NULL,lease_until=NULL,last_error=NULL WHERE kind='page' AND target_id=?",
                    (p["id"],),
                )
            if pages:
                c.execute(
                    "UPDATE books SET status='PROCESSING',completed_at=NULL WHERE id=?",
                    (book_id,),
                )
                c.execute(
                    "DELETE FROM jobs WHERE kind='structure' AND book_id=?", (book_id,)
                )
            return len(pages)

    def reextract_page(self, book_id, pdf_page, config, key, vault, workers):
        """Explicit fresh Vision for one terminal page; no cached raw response reused."""
        if not 1 <= workers <= self.settings.worker_ceiling:
            raise ValueError("Worker count outside configured limits")
        run_id = new_id("run")
        job_id = new_id("job")
        now = time.time()
        with self.db.transaction() as c:
            book = c.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
            page = c.execute(
                "SELECT * FROM pages WHERE book_id=? AND pdf_page=?",
                (book_id, pdf_page),
            ).fetchone()
            if not book or not page:
                raise ValueError("Unknown source page")
            if (
                book["status"] == "PROCESSING"
                or c.execute(
                    "SELECT 1 FROM jobs WHERE book_id=? AND status IN ('PENDING','RUNNING')",
                    (book_id,),
                ).fetchone()
            ):
                raise ValueError("Wait for current extraction to finish")
            if (
                not book["run_id"]
                or c.execute(
                    "SELECT 1 FROM pages WHERE book_id=? AND status NOT IN ('SUCCESS','NEEDS_REVIEW','FAILED')",
                    (book_id,),
                ).fetchone()
            ):
                raise ValueError(
                    "Complete the initial extraction before re-extracting a page"
                )
            c.execute(
                "INSERT INTO runs VALUES(?,?,?,?)",
                (run_id, dumps(config), vault.encrypt(key), now),
            )
            c.execute("UPDATE settings SET workers=? WHERE id=1", (workers,))
            c.execute(
                "DELETE FROM jobs WHERE book_id=? AND (kind='structure' OR (kind='page' AND target_id=?))",
                (book_id, page["id"]),
            )
            c.execute(
                "UPDATE pages SET status='PENDING',printed_page=NULL,languages='[]',quality='[]',artifact_dir=NULL,elapsed=NULL,completed_at=NULL,error=NULL WHERE id=?",
                (page["id"],),
            )
            c.execute("DELETE FROM elements WHERE page_id=?", (page["id"],))
            c.execute("DELETE FROM search_fts WHERE page_id=?", (page["id"],))
            c.execute(
                "INSERT INTO jobs(id,kind,target_id,book_id,available_at,raw_file) VALUES(?,?,?,?,?,NULL)",
                (job_id, "page", page["id"], book_id, now),
            )
            c.execute(
                "UPDATE books SET run_id=?,status='PROCESSING',completed_at=NULL WHERE id=?",
                (run_id, book_id),
            )
        self.db.event("Manual page re-extraction queued", book_id, page["id"])
        return {"run_id": run_id, "job_id": job_id, "scheduled": 1, "page": pdf_page}

    def retry_structure(self, book_id):
        with self.db.transaction() as c:
            b = c.execute("SELECT status FROM books WHERE id=?", (book_id,)).fetchone()
            if not b or b["status"] != "STRUCTURE_FAILED":
                raise ValueError("Structure is not failed")
            c.execute(
                "UPDATE jobs SET status='PENDING',attempts=0,available_at=0,last_error=NULL WHERE kind='structure' AND book_id=?",
                (book_id,),
            )
            c.execute("UPDATE books SET status='PROCESSING' WHERE id=?", (book_id,))

    def rate_slot(self):
        with self.db.transaction() as c:
            state = c.execute("SELECT * FROM settings WHERE id=1").fetchone()
            slot = max(time.time(), state["next_request"], state["cooldown_until"])
            c.execute(
                "UPDATE settings SET next_request=? WHERE id=1",
                (slot + self.settings.min_request_interval,),
            )
            return slot
