"""Explicit process configuration; secret resolution belongs to pass-cli run."""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from telethon.sessions import StringSession


class AppError(Exception):
    """A safe, user-facing error without underlying service output."""


@dataclass(frozen=True, repr=False)
class Config:
    api_id: int
    api_hash: str
    phone: str | None = None
    session: str | None = None


def load_config(env: Mapping[str, str], *, session_required: bool) -> Config:
    if env.get("AENEA_ENV") != "dev":
        raise AppError("Требуется явный профиль AENEA_ENV=dev.")

    def required(name: str) -> str:
        value = env.get(name, "").strip()
        if not value or value.startswith("pass://"):
            raise AppError(f"Не разрешена переменная {name}; используйте pass-cli run.")
        return value

    raw_id = required("TELEGRAM_API_ID")
    if not raw_id.isascii() or not raw_id.isdecimal() or not 0 < int(raw_id) < 2**31:
        raise AppError("Некорректный TELEGRAM_API_ID.")
    api_hash = required("TELEGRAM_API_HASH")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash):
        raise AppError("TELEGRAM_API_HASH должен содержать 32 шестнадцатеричных символа.")
    if session_required:
        session = required("TELEGRAM_SESSION")
        try:
            parsed = StringSession(session)
            if not parsed.auth_key or parsed.dc_id <= 0:
                raise ValueError
        except Exception:
            raise AppError("Некорректный TELEGRAM_SESSION в выбранном профиле.") from None
        return Config(int(raw_id), api_hash, session=session)
    phone = required("TELEGRAM_PHONE")
    if not re.fullmatch(r"\+[1-9][0-9]{6,14}", phone):
        raise AppError("TELEGRAM_PHONE должен быть в международном формате с +.")
    return Config(int(raw_id), api_hash, phone=phone)
