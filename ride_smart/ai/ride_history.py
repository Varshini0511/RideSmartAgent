"""Ride history database — SQLite storage for all comparisons, bookings,
and user choices.  Foundation for every ML feature.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

from ride_smart.models import Location, RideComparison, RideQuote

DB_DIR = Path.home() / ".ridesmart"
DB_PATH = DB_DIR / "history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS comparisons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    day_of_week INTEGER NOT NULL,
    hour        INTEGER NOT NULL,
    pickup_addr TEXT    NOT NULL,
    pickup_lat  REAL,
    pickup_lng  REAL,
    drop_addr   TEXT    NOT NULL,
    drop_lat    REAL,
    drop_lng    REAL,
    distance_km REAL
);

CREATE TABLE IF NOT EXISTS quotes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    comparison_id INTEGER NOT NULL REFERENCES comparisons(id),
    provider      TEXT    NOT NULL,
    ride_type     TEXT    NOT NULL,
    vehicle_type  TEXT,
    price         REAL    NOT NULL,
    eta_minutes   INTEGER,
    surge         REAL    DEFAULT 1.0,
    is_estimated  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bookings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    comparison_id INTEGER NOT NULL REFERENCES comparisons(id),
    quote_id      INTEGER REFERENCES quotes(id),
    provider      TEXT    NOT NULL,
    vehicle_type  TEXT,
    price         REAL    NOT NULL,
    status        TEXT    NOT NULL,
    wait_seconds  INTEGER,
    ts            REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS user_choices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    comparison_id INTEGER NOT NULL REFERENCES comparisons(id),
    chosen_provider  TEXT NOT NULL,
    chosen_vehicle   TEXT,
    chosen_price     REAL NOT NULL,
    cheapest_provider TEXT,
    cheapest_price    REAL,
    ts               REAL NOT NULL
);
"""


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(_SCHEMA)


def save_comparison(
    pickup: Location,
    dropoff: Location,
    quotes: list[RideQuote],
    distance_km: float | None = None,
) -> int:
    init_db()
    now = datetime.now()
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO comparisons
               (ts, day_of_week, hour, pickup_addr, pickup_lat, pickup_lng,
                drop_addr, drop_lat, drop_lng, distance_km)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(), now.weekday(), now.hour,
                pickup.address, pickup.latitude, pickup.longitude,
                dropoff.address, dropoff.latitude, dropoff.longitude,
                distance_km,
            ),
        )
        comp_id = cur.lastrowid

        for q in quotes:
            conn.execute(
                """INSERT INTO quotes
                   (comparison_id, provider, ride_type, vehicle_type,
                    price, eta_minutes, surge, is_estimated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    comp_id, q.provider.value, q.ride_type.value,
                    q.vehicle_type, q.price, q.eta_minutes,
                    q.surge_multiplier,
                    1 if q.distance_km and not q.eta_minutes else 0,
                ),
            )

        return comp_id


def save_booking(
    comparison_id: int,
    provider: str,
    vehicle_type: str,
    price: float,
    status: str,
    wait_seconds: int | None = None,
) -> int:
    init_db()
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO bookings
               (comparison_id, provider, vehicle_type, price, status,
                wait_seconds, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (comparison_id, provider, vehicle_type, price, status,
             wait_seconds, time.time()),
        )
        return cur.lastrowid


def save_user_choice(
    comparison_id: int,
    chosen_provider: str,
    chosen_vehicle: str,
    chosen_price: float,
    cheapest_provider: str | None = None,
    cheapest_price: float | None = None,
) -> None:
    init_db()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO user_choices
               (comparison_id, chosen_provider, chosen_vehicle, chosen_price,
                cheapest_provider, cheapest_price, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (comparison_id, chosen_provider, chosen_vehicle, chosen_price,
             cheapest_provider, cheapest_price, time.time()),
        )


def get_route_history(
    pickup_addr: str, drop_addr: str, limit: int = 50
) -> list[dict]:
    init_db()
    with _conn() as conn:
        rows = conn.execute(
            """SELECT c.*, q.provider, q.vehicle_type, q.price,
                      q.eta_minutes, q.surge
               FROM comparisons c
               JOIN quotes q ON q.comparison_id = c.id
               WHERE c.pickup_addr = ? AND c.drop_addr = ?
               ORDER BY c.ts DESC
               LIMIT ?""",
            (pickup_addr, drop_addr, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_history(limit: int = 200) -> list[dict]:
    init_db()
    with _conn() as conn:
        rows = conn.execute(
            """SELECT c.id, c.ts, c.day_of_week, c.hour,
                      c.pickup_addr, c.drop_addr, c.distance_km,
                      q.provider, q.vehicle_type, q.price,
                      q.eta_minutes, q.surge
               FROM comparisons c
               JOIN quotes q ON q.comparison_id = c.id
               ORDER BY c.ts DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_user_choices(limit: int = 100) -> list[dict]:
    init_db()
    with _conn() as conn:
        rows = conn.execute(
            """SELECT * FROM user_choices ORDER BY ts DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_frequent_routes(limit: int = 10) -> list[dict]:
    init_db()
    with _conn() as conn:
        rows = conn.execute(
            """SELECT pickup_addr, drop_addr,
                      COUNT(*) as trip_count,
                      AVG(hour) as avg_hour,
                      GROUP_CONCAT(DISTINCT day_of_week) as days
               FROM comparisons
               GROUP BY pickup_addr, drop_addr
               ORDER BY trip_count DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_price_stats(
    pickup_addr: str, drop_addr: str, provider: str
) -> dict | None:
    init_db()
    with _conn() as conn:
        row = conn.execute(
            """SELECT provider,
                      AVG(q.price) as avg_price,
                      MIN(q.price) as min_price,
                      MAX(q.price) as max_price,
                      COUNT(*) as sample_count,
                      AVG(q.eta_minutes) as avg_eta
               FROM comparisons c
               JOIN quotes q ON q.comparison_id = c.id
               WHERE c.pickup_addr = ? AND c.drop_addr = ?
                 AND q.provider = ?
               GROUP BY q.provider""",
            (pickup_addr, drop_addr, provider),
        ).fetchone()
        return dict(row) if row else None


def get_hourly_prices(
    pickup_addr: str, drop_addr: str, provider: str
) -> list[dict]:
    init_db()
    with _conn() as conn:
        rows = conn.execute(
            """SELECT c.hour, AVG(q.price) as avg_price,
                      COUNT(*) as samples
               FROM comparisons c
               JOIN quotes q ON q.comparison_id = c.id
               WHERE c.pickup_addr = ? AND c.drop_addr = ?
                 AND q.provider = ?
               GROUP BY c.hour
               ORDER BY c.hour""",
            (pickup_addr, drop_addr, provider),
        ).fetchall()
        return [dict(r) for r in rows]
