"""A bounded read-only POC. No message writer or persistent local session."""

import asyncio
import logging
from collections.abc import Callable

from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession
from telethon.tl import types

from .config import AppError, Config
from .inbox import Inbox
from .normalization import normalize_message
from .session_store import ProtonSessionStore
from .terminal import prompt_secret

AUTH_TIMEOUT = 30


class InboxNewMessage(events.NewMessage):
    """NewMessage with service messages, still using the explicit group filter."""

    @classmethod
    def build(cls, update, others=None, self_id=None):
        if isinstance(update, (types.UpdateNewMessage, types.UpdateNewChannelMessage)):
            if isinstance(update.message, types.MessageService):
                return cls.Event(update.message)
        return super().build(update, others=others, self_id=self_id)


async def _auth_request(request):
    try:
        return await asyncio.wait_for(request, timeout=AUTH_TIMEOUT)
    except TimeoutError:
        raise AppError(
            "Telegram не ответил за 30 секунд. Вход остановлен; "
            "не запрашивайте новые коды многократно."
        ) from None


async def run(
    command: str,
    config: Config,
    *,
    chat_id: int | None = None,
    store: ProtonSessionStore | None = None,
    inbox: Inbox | None = None,
    emit: Callable[[dict], None],
) -> None:
    if command == "login":
        if store is None:
            raise AppError("Не задано хранилище сессии.")
        store.ensure_absent()
    elif not config.session:
        raise AppError("Для чтения требуется сохранённая сессия.")
    if command == "watch" and chat_id is None:
        raise AppError("Выберите группу через --chat-id.")

    if command == "watch" and inbox is None:
        raise AppError("Для watch требуется Inbox и явный путь --db.")

    # Library diagnostics must not publish RPC payloads, phone numbers or session details.
    logger = logging.getLogger("aenea.telegram.transport")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    logger.disabled = True
    session = StringSession(config.session if command != "login" else None)
    client = TelegramClient(
        session,
        config.api_id,
        config.api_hash,
        receive_updates=command == "watch",
        catch_up=False,
        request_retries=1,
        connection_retries=2,
        flood_sleep_threshold=0,
        base_logger=logger,
    )
    initial_session = session.save()
    try:
        await _auth_request(client.connect())
        if command == "login":
            await _login(client, config, store, emit)
            return
        _check_session(session, initial_session)
        if not await client.is_user_authorized():
            raise AppError(
                "Сессия не авторизована или отозвана. Чтение остановлено; "
                "восстановление описано в docs/telegram-reader.md."
            )
        if command == "groups":
            async for dialog in client.iter_dialogs():
                if dialog.is_group:
                    emit({"chat_id": dialog.id, "title": dialog.title})
        else:
            await _watch(client, chat_id, emit, initial_session, inbox)
    finally:
        await client.disconnect()
        if command != "login":
            _check_session(session, initial_session)


def _check_session(session: StringSession, initial: str) -> None:
    if session.save() != initial:
        raise AppError(
            "Параметры сессии изменились. Обновление через argv запрещено; "
            "нужно явное восстановление по docs/telegram-reader.md."
        )


async def _login(client, config, store, emit) -> None:
    try:
        emit({"type": "login", "status": "requesting_code", "message": "Запрашиваю код Telegram…"})
        sent = await _auth_request(client.send_code_request(config.phone))
        try:
            code = await prompt_secret(
                "Код Telegram (* — введённый символ, Enter — отправить): ", digits_only=True
            )
            emit({"type": "login", "status": "checking_code", "message": "Код введён. Проверяю…"})
            await _auth_request(
                client.sign_in(
                    phone=config.phone,
                    code=code,
                    phone_code_hash=sent.phone_code_hash,
                )
            )
        except SessionPasswordNeededError:
            password = await prompt_secret("Пароль Telegram 2FA (* — введённый символ): ")
            emit({"type": "login", "status": "checking_password", "message": "Проверяю 2FA…"})
            await _auth_request(client.sign_in(password=password))
        saved = client.session.save()
        if not saved:
            raise AppError("Telegram не вернул авторизованную сессию.")
        emit(
            {
                "type": "login",
                "status": "saving_session",
                "message": "Сохраняю сессию в Proton Pass…",
            }
        )
        store.save(saved)
    except BaseException:
        try:
            if not await asyncio.wait_for(client.log_out(), timeout=10):
                raise AppError("Отзыв не подтверждён.")
        except Exception:
            raise AppError(
                "Не удалось сохранить сессию и подтвердить её отзыв. "
                "Завершите новый сеанс вручную в Telegram → Устройства."
            ) from None
        raise
    emit({"type": "login", "status": "saved", "reference": "pass://aenea/telegram-session/secret"})


async def _watch(client, chat_id, emit, initial_session, inbox: Inbox) -> None:
    selected = None
    async for dialog in client.iter_dialogs():
        if dialog.is_group and dialog.id == chat_id:
            selected = dialog
            break
    if selected is None:
        raise AppError("Выбранная группа не найдена среди групп аккаунта. Выполните groups.")

    account = await client.get_me()
    if account is None or not isinstance(account.id, int):
        raise AppError("Не удалось определить ID аккаунта Reader.")
    failure = asyncio.get_running_loop().create_future()
    active: set[asyncio.Task] = set()
    serial = asyncio.Lock()
    stopping = False

    async def accept_message(event):
        async with serial:
            if failure.done():
                return
            try:
                _check_session(client.session, initial_session)
                message = normalize_message(
                    event.message, source_account_id=account.id, chat_id=chat_id
                )
                result = await inbox.accept(message)
                emit(
                    {
                        "type": result.status,
                        "source": message.source,
                        "source_account_id": message.source_account_id,
                        "chat_id": message.chat_id,
                        "message_id": message.message_id,
                    }
                )
            except Exception as exc:
                # Telethon swallows callback exceptions. Wake the controlling coroutine.
                if not failure.done():
                    failure.set_result(exc)

    async def on_message(event):
        if stopping or failure.done() or not event.is_group or event.chat_id != chat_id:
            return
        task = asyncio.create_task(accept_message(event))
        active.add(task)
        task.add_done_callback(active.discard)
        # Transport cancellation must not abandon an already started commit.
        await asyncio.shield(task)

    client.add_event_handler(on_message, InboxNewMessage(chats=[selected.entity]))
    updates = None
    try:
        emit({"type": "watching", "chat_id": chat_id, "title": selected.title})
        updates = asyncio.ensure_future(client.run_until_disconnected())
        while not updates.done() and not failure.done():
            _check_session(client.session, initial_session)
            await asyncio.wait({updates, failure}, timeout=1)
        if failure.done():
            raise failure.result()
        await updates
    finally:
        stopping = True
        client.remove_event_handler(on_message)
        if updates is not None:
            updates.cancel()
            await asyncio.gather(updates, return_exceptions=True)
        if active:
            await asyncio.gather(*active)
        # A pending commit can fail while shutdown drains the callbacks.
        if failure.done():
            raise failure.result()
