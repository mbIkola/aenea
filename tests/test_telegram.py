import asyncio
import io
import json
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aenea_telegram import cli, config, reader, session_store
from telethon.crypto import AuthKey
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession


def session_string():
    session = StringSession()
    session.set_dc(2, "149.154.167.50", 443)
    session.auth_key = AuthKey(bytes(range(256)))
    return session.save()


def environment():
    return {
        "AENEA_ENV": "dev",
        "TELEGRAM_API_ID": "1194219",
        "TELEGRAM_API_HASH": "a" * 32,
        "TELEGRAM_PHONE": "+9991234567",
        "TELEGRAM_SESSION": session_string(),
    }


class ConfigTests(unittest.TestCase):
    def test_loads_explicit_dev_profile_without_exposing_secrets_in_repr(self):
        cfg = config.load_config(environment(), session_required=True)
        self.assertEqual(cfg.api_id, 1194219)
        self.assertNotIn("a" * 32, repr(cfg))
        self.assertNotIn(session_string(), repr(cfg))

    def test_rejects_missing_invalid_and_unresolved_values(self):
        for name, value in [
            ("AENEA_ENV", "prod"),
            ("TELEGRAM_API_ID", "0"),
            ("TELEGRAM_API_HASH", ""),
            ("TELEGRAM_API_HASH", "pass://aenea/telegram/api_hash"),
            ("TELEGRAM_API_HASH", "wrong"),
            ("TELEGRAM_SESSION", "bad-session"),
            ("TELEGRAM_SESSION", ""),
        ]:
            with self.subTest(name=name, value=value):
                env = environment()
                env[name] = value
                with self.assertRaises(config.AppError):
                    config.load_config(env, session_required=True)

    def test_reader_does_not_require_phone_and_login_does_not_require_session(self):
        env = environment()
        del env["TELEGRAM_PHONE"]
        config.load_config(env, session_required=True)
        env = environment()
        del env["TELEGRAM_SESSION"]
        config.load_config(env, session_required=False)

    def test_login_requires_international_phone(self):
        env = environment()
        env["TELEGRAM_PHONE"] = "123"
        with self.assertRaises(config.AppError):
            config.load_config(env, session_required=False)


class StoreTests(unittest.TestCase):
    @patch("aenea_telegram.session_store.subprocess.run")
    def test_creation_error_and_timeout_are_not_reported_as_success(self, run):
        for failure in [
            SimpleNamespace(returncode=1, stdout="synthetic-secret"),
            subprocess.TimeoutExpired("pass-cli", 60, output="synthetic-secret"),
        ]:
            run.side_effect = [SimpleNamespace(returncode=0, stdout='{"items": []}'), failure]
            with self.assertRaises(config.AppError) as caught:
                session_store.ProtonSessionStore().save("synthetic-secret")
            self.assertNotIn("synthetic-secret", str(caught.exception))

    @patch("aenea_telegram.session_store.subprocess.run")
    def test_secret_goes_only_to_stdin_of_explicit_vault_creation(self, run):
        run.side_effect = [
            SimpleNamespace(returncode=0, stdout='{"items": [], "folders": []}'),
            SimpleNamespace(returncode=0, stdout="sensitive CLI output"),
        ]
        session_store.ProtonSessionStore().save("synthetic-secret")
        args, kwargs = run.call_args
        self.assertNotIn("synthetic-secret", " ".join(args[0]))
        self.assertIn("aenea", args[0])
        self.assertEqual(args[0][-2:], ["--from-template", "-"])
        payload = json.loads(kwargs["input"])
        self.assertEqual(payload["title"], "telegram-session")
        self.assertEqual(
            payload["extra_fields"],
            [{"kind": "hidden", "title": "secret", "value": "synthetic-secret"}],
        )
        self.assertTrue(kwargs["capture_output"])

    @patch("aenea_telegram.session_store.subprocess.run")
    def test_existing_session_is_never_overwritten(self, run):
        run.return_value = SimpleNamespace(
            returncode=0, stdout='{"items": [{"title": "telegram-session"}]}'
        )
        with self.assertRaises(config.AppError):
            session_store.ProtonSessionStore().save("synthetic-secret")
        self.assertEqual(run.call_count, 1)

    @patch("aenea_telegram.session_store.subprocess.run")
    def test_vault_errors_and_unknown_json_fail_closed(self, run):
        for result in [
            SimpleNamespace(returncode=1, stdout="secret in error"),
            SimpleNamespace(returncode=0, stdout="not json"),
            SimpleNamespace(returncode=0, stdout="[]"),
            SimpleNamespace(returncode=0, stdout='{"items": [{}]}'),
        ]:
            run.return_value = result
            with self.assertRaises(config.AppError) as caught:
                session_store.ProtonSessionStore().ensure_absent()
            self.assertNotIn("secret in error", str(caught.exception))


