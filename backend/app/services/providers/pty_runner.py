"""Low-level PTY process management for the interactive `claude` CLI (NEX-352).

A non-TTY invocation of `claude` is reclassified as `sdk-cli`. To get the real
subscription-billed `entrypoint: cli`, `claude` MUST run attached to a real
pseudo-terminal. This module owns that PTY lifecycle.
"""

from __future__ import annotations

import asyncio
import errno
import fcntl
import os
import pty
import signal
import struct
import termios


class PtyProcess:
    """A child process attached to its own PTY, drained asynchronously."""

    def __init__(self, argv: list[str], cwd: str, env: dict | None = None):
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.pid: int | None = None
        self._master_fd: int | None = None
        self._output: list[bytes] = []
        self._reader_task: asyncio.Task | None = None
        self._exited = asyncio.Event()
        self.exit_code: int | None = None

    def _set_winsize(self, rows: int = 50, cols: int = 200) -> None:
        if self._master_fd is None:
            return
        try:
            fcntl.ioctl(
                self._master_fd,
                termios.TIOCSWINSZ,
                struct.pack("HHHH", rows, cols, 0, 0),
            )
        except OSError:
            pass

    def start(self) -> None:
        pid, master_fd = pty.fork()
        if pid == 0:
            try:
                os.chdir(self.cwd)
                if self.env is not None:
                    os.execvpe(self.argv[0], self.argv, self.env)
                else:
                    os.execvp(self.argv[0], self.argv)
            except Exception:
                os._exit(127)
        self.pid = pid
        self._master_fd = master_fd
        os.set_blocking(master_fd, False)
        self._set_winsize()

    def _read_once(self) -> None:
        if self._master_fd is None:
            return
        try:
            data = os.read(self._master_fd, 65536)
            if data:
                self._output.append(data)
        except OSError as e:
            if e.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise

    async def _drain_loop(self) -> None:
        while True:
            try:
                self._read_once()
            except OSError:
                break
            done_pid, status = os.waitpid(self.pid, os.WNOHANG)
            if done_pid == self.pid:
                try:
                    self._read_once()
                except OSError:
                    pass
                if os.WIFEXITED(status):
                    self.exit_code = os.WEXITSTATUS(status)
                elif os.WIFSIGNALED(status):
                    self.exit_code = -os.WTERMSIG(status)
                self._exited.set()
                break
            await asyncio.sleep(0.05)

    def begin_drain(self) -> None:
        self._reader_task = asyncio.create_task(self._drain_loop())

    def write(self, data: bytes) -> None:
        if self._master_fd is None:
            return
        try:
            os.write(self._master_fd, data)
        except OSError:
            pass

    @property
    def exited(self) -> asyncio.Event:
        return self._exited

    def output_text(self) -> str:
        return b"".join(self._output).decode("utf-8", errors="replace")

    async def wait(self, timeout: float | None = None) -> int | None:
        try:
            await asyncio.wait_for(self._exited.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        return self.exit_code

    def terminate(self) -> None:
        """Best-effort clean shutdown: SIGINT, then SIGTERM, then SIGKILL."""
        if self.pid is None:
            return
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(self.pid, sig)
            except ProcessLookupError:
                break
            except OSError:
                break

    async def shutdown(self, grace: float = 3.0) -> None:
        if self.pid is not None and not self._exited.is_set():
            try:
                os.kill(self.pid, signal.SIGINT)
            except OSError:
                pass
            if await self.wait(timeout=grace) is None:
                try:
                    os.kill(self.pid, signal.SIGTERM)
                except OSError:
                    pass
                if await self.wait(timeout=2.0) is None:
                    try:
                        os.kill(self.pid, signal.SIGKILL)
                    except OSError:
                        pass
                    await self.wait(timeout=2.0)
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
