"""Telegram Reader commands; credentials arrive through native pass-cli run."""

import argparse
import asyncio
import json
import os
import sys
from importlib.metadata import version

from telethon.errors import FloodWaitError

from .config import AppError, load_config
from .reader import run
from .session_store import ProtonSessionStore


def emit_json(row: dict) -> None:
    # ASCII JSON also escapes terminal controls and bidirectional formatting characters.
    print(json.dumps(row, ensure_ascii=True), flush=True)


def emit_output(row: dict) -> None:
    if row.get("type") == "login" and "message" in row:
        print(row["message"], file=sys.stderr, flush=True)
    else:
        emit_json(row)


def require_terminal() -> None:
    # pass-cli masks stdout/stderr through pipes. The prompt uses the controlling
    # terminal directly, so pipe isatty() checks would reject a valid local login.
    try:
        descriptor = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
        try:
            if not os.isatty(descriptor):
                raise OSError
        finally:
            os.close(descriptor)
    except OSError:
        raise AppError("Выполните login в интерактивном локальном терминале.") from None


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="aenea-telegram",
        description="Aenea Telegram Reader: явный вход, группы и чтение выбранной группы.",
    )
    parser.add_argument("--version", action="version", version=version("aenea-telegram-agent"))
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("login", help="Войти и сохранить новую сессию в Proton Pass vault aenea")
    commands.add_parser("groups", help="Показать ID и названия групп аккаунта")
    watch = commands.add_parser("watch", help="Читать новые сообщения одной выбранной группы")
    watch.add_argument("--chat-id", type=int, required=True, help="ID группы из команды groups")
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return
    try:
        cfg = load_config(os.environ, session_required=args.command != "login")
        if args.command == "login":
            require_terminal()
        asyncio.run(
            run(
                args.command,
                cfg,
                chat_id=getattr(args, "chat_id", None),
                store=ProtonSessionStore() if args.command == "login" else None,
                emit=emit_output,
            )
        )
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except AppError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except FloodWaitError as exc:
        print(f"Telegram требует подождать {exc.seconds} секунд. Запустите позже.", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as exc:
        # Exception text may contain RPC parameters, phone numbers or credentials.
        print(f"Операция остановлена ({type(exc).__name__}). Секреты скрыты.", file=sys.stderr)
        raise SystemExit(1) from None
