"""A lock on a state file that other programs honour too: the server, the `aerosuite` command, a second server.

Held while the file is read, changed and saved, so one program's save cannot undo another's. The lock is on
`<file>.lock` beside the file (flock; on Windows a locked first byte) and the system drops it when its program ends,
so a crash never leaves one behind."""
from __future__ import annotations

import errno
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .errors import AeroSuiteError

LOCK_TIMEOUT = 20.0  # seconds to wait for another program; it holds the lock for one read and one save
_RETRY = 0.02
_held = threading.local()  # this thread's locks, by path: taking one again inside itself just goes on


class LockError(AeroSuiteError):
    """Another AeroSuite program kept a state file's lock for too long."""


def _try_lock(handle) -> bool:
    """Take the lock without waiting. True when it is held, or when this folder cannot lock at all (some network
    drives): going on unlocked is then what there was before."""
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        if exc.errno in (errno.EAGAIN, errno.EACCES, errno.EDEADLK) or isinstance(exc, BlockingIOError):
            return False
        return True


def _unlock(handle) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def file_lock(target: Path, timeout: float = LOCK_TIMEOUT) -> Iterator[None]:
    """Hold the lock of the state file `target` (the lock file is `<target>.lock`) for the block."""
    path = Path(str(target) + ".lock")
    held = _held.__dict__.setdefault("locks", {})
    if str(path) in held:  # this thread has it already
        yield
        return
    handle = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+b")
        if os.name == "nt" and path.stat().st_size == 0:
            handle.write(b"\0")  # a byte to lock
            handle.flush()
    except OSError:
        handle = None  # a folder that cannot be written: the save itself will say so
    if handle is not None:
        deadline = time.monotonic() + timeout
        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                handle.close()
                raise LockError(f"{Path(target).name} is in use by another AeroSuite program (waited {timeout:.0f} s "
                                f"for {path}); try again")
            time.sleep(_RETRY)
    held[str(path)] = True
    try:
        yield
    finally:
        del held[str(path)]
        if handle is not None:
            _unlock(handle)
            handle.close()
