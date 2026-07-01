"""Cross-process locks for build-job store files."""

from __future__ import annotations

import os
import threading
from types import TracebackType
from typing import Any, BinaryIO, cast

_PROCESS_FILE_LOCKS: dict[str, threading.Lock] = {}
_PROCESS_FILE_LOCKS_LOCK = threading.Lock()


def _process_file_lock(path: str) -> threading.Lock:
    normalized_path = os.path.abspath(path)
    with _PROCESS_FILE_LOCKS_LOCK:
        lock = _PROCESS_FILE_LOCKS.get(normalized_path)
        if lock is None:
            lock = threading.Lock()
            _PROCESS_FILE_LOCKS[normalized_path] = lock
        return lock


class _InterprocessFileLock:
    """Small cross-platform exclusive file lock."""

    def __init__(self, path: str, *, blocking: bool = True) -> None:
        self.path = os.path.abspath(path)
        self.blocking = bool(blocking)
        self._process_lock = _process_file_lock(self.path)
        self._file: BinaryIO | None = None
        self._acquired = False

    def acquire(self) -> bool:
        if self._acquired:
            return True
        if not self._process_lock.acquire(blocking=self.blocking):
            return False
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        file = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                file.seek(0)
                mode = msvcrt.LK_LOCK if self.blocking else msvcrt.LK_NBLCK
                msvcrt.locking(file.fileno(), mode, 1)
            else:
                fcntl = cast(Any, __import__("fcntl"))

                flags = fcntl.LOCK_EX
                if not self.blocking:
                    flags |= fcntl.LOCK_NB
                fcntl.flock(file.fileno(), flags)
        except OSError:
            file.close()
            self._process_lock.release()
            if self.blocking:
                raise
            return False
        self._file = file
        self._acquired = True
        return True

    def release(self) -> None:
        if not self._acquired:
            return
        file = self._file
        self._file = None
        self._acquired = False
        try:
            if file is not None:
                if os.name == "nt":
                    import msvcrt

                    file.seek(0)
                    msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl = cast(Any, __import__("fcntl"))

                    fcntl.flock(file.fileno(), fcntl.LOCK_UN)
        finally:
            if file is not None:
                file.close()
            self._process_lock.release()

    def __enter__(self) -> "_InterprocessFileLock":
        if not self.acquire():
            raise BlockingIOError(f"Could not acquire file lock: {self.path}")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()


__all__ = ["_InterprocessFileLock"]
