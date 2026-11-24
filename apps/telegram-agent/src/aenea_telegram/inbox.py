"""Durable local Inbox backed by a single SQLite messages table."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from aenea_contracts import IncomingMessage, StoreResult

SCHEMA_VERSION = 1
BUSY_TIMEOUT_SECONDS = 0.5


class InboxError(Exception):
    """Base class for Inbox-specific errors."""


class SchemaVersionError(InboxError):
    """The database schema is unknown or incompatible."""


class MetadataVersionError(InboxError):
    """Stored and incoming metadata projections cannot be compared."""


class ContentConflictError(InboxError):
    """A known message key was received with different stable content."""


class Inbox(Protocol):
    async def accept(self, message: IncomingMessage) -> StoreResult: ...


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Inbox timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _canonical_metadata(raw: str) -> tuple[str, object]:
    value = json.loads(raw)
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return canonical, value


def _stable_metadata(value: object) -> object:
    if isinstance(value, dict) and "content" in value and "snapshot" in value:
        return {key: item for key, item in value.items() if key != "snapshot"}
    return value


class SQLiteInbox:
    """Synchronous short SQLite transactions exposed through async accept."""

    def __init__(self, path: str | Path, *, timeout: float = BUSY_TIMEOUT_SECONDS):
        self.path = Path(path)
        self._connection = sqlite3.connect(self.path, timeout=timeout, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(f"PRAGMA busy_timeout = {max(0, int(timeout * 1000))}")
        try:
            self._initialize()
        except BaseException:
            self._connection.close()
            raise

    def _initialize(self) -> None:
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if version == 0:
            if tables:
                raise SchemaVersionError("Refusing to modify a database with an unknown schema")
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                self._connection.execute(
                    """CREATE TABLE messages (
                        source TEXT NOT NULL,
                        source_account_id INTEGER NOT NULL,
                        chat_id INTEGER NOT NULL,
                        message_id INTEGER NOT NULL,
                        sender_id INTEGER,
                        text TEXT NOT NULL,
                        sent_at TEXT NOT NULL,
                        received_at TEXT NOT NULL,
                        reply_to_message_id INTEGER,
                        reply_to_peer_id INTEGER,
                        topic_id INTEGER,
                        metadata_version INTEGER NOT NULL,
                        metadata_json TEXT NOT NULL,
                        PRIMARY KEY (source, source_account_id, chat_id, message_id)
                    )"""
                )
                self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                self._connection.execute("COMMIT")
            except BaseException:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
            return
        if version != SCHEMA_VERSION or tables != {"messages"}:
            raise SchemaVersionError(f"Unsupported Inbox schema version: {version}")
        schema = self._connection.execute("PRAGMA table_info(messages)").fetchall()
        expected = {
            "source": ("TEXT", 1, 1),
            "source_account_id": ("INTEGER", 1, 2),
            "chat_id": ("INTEGER", 1, 3),
            "message_id": ("INTEGER", 1, 4),
            "sender_id": ("INTEGER", 0, 0),
            "text": ("TEXT", 1, 0),
            "sent_at": ("TEXT", 1, 0),
            "received_at": ("TEXT", 1, 0),
            "reply_to_message_id": ("INTEGER", 0, 0),
            "reply_to_peer_id": ("INTEGER", 0, 0),
            "topic_id": ("INTEGER", 0, 0),
            "metadata_version": ("INTEGER", 1, 0),
            "metadata_json": ("TEXT", 1, 0),
        }
        actual = {row[1]: (row[2].upper(), row[3], row[5]) for row in schema}
        if actual != expected:
            raise SchemaVersionError("Inbox messages table does not match the supported schema")

    async def accept(self, message: IncomingMessage) -> StoreResult:
        if message.metadata_version != 1:
            raise MetadataVersionError(f"Unsupported metadata version: {message.metadata_version}")
        received_at = _timestamp(message.received_at)
        sent_at = _timestamp(message.sent_at)
        canonical_metadata, incoming_metadata = _canonical_metadata(message.metadata_json)
        row_values = (
            message.source,
            message.source_account_id,
            message.chat_id,
            message.message_id,
            message.sender_id,
            message.text,
            sent_at,
            received_at,
            message.reply_to_message_id,
            message.reply_to_peer_id,
            message.topic_id,
            message.metadata_version,
            canonical_metadata,
        )
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._connection.execute(
                """SELECT * FROM messages
                   WHERE source=? AND source_account_id=? AND chat_id=? AND message_id=?""",
                (message.source, message.source_account_id, message.chat_id, message.message_id),
            ).fetchone()
            if existing is None:
                self._connection.execute(
                    """INSERT INTO messages (
                        source, source_account_id, chat_id, message_id, sender_id, text,
                        sent_at, received_at, reply_to_message_id, reply_to_peer_id,
                        topic_id, metadata_version, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    row_values,
                )
                status = "stored"
            else:
                if existing["metadata_version"] != message.metadata_version:
                    raise MetadataVersionError(
                        "Cannot compare metadata versions "
                        f"{existing['metadata_version']} and {message.metadata_version}"
                    )
                _, stored_metadata = _canonical_metadata(existing["metadata_json"])
                stable_match = _stable_metadata(stored_metadata) == _stable_metadata(
                    incoming_metadata
                )
                scalar_fields = (
                    "sender_id",
                    "text",
                    "sent_at",
                    "reply_to_message_id",
                    "reply_to_peer_id",
                    "topic_id",
                )
                scalar_values = (
                    message.sender_id,
                    message.text,
                    sent_at,
                    message.reply_to_message_id,
                    message.reply_to_peer_id,
                    message.topic_id,
                )
                if not stable_match or any(
                    existing[name] != value
                    for name, value in zip(scalar_fields, scalar_values, strict=True)
                ):
                    raise ContentConflictError(f"Message content conflicts for key {message.key!r}")
                status = "duplicate"
            self._connection.execute("COMMIT")
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
        return StoreResult(message.key, status)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "SQLiteInbox":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
