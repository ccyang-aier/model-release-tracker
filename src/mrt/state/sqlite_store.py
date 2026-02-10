from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from ..models import Alert


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


@dataclass(slots=True)
class SqliteStateStore:
    """
    v0 默认状态存储：SQLite

    表设计（最小可用）：
    - cursors：每个 source_key 的 cursor
    - seen_events：fingerprint 去重集合
    - alerts：告警记录（JSON 形式保存）
    - notify_failures：通知失败留痕（v0 不做队列重试，但保证可追踪）
    """

    sqlite_path: str

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cursors (
                    source_key TEXT PRIMARY KEY,
                    cursor TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_events (
                    fingerprint TEXT PRIMARY KEY,
                    first_seen_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    fingerprint TEXT PRIMARY KEY,
                    alert_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notify_failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def get_cursor(self, source_key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT cursor FROM cursors WHERE source_key = ?", (source_key,)).fetchone()
            if not row:
                return None
            return row["cursor"]

    def set_cursor(self, source_key: str, cursor: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cursors(source_key, cursor, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(source_key) DO UPDATE SET
                    cursor=excluded.cursor,
                    updated_at=excluded.updated_at
                """,
                (source_key, cursor, _utc_now_iso()),
            )

    def has_seen(self, fingerprint: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_events WHERE fingerprint = ? LIMIT 1",
                (fingerprint,),
            ).fetchone()
            return row is not None

    def mark_seen(self, fingerprint: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO seen_events(fingerprint, first_seen_at)
                VALUES(?, ?)
                """,
                (fingerprint, _utc_now_iso()),
            )

    def save_alert(self, alert: Alert) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO alerts(fingerprint, alert_json, created_at)
                VALUES(?, ?, ?)
                """,
                (alert.fingerprint, json.dumps(alert.to_json_dict(), ensure_ascii=False), alert.created_at.isoformat()),
            )

    def record_notify_failure(self, *, fingerprint: str, channel: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO notify_failures(fingerprint, channel, error, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (fingerprint, channel, error, _utc_now_iso()),
            )

