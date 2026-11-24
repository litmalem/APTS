"""OS ownership fencing and interruptible trusted broker/worker resources."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import queue
import socket
from threading import Event, RLock, Thread
import time

from .execution_contract import ExecutionSourceRejected
from .request_repository import ExecutionRepositoryError
from .runtime_contract import HEARTBEAT_TIMEOUT_SECONDS, POLL_SECONDS


class RuntimeStopped(ExecutionSourceRejected):
    pass


class RuntimeOwnerLock:
    def __init__(self, database):
        self.path = Path(str(database) + ".runtime.lock")
        self.file = None

    def acquire(self):
        database = Path(str(self.path)[:-len(".runtime.lock")])
        if database.exists() and database.stat().st_nlink > 1:
            raise ExecutionRepositoryError("HARD_LINKED_RUNTIME_DATABASE_FORBIDDEN")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if self.path.stat().st_size == 0:
                    f.write(b"\0"); f.flush()
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError) as exc:
            f.close()
            raise ExecutionRepositoryError("RUNTIME_OWNER_ALREADY_ACTIVE") from exc
        self.file = f
        return self

    def close(self):
        if self.file:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
            self.file = None


class RuntimeResources:
    def __init__(self, deadline, *, ready=None, boundary=None):
        self.deadline = deadline
        self._ready = ready
        self._boundary = boundary
        self._lock = RLock()
        self._closers = set()
        self.stopped = Event()
        self.done = Event()
        self._authorization_pending = 0
        self._authorization_idle = Event()
        self._authorization_idle.set()
        self.state = None
        self.reason = None
        self.cleanup_errors = []
        # Forensic breadcrumbs attached to the terminal event so a future
        # operator can tell a stalled source read from a true liveness loss.
        self.diagnostics = {}
        self.supervisor_ident = None

    def record_diagnostic(self, key, value):
        with self._lock:
            self.diagnostics[key] = value

    def check(self):
        if time.monotonic() >= self.deadline and not self.stopped.is_set():
            self.stop("TIMEOUT", "RUNTIME_WALL_DEADLINE")
        if self.stopped.is_set():
            raise RuntimeStopped(self.reason or "RUNTIME_STOPPED")

    def tighten_deadline(self, deadline):
        with self._lock:
            self.deadline = min(self.deadline, deadline)
        self.check()

    def stop(self, state, reason):
        with self._lock:
            ranks = {None:0, "TIMEOUT":1, "FAILED":2, "CANCELLED":3, "ABORTED":4}
            if ranks.get(state, 0) > ranks.get(self.state, 0):
                self.state, self.reason = state, reason
            self.stopped.set()
            closers = list(self._closers)
        for close in closers:
            try:
                close()
            except Exception as exc:
                self.cleanup_errors.append(type(exc).__name__)

    @contextmanager
    def attach(self, closer):
        with self._lock:
            if self.stopped.is_set():
                closer()
                self.check()
            self._closers.add(closer)
        try:
            self.check()
            yield
        finally:
            with self._lock:
                self._closers.discard(closer)

    def attach_worker(self, closer):
        with self._lock:
            if self.stopped.is_set():
                closer()
                self.check()
            self._closers.add(closer)

    def detach_worker(self, closer):
        with self._lock:
            self._closers.discard(closer)

    def worker_ready(self, worker):
        self.check()
        if self._ready:
            self._ready(worker)
        self.check()

    def before_target_io(self):
        self.check()
        if self._boundary:
            self._boundary()
        self.check()

    def check_authorization(self):
        if self.done.is_set():
            raise RuntimeStopped("RUNTIME_ATTEMPT_COMPLETED")
        self.check()

    @contextmanager
    def authorization(self):
        # Admission and completion share a lock: a delayed helper cannot enter
        # authority work after finish() closes this attempt's lifecycle.
        self.check_authorization()
        with self._lock:
            if self.done.is_set() or self.stopped.is_set():
                raise RuntimeStopped(self.reason or "RUNTIME_ATTEMPT_COMPLETED")
            self._authorization_pending += 1
            self._authorization_idle.clear()
        try:
            yield
        finally:
            with self._lock:
                self._authorization_pending -= 1
                if not self._authorization_pending:
                    self._authorization_idle.set()

    def finish(self):
        with self._lock:
            if self.done.is_set():
                return
            self.done.set()
        # Successful completion drains already admitted authority work before
        # publishing a terminal record. Cancellation remains interruptible;
        # an already issued control-plane call may return, but its result is
        # rejected by check_authorization() and cannot authorize target I/O.
        until = time.monotonic() + HEARTBEAT_TIMEOUT_SECONDS
        while True:
            try:
                self.check()
            except RuntimeStopped:
                return
            if self._authorization_idle.is_set():
                return
            remaining = until - time.monotonic()
            if remaining <= 0:
                self.stop("ABORTED", "RUNTIME_AUTHORIZATION_QUIESCENCE_TIMEOUT")
                return
            self._authorization_idle.wait(min(POLL_SECONDS, remaining))

    def bounded_call(self, action):
        # The detached helper can finish only source/authority work. Its return
        # value is discarded on stop and never controls a target on its own.
        pending = queue.Queue(maxsize=1)
        def call():
            try:
                with self.authorization():
                    pending.put((True, action()))
            except BaseException as exc:
                pending.put((False, exc))
        self.check_authorization()
        Thread(target=call, daemon=True).start()
        while True:
            self.check_authorization()
            try:
                ok, value = pending.get(timeout=POLL_SECONDS)
            except queue.Empty:
                continue
            self.check_authorization()
            if not ok:
                raise value
            return value


def stop_socket(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    sock.close()
