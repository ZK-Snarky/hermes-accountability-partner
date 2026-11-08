"""The promise ledger: what the user said they would do, and what they reported doing.

Plain sqlite, one file per Hermes profile. Nothing here talks to a model: every count, streak
and verdict is computed from rows, so the agent can't round a miss up to a win.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

CADENCES = ("daily", "weekdays", "weekly", "once")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS promises (
    id INTEGER PRIMARY KEY,
    what TEXT NOT NULL,
    cadence TEXT NOT NULL,
    per_week INTEGER NOT NULL DEFAULT 1,
    due TEXT,
    consequence TEXT,
    proof TEXT,
    enforcer TEXT,
    max_amount REAL,
    pay_to TEXT,
    locked_until TEXT,
    locked_at TEXT,
    starts TEXT,
    proof_tool TEXT,
    proof_args TEXT,
    rule TEXT,
    data_decides INTEGER,
    quote TEXT NOT NULL,
    created TEXT NOT NULL,
    dropped TEXT,
    drop_quote TEXT
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    promise_id INTEGER NOT NULL REFERENCES promises(id),
    day TEXT NOT NULL,
    kept INTEGER NOT NULL,
    quote TEXT NOT NULL,
    source TEXT,
    at TEXT NOT NULL,
    UNIQUE (promise_id, day)
);
CREATE TABLE IF NOT EXISTS enforcements (
    id INTEGER PRIMARY KEY,
    promise_id INTEGER NOT NULL REFERENCES promises(id),
    period TEXT NOT NULL,
    source TEXT NOT NULL,
    evidence TEXT NOT NULL,
    at TEXT NOT NULL,
    UNIQUE (promise_id, period)
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass(frozen=True)
class Promise:
    id: int
    what: str
    cadence: str
    per_week: int
    due: Optional[str]
    consequence: Optional[str]
    proof: Optional[str]
    quote: str
    created: str
    enforcer: Optional[str] = None
    max_amount: Optional[float] = None
    pay_to: Optional[str] = None
    locked_until: Optional[str] = None
    locked_at: Optional[str] = None
    starts: Optional[str] = None
    proof_tool: Optional[str] = None
    proof_args: Optional[str] = None
    rule: Optional[str] = None
    data_decides: bool = False

    def _from(self) -> str:
        return _from_label(self)

    def first_day(self) -> date:
        return date.fromisoformat(self.starts or self.created[:10])

    def label(self) -> str:
        if self.cadence in ("daily", "weekdays"):
            return f"{self.what} ({self.cadence}{self._from()})"
        if self.cadence == "weekly":
            return f"{self.what} ({self.per_week}x a week{self._from()})"
        return f"{self.what} (by {self.due})" if self.due else f"{self.what} (once)"


def _from_label(p: "Promise") -> str:
    if not p.starts or date.fromisoformat(p.starts) <= date.fromisoformat(p.created[:10]):
        return ""
    d = date.fromisoformat(p.starts)
    return f", from {d.strftime('%b')} {d.day}"


def week_start(day: date) -> date:
    """Weeks run Monday to Sunday."""
    return day - timedelta(days=day.weekday())


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._add_new_columns()
        self._db.commit()

    def _add_new_columns(self) -> None:
        """Ledgers made by an older version get the newer columns (all optional)."""
        have = {r["name"] for r in self._db.execute("PRAGMA table_info(promises)")}
        for col, kind in (("proof", "TEXT"), ("enforcer", "TEXT"), ("max_amount", "REAL"),
                          ("pay_to", "TEXT"), ("locked_until", "TEXT"), ("locked_at", "TEXT"),
                          ("starts", "TEXT"), ("proof_tool", "TEXT"), ("proof_args", "TEXT"), ("rule", "TEXT"),
                          ("data_decides", "INTEGER")):
            if col not in have:
                self._db.execute(f"ALTER TABLE promises ADD COLUMN {col} {kind}")
        if "source" not in {r["name"] for r in self._db.execute("PRAGMA table_info(reports)")}:
            self._db.execute("ALTER TABLE reports ADD COLUMN source TEXT")

    # --- promises -------------------------------------------------------------------------

    def add(self, what: str, cadence: str, quote: str, *, per_week: int = 1,
            due: Optional[str] = None, consequence: Optional[str] = None,
            proof: Optional[str] = None, enforcer: Optional[str] = None,
            max_amount: Optional[float] = None, pay_to: Optional[str] = None,
            starts: Optional[str] = None, proof_tool: Optional[str] = None,
            proof_args: Optional[str] = None,
            rule: Optional[str] = None, data_decides: bool = False,
            now: Optional[datetime] = None) -> Promise:
        what = " ".join((what or "").split())
        if not what:
            raise ValueError("say what the promise is")
        if cadence not in CADENCES:
            raise ValueError(f"cadence must be one of {', '.join(CADENCES)}")
        if cadence == "weekly" and not 1 <= int(per_week) <= 7:
            raise ValueError("per_week must be 1 to 7")
        if due:
            date.fromisoformat(due)  # raises on a bad date
        if starts:
            date.fromisoformat(starts)
        now = now or datetime.now()
        cur = self._db.execute(
            "INSERT INTO promises (what, cadence, per_week, due, consequence, proof, enforcer,"
            " max_amount, pay_to, starts, proof_tool, proof_args, rule, data_decides, quote, created)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (what, cadence, int(per_week) if cadence == "weekly" else 1, due,
             (consequence or "").strip() or None, (proof or "").strip() or None,
             (enforcer or "").strip() or None, float(max_amount) if max_amount else None,
             (pay_to or "").strip() or None, starts or None, (proof_tool or "").strip() or None, proof_args or None,
             (rule or "").strip() or None, 1 if data_decides else None, quote, now.isoformat(timespec="seconds")))
        self._db.commit()
        return self.get(cur.lastrowid)

    def get(self, promise_id: int) -> Promise:
        row = self._db.execute(
            "SELECT * FROM promises WHERE id = ? AND dropped IS NULL", (int(promise_id),)).fetchone()
        if row is None:
            raise KeyError(f"no open promise #{promise_id}")
        return _promise(row)

    def _get_any(self, promise_id: int) -> Promise:
        row = self._db.execute("SELECT * FROM promises WHERE id = ?", (int(promise_id),)).fetchone()
        if row is None:
            raise KeyError(f"no promise #{promise_id}")
        return _promise(row)

    def active(self, include_finished: bool = False) -> list[Promise]:
        """Open promises. A one-time promise leaves the list once it has been reported, unless
        ``include_finished``."""
        rows = self._db.execute(
            "SELECT * FROM promises WHERE dropped IS NULL ORDER BY id").fetchall()
        out = []
        for row in rows:
            p = _promise(row)
            if p.cadence == "once" and not include_finished and self.last_report(p.id) is not None:
                continue
            out.append(p)
        return out

    def lock(self, promise_id: int, until: date, now: Optional[datetime] = None) -> Promise:
        now = now or datetime.now()
        self._db.execute("UPDATE promises SET locked_until = ?, locked_at = ? WHERE id = ?",
                         (until.isoformat(), now.isoformat(timespec="seconds"), int(promise_id)))
        self._db.commit()
        return self.get(promise_id)

    def drop(self, promise_id: int, quote: str, now: Optional[datetime] = None) -> Promise:
        p = self.get(promise_id)
        now = now or datetime.now()
        if locked(p, now):
            raise ValueError(f"#{p.id} is locked in until {p.locked_until}. It can't be dropped or "
                             "softened before then; that was the deal.")
        self._db.execute("UPDATE promises SET dropped = ?, drop_quote = ? WHERE id = ?",
                         (now.isoformat(timespec="seconds"), quote, p.id))
        self._db.commit()
        return p

    # --- reports --------------------------------------------------------------------------

    def report(self, promise_id: int, day: date, kept: bool, quote: str,
               now: Optional[datetime] = None, source: Optional[str] = None) -> None:
        """Record one promise on one day: the user's word (``source`` None) or a tool's receipt
        (``source`` = the tool's name, ``quote`` = what it returned). A later report for the day wins."""
        self._get_any(promise_id)
        now = now or datetime.now()
        self._db.execute(
            "INSERT INTO reports (promise_id, day, kept, quote, source, at) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (promise_id, day) DO UPDATE SET kept = excluded.kept,"
            " quote = excluded.quote, source = excluded.source, at = excluded.at",
            (int(promise_id), day.isoformat(), 1 if kept else 0, quote, source,
             now.isoformat(timespec="seconds")))
        self._db.commit()

    def day_report(self, promise_id: int, day: date) -> Optional[bool]:
        row = self._db.execute("SELECT kept FROM reports WHERE promise_id = ? AND day = ?",
                               (int(promise_id), day.isoformat())).fetchone()
        return None if row is None else bool(row["kept"])

    def receipt(self, promise_id: int, day: date) -> Optional[str]:
        """The tool that proved this day, if a tool did."""
        row = self._db.execute("SELECT source FROM reports WHERE promise_id = ? AND day = ?",
                               (int(promise_id), day.isoformat())).fetchone()
        return None if row is None else row["source"]

    def report_quote(self, promise_id: int, day: date) -> Optional[str]:
        row = self._db.execute("SELECT quote FROM reports WHERE promise_id = ? AND day = ?",
                               (int(promise_id), day.isoformat())).fetchone()
        return None if row is None else row["quote"]

    def kept_with_receipts(self, promise_id: int, start: date, end: date) -> int:
        return self._db.execute(
            "SELECT COUNT(*) FROM reports WHERE promise_id = ? AND kept = 1 AND source IS NOT NULL"
            " AND day BETWEEN ? AND ?", (int(promise_id), start.isoformat(), end.isoformat())).fetchone()[0]

    def last_report(self, promise_id: int) -> Optional[bool]:
        row = self._db.execute("SELECT kept FROM reports WHERE promise_id = ? ORDER BY day DESC LIMIT 1",
                               (int(promise_id),)).fetchone()
        return None if row is None else bool(row["kept"])

    def kept_between(self, promise_id: int, start: date, end: date) -> int:
        """Days marked kept in [start, end]."""
        return self._db.execute(
            "SELECT COUNT(*) FROM reports WHERE promise_id = ? AND kept = 1 AND day BETWEEN ? AND ?",
            (int(promise_id), start.isoformat(), end.isoformat())).fetchone()[0]

    def streak(self, promise_id: int, today: date, weekdays_only: bool = False) -> int:
        """Consecutive kept days ending today (or the day before, if today has no word yet).
        ``weekdays_only`` steps over weekends."""
        def back(d: date) -> date:
            d -= timedelta(days=1)
            while weekdays_only and d.weekday() >= 5:
                d -= timedelta(days=1)
            return d
        day = today if self.day_report(promise_id, today) is not None else back(today)
        count = 0
        while self.day_report(promise_id, day) is True:
            count += 1
            day = back(day)
        return count

    # --- consequences --------------------------------------------------------------------

    def misses(self, promise_id: int, start: date, end: date) -> list[date]:
        rows = self._db.execute(
            "SELECT day FROM reports WHERE promise_id = ? AND kept = 0 AND day BETWEEN ? AND ? ORDER BY day",
            (int(promise_id), start.isoformat(), end.isoformat())).fetchall()
        return [date.fromisoformat(r["day"]) for r in rows]

    def enforce(self, promise_id: int, period: str, source: str, evidence: str,
                now: Optional[datetime] = None) -> None:
        """A consequence was carried out: ``source`` tool returned ``evidence``."""
        now = now or datetime.now()
        self._db.execute(
            "INSERT OR REPLACE INTO enforcements (promise_id, period, source, evidence, at)"
            " VALUES (?, ?, ?, ?, ?)",
            (int(promise_id), period, source, evidence, now.isoformat(timespec="seconds")))
        self._db.commit()

    def enforced(self, promise_id: int, period: str) -> Optional[str]:
        row = self._db.execute("SELECT source FROM enforcements WHERE promise_id = ? AND period = ?",
                               (int(promise_id), period)).fetchone()
        return None if row is None else row["source"]

    # --- check-in state -------------------------------------------------------------------

    def set_pending(self, day: date, ids: Iterable[int], now: Optional[datetime] = None) -> None:
        now = now or datetime.now()
        value = f"{day.isoformat()}|{now.isoformat(timespec='seconds')}|{','.join(str(i) for i in ids)}"
        self._db.execute("INSERT INTO state (key, value) VALUES ('pending', ?)"
                         " ON CONFLICT (key) DO UPDATE SET value = excluded.value", (value,))
        self._db.commit()

    def pending(self, now: Optional[datetime] = None, max_age_hours: int = 18):
        """(day, [ids]) of the last check-in still waiting for an answer, or None."""
        row = self._db.execute("SELECT value FROM state WHERE key = 'pending'").fetchone()
        if row is None:
            return None
        day, asked, ids = row["value"].split("|")
        now = now or datetime.now()
        if now - datetime.fromisoformat(asked) > timedelta(hours=max_age_hours):
            return None
        return date.fromisoformat(day), [int(i) for i in ids.split(",") if i]

    def set_reading(self, promise_id: int, day: date, text: str) -> None:
        """What a proof tool showed when it didn't meet the rule; shown at the check-in."""
        self._db.execute("INSERT INTO state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE"
                         " SET value = excluded.value", (f"reading:{promise_id}:{day.isoformat()}", text))
        self._db.commit()

    def reading(self, promise_id: int, day: date) -> Optional[str]:
        row = self._db.execute("SELECT value FROM state WHERE key = ?",
                               (f"reading:{promise_id}:{day.isoformat()}",)).fetchone()
        return row["value"] if row else None

    def clear_pending(self) -> None:
        self._db.execute("DELETE FROM state WHERE key = 'pending'")
        self._db.commit()


COOL_OFF = timedelta(hours=24)


def locked(p: Promise, now: datetime) -> bool:
    """Locked in, past the 24-hour cool-off, and before the end date."""
    if not p.locked_until or not p.locked_at:
        return False
    return (now - datetime.fromisoformat(p.locked_at) >= COOL_OFF
            and now.date() <= date.fromisoformat(p.locked_until))


def _promise(row: sqlite3.Row) -> Promise:
    return Promise(id=row["id"], what=row["what"], cadence=row["cadence"],
                   per_week=row["per_week"], due=row["due"], consequence=row["consequence"],
                   proof=row["proof"], enforcer=row["enforcer"], max_amount=row["max_amount"],
                   pay_to=row["pay_to"], locked_until=row["locked_until"], locked_at=row["locked_at"],
                   starts=row["starts"], proof_tool=row["proof_tool"], proof_args=row["proof_args"], rule=row["rule"],
                   data_decides=bool(row["data_decides"]), quote=row["quote"], created=row["created"])
