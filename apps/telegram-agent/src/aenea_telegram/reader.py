"""A bounded read-only POC. No message writer or persistent local session."""

import asyncio
import logging
from collections.abc import Callable

from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from .config import AppError, Config
from .session_store import ProtonSessionStore
from .terminal import prompt_secret

AUTH_TIMEOUT = 30


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
            await _watch(client, chat_id, emit, initial_session)
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


async def _watch(client, chat_id, emit, initial_session) -> None:
    selected = None
    async for dialog in client.iter_dialogs():
        if dialog.is_group and dialog.id == chat_id:
            selected = dialog
            break
    if selected is None:
        raise AppError("Выбранная группа не найдена среди групп аккаунта. Выполните groups.")

    async def on_message(event):
        if not event.is_group or event.chat_id != chat_id:
            return
        if client.session.save() != initial_session:
            return
        message = event.message
        emit(
            {
                "type": "message",
                "chat_id": chat_id,
                "message_id": message.id,
                "sender_id": message.sender_id,
                "date": message.date.isoformat() if message.date else None,
                "text": message.raw_text or "",
            }
        )

    client.add_event_handler(on_message, events.NewMessage(chats=[selected.entity]))
    emit({"type": "watching", "chat_id": chat_id, "title": selected.title})
    updates = asyncio.ensure_future(client.run_until_disconnected())
    try:
        while not updates.done():
            _check_session(client.session, initial_session)
            await asyncio.wait({updates}, timeout=1)
        await updates
    finally:
        updates.cancel()
        await asyncio.gather(updates, return_exceptions=True)
