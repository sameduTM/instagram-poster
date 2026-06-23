"""
Tiny SQLite data layer. No ORM — just plain SQL, kept simple on purpose.

Two tables:
  accounts        -> one row per connected Instagram account (we support one
                      "active" account at a time, but the schema allows more)
  scheduled_posts -> every post you've asked the app to publish, plus its status
"""
import sqlite3
from datetime import datetime, timezone
from config import Config

DB_PATH = Config.DATABASE_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ig_user_id TEXT UNIQUE NOT NULL,
            username TEXT,
            access_token TEXT NOT NULL,
            token_expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            caption TEXT,
            media_url TEXT NOT NULL,
            media_type TEXT NOT NULL DEFAULT 'IMAGE',   -- IMAGE | VIDEO | REELS
            scheduled_time TEXT NOT NULL,                -- ISO 8601, UTC
            status TEXT NOT NULL DEFAULT 'pending',      -- pending|processing|published|failed|canceled
            container_id TEXT,
            ig_media_id TEXT,
            permalink TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- accounts --

def save_account(ig_user_id, username, access_token, token_expires_at):
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM accounts WHERE ig_user_id = ?", (ig_user_id,)
    ).fetchone()
    ts = now_iso()
    if existing:
        conn.execute(
            """UPDATE accounts SET username=?, access_token=?, token_expires_at=?, updated_at=?
               WHERE ig_user_id=?""",
            (username, access_token, token_expires_at, ts, ig_user_id),
        )
    else:
        conn.execute(
            """INSERT INTO accounts (ig_user_id, username, access_token, token_expires_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ig_user_id, username, access_token, token_expires_at, ts, ts),
        )
    conn.commit()
    conn.close()


def get_active_account():
    """Returns the most recently updated connected account, or None."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM accounts ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_accounts():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM accounts").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_account_token(account_id, access_token, token_expires_at):
    conn = get_connection()
    conn.execute(
        "UPDATE accounts SET access_token=?, token_expires_at=?, updated_at=? WHERE id=?",
        (access_token, token_expires_at, now_iso(), account_id),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------- scheduled posts --

def create_scheduled_post(account_id, caption, media_url, media_type, scheduled_time):
    conn = get_connection()
    ts = now_iso()
    cur = conn.execute(
        """INSERT INTO scheduled_posts
           (account_id, caption, media_url, media_type, scheduled_time, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
        (account_id, caption, media_url, media_type, scheduled_time, ts, ts),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def get_post(post_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM scheduled_posts WHERE id=?", (post_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_posts():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM scheduled_posts ORDER BY scheduled_time DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_due_posts(now_iso_str):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM scheduled_posts WHERE status='pending' AND scheduled_time <= ?",
        (now_iso_str,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_post_status(post_id, status, **fields):
    """fields can include: container_id, ig_media_id, permalink, error_message"""
    allowed = {"container_id", "ig_media_id", "permalink", "error_message"}
    set_clauses = ["status=?", "updated_at=?"]
    values = [status, now_iso()]
    for key, value in fields.items():
        if key in allowed:
            set_clauses.append(f"{key}=?")
            values.append(value)
    values.append(post_id)
    conn = get_connection()
    conn.execute(
        f"UPDATE scheduled_posts SET {', '.join(set_clauses)} WHERE id=?", values
    )
    conn.commit()
    conn.close()


def cancel_post(post_id):
    conn = get_connection()
    conn.execute(
        "UPDATE scheduled_posts SET status='canceled', updated_at=? WHERE id=? AND status='pending'",
        (now_iso(), post_id),
    )
    conn.commit()
    conn.close()
