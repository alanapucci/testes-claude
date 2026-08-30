"""Camada de acesso ao SQLite. Sem dependências externas."""
import os
import sqlite3
import threading

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db")

_local = threading.local()


def get_conn():
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person TEXT NOT NULL DEFAULT 'bebe',  -- 'bebe' | 'rapha'
            type TEXT NOT NULL,        -- 'feed' | 'bath' | 'sleep'
            subtype TEXT,              -- 'peito' | 'mamadeira' (somente feed)
            start_ts TEXT NOT NULL,    -- ISO 8601 local, ex: 2026-08-29T14:05:00
            end_ts TEXT,               -- somente sleep; NULL enquanto em andamento
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS work_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,        -- YYYY-MM-DD
            title TEXT NOT NULL,
            start_ts TEXT NOT NULL,
            end_ts TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS daily_checks (
            date TEXT NOT NULL,        -- YYYY-MM-DD
            key TEXT NOT NULL,         -- 'house:<task_key>' | 'children_bedtime' | 'mom_self_care'
            done_at TEXT NOT NULL,
            PRIMARY KEY (date, key)
        );
        """
    )
    # migracao: bancos criados antes do perfil do Rapha nao tem a coluna 'person'
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(events)").fetchall()]
    if "person" not in cols:
        conn.execute("ALTER TABLE events ADD COLUMN person TEXT NOT NULL DEFAULT 'bebe'")
    conn.commit()
