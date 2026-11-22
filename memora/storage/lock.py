"""
Cross-platform advisory locking for MEMORA.

Provides consistent lock semantics across Windows and POSIX systems.
Uses native OS locking primitives with a persistent lock file.
"""

import os
import sys
import time
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

logger = logging.getLogger("memora.storage.lock")


class LockBackend(ABC):
    """Abstract base class for platform-specific lock implementations."""

    @abstractmethod
    def acquire(self, fd: int, blocking: bool, timeout: float) -> bool:
        """Acquire lock on file descriptor."""
        pass

    @abstractmethod
    def release(self, fd: int) -> None:
        """Release lock on file descriptor."""
        pass


class PosixLockBackend(LockBackend):
    """POSIX advisory locking using fcntl.flock()."""

    def acquire(self, fd: int, blocking: bool, timeout: float) -> bool:
        import fcntl

        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB

        end_time = time.monotonic() + timeout if blocking else 0

        while True:
            try:
                fcntl.flock(fd, flags)
                return True
            except BlockingIOError:
                if not blocking:
                    return False
                if time.monotonic() >= end_time:
                    raise TimeoutError(f"Lock acquisition timed out after {timeout}s")
                time.sleep(0.1)
            except Exception:
                raise

    def release(self, fd: int) -> None:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


class WindowsLockBackend(LockBackend):
    """Windows mandatory locking using msvcrt.locking()."""

    def acquire(self, fd: int, blocking: bool, timeout: float) -> bool:
        import msvcrt

        end_time = time.monotonic() + timeout if blocking else 0

        while True:
            try:
                # msvcrt.locking uses bytes count, lock entire file region
                # Seek to beginning and lock maximum possible range
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 2**31 - 1)
                return True
            except OSError as e:
                if not blocking and e.errno == 13:  # Permission denied / would block
                    return False
                if blocking and time.monotonic() >= end_time:
                    raise TimeoutError(f"Lock acquisition timed out after {timeout}s")
                if blocking:
                    time.sleep(0.1)
                else:
                    raise
            except Exception:
                raise

    def release(self, fd: int) -> None:
        import msvcrt
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 2**31 - 1)
        except OSError:
            # Best effort release
            pass


def get_lock_backend() -> LockBackend:
    """Get the appropriate lock backend for the current platform."""
    if sys.platform == "win32":
        return WindowsLockBackend()
    return PosixLockBackend()


class LockManager:
    """
    Persistent advisory lock manager for SQLite database.

    Features:
    - Cross-platform (Windows + POSIX)
    - Persistent lock file (NEVER unlinked)
    - Configurable timeout (default 30s)
    - Async-safe acquisition via asyncio.to_thread()
    - Context manager support (sync + async)
    """

    def __init__(self, db_path: Path, timeout: float = 30.0):
        """
        Initialize lock manager.

        Args:
            db_path: Path to SQLite database file
            timeout: Maximum time to wait for lock acquisition (seconds)
        """
        self.db_path = db_path
        self.timeout = timeout
        self.lock_path = db_path.with_suffix(db_path.suffix + ".lock")
        self._lock_fd: Optional[int] = None
        self._acquired = False
        self._backend = get_lock_backend()

    def acquire(self, blocking: bool = True) -> bool:
        """
        Acquire the advisory lock.

        Args:
            blocking: If True, wait up to timeout. If False, return immediately.

        Returns:
            True if lock acquired, False if non-blocking and lock not available.

        Raises:
            TimeoutError: If blocking=True and timeout exceeded.
        """
        # Ensure lock file exists (create if needed, keep persistent)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.touch(mode=0o644, exist_ok=True)

        # Open lock file (keep fd open for duration of lock)
        # O_RDWR for both read/write locking compatibility
        self._lock_fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT)

        try:
            result = self._backend.acquire(self._lock_fd, blocking, self.timeout)
            if result:
                self._acquired = True
                logger.debug(f"Lock acquired on {self.lock_path}")
            return result
        except Exception:
            self._close_fd()
            raise

    def release(self) -> None:
        """Release the advisory lock. Keeps lock file persistent (no unlink)."""
        if self._acquired and self._lock_fd is not None:
            try:
                self._backend.release(self._lock_fd)
                logger.debug(f"Lock released on {self.lock_path}")
            finally:
                self._close_fd()
                self._acquired = False

    def _close_fd(self) -> None:
        """Close the lock file descriptor."""
        if self._lock_fd is not None:
            try:
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

    def __enter__(self):
        """Sync context manager entry - acquires blocking lock."""
        self.acquire(blocking=True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Sync context manager exit - releases lock."""
        self.release()

    async def acquire_async(self, blocking: bool = True) -> bool:
        """
        Asynchronously acquire the advisory lock.

        Uses asyncio.to_thread() to avoid blocking the event loop
        during synchronous flock polling. Preserves the existing
        30-second timeout.

        Args:
            blocking: If True, wait up to timeout. If False, return immediately.

        Returns:
            True if lock acquired, False if non-blocking and lock not available.

        Raises:
            TimeoutError: If blocking=True and timeout exceeded.
        """
        import asyncio
        return await asyncio.to_thread(self.acquire, blocking)

    async def __aenter__(self):
        """Async context manager entry - acquires blocking lock."""
        await self.acquire_async(blocking=True)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - releases lock."""
        self.release()

    def is_locked(self) -> bool:
        """Check if lock is currently held by this process."""
        return self._acquired