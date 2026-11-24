"""Masked controlling-terminal input without blocking Telethon's event loop."""

import asyncio
import codecs
import os
import select
import termios

from .config import AppError


async def prompt_secret(prompt: str, *, digits_only: bool = False) -> str:
    try:
        descriptor = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except OSError:
        raise AppError("Для скрытого ввода нужен локальный управляющий терминал.") from None
    original = None
    characters = []
    decoder = codecs.getincrementaldecoder("utf-8")("ignore")

    def write(text: str) -> None:
        os.write(descriptor, text.encode("utf-8"))

    async def read() -> str:
        escape = ""
        while True:
            # macOS kqueue cannot register /dev/tty with loop.add_reader().
            # Nonblocking select plus a short async sleep keeps RPCs/cancellation live.
            if not select.select([descriptor], [], [], 0)[0]:
                await asyncio.sleep(0.02)
                continue
            data = os.read(descriptor, 1)
            if not data or data == b"\x04":
                raise EOFError
            character = decoder.decode(data)
            if escape:
                if escape == "\x1b" and character in ("[", "O"):
                    escape += character
                    continue
                if escape == "\x1b" or character in ("\r", "\n"):
                    # A standalone Esc must not consume the next digit or Enter.
                    escape = ""
                else:
                    if "@" <= character <= "~" or len(escape) > 16:
                        escape = ""
                    else:
                        escape += character
                    continue
            if character == "\x1b":
                escape = character
                continue
            if character in ("\n", "\r"):
                if not characters:
                    raise AppError("Пустой ввод; вход остановлен.")
                return "".join(characters)
            elif character in ("\x7f", "\b"):
                if characters:
                    characters.pop()
                    write("\b \b")
            elif character == "\x15":
                write("\b \b" * len(characters))
                characters.clear()
            elif character.isprintable() and (not digits_only or character in "0123456789"):
                if len(characters) >= 1024:
                    raise AppError("Слишком длинный ввод; вход остановлен.")
                characters.append(character)
                write("*")

    try:
        original = termios.tcgetattr(descriptor)
        masked = original[:]
        masked[6] = original[6][:]
        masked[3] &= ~(termios.ECHO | termios.ECHONL | termios.ICANON)
        masked[6][termios.VMIN] = 1
        masked[6][termios.VTIME] = 0
        termios.tcsetattr(descriptor, termios.TCSANOW, masked)
        write(prompt)
        try:
            return await asyncio.wait_for(read(), timeout=300)
        except TimeoutError:
            raise AppError("Время ввода истекло; вход остановлен.") from None
    finally:
        try:
            if original is not None:
                termios.tcsetattr(descriptor, termios.TCSAFLUSH, original)
                write("\n")
        finally:
            characters.clear()
            os.close(descriptor)