class FakeClient:
    def __init__(self, session, authorized=True):
        self.session = session
        self.connect = AsyncMock()
        self.disconnect = AsyncMock()
        self.is_user_authorized = AsyncMock(return_value=authorized)
        self.send_code_request = AsyncMock(return_value=SimpleNamespace(phone_code_hash="hash"))
        self.sign_in = AsyncMock(side_effect=self.authorize)
        self.log_out = AsyncMock(return_value=True)
        self.dialogs = []
        self.events = []
        self.handler = None

    async def authorize(self, **kwargs):
        self.session.set_dc(2, "149.154.167.50", 443)
        self.session.auth_key = AuthKey(bytes(range(256)))

    async def iter_dialogs(self):
        for dialog in self.dialogs:
            yield dialog

    def add_event_handler(self, handler, event):
        self.handler = handler

    async def run_until_disconnected(self):
        for event in self.events:
            await self.handler(event)


def group(chat_id=-100123, title="Test group"):
    return SimpleNamespace(id=chat_id, title=title, is_group=True, entity=object())


class ReaderTests(unittest.IsolatedAsyncioTestCase):
    def make_factory(self, authorized=True):
        def factory(session, *args, **kwargs):
            self.client = FakeClient(session, authorized)
            self.options = kwargs
            self.client.dialogs = self.dialogs
            self.client.events = self.events
            return self.client

        return factory

    def setUp(self):
        self.dialogs = []
        self.events = []
        self.rows = []
        self.cfg = config.load_config(environment(), session_required=True)

    async def test_groups_outputs_only_group_metadata(self):
        self.dialogs = [group(), SimpleNamespace(is_group=False, title="Private", id=9)]
        with patch.object(reader, "TelegramClient", self.make_factory()):
            await reader.run("groups", self.cfg, emit=self.rows.append)
        self.assertEqual(self.rows, [{"chat_id": -100123, "title": "Test group"}])
        self.assertFalse(self.options["receive_updates"])
        self.client.disconnect.assert_awaited_once()

    async def test_unauthorized_reader_fails_without_login(self):
        with patch.object(reader, "TelegramClient", self.make_factory(authorized=False)):
            with self.assertRaises(config.AppError):
                await reader.run("groups", self.cfg, emit=self.rows.append)
        self.client.send_code_request.assert_not_awaited()
        self.client.sign_in.assert_not_awaited()
        self.client.disconnect.assert_awaited_once()

    async def test_watch_rejects_private_dialog_and_unknown_group(self):
        self.dialogs = [SimpleNamespace(is_group=False, title="Private", id=9)]
        for chat_id in [9, -100999]:
            with patch.object(reader, "TelegramClient", self.make_factory()):
                with self.assertRaises(config.AppError):
                    await reader.run("watch", self.cfg, chat_id=chat_id, emit=self.rows.append)
            self.assertIsNone(self.client.handler)
            self.client.disconnect.assert_awaited_once()

    async def test_watch_filters_before_accessing_message_content(self):
        self.dialogs = [group()]
        self.events = [
            SimpleNamespace(is_group=False, chat_id=9),
            SimpleNamespace(is_group=True, chat_id=-100999),
            SimpleNamespace(
                is_group=True,
                chat_id=-100123,
                message=SimpleNamespace(id=42, raw_text="message\x1b[31m", date=None, sender_id=12),
            ),
        ]
        with patch.object(reader, "TelegramClient", self.make_factory()):
            await reader.run("watch", self.cfg, chat_id=-100123, emit=self.rows.append)
        messages = [row for row in self.rows if row.get("type") == "message"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["message_id"], 42)
        self.assertEqual(messages[0]["text"], "message\x1b[31m")
        self.assertTrue(self.options["receive_updates"])
        self.assertFalse(self.options["catch_up"])

    async def test_login_saves_new_session_and_disconnects(self):
        cfg = config.load_config(environment(), session_required=False)
        store = SimpleNamespace(ensure_absent=unittest.mock.Mock(), save=unittest.mock.Mock())
        with (
            patch.object(reader, "TelegramClient", self.make_factory(authorized=False)),
            patch.object(reader, "prompt_secret", return_value="12345"),
        ):
            await reader.run("login", cfg, store=store, emit=self.rows.append)
        store.ensure_absent.assert_called_once()
        store.save.assert_called_once_with(session_string())
        self.client.disconnect.assert_awaited_once()

    async def test_enter_reports_checking_before_sign_in_and_saving_after(self):
        store = SimpleNamespace(ensure_absent=unittest.mock.Mock(), save=unittest.mock.Mock())
        factory = self.make_factory(authorized=False)

        def checking_factory(*args, **kwargs):
            client = factory(*args, **kwargs)

            async def sign_in(**fields):
                self.assertEqual(self.rows[-1]["status"], "checking_code")
                await client.authorize()

            client.sign_in.side_effect = sign_in
            return client

        with (
            patch.object(reader, "TelegramClient", checking_factory),
            patch.object(reader, "prompt_secret", return_value="12345"),
        ):
            await reader.run("login", self.cfg, store=store, emit=self.rows.append)
        self.assertEqual(
            [row["status"] for row in self.rows],
            ["requesting_code", "checking_code", "saving_session", "saved"],
        )

    async def test_slow_telegram_sign_in_times_out_and_revokes_session(self):
        store = SimpleNamespace(ensure_absent=unittest.mock.Mock(), save=unittest.mock.Mock())
        factory = self.make_factory(authorized=False)

        def stalled_factory(*args, **kwargs):
            client = factory(*args, **kwargs)

            async def stall(**fields):
                await asyncio.Event().wait()

            client.sign_in.side_effect = stall
            return client

        with (
            patch.object(reader, "TelegramClient", stalled_factory),
            patch.object(reader, "prompt_secret", return_value="12345"),
            patch.object(reader, "AUTH_TIMEOUT", 0.05),
        ):
            with self.assertRaisesRegex(config.AppError, "не ответил"):
                await reader.run("login", self.cfg, store=store, emit=self.rows.append)
        self.client.log_out.assert_awaited_once()
        store.save.assert_not_called()

    async def test_two_factor_login_saves_only_after_password_sign_in(self):
        store = SimpleNamespace(ensure_absent=unittest.mock.Mock(), save=unittest.mock.Mock())
        factory = self.make_factory(authorized=False)

        def two_factor_factory(*args, **kwargs):
            client = factory(*args, **kwargs)

            async def sign_in(**fields):
                if "password" not in fields:
                    raise SessionPasswordNeededError(request=None)
                await client.authorize()

            client.sign_in.side_effect = sign_in
            return client

        with (
            patch.object(reader, "TelegramClient", two_factor_factory),
            patch.object(reader, "prompt_secret", side_effect=["12345", "synthetic-password"]),
        ):
            await reader.run("login", self.cfg, store=store, emit=self.rows.append)
        self.assertEqual(self.client.sign_in.await_count, 2)
        store.save.assert_called_once_with(session_string())

    async def test_interrupted_login_revokes_new_authorization(self):
        store = SimpleNamespace(ensure_absent=unittest.mock.Mock(), save=unittest.mock.Mock())
        with (
            patch.object(reader, "TelegramClient", self.make_factory(authorized=False)),
            patch.object(reader, "prompt_secret", side_effect=KeyboardInterrupt),
        ):
            with self.assertRaises(KeyboardInterrupt):
                await reader.run("login", self.cfg, store=store, emit=self.rows.append)
        self.client.log_out.assert_awaited_once()
        self.client.disconnect.assert_awaited_once()
        store.save.assert_not_called()

    async def test_failed_connection_always_disconnects(self):
        factory = self.make_factory()

        def failing_factory(*args, **kwargs):
            client = factory(*args, **kwargs)
            client.connect.side_effect = OSError("synthetic-secret")
            return client

        with patch.object(reader, "TelegramClient", failing_factory):
            with self.assertRaises(OSError):
                await reader.run("groups", self.cfg, emit=self.rows.append)
        self.client.disconnect.assert_awaited_once()

    async def test_session_change_during_connect_blocks_group_output(self):
        self.dialogs = [group()]
        factory = self.make_factory()

        def migrating_factory(*args, **kwargs):
            client = factory(*args, **kwargs)

            async def migrate():
                client.session.set_dc(3, "149.154.175.100", 443)

            client.connect.side_effect = migrate
            return client

        with patch.object(reader, "TelegramClient", migrating_factory):
            with self.assertRaises(config.AppError):
                await reader.run("groups", self.cfg, emit=self.rows.append)
        self.assertEqual(self.rows, [])
        self.client.disconnect.assert_awaited_once()

    async def test_session_change_detected_even_when_watch_is_cancelled(self):
        self.dialogs = [group()]
        factory = self.make_factory()

        def migrating_factory(*args, **kwargs):
            client = factory(*args, **kwargs)

            async def migrate():
                client.session.set_dc(3, "149.154.175.100", 443)
                raise asyncio.CancelledError

            client.run_until_disconnected = migrate
            return client

        with patch.object(reader, "TelegramClient", migrating_factory):
            with self.assertRaises(config.AppError):
                await reader.run("watch", self.cfg, chat_id=-100123, emit=self.rows.append)
        self.client.disconnect.assert_awaited_once()

    async def test_watch_stops_on_session_change_without_an_incoming_message(self):
        self.dialogs = [group()]
        factory = self.make_factory()
        stopped = asyncio.Event()

        def migrating_factory(*args, **kwargs):
            client = factory(*args, **kwargs)

            async def migrate():
                client.session.set_dc(3, "149.154.175.100", 443)
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

            client.run_until_disconnected = migrate
            return client

        with patch.object(reader, "TelegramClient", migrating_factory):
            with self.assertRaises(config.AppError):
                await asyncio.wait_for(
                    reader.run("watch", self.cfg, chat_id=-100123, emit=self.rows.append),
                    timeout=3,
                )
        self.assertTrue(stopped.is_set())
        self.client.disconnect.assert_awaited_once()

    async def test_partly_successful_login_is_revoked_when_post_auth_rpc_fails(self):
        factory = self.make_factory(authorized=False)
        store = SimpleNamespace(ensure_absent=unittest.mock.Mock(), save=unittest.mock.Mock())

        def failing_factory(*args, **kwargs):
            client = factory(*args, **kwargs)

            async def partial_sign_in(**fields):
                await client.authorize()
                raise OSError("post-auth getState failed")

            client.sign_in.side_effect = partial_sign_in
            return client

        with (
            patch.object(reader, "TelegramClient", failing_factory),
            patch.object(reader, "prompt_secret", return_value="12345"),
        ):
            with self.assertRaises(OSError):
                await reader.run("login", self.cfg, store=store, emit=self.rows.append)
        self.client.log_out.assert_awaited_once()
        store.save.assert_not_called()

    async def test_existing_item_blocks_login_before_network(self):
        store = SimpleNamespace(
            ensure_absent=unittest.mock.Mock(side_effect=config.AppError("exists"))
        )
        with patch.object(reader, "TelegramClient") as factory:
            with self.assertRaises(config.AppError):
                await reader.run("login", self.cfg, store=store, emit=self.rows.append)
        factory.assert_not_called()

    async def test_failed_save_revokes_only_new_login(self):
        store = SimpleNamespace(
            ensure_absent=unittest.mock.Mock(),
            save=unittest.mock.Mock(side_effect=config.AppError("save failed")),
        )
        with (
            patch.object(reader, "TelegramClient", self.make_factory(authorized=False)),
            patch.object(reader, "prompt_secret", return_value="12345"),
        ):
            with self.assertRaises(config.AppError):
                await reader.run("login", self.cfg, store=store, emit=self.rows.append)
        self.client.log_out.assert_awaited_once()
        self.client.disconnect.assert_awaited_once()

    async def test_unconfirmed_revoke_requires_manual_termination(self):
        factory = self.make_factory(authorized=False)
        store = SimpleNamespace(
            ensure_absent=unittest.mock.Mock(),
            save=unittest.mock.Mock(side_effect=config.AppError("save failed")),
        )

        def failing_factory(*args, **kwargs):
            client = factory(*args, **kwargs)
            client.log_out.return_value = False
            return client

        with (
            patch.object(reader, "TelegramClient", failing_factory),
            patch.object(reader, "prompt_secret", return_value="12345"),
        ):
            with self.assertRaisesRegex(config.AppError, "вручную"):
                await reader.run("login", self.cfg, store=store, emit=self.rows.append)


