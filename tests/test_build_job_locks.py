from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from rag_modules.runtime.build_jobs import locks
from rag_modules.runtime.build_jobs.locks import InterprocessFileLock

ROOT = Path(__file__).resolve().parents[1]


class _File:
    def __init__(self, *, close_error: OSError | None = None) -> None:
        self.closed = False
        self.close_error = close_error
        self.seeks: list[int] = []

    def seek(self, offset: int) -> None:
        self.seeks.append(offset)

    def fileno(self) -> int:
        return 7

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class _ControlledProcessLock:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.allowed = threading.Event()
        self.released = threading.Event()

    def acquire(self, *, blocking: bool) -> bool:
        assert blocking is True
        self.entered.set()
        if not self.allowed.wait(timeout=10):
            raise TimeoutError("process lock gate was not released")
        return True

    def release(self) -> None:
        self.released.set()


def _run_nonblocking_process_probe(path: Path) -> subprocess.CompletedProcess[str]:
    program = """
import sys
from rag_modules.runtime.build_jobs.locks import InterprocessFileLock

lock = InterprocessFileLock(sys.argv[1], blocking=False)
if not lock.acquire():
    raise SystemExit(3)
lock.release()
"""
    return subprocess.run(
        [sys.executable, "-c", program, str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_windows_backend_selects_blocking_flags_and_unlocks() -> None:
    api = SimpleNamespace(LK_LOCK=1, LK_NBLCK=2, LK_UNLCK=3, locking=Mock())
    backend = locks._WindowsFileLockBackend(api)
    file = _File()

    backend.lock(file, blocking=True)
    backend.lock(file, blocking=False)
    backend.unlock(file)

    assert api.locking.call_args_list[0].args == (7, 1, 1)
    assert api.locking.call_args_list[1].args == (7, 2, 1)
    assert api.locking.call_args_list[2].args == (7, 3, 1)
    assert file.seeks == [0, 0, 0]


def test_posix_backend_selects_blocking_flags_and_unlocks() -> None:
    api = SimpleNamespace(LOCK_EX=1, LOCK_NB=2, LOCK_UN=4, flock=Mock())
    backend = locks._PosixFileLockBackend(api)
    file = _File()

    backend.lock(file, blocking=True)
    backend.lock(file, blocking=False)
    backend.unlock(file)

    assert api.flock.call_args_list[0].args == (7, 1)
    assert api.flock.call_args_list[1].args == (7, 3)
    assert api.flock.call_args_list[2].args == (7, 4)


def test_backend_loader_selects_windows_api() -> None:
    api = SimpleNamespace(LK_LOCK=1, LK_NBLCK=2, LK_UNLCK=3, locking=Mock())
    with patch.object(locks.sys, "platform", "win32"), patch.dict(sys.modules, {"msvcrt": api}):
        backend = locks._load_file_lock_backend()

    assert isinstance(backend, locks._WindowsFileLockBackend)
    assert backend._api is api


def test_backend_loader_selects_posix_api() -> None:
    api = SimpleNamespace(LOCK_EX=1, LOCK_NB=2, LOCK_UN=4, flock=Mock())
    with patch.object(locks.sys, "platform", "linux"), patch.dict(sys.modules, {"fcntl": api}):
        backend = locks._load_file_lock_backend()

    assert isinstance(backend, locks._PosixFileLockBackend)
    file = _File()
    backend.lock(file, blocking=False)
    backend.unlock(file)
    assert api.flock.call_args_list[0].args == (7, 3)
    assert api.flock.call_args_list[1].args == (7, 4)


def test_windows_process_lock_identity_collapses_case_aliases() -> None:
    with (
        patch.object(locks.sys, "platform", "win32"),
        patch.object(locks.os.path, "abspath", side_effect=lambda value: value),
        patch.object(locks.os.path, "normcase", side_effect=lambda value: value.casefold()),
    ):
        first = locks._process_file_lock("C:/TaskFix/Jobs.LOCK")
        second = locks._process_file_lock("c:/taskfix/jobs.lock")

    assert first is second


def test_posix_process_lock_identity_preserves_case_distinctions() -> None:
    normcase = Mock(side_effect=lambda value: value.casefold())
    with (
        patch.object(locks.sys, "platform", "linux"),
        patch.object(locks.os.path, "abspath", side_effect=lambda value: value),
        patch.object(locks.os.path, "normcase", normcase),
    ):
        upper = locks._process_file_lock("/tmp/TaskFix/Jobs.LOCK")
        lower = locks._process_file_lock("/tmp/taskfix/jobs.lock")

    assert upper is not lower
    normcase.assert_not_called()


def test_nonblocking_same_process_contention_and_context_failure(tmp_path: Path) -> None:
    path = tmp_path / "locks" / "jobs.lock"
    equivalent_path = path.parent / ".." / "locks" / "jobs.lock"
    first = InterprocessFileLock(str(path))
    second = InterprocessFileLock(str(equivalent_path), blocking=False)

    assert first.path == second.path
    assert first._process_lock is second._process_lock
    assert first.acquire() is True
    assert first.acquire() is True
    assert second.acquire() is False
    with pytest.raises(BlockingIOError, match="Could not acquire"):
        with second:
            raise AssertionError("context body must not run")

    first.release()
    assert second.acquire() is True
    second.release()
    second.release()


def test_blocking_thread_contender_waits_inside_process_lock(tmp_path: Path) -> None:
    path = tmp_path / "jobs.lock"
    contender = InterprocessFileLock(str(path))
    process_lock = _ControlledProcessLock()
    contender._process_lock = process_lock
    acquired = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def acquire_in_thread() -> None:
        try:
            with contender:
                acquired.set()
        except BaseException as exc:  # pragma: no cover - asserted through errors
            errors.append(exc)
        finally:
            finished.set()

    thread = threading.Thread(target=acquire_in_thread)
    thread.start()
    try:
        assert process_lock.entered.wait(timeout=10)
        assert acquired.is_set() is False
    finally:
        process_lock.allowed.set()
    assert acquired.wait(timeout=10)
    assert finished.wait(timeout=10)
    thread.join(timeout=10)

    assert thread.is_alive() is False
    assert process_lock.released.is_set()
    assert errors == []


def test_nonblocking_process_contender_observes_os_lock_and_release(tmp_path: Path) -> None:
    path = tmp_path / "jobs.lock"
    with InterprocessFileLock(str(path)):
        blocked = _run_nonblocking_process_probe(path)
        assert blocked.returncode == 3, blocked.stderr

    acquired = _run_nonblocking_process_probe(path)
    assert acquired.returncode == 0, acquired.stderr


def test_acquire_open_failure_releases_process_lock(tmp_path: Path) -> None:
    path = tmp_path / "jobs.lock"
    lock = InterprocessFileLock(str(path))

    with patch("builtins.open", side_effect=OSError("disk unavailable")):
        with pytest.raises(OSError, match="disk unavailable"):
            lock.acquire()

    contender = InterprocessFileLock(str(path), blocking=False)
    assert contender.acquire() is True
    contender.release()


def test_nonblocking_open_failure_propagates_and_releases_process_lock(tmp_path: Path) -> None:
    path = tmp_path / "jobs.lock"
    lock = InterprocessFileLock(str(path), blocking=False)

    with patch("builtins.open", side_effect=OSError("disk unavailable")):
        with pytest.raises(OSError, match="disk unavailable"):
            lock.acquire()

    contender = InterprocessFileLock(str(path), blocking=False)
    assert contender.acquire() is True
    contender.release()


@pytest.mark.parametrize("blocking", [True, False])
def test_acquire_directory_failure_propagates_and_releases_process_lock(
    tmp_path: Path, *, blocking: bool
) -> None:
    path = tmp_path / "missing" / "jobs.lock"
    lock = InterprocessFileLock(str(path), blocking=blocking)

    with patch.object(locks.os, "makedirs", side_effect=OSError("directory unavailable")):
        with pytest.raises(OSError, match="directory unavailable"):
            lock.acquire()

    contender = InterprocessFileLock(str(path), blocking=False)
    assert contender.acquire() is True
    contender.release()


def test_backend_failure_closes_file_and_nonblocking_returns_false(tmp_path: Path) -> None:
    backend = Mock()
    backend.lock.side_effect = OSError("busy")
    file = _File()
    lock = InterprocessFileLock(str(tmp_path / "jobs.lock"), blocking=False)
    lock._backend = backend

    with patch("builtins.open", return_value=file):
        assert lock.acquire() is False

    backend.lock.assert_called_once_with(file, blocking=False)
    assert file.closed is True
    contender = InterprocessFileLock(str(tmp_path / "jobs.lock"), blocking=False)
    assert contender.acquire() is True
    contender.release()


def test_backend_and_close_failures_during_acquire_still_release_process_lock(
    tmp_path: Path,
) -> None:
    path = tmp_path / "jobs.lock"
    backend = Mock()
    backend.lock.side_effect = OSError("busy")
    file = _File(close_error=OSError("close failed"))
    lock = InterprocessFileLock(str(path), blocking=False)
    lock._backend = backend

    with patch("builtins.open", return_value=file):
        with pytest.raises(OSError, match="close failed") as error:
            lock.acquire()

    assert str(error.value.__context__) == "busy"
    assert file.closed is True
    contender = InterprocessFileLock(str(path), blocking=False)
    assert contender.acquire() is True
    contender.release()


def test_unexpected_backend_failure_closes_file_and_releases_process_lock(
    tmp_path: Path,
) -> None:
    path = tmp_path / "jobs.lock"
    backend = Mock()
    backend.lock.side_effect = RuntimeError("unsupported backend failure")
    file = _File()
    lock = InterprocessFileLock(str(path))
    lock._backend = backend

    with patch("builtins.open", return_value=file):
        with pytest.raises(RuntimeError, match="unsupported backend failure"):
            lock.acquire()

    assert file.closed is True
    contender = InterprocessFileLock(str(path), blocking=False)
    assert contender.acquire() is True
    contender.release()


def test_context_body_exception_releases_os_and_process_locks(tmp_path: Path) -> None:
    path = tmp_path / "jobs.lock"

    with pytest.raises(RuntimeError, match="body failed"):
        with InterprocessFileLock(str(path)):
            raise RuntimeError("body failed")

    with InterprocessFileLock(str(path), blocking=False):
        pass


def test_unlock_failure_closes_file_and_releases_process_lock(tmp_path: Path) -> None:
    path = tmp_path / "jobs.lock"
    backend = Mock()
    backend.unlock.side_effect = OSError("unlock failed")
    file = _File()
    lock = InterprocessFileLock(str(path))
    lock._backend = backend

    with patch("builtins.open", return_value=file):
        assert lock.acquire() is True
        with pytest.raises(OSError, match="unlock failed"):
            lock.release()

    assert file.closed is True
    contender = InterprocessFileLock(str(path), blocking=False)
    assert contender.acquire() is True
    contender.release()


def test_close_failure_still_releases_process_lock(tmp_path: Path) -> None:
    path = tmp_path / "jobs.lock"
    backend = Mock()
    file = _File(close_error=OSError("close failed"))
    lock = InterprocessFileLock(str(path))
    lock._backend = backend

    with patch("builtins.open", return_value=file):
        assert lock.acquire() is True
        with pytest.raises(OSError, match="close failed"):
            lock.release()

    contender = InterprocessFileLock(str(path), blocking=False)
    assert contender.acquire() is True
    contender.release()


def test_existing_stale_lock_file_is_reused_without_truncation(tmp_path: Path) -> None:
    path = tmp_path / "jobs.lock"
    path.write_bytes(b"stale-owner-marker")

    with InterprocessFileLock(str(path)):
        pass
    assert path.read_bytes() == b"stale-owner-marker"

    with InterprocessFileLock(str(path), blocking=False):
        pass
    assert path.read_bytes() == b"stale-owner-marker"


def test_empty_path_preserves_blocking_and_nonblocking_failure_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    blocking = InterprocessFileLock("")
    nonblocking = InterprocessFileLock("", blocking=False)

    assert blocking.path == nonblocking.path == str(tmp_path)
    for lock in (blocking, nonblocking):
        with pytest.raises(OSError):
            lock.acquire()
