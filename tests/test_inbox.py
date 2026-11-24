import json
import sqlite3
import tempfile
import time
import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

from aenea_contracts import IncomingMessage, MessageKey, StoreResult
from aenea_telegram.inbox import (
    ContentConflictError,
    MetadataVersionError,
    SchemaVersionError,
    SQLiteInbox,
)

STAMP = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)


def message(**overrides):
    fields = dict(
        source="telegram",
        source_account_id=11,
        chat_id=-10022,
        message_id=33,
        sender_id=44,
        text="hello",
        sent_at=STAMP,
        received_at=STAMP,
        reply_to_message_id=12,
        reply_to_peer_id=None,
        topic_id=7,
        metadata_version=1,
        metadata_json=json.dumps(
            {"content": {"entities": [{"type": "bold"}]}, "snapshot": {"views": 1}}
        ),
    )
    fields.update(overrides)
    return IncomingMessage(**fields)


class ContractTests(unittest.TestCase):
    def test_immutable_message_key_and_result(self):
        item = message()
        self.assertEqual(item.key, MessageKey("telegram", 11, -10022, 33))
        with self.assertRaises(FrozenInstanceError):
            item.text = "changed"
        result = StoreResult(item.key, "stored")
        self.assertEqual(result.status, "stored")
        with self.assertRaises(FrozenInstanceError):
            result.status = "duplicate"


class SQLiteInboxTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "inbox.sqlite3"
        self.inbox = SQLiteInbox(self.path)

    async def asyncTearDown(self):
        self.inbox.close()
        self.temp.cleanup()

    async def test_persists_and_duplicate_preserves_first_snapshot_and_time(self):
        first = message()
        self.assertEqual(await self.inbox.accept(first), StoreResult(first.key, "stored"))
        self.inbox.close()
        self.inbox = SQLiteInbox(self.path)
        repeated = message(
            received_at=datetime(2026, 11, 24, 11, 0, tzinfo=UTC),
            metadata_json=json.dumps(
                {"snapshot": {"views": 999}, "content": {"entities": [{"type": "bold"}]}}
            ),
        )
        self.assertEqual(await self.inbox.accept(repeated), StoreResult(first.key, "duplicate"))
        row = self.inbox._connection.execute(
            "SELECT received_at, metadata_json FROM messages"
        ).fetchone()
        self.assertEqual(row["received_at"], "2026-11-24T10:00:00+00:00")
        self.assertEqual(json.loads(row["metadata_json"])["snapshot"]["views"], 1)

    async def test_identity_scopes_accounts_and_chats(self):
        variants = [message(), message(source_account_id=12), message(chat_id=-10023)]
        for item in variants:
            self.assertEqual((await self.inbox.accept(item)).status, "stored")
        self.assertEqual(
            self.inbox._connection.execute("SELECT count(*) FROM messages").fetchone()[0], 3
        )

    async def test_content_conflicts_in_fields_and_content_projection(self):
        original = message()
        await self.inbox.accept(original)
        for changed in (
            message(text="different"),
            message(sender_id=45),
            message(sent_at=datetime(2026, 11, 24, 10, 1, tzinfo=UTC)),
            message(reply_to_message_id=13),
            message(topic_id=8),
            message(
                metadata_json='{"content":{"entities":[{"type":"italic"}]},"snapshot":{"views":1}}'
            ),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(ContentConflictError):
                    await self.inbox.accept(changed)
        row = self.inbox._connection.execute("SELECT text FROM messages").fetchone()
        self.assertEqual(row["text"], "hello")

    async def test_arbitrary_metadata_compares_all_unknown_content(self):
        await self.inbox.accept(message(metadata_json='{"custom":{"x":1}}'))
        with self.assertRaises(ContentConflictError):
            await self.inbox.accept(message(metadata_json='{"custom":{"x":2}}'))

    async def test_metadata_version_mismatch_is_rejected(self):
        item = message()
        await self.inbox.accept(item)
        with self.assertRaises(MetadataVersionError):
            await self.inbox.accept(message(metadata_version=2))
        with self.assertRaises(MetadataVersionError):
            await self.inbox.accept(message(message_id=99, metadata_version=2))
        stored = self.inbox._connection.execute(
            "SELECT metadata_version, metadata_json, received_at FROM messages"
        ).fetchone()
        self.assertEqual(stored["metadata_version"], 1)
        self.assertEqual(json.loads(stored["metadata_json"])["snapshot"]["views"], 1)
        self.assertEqual(stored["received_at"], "2026-11-24T10:00:00+00:00")
        self.assertEqual(
            self.inbox._connection.execute("SELECT count(*) FROM messages").fetchone()[0], 1
        )

    async def test_metadata_snapshot_is_ignored_but_unknown_top_level_data_conflicts(self):
        await self.inbox.accept(
            message(metadata_json='{"content":{"x":1},"snapshot":{"views":1},"extra":{"x":1}}')
        )
        duplicate = message(
            metadata_json='{"content":{"x":1},"snapshot":{"views":2},"extra":{"x":1}}'
        )
        self.assertEqual((await self.inbox.accept(duplicate)).status, "duplicate")
        changed = message(
            metadata_json='{"content":{"x":1},"snapshot":{"views":2},"extra":{"x":2}}'
        )
        with self.assertRaises(ContentConflictError):
            await self.inbox.accept(changed)

    async def test_reordered_supported_schema_inserts_by_column_name(self):
        self.inbox.close()
        self.path.unlink()
        db = sqlite3.connect(self.path)
        db.execute(
            """CREATE TABLE messages (
                message_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                source_account_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
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
        db.execute("PRAGMA user_version = 1")
        db.commit()
        db.close()
        self.inbox = SQLiteInbox(self.path)

        item = message()
        self.assertEqual((await self.inbox.accept(item)).status, "stored")
        row = self.inbox._connection.execute("SELECT * FROM messages").fetchone()
        self.assertEqual(row["message_id"], item.message_id)
        self.assertEqual(row["source"], item.source)
        self.assertEqual(row["chat_id"], item.chat_id)
        self.assertEqual(row["text"], item.text)

    async def test_commit_failure_rolls_back_and_can_retry(self):
        item = message()
        denied_commit = False

        def deny_first_commit(action, arg1, arg2, database, trigger):
            nonlocal denied_commit
            if action == sqlite3.SQLITE_TRANSACTION and arg1 == "COMMIT" and not denied_commit:
                denied_commit = True
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        self.inbox._connection.set_authorizer(deny_first_commit)
        with self.assertRaises(sqlite3.DatabaseError):
            await self.inbox.accept(item)
        self.assertTrue(denied_commit)
        self.assertFalse(self.inbox._connection.in_transaction)
        self.assertEqual(
            self.inbox._connection.execute("SELECT count(*) FROM messages").fetchone()[0], 0
        )
        self.inbox._connection.set_authorizer(None)
        self.assertEqual((await self.inbox.accept(item)).status, "stored")

    async def test_busy_lock_is_bounded(self):
        locked = sqlite3.connect(self.path, timeout=0)
        locked.execute("BEGIN IMMEDIATE")
        bounded = SQLiteInbox(self.path, timeout=0.02)
        started = time.monotonic()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                await bounded.accept(message())
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            bounded.close()
            locked.rollback()
            locked.close()

    async def test_invalid_json_does_not_write(self):
        with self.assertRaises(json.JSONDecodeError):
            await self.inbox.accept(message(metadata_json="{"))
        self.assertEqual(
            self.inbox._connection.execute("SELECT count(*) FROM messages").fetchone()[0], 0
        )

    async def test_failed_insert_rolls_back(self):
        self.inbox._connection.execute(
            "CREATE TRIGGER fail_insert BEFORE INSERT ON messages "
            "BEGIN SELECT RAISE(ABORT, 'forced'); END"
        )
        item = message()
        with self.assertRaises(sqlite3.IntegrityError):
            await self.inbox.accept(item)
        self.assertEqual(
            self.inbox._connection.execute("SELECT count(*) FROM messages").fetchone()[0], 0
        )
        self.inbox._connection.execute("DROP TRIGGER fail_insert")
        self.assertEqual((await self.inbox.accept(item)).status, "stored")

    async def test_unknown_schema_version_and_tables_are_not_modified(self):
        self.inbox.close()
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA user_version = 91")
        db.commit()
        db.close()
        before = self.path.read_bytes()
        with self.assertRaises(SchemaVersionError):
            SQLiteInbox(self.path)
        self.assertEqual(self.path.read_bytes(), before)

        other = Path(self.temp.name) / "other.sqlite3"
        db = sqlite3.connect(other)
        db.execute("CREATE TABLE unrelated (value TEXT)")
        db.commit()
        db.close()
        before = other.read_bytes()
        with self.assertRaises(SchemaVersionError):
            SQLiteInbox(other)
        self.assertEqual(other.read_bytes(), before)

        malformed = Path(self.temp.name) / "malformed.sqlite3"
        db = sqlite3.connect(malformed)
        db.execute("PRAGMA user_version = 1")
        db.execute(
            "CREATE TABLE messages (source TEXT, source_account_id INTEGER, "
            "chat_id INTEGER, message_id INTEGER)"
        )
        db.commit()
        db.close()
        before = malformed.read_bytes()
        with self.assertRaises(SchemaVersionError):
            SQLiteInbox(malformed)
        self.assertEqual(malformed.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
