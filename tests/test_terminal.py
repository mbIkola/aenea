"""Real PTY checks with synthetic input only; no Telegram or Proton access."""

import os
import pty
import select
import signal
import sys
import time
import unittest


class TerminalTests(unittest.TestCase):
    def run_terminal(self, script, input_bytes=b"", *, wait_for=b"HEARTBEAT"):
        pid, descriptor = pty.fork()
        if pid == 0:
            # Login command deliberately disconnects pass-cli's stdin reader.
            null = os.open(os.devnull, os.O_RDONLY)
            os.dup2(null, 0)
            os.close(null)
            os.execv(sys.executable, [sys.executable, "-c", script])
        output = b""
        sent = False
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if select.select([descriptor], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(descriptor, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output += chunk
                if not sent and wait_for in output:
                    os.write(descriptor, input_bytes)
                    sent = True
                if b"RESTORED" in output:
                    break
        finally:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
            os.close(descriptor)
        return output

    def test_masked_input_enter_backspace_and_event_loop_progress(self):
        output = self.run_terminal(
            """
import asyncio, os, termios
from aenea_telegram.terminal import prompt_secret
async def main():
    fd = os.open('/dev/tty', os.O_RDWR)
    before = termios.tcgetattr(fd)
    async def heartbeat():
        await asyncio.sleep(0.05)
        print('HEARTBEAT', flush=True)
    task = asyncio.create_task(heartbeat())
    value = await prompt_secret('SYNTHETIC CODE: ', digits_only=True)
    assert value == '12345'
    after = termios.tcgetattr(fd)
    before[3] &= ~getattr(termios, 'PENDIN', 0)
    after[3] &= ~getattr(termios, 'PENDIN', 0)
    assert after == before
    await task
    os.close(fd)
    print('ACCEPTED RESTORED', flush=True)
asyncio.run(main())
""",
            b"12\x7f2345\r",
        )
        self.assertIn(b"HEARTBEAT", output)
        self.assertGreaterEqual(output.count(b"*"), 5)
        self.assertIn(b"ACCEPTED RESTORED", output)
        self.assertNotIn(b"12345", output)

    def test_cancellation_restores_terminal_without_waiting_for_enter(self):
        output = self.run_terminal("""
import asyncio, os, termios
from aenea_telegram.terminal import prompt_secret
async def main():
    fd = os.open('/dev/tty', os.O_RDWR)
    before = termios.tcgetattr(fd)
    task = asyncio.create_task(prompt_secret('SYNTHETIC CODE: '))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    after = termios.tcgetattr(fd)
    before[3] &= ~getattr(termios, 'PENDIN', 0)
    after[3] &= ~getattr(termios, 'PENDIN', 0)
    assert after == before
    os.close(fd)
    print('RESTORED', flush=True)
asyncio.run(main())
""")
        self.assertIn(b"RESTORED", output)

    def test_eof_restores_terminal(self):
        output = self.run_terminal(
            """
import asyncio, os, termios
from aenea_telegram.terminal import prompt_secret
async def main():
    fd = os.open('/dev/tty', os.O_RDWR)
    before = termios.tcgetattr(fd)
    print('HEARTBEAT', flush=True)
    try:
        await prompt_secret('SYNTHETIC CODE: ')
    except EOFError:
        pass
    else:
        raise AssertionError('Expected EOF')
    after = termios.tcgetattr(fd)
    before[3] &= ~getattr(termios, 'PENDIN', 0)
    after[3] &= ~getattr(termios, 'PENDIN', 0)
    assert after == before
    os.close(fd)
    print('RESTORED', flush=True)
asyncio.run(main())
""",
            b"\x04",
            wait_for=b"SYNTHETIC CODE:",
        )
        self.assertIn(b"RESTORED", output)

    def test_bracketed_paste_does_not_become_part_of_code(self):
        output = self.run_terminal(
            """
import asyncio
from aenea_telegram.terminal import prompt_secret
async def main():
    code = await prompt_secret('SYNTHETIC CODE: ', digits_only=True)
    assert code == '12345'
    print('RESTORED', flush=True)
asyncio.run(main())
""",
            b"\x1b[200~12345\x1b[201~\r",
            wait_for=b"SYNTHETIC CODE:",
        )
        self.assertIn(b"RESTORED", output)
        self.assertEqual(output.count(b"*"), 5)
        self.assertNotIn(b"12345", output)

    def test_standalone_escape_does_not_swallow_code_or_enter(self):
        output = self.run_terminal(
            """
import asyncio
from aenea_telegram.terminal import prompt_secret
async def main():
    code = await prompt_secret('SYNTHETIC CODE: ', digits_only=True)
    assert code == '12345'
    print('RESTORED', flush=True)
asyncio.run(main())
""",
            b"\x1b12345\x1b\r",
            wait_for=b"SYNTHETIC CODE:",
        )
        self.assertIn(b"RESTORED", output)
        self.assertEqual(output.count(b"*"), 5)
