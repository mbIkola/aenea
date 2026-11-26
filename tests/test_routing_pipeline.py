import asyncio
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aenea_agents import AgentHub, Dispatcher
from aenea_raidsl.dummy import DummyRaidSLAgent as RaidSLAgent
from aenea_telegram import cli, config, reader
from aenea_telegram.inbox import SQLiteInbox
from aenea_telegram.routing import RoutingProcessor
from telethon.tl.types import Message, PeerChannel
from test_inbox import STAMP, message
from test_telegram import FakeClient, environment, group


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "messages.sqlite3"
        self.inbox = SQLiteInbox(self.path)
        self.rows = []

    async def asyncTearDown(self):
        self.inbox.close()
        self.temp.cleanup()

    def processor(self, emit=None):
        return RoutingProcessor(
            self.inbox, Dispatcher(AgentHub([RaidSLAgent()])), emit or self.rows.append
        )

    async def test_saved_message_to_agent_card_to_ignore_writer_survives_restart(self):
        item = message(text="дайте таланты на Аллюру")
        await self.inbox.accept(item)
        self.processor().process_scope(11, -10022)
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(self.rows[0]["dispatch"]["route"]["candidates"], ["raidsl"])
        self.assertEqual(self.rows[0]["dispatch"]["receipt"]["status"], "ignored")
        self.inbox.close()
        self.inbox = SQLiteInbox(self.path)
        await self.inbox.accept(item)
        self.processor().process_scope(11, -10022)
        self.assertEqual(len(self.rows), 1)

    async def test_routes_only_explicit_account_and_group_and_records_unmatched(self):
        for item in (
            message(text="дайте таланты", source_account_id=12),
            message(text="дайте таланты", chat_id=-10023),
            message(text="обычное сообщение"),
        ):
            await self.inbox.accept(item)
        self.processor().process_scope(11, -10022)
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(self.rows[0]["dispatch"]["route"]["status"], "unmatched")
        self.assertEqual(len(self.inbox.pending_dispatches(12, -10022)), 1)
        self.assertEqual(len(self.inbox.pending_dispatches(11, -10023)), 1)

    async def test_failed_result_commit_leaves_work_pending_without_output(self):
        await self.inbox.accept(message(text="дайте таланты"))
        self.inbox._connection.execute(
            "CREATE TRIGGER reject_dispatch BEFORE INSERT ON agent_dispatches "
            "BEGIN SELECT RAISE(ABORT, 'forced'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.processor().process_scope(11, -10022)
        self.assertEqual(self.rows, [])
        self.assertEqual(len(self.inbox.pending_dispatches(11, -10022)), 1)
        self.inbox._connection.execute("DROP TRIGGER reject_dispatch")
        self.processor().process_scope(11, -10022)
        self.assertEqual(len(self.rows), 1)

    async def test_output_failure_does_not_undo_result_or_duplicate_writer_result(self):
        await self.inbox.accept(message(text="дайте таланты"))

        def fail(row):
            raise OSError("closed output")

        with self.assertRaises(OSError):
            self.processor(fail).process_scope(11, -10022)
        self.assertEqual(self.inbox.pending_dispatches(11, -10022), [])
        self.processor().process_scope(11, -10022)
        self.assertEqual(self.rows, [])
        row = self.inbox._connection.execute("SELECT result_json FROM agent_dispatches").fetchone()
        self.assertEqual(json.loads(row[0])["receipt"]["status"], "ignored")

    async def test_registration_or_handler_error_leaves_work_pending(self):
        class BrokenRaid(RaidSLAgent):
            def handle(self, item):
                raise RuntimeError("handler failed")

        await self.inbox.accept(message(text="дайте таланты"))
        processor = RoutingProcessor(
            self.inbox, Dispatcher(AgentHub([BrokenRaid()])), self.rows.append
        )
        with self.assertRaises(RuntimeError):
            processor.process_scope(11, -10022)
        self.assertEqual(len(self.inbox.pending_dispatches(11, -10022)), 1)
        self.assertEqual(self.rows, [])

    async def test_version_one_migrates_without_losing_messages(self):
        await self.inbox.accept(message(text="дайте таланты"))
        self.inbox.close()
        with sqlite3.connect(self.path) as database:
            database.execute("DROP TABLE IF EXISTS agent_dispatches")
            database.execute("PRAGMA user_version = 1")
        self.inbox = SQLiteInbox(self.path)
        self.assertEqual(self.inbox._connection.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(len(self.inbox.pending_dispatches(11, -10022)), 1)
        self.processor().process_scope(11, -10022)
        self.assertEqual(len(self.rows), 1)

    async def test_live_watch_routes_saved_messages_and_recovers_only_its_scope(self):
        await self.inbox.accept(message(source_account_id=777, text="дайте таланты"))
        await self.inbox.accept(message(text="дайте таланты"))

        def factory(session, *args, **kwargs):
            client = FakeClient(session)
            client.dialogs = [group(-10022)]
            client.events = [
                SimpleNamespace(
                    is_group=True,
                    chat_id=-10022,
                    message=Message(
                        id=99,
                        peer_id=PeerChannel(22),
                        date=STAMP,
                        message="подскажите таланты на Аллюру",
                    ),
                )
            ]
            return client

        with patch.object(reader, "TelegramClient", factory):
            await reader.run(
                "watch",
                config.load_config(environment(), session_required=True),
                chat_id=-10022,
                inbox=self.inbox,
                processor=self.processor(),
                emit=self.rows.append,
            )
        cards = [row for row in self.rows if row["type"] == "agent_dispatch"]
        self.assertEqual(len(cards), 2)
        self.assertEqual({card["dispatch"]["key"]["message_id"] for card in cards}, {33, 99})
        self.assertEqual(len(self.inbox.pending_dispatches(11, -10022)), 1)

    async def test_result_commit_failure_is_retryable(self):
        await self.inbox.accept(message(text="дайте таланты"))
        denied = False

        def deny_first_commit(action, first, second, database, trigger):
            nonlocal denied
            if action == sqlite3.SQLITE_TRANSACTION and first == "COMMIT" and not denied:
                denied = True
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        self.inbox._connection.set_authorizer(deny_first_commit)
        with self.assertRaises(sqlite3.DatabaseError):
            self.processor().process_scope(11, -10022)
        self.inbox._connection.set_authorizer(None)
        self.assertTrue(denied)
        self.assertEqual(self.rows, [])
        self.assertFalse(self.inbox._connection.in_transaction)
        self.processor().process_scope(11, -10022)
        self.assertEqual(len(self.rows), 1)


class OfflineCliTests(unittest.TestCase):
    def test_agents_and_route_do_not_load_credentials_or_connect_telegram(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "messages.sqlite3"
            with SQLiteInbox(path) as inbox:
                asyncio.run(inbox.accept(message(text="дайте таланты")))
            for argv in (
                ["aenea-telegram", "agents"],
                [
                    "aenea-telegram",
                    "route",
                    "--db",
                    str(path),
                    "--source-account-id",
                    "11",
                    "--chat-id=-10022",
                ],
            ):
                with (
                    patch("sys.argv", argv),
                    patch.object(cli, "load_config", side_effect=AssertionError("no credentials")),
                    patch.object(cli, "run", side_effect=AssertionError("no network")),
                    redirect_stdout(io.StringIO()) as output,
                ):
                    cli.main()
                self.assertIn("raidsl", output.getvalue())