class CliTests(unittest.TestCase):
    def test_json_output_escapes_terminal_controls(self):
        output = io.StringIO()
        with redirect_stdout(output):
            cli.emit_json({"text": "hello\x1b[31m\n\u202e"})
        self.assertNotIn("\x1b", output.getvalue())
        self.assertNotIn("\u202e", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["text"], "hello\x1b[31m\n\u202e")

    @patch.dict("os.environ", environment(), clear=True)
    @patch("sys.argv", ["aenea-telegram", "groups"])
    def test_service_error_does_not_print_secret_exception_text(self):
        output = io.StringIO()
        with (
            patch.object(cli, "run", AsyncMock(side_effect=RuntimeError("synthetic-secret"))),
            redirect_stderr(output),
        ):
            with self.assertRaises(SystemExit) as caught:
                cli.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertNotIn("synthetic-secret", output.getvalue())
        self.assertIn("RuntimeError", output.getvalue())

    @patch.dict("os.environ", environment(), clear=True)
    @patch("sys.argv", ["aenea-telegram", "login"])
    def test_noninteractive_login_fails_before_client_creation(self):
        with (
            patch("os.open", side_effect=OSError("no controlling terminal")),
            patch.object(cli, "run") as run,
            redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit):
                cli.main()
        run.assert_not_called()

    @patch.dict("os.environ", environment(), clear=True)
    @patch("sys.argv", ["aenea-telegram", "login"])
    def test_login_accepts_masked_pipes_with_controlling_terminal(self):
        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("sys.stderr.isatty", return_value=False),
            patch("os.open", return_value=77),
            patch("os.isatty", return_value=True),
            patch("os.close") as close,
            patch.object(cli, "run", AsyncMock()) as run,
        ):
            cli.main()
        run.assert_awaited_once()
        close.assert_called_once_with(77)


if __name__ == "__main__":
    unittest.main()
