"""Integration guarantees across the transport projection and durable Inbox."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from aenea_telegram.inbox import ContentConflictError, SQLiteInbox
from aenea_telegram.normalization import normalize_message
from telethon.tl import types

STAMP = datetime(2026, 11, 24, tzinfo=UTC)


class ProjectionInboxTests(unittest.IsolatedAsyncioTestCase):
    def message(self, **kwargs):
        return types.Message(
            id=15, peer_id=types.PeerChat(5), date=STAMP, message="Юникод 🛰" * 10000, **kwargs
        )

    def normalize(self, message):
        return normalize_message(message, source_account_id=7, chat_id=-5)

    async def test_long_text_entities_and_metadata_survive_reopen(self):
        incoming = self.normalize(self.message(entities=[types.MessageEntityBold(8, 2)]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inbox.sqlite3"
            with SQLiteInbox(path) as inbox:
                await inbox.accept(incoming)
            with closing(sqlite3.connect(path)) as database:
                text, metadata = database.execute(
                    "SELECT text, metadata_json FROM messages"
                ).fetchone()
            self.assertEqual(text, incoming.text)
            self.assertEqual(json.loads(metadata), json.loads(incoming.metadata_json))
            with SQLiteInbox(path) as inbox:
                self.assertEqual((await inbox.accept(incoming)).status, "duplicate")

    async def test_observation_changes_do_not_change_stable_content(self):
        first = self.normalize(self.message())
        changed = self.normalize(
            self.message(
                views=4,
                edit_date=STAMP,
                reactions=types.MessageReactions(
                    results=[types.ReactionCount(types.ReactionEmoji("👍"), 2)]
                ),
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            with SQLiteInbox(Path(directory) / "inbox.sqlite3") as inbox:
                await inbox.accept(first)
                self.assertEqual((await inbox.accept(changed)).status, "duplicate")

    async def test_nested_reply_poll_results_are_snapshot_state(self):
        def item(votes):
            return self.normalize(
                self.message(
                    reply_to=types.MessageReplyHeader(
                        reply_to_msg_id=1,
                        reply_media=types.MessageMediaPoll(
                            poll=types.Poll(
                                id=2,
                                question=types.TextWithEntities("?", []),
                                answers=[types.PollAnswer(types.TextWithEntities("Да", []), b"1")],
                                hash=0,
                            ),
                            results=types.PollResults(total_voters=votes),
                        ),
                    )
                )
            )

        with tempfile.TemporaryDirectory() as directory:
            with SQLiteInbox(Path(directory) / "inbox.sqlite3") as inbox:
                first, observed = item(1), item(9)
                snapshot = json.dumps(json.loads(observed.metadata_json)["snapshot"])
                self.assertIn('"total_voters": 9', snapshot)
                await inbox.accept(first)
                self.assertEqual((await inbox.accept(observed)).status, "duplicate")

    async def test_web_preview_refresh_keeps_first_snapshot(self):
        def item(title):
            return self.normalize(
                self.message(
                    media=types.MessageMediaWebPage(
                        webpage=types.WebPage(
                            id=3,
                            url="https://example.test",
                            display_url="example.test",
                            hash=1,
                            title=title,
                            author=title,
                        )
                    )
                )
            )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inbox.sqlite3"
            with SQLiteInbox(path) as inbox:
                await inbox.accept(item("Original"))
                self.assertEqual((await inbox.accept(item("Changed"))).status, "duplicate")
            with closing(sqlite3.connect(path)) as database:
                metadata = database.execute("SELECT metadata_json FROM messages").fetchone()[0]
                self.assertIn("Original", metadata)
                self.assertNotIn("Changed", metadata)

    async def test_poll_closed_state_is_retained_without_conflict(self):
        def item(closed):
            return self.normalize(
                self.message(
                    media=types.MessageMediaPoll(
                        poll=types.Poll(
                            id=2,
                            question=types.TextWithEntities("?", []),
                            answers=[],
                            hash=0,
                            closed=closed,
                        ),
                        results=types.PollResults(),
                    )
                )
            )

        observed = item(True)
        snapshot = json.dumps(json.loads(observed.metadata_json)["snapshot"])
        self.assertIn('"closed": true', snapshot)
        with tempfile.TemporaryDirectory() as directory:
            with SQLiteInbox(Path(directory) / "inbox.sqlite3") as inbox:
                await inbox.accept(item(False))
                self.assertEqual((await inbox.accept(observed)).status, "duplicate")

    async def test_unknown_voter_does_not_change_content_completeness(self):
        class FuturePeer:
            access_hash = 99

        def item(voters):
            return self.normalize(
                self.message(
                    media=types.MessageMediaPoll(
                        poll=types.Poll(
                            id=2, question=types.TextWithEntities("?", []), answers=[], hash=0
                        ),
                        results=types.PollResults(recent_voters=voters),
                    )
                )
            )

        with tempfile.TemporaryDirectory() as directory:
            with SQLiteInbox(Path(directory) / "inbox.sqlite3") as inbox:
                await inbox.accept(item(None))
                self.assertEqual((await inbox.accept(item([FuturePeer()]))).status, "duplicate")

    async def test_changed_media_identity_is_content_conflict(self):
        def item(document_id):
            document = types.Document(
                document_id,
                99,
                b"sensitive",
                STAMP,
                "text/plain",
                3,
                2,
                [types.DocumentAttributeFilename("a.txt")],
            )
            return self.normalize(self.message(media=types.MessageMediaDocument(document=document)))

        with tempfile.TemporaryDirectory() as directory:
            with SQLiteInbox(Path(directory) / "inbox.sqlite3") as inbox:
                await inbox.accept(item(1))
                with self.assertRaises(ContentConflictError):
                    await inbox.accept(item(2))
