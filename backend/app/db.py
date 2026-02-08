import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

DB_PATH = os.getenv("DB_PATH", "/data/database.db")


def ensure_db_dir() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def get_connection() -> sqlite3.Connection:
    ensure_db_dir()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_cursor() -> Iterator[sqlite3.Cursor]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    ensure_db_dir()
    with db_cursor() as cursor:
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,
                is_blocked INTEGER DEFAULT 0,
                referrer_id INTEGER,
                pro_balance INTEGER DEFAULT 0,
                usd_balance REAL DEFAULT 0,
                is_deposit INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(referrer_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                telegram_id TEXT NOT NULL,
                url TEXT NOT NULL,
                required INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                type TEXT NOT NULL,
                display_type TEXT NOT NULL,
                reward_pro INTEGER DEFAULT 0,
                reward_usd REAL DEFAULT 0,
                channel_id INTEGER,
                offer_url TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(channel_id) REFERENCES channels(id)
            );

            CREATE TABLE IF NOT EXISTS user_tasks (
                user_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, task_id),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(task_id) REFERENCES tasks(id)
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount_pro INTEGER DEFAULT 0,
                amount_usd REAL DEFAULT 0,
                type TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS postbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount_pro INTEGER DEFAULT 0,
                amount_usd REAL DEFAULT 0,
                details TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS broadcast_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL,
                audience TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
