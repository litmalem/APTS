"""Compensate only resources created by this runtime; no paths, commands or PID lookup."""
from __future__ import annotations

from pathlib import Path


def resource_snapshot(runtime):
    workers = []
    for index, worker in enumerate(runtime.cleanup_workers, 1):
        process = worker.process
        workers.append({"ordinal":index, "backend":worker.backend,
            "process_started":process is not None,
            "worker_exit_confirmed":process is None or process.poll() is not None,
            "return_code":None if process is None else process.returncode,
            "pipes_closed":process is None or all(s is None or s.closed for s in
                (process.stdin, process.stdout, process.stderr)),
            "readers_stopped":all(t is None or not t.is_alive() for t in (worker.reader, worker.stderr_reader)),
            "temporary_directory_removed":worker.folder is not None and not Path(worker.folder.name).exists(),
            "job_handle_released":worker.job is None or worker.job.handle is None})
    with runtime._lock:
        detached = not runtime._closers
    return {"workers":workers, "socket_count":len(runtime.cleanup_sockets),
        "sockets_closed":all(s.fileno() == -1 for s in runtime.cleanup_sockets),
        "runtime_closers_detached":detached}


def resources_verified(snapshot):
    return (snapshot["sockets_closed"] and snapshot["runtime_closers_detached"]
        and all(all(w[k] for k in ("worker_exit_confirmed", "pipes_closed", "readers_stopped",
            "temporary_directory_removed", "job_handle_released")) for w in snapshot["workers"]))


def rollback_local_resources(runtime):
    """A bounded second cleanup of exact owned objects, followed by OS-level checks."""
    before = resource_snapshot(runtime)
    attempted = not resources_verified(before)
    errors = []
    if attempted:
        for sock in runtime.cleanup_sockets:
            try:
                sock.close()
            except Exception as exc:
                errors.append(type(exc).__name__)
        for worker in runtime.cleanup_workers:
            try:
                worker.close()
            except Exception as exc:
                errors.append(type(exc).__name__)
    after = resource_snapshot(runtime)
    return {"before_rollback":before, "after_rollback":after,
        "rollback_attempted":attempted, "rollback_errors":errors[:8],
        "interrupt_cleanup_errors":list(runtime.cleanup_errors[:8])}


class RevocableCredentialLeaseStore:
    """Deny persistent execution-scoped lease access; never claim issuer token revocation."""
    def __init__(self, delegate, repository):
        self.delegate = delegate
        self.repository = repository

    def acquire(self, lease_id, request, adapter, now):
        from .execution_contract import ExecutionSourceRejected
        if self.repository.lease_revoked(lease_id, request["execution_id"]):
            raise ExecutionSourceRejected("CREDENTIAL_LEASE_LOCALLY_REVOKED")
        return self.delegate.acquire(lease_id, request, adapter, now)
