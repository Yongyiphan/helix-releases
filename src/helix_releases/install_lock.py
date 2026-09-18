"""Cross-process lock shared by HR and HU during installation handoffs."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import platform
from typing import Iterator


DEFAULT_INSTALL_LOCK = Path("/run/helix/install.lock")


def lock_path(path: Path | None = None) -> Path:
    return Path(path or os.environ.get("HELIX_INSTALL_LOCK_PATH", DEFAULT_INSTALL_LOCK)).expanduser()


@contextmanager
def installation_lock(path: Path | None = None) -> Iterator[None]:
    """Serialize HR bootstrap and HU activation across processes.

    The path is intentionally overridable so disposable rehearsals never touch
    the host runtime.  Both components use the same default path in production.
    """
    target = lock_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = target.open("a+")
    try:
        if platform.system().lower() == "windows":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if platform.system().lower() == "windows":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
