"""Cross-process locks for build-job runtime adapters."""

from __future__ import annotations

import os
import sys
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


class _WindowsFileLockBackend:
    def __init__(self, api: Any) -> None:
        self._api = api

    def lock(self, file: BinaryIO, *, blocking: bool) -> None:
        file.seek(0)
        mode = self._api.LK_LOCK if blocking else self._api.LK_NBLCK
        self._api.locking(file.fileno(), mode, 1)

    def unlock(self, file: BinaryIO) -> None:
        file.seek(0)
        self._api.locking(file.fileno(), self._api.LK_UNLCK, 1)


class _PosixFileLockBackend:
    def __init__(self, api: Any) -> None:
        self._api = api

    def lock(self, file: BinaryIO, *, blocking: bool) -> None:
        flags = self._api.LOCK_EX
        if not blocking:
            flags |= self._api.LOCK_NB
        self._api.flock(file.fileno(), flags)

    def unlock(self, file: BinaryIO) -> None:
        self._api.flock(file.fileno(), self._api.LOCK_UN)


def _load_file_lock_backend() -> _WindowsFileLockBackend | _PosixFileLockBackend:
    if sys.platform == "win32":
        import msvcrt

        return _WindowsFileLockBackend(msvcrt)
    fcntl = cast(Any, __import__("fcntl"))
    return _PosixFileLockBackend(fcntl)


class InterprocessFileLock:
    """Small cross-platform exclusive file lock."""

    def __init__(self, path: str, *, blocking: bool = True) -> None:
        self.path = os.path.abspath(path)
        self.blocking = bool(blocking)
        self._process_lock = _process_file_lock(self.path)
        self._backend = _load_file_lock_backend()
        self._file: BinaryIO | None = None
        self._acquired = False

    def acquire(self) -> bool:
        if self._acquired:
            return True
        if not self._process_lock.acquire(blocking=self.blocking):
            return False
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            file = open(self.path, "a+b")
        except BaseException:
            self._process_lock.release()
            raise
        try:
            self._backend.lock(file, blocking=self.blocking)
        except BaseException as exc:
            try:
                file.close()
            finally:
                self._process_lock.release()
            if isinstance(exc, OSError) and not self.blocking:
                return False
            raise
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
                self._backend.unlock(file)
        finally:
            try:
                if file is not None:
                    file.close()
            finally:
                self._process_lock.release()

    def __enter__(self) -> "InterprocessFileLock":
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


__all__ = ["InterprocessFileLock"]
