"""Session persistence store for Codex lifecycle hooks."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any, Iterator

from agentcontract.constraints.ledger import ConstraintLedger
from agentcontract.trace.store import TraceStore


class SessionLock:
    """Cross-process per-session file lock supporting both Windows and POSIX."""

    def __init__(
        self,
        lock_path: str | Path,
        timeout: float = 10.0,
        retry_interval: float = 0.05,
    ) -> None:
        self.lock_path = Path(lock_path)
        self.timeout = timeout
        self.retry_interval = retry_interval
        self._fd: int | None = None

    def acquire(self) -> None:
        """Acquire lock within timeout seconds, or raise TimeoutError."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        start_time = time.monotonic()
        fd = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT)

        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    # Lock first byte non-blocking
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fd = fd
                return
            except (OSError, BlockingIOError, PermissionError):
                elapsed = time.monotonic() - start_time
                if elapsed >= self.timeout:
                    os.close(fd)
                    raise TimeoutError(
                        f"Timed out after {self.timeout:.1f}s waiting for session lock at {self.lock_path}"
                    )
                time.sleep(self.retry_interval)

    def release(self) -> None:
        """Release lock and close file descriptor."""
        if self._fd is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    try:
                        msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl
                    try:
                        fcntl.flock(self._fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
            finally:
                os.close(self._fd)
                self._fd = None

    def __enter__(self) -> "SessionLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


class SessionTransaction:
    """Active transaction context for atomic, concurrency-safe session operations."""

    def __init__(
        self,
        session_id: str,
        trace_id: str,
        ledger: ConstraintLedger,
        trace_store: TraceStore,
        meta: dict[str, Any],
    ) -> None:
        self.session_id = session_id
        self.trace_id = trace_id
        self.ledger = ledger
        self.trace_store = trace_store
        self.meta = meta
        self.evidence: dict[str, Any] | None = None


def _sanitize_session_id(session_id: str) -> str:
    """Sanitize session_id to ensure safe local filesystem paths."""
    # Allow alphanumeric, hyphen, underscore; replace anything else with underscore
    sanitized = re.sub(r"[^A-Za-z0-9_\-]", "_", session_id.strip())
    return sanitized or "default_session"


def _atomic_write_text(target_path: Path, content: str) -> None:
    """Atomically write text content to target_path using a temporary file in the same directory."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = target_path.parent
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=temp_dir, delete=False) as tf:
        temp_name = tf.name
        tf.write(content)
        tf.flush()
        os.fsync(tf.fileno())

    try:
        os.replace(temp_name, target_path)
    except Exception:
        if os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except OSError:
                pass
        raise


class CodexSessionStore:
    """Persistent storage engine for Codex agent sessions.

    Maintains:
    - ConstraintLedger snapshot (`ledger.json`)
    - TraceStore events (`trace.json`)
    - Session metadata and trace ID correlation (`meta.json`)
    - Additional verification and context records (`evidence.json`)
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        if base_dir is None:
            self._base_dir = Path.cwd() / ".agentcontract" / "sessions"
        else:
            self._base_dir = Path(base_dir).resolve()

    @property
    def base_dir(self) -> Path:
        """Root directory where sessions are persisted."""
        return self._base_dir

    def get_session_dir(self, session_id: str) -> Path:
        """Resolve directory path for a given session ID."""
        clean_id = _sanitize_session_id(session_id)
        return self._base_dir / clean_id

    def session_exists(self, session_id: str) -> bool:
        """Check whether a persisted session exists."""
        sdir = self.get_session_dir(session_id)
        return sdir.is_dir() and (sdir / "meta.json").is_file()

    def get_or_create_session(
        self, session_id: str
    ) -> tuple[str, ConstraintLedger, TraceStore, dict[str, Any]]:
        """Load an existing session or initialize a fresh session state.

        Returns:
            Tuple of `(trace_id, ledger, trace_store, meta_dict)`.
        """
        sdir = self.get_session_dir(session_id)
        meta_file = sdir / "meta.json"
        ledger_file = sdir / "ledger.json"
        trace_file = sdir / "trace.json"

        now_iso = datetime.now(timezone.utc).isoformat()

        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
            trace_id = meta.get("trace_id") or f"trace_{_sanitize_session_id(session_id)}"
            meta["updated_at"] = now_iso
        else:
            trace_id = f"trace_{_sanitize_session_id(session_id)}"
            meta = {
                "session_id": session_id,
                "trace_id": trace_id,
                "created_at": now_iso,
                "updated_at": now_iso,
                "processed_prompts": [],
            }

        # Load Ledger
        if ledger_file.is_file():
            try:
                ledger = ConstraintLedger.from_json(ledger_file.read_text(encoding="utf-8"))
            except Exception:
                ledger = ConstraintLedger()
        else:
            ledger = ConstraintLedger()

        # Load TraceStore
        if trace_file.is_file():
            try:
                trace_store = TraceStore.from_json(trace_file.read_text(encoding="utf-8"))
            except Exception:
                trace_store = TraceStore()
        else:
            trace_store = TraceStore()

        if not meta_file.is_file():
            self.save_session(session_id, ledger, trace_store, meta)

        return trace_id, ledger, trace_store, meta

    def save_session(
        self,
        session_id: str,
        ledger: ConstraintLedger,
        trace_store: TraceStore,
        meta: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        """Persist session state atomically to disk."""
        sdir = self.get_session_dir(session_id)
        sdir.mkdir(parents=True, exist_ok=True)

        now_iso = datetime.now(timezone.utc).isoformat()
        current_meta = dict(meta or {})
        current_meta.setdefault("session_id", session_id)
        current_meta.setdefault("trace_id", f"trace_{_sanitize_session_id(session_id)}")
        current_meta.setdefault("created_at", now_iso)
        current_meta["updated_at"] = now_iso

        # Atomic writes
        _atomic_write_text(sdir / "meta.json", json.dumps(current_meta, indent=2))
        _atomic_write_text(sdir / "ledger.json", ledger.to_json(indent=2))
        _atomic_write_text(sdir / "trace.json", trace_store.to_json(indent=2))

        if evidence is not None:
            _atomic_write_text(sdir / "evidence.json", json.dumps(evidence, indent=2))

    @contextmanager
    def session_transaction(
        self, session_id: str, timeout: float = 10.0
    ) -> Iterator[SessionTransaction]:
        """Execute a concurrency-safe read-modify-write session transaction.

        Acquires a cross-process lock for the session, loads current state,
        yields a SessionTransaction object, and automatically saves the updated
        state upon exiting the context.
        """
        clean_id = _sanitize_session_id(session_id)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self._base_dir / f"{clean_id}.lock"

        with SessionLock(lock_path, timeout=timeout):
            trace_id, ledger, trace_store, meta = self.get_or_create_session(session_id)
            tx = SessionTransaction(
                session_id=session_id,
                trace_id=trace_id,
                ledger=ledger,
                trace_store=trace_store,
                meta=meta,
            )
            yield tx
            self.save_session(
                session_id=session_id,
                ledger=tx.ledger,
                trace_store=tx.trace_store,
                meta=tx.meta,
                evidence=tx.evidence,
            )

    def list_sessions(self) -> list[dict[str, Any]]:
        """List summary information for all stored sessions."""
        if not self._base_dir.is_dir():
            return []

        results: list[dict[str, Any]] = []
        for child in self._base_dir.iterdir():
            if child.is_dir():
                meta_file = child / "meta.json"
                if meta_file.is_file():
                    try:
                        m = json.loads(meta_file.read_text(encoding="utf-8"))
                        results.append(m)
                    except Exception:
                        results.append({"session_id": child.name, "error": "corrupted_meta"})
        return results

    def delete_session(self, session_id: str) -> bool:
        """Remove a session directory."""
        sdir = self.get_session_dir(session_id)
        if not sdir.is_dir():
            return False
        import shutil

        shutil.rmtree(sdir, ignore_errors=True)
        return True
