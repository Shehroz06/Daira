"""Persistent chat history for Daira.

Separate from app.daira's in-memory Session (which stays bounded/ephemeral,
used only to give the LLM short-term conversational context). This module
holds the full, durable transcript that the frontend's history drawer lists,
opens, and deletes:

    daira.chat()
        │  (question, full answer, sources, provider)
        ▼
    record_turn() ──upsert──▶  chats(id, title, created_at, updated_at)
                   ──insert─▶  messages(id, chat_id, role, text,
                                        provider, sources_json, created_at)

A fresh sqlite3 connection is opened and closed per call — no long-lived
global connection — so this needs no thread-safety handling despite FastAPI
serving requests from a threadpool. Every public function degrades
gracefully (log + return the documented empty/failure value) rather than
raising, matching how Gemini failures fall back to Ollama silently
elsewhere in this codebase — a chat-history hiccup must never break a
/chat request.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("daira.chat_store")

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "chats.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id      TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role         TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    text         TEXT NOT NULL,
    provider     TEXT,
    sources_json TEXT,
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _derive_title(text: str) -> str:
    t = " ".join(text.split())
    return t[:60] + "…" if len(t) > 60 else t


def init_db() -> None:
    """Create the schema if it doesn't exist. Idempotent."""
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = _connect()
        try:
            with conn:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.executescript(_SCHEMA)
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        logger.error("Failed to initialize chat history DB: %s", exc)


def record_turn(
    chat_id: str,
    user_text: str,
    assistant_text: str,
    *,
    provider: Optional[str] = None,
    sources: Optional[list[dict]] = None,
) -> None:
    """Append one user + one assistant message, creating the chat row (with
    a title derived from user_text) on first use. Never raises."""
    now = time.time()
    sources_json = json.dumps(sources, ensure_ascii=False) if sources else None
    try:
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    """INSERT INTO chats (id, title, created_at, updated_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at""",
                    (chat_id, _derive_title(user_text), now, now),
                )
                conn.execute(
                    """INSERT INTO messages (chat_id, role, text, provider, sources_json, created_at)
                       VALUES (?, 'user', ?, NULL, NULL, ?)""",
                    (chat_id, user_text, now),
                )
                conn.execute(
                    """INSERT INTO messages (chat_id, role, text, provider, sources_json, created_at)
                       VALUES (?, 'assistant', ?, ?, ?, ?)""",
                    (chat_id, assistant_text, provider, sources_json, now),
                )
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        logger.error("Failed to record chat turn for %r: %s", chat_id, exc)


def list_chats() -> list[dict]:
    """[{"id", "title", "updated_at"}, ...] ordered by most recently updated."""
    try:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT id, title, updated_at FROM chats ORDER BY updated_at DESC"
            ).fetchall()
        finally:
            conn.close()
        return [{"id": r[0], "title": r[1], "updated_at": r[2]} for r in rows]
    except (sqlite3.Error, OSError) as exc:
        logger.error("Failed to list chats: %s", exc)
        return []


def get_chat(chat_id: str) -> Optional[dict]:
    """Full transcript for one chat, or None if missing/on failure."""
    try:
        conn = _connect()
        try:
            chat_row = conn.execute(
                "SELECT id, title FROM chats WHERE id = ?", (chat_id,)
            ).fetchone()
            if chat_row is None:
                return None
            message_rows = conn.execute(
                """SELECT role, text, provider, sources_json, created_at
                   FROM messages WHERE chat_id = ? ORDER BY id""",
                (chat_id,),
            ).fetchall()
        finally:
            conn.close()
        messages = [
            {
                "role": role,
                "text": text,
                "provider": provider,
                "sources": json.loads(sources_json) if sources_json else None,
                "created_at": created_at,
            }
            for role, text, provider, sources_json, created_at in message_rows
        ]
        return {"id": chat_row[0], "title": chat_row[1], "messages": messages}
    except (sqlite3.Error, OSError) as exc:
        logger.error("Failed to load chat %r: %s", chat_id, exc)
        return None


def delete_chat(chat_id: str) -> bool:
    """Delete a chat and its messages. True if a chat was actually deleted."""
    try:
        conn = _connect()
        try:
            with conn:
                cur = conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
                rowcount = cur.rowcount
        finally:
            conn.close()
        return rowcount > 0
    except (sqlite3.Error, OSError) as exc:
        logger.error("Failed to delete chat %r: %s", chat_id, exc)
        return False
