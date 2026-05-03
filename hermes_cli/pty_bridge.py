"""PTY bridge for `hermes dashboard` chat tab.

Wraps a child process behind a pseudo-terminal so its ANSI output can be
streamed to a browser-side terminal emulator (xterm.js) and typed
keystrokes can be fed back in.  The only caller today is the
``/api/pty`` WebSocket endpoint in ``hermes_cli.web_server``.

* **POSIX:** ``ptyprocess`` + ``fcntl``/``termios`` on the master fd.
* **Windows:** ``pywinpty`` (ConPTY/WinPTY) with a socket bridge — same
  ``hermes --tui`` argv as POSIX.  Install ``pywinpty`` (pulled in by the
  ``[web]`` extra on Windows, or ``pip install pywinpty``).
* **Byte-safe I/O.**  Reads and writes are byte-oriented for the WebSocket
  path; winpty text I/O is transcoded at the boundary.
"""

from __future__ import annotations

import errno
import os
import select
import signal
import socket
import struct
import sys
import time
from typing import Any, Optional, Sequence

# POSIX-only; native Windows has no fcntl/termios — import lazily so the
# dashboard can load and serve API/static routes without the embedded PTY tab.
if sys.platform.startswith("win"):
    fcntl = None  # type: ignore[assignment]
    termios = None  # type: ignore[assignment]
else:
    import fcntl
    import termios

try:
    import ptyprocess  # type: ignore
except ImportError:  # pragma: no cover - dev env without ptyprocess
    ptyprocess = None  # type: ignore

_WINPTY_PTYPROCESS: Any = None
if sys.platform.startswith("win"):
    try:
        import winpty.ptyprocess as _winpty_ptyprocess  # type: ignore

        _WINPTY_PTYPROCESS = _winpty_ptyprocess
    except Exception:
        _WINPTY_PTYPROCESS = None


def _pty_supported() -> bool:
    if sys.platform.startswith("win"):
        return _WINPTY_PTYPROCESS is not None
    return ptyprocess is not None


_PTY_AVAILABLE = _pty_supported()

__all__ = ["PtyBridge", "PtyUnavailableError"]


class PtyUnavailableError(RuntimeError):
    """Raised when a PTY cannot be created on this platform.

    On Windows without ``pywinpty``, or when ``ptyprocess`` is missing on
    POSIX, the dashboard surfaces this message in the chat tab.
    """


class PtyBridge:
    """Thin wrapper: ``ptyprocess`` (POSIX) or ``winpty.PtyProcess`` (Windows)."""

    def __init__(
        self,
        proc: Any,
        *,
        backend: str = "posix",
        win_sock: Optional[socket.socket] = None,
    ):
        self._proc = proc
        self._backend = backend
        self._closed = False
        if backend == "winpty":
            self._fd = int(proc.fd)
            self._win_sock: Optional[socket.socket] = win_sock or getattr(
                proc, "fileobj", None
            )
        else:
            self._fd: int = proc.fd
            self._win_sock = None

    @classmethod
    def is_available(cls) -> bool:
        """True if a PTY can be spawned on this platform."""
        return bool(_PTY_AVAILABLE)

    @classmethod
    def spawn(
        cls,
        argv: Sequence[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
        cols: int = 80,
        rows: int = 24,
    ) -> "PtyBridge":
        """Spawn ``argv`` behind a new PTY and return a bridge."""
        if not _PTY_AVAILABLE:
            if sys.platform.startswith("win"):
                raise PtyUnavailableError(
                    "Pseudo-terminals need pywinpty on Windows. "
                    "Install with: pip install pywinpty "
                    "(or pip install -e '.[web]')."
                )
            if ptyprocess is None:
                raise PtyUnavailableError(
                    "The `ptyprocess` package is missing. "
                    "Install with: pip install ptyprocess "
                    "(or pip install -e '.[pty]')."
                )
            raise PtyUnavailableError("Pseudo-terminals are unavailable.")

        spawn_env = os.environ.copy() if env is None else env

        if sys.platform.startswith("win") and _WINPTY_PTYPROCESS is not None:
            proc = _WINPTY_PTYPROCESS.PtyProcess.spawn(  # type: ignore[union-attr]
                list(argv),
                cwd=cwd or os.getcwd(),
                env=spawn_env,
                dimensions=(rows, cols),
            )
            return cls(proc, backend="winpty")

        proc = ptyprocess.PtyProcess.spawn(  # type: ignore[union-attr]
            list(argv),
            cwd=cwd,
            env=spawn_env,
            dimensions=(rows, cols),
        )
        return cls(proc, backend="posix")

    @property
    def pid(self) -> int:
        return int(self._proc.pid)

    def is_alive(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self._proc.isalive())
        except Exception:
            return False

    def read(self, timeout: float = 0.2) -> Optional[bytes]:
        """Read raw bytes from the PTY (POSIX: master fd; Windows: bridge socket)."""
        if self._closed:
            return None

        if self._backend == "winpty":
            sock = self._win_sock
            if sock is None:
                return None
            try:
                sock.settimeout(timeout)
                data = sock.recv(65536)
            except socket.timeout:
                return b""
            except OSError as exc:
                if exc.errno in (errno.ECONNRESET, errno.ECONNABORTED, errno.EPIPE):
                    return None
                return b""
            if not data:
                return None
            return data

        try:
            readable, _, _ = select.select([self._fd], [], [], timeout)
        except (OSError, ValueError):
            return None
        if not readable:
            return b""
        try:
            data = os.read(self._fd, 65536)
        except OSError as exc:
            if exc.errno in (errno.EIO, errno.EBADF):
                return None
            raise
        if not data:
            return None
        return data

    def write(self, data: bytes) -> None:
        """Write raw bytes to the PTY master."""
        if self._closed or not data:
            return

        if self._backend == "winpty":
            try:
                text = data.decode("utf-8", errors="surrogateescape")
            except Exception:
                text = data.decode("latin-1", errors="replace")
            try:
                self._proc.write(text)
            except (OSError, EOFError, TypeError, ValueError):
                return
            return

        view = memoryview(data)
        while view:
            try:
                n = os.write(self._fd, view)
            except OSError as exc:
                if exc.errno in (errno.EIO, errno.EBADF, errno.EPIPE):
                    return
                raise
            if n <= 0:
                return
            view = view[n:]

    def resize(self, cols: int, rows: int) -> None:
        """Forward a terminal resize to the child."""
        if self._closed:
            return
        if self._backend == "winpty":
            try:
                self._proc.setwinsize(rows, cols)  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        if fcntl is None or termios is None:
            return
        winsize = struct.pack("HHHH", max(1, rows), max(1, cols), 0, 0)
        try:
            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    def close(self) -> None:
        """Terminate the child and release resources."""
        if self._closed:
            return
        self._closed = True

        if self._backend == "winpty":
            try:
                self._proc.close(force=True)  # type: ignore[attr-defined]
            except Exception:
                pass
            return

        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGKILL):
            if not self._proc.isalive():
                break
            try:
                self._proc.kill(sig)
            except Exception:
                pass
            deadline = time.monotonic() + 0.5
            while self._proc.isalive() and time.monotonic() < deadline:
                time.sleep(0.02)

        try:
            self._proc.close(force=True)
        except Exception:
            pass

    def __enter__(self) -> "PtyBridge":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
