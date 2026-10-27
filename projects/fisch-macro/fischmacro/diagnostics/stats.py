"""Session statistics, persisted locally in SQLite."""
from __future__ import annotations

import csv
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from fischmacro import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile TEXT, started REAL, ended REAL, simulated INTEGER DEFAULT 0,
    catches INTEGER DEFAULT 0, failures INTEGER DEFAULT 0, unconfirmed INTEGER DEFAULT 0,
    recoveries INTEGER DEFAULT 0, detection_errors INTEGER DEFAULT 0, end_reason TEXT
);
CREATE TABLE IF NOT EXISTS cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER, ended REAL, outcome TEXT, duration REAL, progress REAL,
    perfect_cast INTEGER, shake_clicks INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER, ts REAL, kind TEXT, message TEXT
);
"""


@dataclass
class SessionStats:
    session_id: int | None = None
    profile: str = ""
    started: float = 0.0          # wall clock
    active_seconds: float = 0.0   # excludes pauses
    catches: int = 0
    failures: int = 0
    unconfirmed: int = 0
    recoveries: int = 0
    detection_errors: int = 0
    casts: int = 0
    perfect_casts: int = 0
    durations: list[float] = field(default_factory=list)
    history: list[tuple[str, float]] = field(default_factory=list)  # (outcome, duration) per cycle

    @property
    def cycles(self) -> int:
        return self.catches + self.failures + self.unconfirmed

    @property
    def avg_cycle(self) -> float:
        return sum(self.durations) / len(self.durations) if self.durations else 0.0

    @property
    def catches_per_hour(self) -> float:
        return self.catches / (self.active_seconds / 3600) if self.active_seconds > 60 else 0.0


class StatsStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else paths.stats_db()
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def start_session(self, profile: str, simulated: bool) -> int:
        with self._lock:
            cur = self._conn.execute("INSERT INTO sessions (profile, started, simulated) VALUES (?, ?, ?)",
                                     (profile, time.time(), int(simulated)))
            self._conn.commit()
            return int(cur.lastrowid)

    def end_session(self, stats: SessionStats, reason: str) -> None:
        if stats.session_id is None:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET ended=?, catches=?, failures=?, unconfirmed=?, recoveries=?, "
                "detection_errors=?, end_reason=? WHERE id=?",
                (time.time(), stats.catches, stats.failures, stats.unconfirmed, stats.recoveries,
                 stats.detection_errors, reason, stats.session_id))
            self._conn.commit()

    def add_cycle(self, session_id: int | None, outcome: str, duration: float, progress, perfect, clicks) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO cycles (session_id, ended, outcome, duration, progress, perfect_cast, shake_clicks) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, time.time(), outcome, duration, progress, None if perfect is None else int(perfect), clicks))
            self._conn.commit()

    def add_event(self, session_id: int | None, kind: str, message: str) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO events (session_id, ts, kind, message) VALUES (?, ?, ?, ?)",
                               (session_id, time.time(), kind, message))
            self._conn.commit()

    def sessions(self, limit: int = 200) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT s.id, s.profile, s.started, s.ended, s.simulated, s.catches, s.failures, s.unconfirmed, "
                "s.recoveries, s.detection_errors, s.end_reason, "
                "(SELECT AVG(duration) FROM cycles c WHERE c.session_id = s.id) "
                "FROM sessions s ORDER BY s.id DESC LIMIT ?", (limit,))
            cols = ["id", "profile", "started", "ended", "simulated", "catches", "failures", "unconfirmed",
                    "recoveries", "detection_errors", "end_reason", "avg_cycle"]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def totals(self) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(outcome='success'),0), COALESCE(SUM(outcome='failure'),0), "
                "COALESCE(SUM(outcome='unconfirmed'),0), AVG(duration) FROM cycles").fetchone()
            rec = self._conn.execute("SELECT COUNT(*) FROM events WHERE kind='recovery'").fetchone()[0]
            err = self._conn.execute("SELECT COUNT(*) FROM events WHERE kind IN ('error','detection_error')").fetchone()[0]
        return {"cycles": row[0], "success": row[1], "failure": row[2], "unconfirmed": row[3],
                "avg_duration": row[4] or 0.0, "recoveries": rec, "errors": err}

    def real_catches(self) -> int:
        """Confirmed catches from live (non-simulated) sessions."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM cycles c JOIN sessions s ON s.id = c.session_id "
                                     "WHERE s.simulated = 0 AND c.outcome = 'success'").fetchone()
        return int(row[0])

    def recent_events(self, kinds: tuple[str, ...], limit: int = 200) -> list[dict]:
        q = ",".join("?" * len(kinds))
        with self._lock:
            cur = self._conn.execute(f"SELECT ts, kind, message FROM events WHERE kind IN ({q}) ORDER BY id DESC LIMIT ?",
                                     (*kinds, limit))
            return [{"ts": r[0], "kind": r[1], "message": r[2]} for r in cur.fetchall()]

    def export_csv(self, destination: Path) -> None:
        with self._lock:
            rows = self._conn.execute("SELECT c.id, c.session_id, s.profile, c.ended, c.outcome, c.duration, c.progress, "
                                      "c.perfect_cast, c.shake_clicks FROM cycles c LEFT JOIN sessions s "
                                      "ON s.id = c.session_id ORDER BY c.id").fetchall()
        with open(destination, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["cycle_id", "session_id", "profile", "ended_unix", "outcome", "duration_s", "final_progress",
                        "perfect_cast", "shake_clicks"])
            w.writerows(rows)

    def clear(self) -> None:
        with self._lock:
            self._conn.executescript("DELETE FROM cycles; DELETE FROM events; DELETE FROM sessions;")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
