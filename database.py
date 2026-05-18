import sqlite3
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "/app/signals.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_number    INTEGER,
            symbol           TEXT NOT NULL,
            buy_low          REAL,
            buy_high         REAL,
            stop             REAL,
            t1               REAL,
            t2               REAL,
            t3               REAL,
            t4               REAL,
            t5               REAL,
            rr               REAL,
            channel_strength REAL,
            entry_price      REAL,
            result           TEXT DEFAULT 'OPEN',
            profit_pct       REAL DEFAULT 0,
            hit_target       INTEGER DEFAULT 0,
            sent_at          TEXT,
            closed_at        TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_next_signal_number() -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM signals")
    count = c.fetchone()[0]
    conn.close()
    return count + 1


def is_signal_sent_recently(symbol: str, hours: int = 96) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*) FROM signals
        WHERE symbol = ?
        AND sent_at >= datetime('now', ?)
    """, (symbol, f'-{hours} hours'))
    count = c.fetchone()[0]
    conn.close()
    return count > 0


def save_signal(signal: dict):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    targets = signal["targets"]
    buy_low, buy_high = signal["buy_zone"]
    entry_price = round((buy_low + buy_high) / 2, 8)
    c.execute("""
        INSERT INTO signals
        (signal_number, symbol, buy_low, buy_high, stop,
         t1, t2, t3, t4, t5, rr, channel_strength, entry_price, sent_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        signal.get("signal_number"),
        signal["symbol"],
        buy_low,
        buy_high,
        signal["stop"],
        targets.get("T1"),
        targets.get("T2"),
        targets.get("T3"),
        targets.get("T4"),
        targets.get("T5"),
        signal["rr"],
        signal.get("channel_strength"),
        entry_price,
        datetime.utcnow().isoformat()
    ))
    conn.commit()
    conn.close()


def get_open_signals() -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM signals WHERE result = 'OPEN'")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def close_signal(signal_id: int, result: str, profit_pct: float, hit_target: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE signals
        SET result=?, profit_pct=?, hit_target=?, closed_at=?
        WHERE id=?
    """, (result, profit_pct, hit_target, datetime.utcnow().isoformat(), signal_id))
    conn.commit()
    conn.close()


def get_signals_last_days(days: int) -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM signals
        WHERE sent_at >= datetime('now', ?)
        AND result != 'OPEN'
        ORDER BY sent_at DESC
    """, (f'-{days} days',))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows
