"""SQLite-backed ownership, limits, jobs, and conservative daily reservations."""
from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import sqlite3
import time
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

from .costs import ExecutionDenied

SCALE = Decimal(1_000_000_000_000)


class RateLimited(ExecutionDenied):
    pass


def units(amount: Decimal) -> int:
    return int((amount * SCALE).to_integral_value(rounding=ROUND_CEILING))


class StateStore:
    def __init__(self, directory: Path, *, daily_usd=Decimal("0.50"), daily_calls=50,
                 retention_seconds=3600, clock=time.time):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database = self.directory / "state.sqlite3"
        self.daily_usd, self.daily_calls = daily_usd, daily_calls
        self.retention_seconds, self.clock = retention_seconds, clock
        self._last_cleanup = None
        self._cleanup_lock = threading.Lock()
        with self.db(write=True) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, owner TEXT, role TEXT, csrf TEXT, expires REAL);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, owner TEXT, status TEXT, created REAL, events TEXT, result TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS rates(key TEXT, window INTEGER, count INTEGER, expires REAL, PRIMARY KEY(key, window));
                CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, job_id TEXT, day TEXT, accounted INTEGER);
                CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner);
                CREATE INDEX IF NOT EXISTS attempts_day ON attempts(day);
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT);
            """)

    @contextmanager
    def db(self, write=False):
        connection = sqlite3.connect(self.database, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def rate(self, key, limit, seconds):
        window = int(self.clock() // seconds)
        with self.db(write=True) as db:
            count = db.execute("SELECT count FROM rates WHERE key=? AND window=?", (key, window)).fetchone()
            if count and count[0] >= limit:
                raise RateLimited("Too many requests. Try again later.")
            db.execute("INSERT INTO rates VALUES(?,?,1,?) ON CONFLICT(key,window) DO UPDATE SET count=count+1", (key, window, (window+1)*seconds))

    def session(self, token):
        if not token or len(token) > 128:
            return None
        with self.db() as db:
            row = db.execute("SELECT * FROM sessions WHERE token_hash=? AND expires>?", (hashlib.sha256(token.encode()).hexdigest(), self.clock())).fetchone()
        return dict(row) if row else None

    def new_session(self, *, role="visitor", old_token=None):
        if not old_token:
            self.rate("new_sessions", 100, 60)
        token = secrets.token_urlsafe(32)
        owner = "operator" if role == "owner" else secrets.token_hex(16)
        csrf = secrets.token_urlsafe(32)
        with self.db(write=True) as db:
            db.execute("DELETE FROM sessions WHERE expires<=?", (self.clock(),))
            if old_token:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(old_token.encode()).hexdigest(),))
            if db.execute("SELECT count(*) FROM sessions").fetchone()[0] >= 1000:
                raise RateLimited("Session capacity reached. Try again later.")
            db.execute("INSERT INTO sessions VALUES(?,?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), owner, role, csrf, self.clock() + 3600))
        return token, self.session(token)

    def recover(self):
        with self.db(write=True) as db:
            db.execute("UPDATE jobs SET status='interrupted', error='Server restarted; this job was interrupted. Start a new comparison.' WHERE status='running'")

    def auth_revision(self, fingerprint):
        with self.db(write=True) as db:
            old = db.execute("SELECT value FROM metadata WHERE key='auth_revision'").fetchone()
            if not old or old[0] != fingerprint:
                db.execute("DELETE FROM sessions WHERE role='owner'")
                db.execute("INSERT INTO metadata VALUES('auth_revision',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(fingerprint,))

    def cleanup(self, force=False):
        with self._cleanup_lock:
            if not force and self._last_cleanup is not None and self.clock()-self._last_cleanup < 30:
                return
            self._cleanup()
            self._last_cleanup = self.clock()

    def _cleanup(self):
        with self.db(write=True) as db:
            rows = db.execute("SELECT id FROM jobs WHERE status!='running' AND created<?", (self.clock()-self.retention_seconds,)).fetchall()
            count = db.execute("SELECT count(*) FROM jobs").fetchone()[0]
            if count >= 100:
                rows += db.execute("SELECT id FROM jobs WHERE status!='running' ORDER BY created LIMIT ?", (count-99,)).fetchall()
            ids = {r[0] for r in rows}
            db.executemany("DELETE FROM jobs WHERE id=?", [(job,) for job in ids])
            db.execute("DELETE FROM sessions WHERE expires<=?", (self.clock(),))
            db.execute("DELETE FROM rates WHERE expires<=?", (self.clock(),))
            cutoff = datetime.fromtimestamp(self.clock()-90*86400,timezone.utc).date().isoformat()
            db.execute("DELETE FROM attempts WHERE day<?", (cutoff,))
        base = (self.directory / "runs").resolve()
        for job in ids:
            if re.fullmatch(r"[a-f0-9]{24}", job):
                target = (base / job).resolve()
                if target.is_relative_to(base) and target != base and target.exists():
                    shutil.rmtree(target)

    def create_job(self, owner):
        self.cleanup(force=True)
        self.rate("start:"+owner, 3, 300)
        self.rate("global_starts", 20, 60)
        job = secrets.token_hex(12)
        with self.db(write=True) as db:
            if db.execute("SELECT count(*) FROM jobs WHERE status='running'").fetchone()[0] >= 2:
                raise RateLimited("Two comparisons are running. Try again shortly.")
            if db.execute("SELECT count(*) FROM jobs WHERE owner=? AND status='running'", (owner,)).fetchone()[0]:
                raise RateLimited("Your comparison is already running.")
            db.execute("INSERT INTO jobs VALUES(?,?,'running',?,'[]',NULL,NULL)", (job, owner, self.clock()))
        return job

    def event(self, job, side, event):
        with self.db(write=True) as db:
            row = db.execute("SELECT events FROM jobs WHERE id=?", (job,)).fetchone()
            events = json.loads(row[0])
            events.append(dict(side=side, **event))
            db.execute("UPDATE jobs SET events=? WHERE id=?", (json.dumps(events), job))

    def finish(self, job, *, result=None, error=None):
        with self.db(write=True) as db:
            db.execute("UPDATE jobs SET status=?, result=?, error=? WHERE id=?", ("completed" if result is not None else "failed",
                json.dumps(result) if result is not None else None, error, job))

    def snapshot(self, job, owner, after=0):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=? AND owner=?", (job, owner)).fetchone()
        if not row or (row["status"] != "running" and row["created"] < self.clock()-self.retention_seconds):
            raise KeyError("Unknown evaluation")
        events = json.loads(row["events"])
        return dict(status=row["status"], events=events[after:], cursor=len(events),
            result=json.loads(row["result"]) if row["result"] else None, error=row["error"])

    def daily_guard(self, job, stop_when=None):
        return DailyGuard(self, job, stop_when)

    def daily_usage(self):
        day = datetime.fromtimestamp(self.clock(), timezone.utc).date().isoformat()
        with self.db() as db:
            row = db.execute("SELECT count(*),coalesce(sum(accounted),0) FROM attempts WHERE day=?", (day,)).fetchone()
        return dict(day=day, calls=row[0], accounted_usd=str(Decimal(row[1])/SCALE),
                    max_calls=self.daily_calls, max_usd=str(self.daily_usd))


class DailyGuard:
    def __init__(self, store, job, stop_when=None):
        self.store, self.job = store, job
        self.stop_when = stop_when

    def reserve(self, attempt):
        if self.stop_when and self.stop_when():
            raise ExecutionDenied("execution_cancelled")
        store = self.store
        day = datetime.fromtimestamp(store.clock(), timezone.utc).date().isoformat()
        amount = units(attempt.reserved_usd)
        reservation = secrets.token_hex(16)
        with store.db(write=True) as db:
            count, total = db.execute("SELECT count(*),coalesce(sum(accounted),0) FROM attempts WHERE day=?", (day,)).fetchone()
            if count >= store.daily_calls:
                raise ExecutionDenied("daily_call_limit_reached")
            if total + amount > units(store.daily_usd):
                raise ExecutionDenied("daily_spend_limit_reached")
            db.execute("INSERT INTO attempts VALUES(?,?,?,?)", (reservation, self.job, day, amount))
        return reservation

    def reconcile(self, reservation, amount):
        with self.store.db(write=True) as db:
            db.execute("UPDATE attempts SET accounted=? WHERE id=? AND job_id=?", (units(amount), reservation, self.job))
