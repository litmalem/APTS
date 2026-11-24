"""Asynchronous, server-owned execution supervision over Stage 6.4 adapters."""
from __future__ import annotations

from datetime import timedelta
import logging
import queue
import sys
from threading import RLock, Thread, local, get_ident
import time
import traceback
from uuid import uuid4

from .adapter_contract import normalize_adapter_intake
from .adapter_policy import compile_runtime_policy
from .adapter_service import ExecutionAdapterService
from .authorization_contract import parse_time, utc_timestamp
from .execution_contract import (ExecutionRequestConflict, ExecutionRequestIntegrityError,
    ExecutionRequestValidationError, ExecutionSourceNotFound, ExecutionSourceRejected, canonical_json)
from .request_repository import ExecutionRepositoryError
from .runtime_contract import (HEARTBEAT_SECONDS, HEARTBEAT_TIMEOUT_SECONDS, POLL_SECONDS,
    REVALIDATE_SECONDS, REVALIDATION_PROBE_TIMEOUT_SECONDS, SOURCE_READ_TIMEOUT_SECONDS,
    RUNTIME_CONTROL_VERSION, START_SCHEMA, TERMINAL, adapter_intake, attempt_id,
    canonical_runtime_contract, normalize_command, normalize_start)
from .runtime_control import RuntimeOwnerLock, RuntimeResources, RuntimeStopped
from .runtime_repository import ExecutionRuntimeRepository
from .tool_registry import registry_sha256, select_adapter


class ExecutionRuntimeService(ExecutionAdapterService):
    def __init__(self, repository=None, proposal_source=None, mission_source=None, governance_client=None,
                 *, clock=None, broker=None, credential_store=None):
        repository = repository or ExecutionRuntimeRepository()
        if not isinstance(repository, ExecutionRuntimeRepository):
            raise ExecutionRequestValidationError("Stage 6.5 requires a runtime repository")
        super().__init__(repository, proposal_source, mission_source, governance_client,
                         clock=clock, broker=broker, credential_store=credential_store)
        self.owner_id = "runtime-owner-" + uuid4().hex
        self._runtime_lock = RLock()
        self._handles = {}
        self._failures = {}
        self._local = local()
        self._closed = False
        self._owner_lock = RuntimeOwnerLock(repository.sqlite_path).acquire()
        try:
            repository.initialize()
            self.recovered_attempts = repository.recover_orphans(utc_timestamp(self.clock()), self.owner_id)
        except BaseException:
            self._owner_lock.close()
            raise

    def _ensure_open(self):
        if self._closed:
            raise ExecutionSourceRejected("RUNTIME_OWNER_CLOSED")

    def health(self):
        result = super().health()
        contract = canonical_runtime_contract()
        with self._runtime_lock:
            failed = bool(self._failures)
            active = len(self._handles)
        result.update({"control_version": RUNTIME_CONTROL_VERSION,
            "supported_controls": [*result["supported_controls"], RUNTIME_CONTROL_VERSION],
            "stage6_5_schema_version": contract["schema_version"],
            "stage6_5_contract_sha256": contract["integrity"]["canonical_sha256"],
            "stage6_5_predecessor_control": contract["predecessor"]["control"],
            "stage6_5_predecessor_contract_sha256": contract["predecessor"]["contract_sha256"],
            "execution_runtime_control_enabled": True, "runtime_owner_exclusive": not self._closed,
            "active_runtime_attempts": active, "runtime_persistence_failures": len(self._failures),
            "runtime_completion_fence_enabled": True,
            "runtime_authorization_quiescence_seconds": HEARTBEAT_TIMEOUT_SECONDS,
            "recovered_orphan_attempts": len(self.recovered_attempts), "caller_heartbeat_supported": False,
            "legacy_quarantined_invocations":self.repository.legacy_quarantined_count(),
            "automatic_retry_enabled": False, "legacy_adapter_synchronous_dispatch_enabled": False,
            "next_stage": "6.6"})
        if failed or self._closed:
            result["status"] = "degraded"
        return result

    def get_runtime_contract(self):
        return {"control_version": RUNTIME_CONTROL_VERSION, "status":"declared", "read_only":True,
                "runtime_self_certification":False, "contract":canonical_runtime_contract()}

    def get_contract(self):
        return {**super().get_contract(), "control_version":RUNTIME_CONTROL_VERSION}

    def get_authorization_contract(self):
        return {**super().get_authorization_contract(), "control_version":RUNTIME_CONTROL_VERSION}

    def get_gateway_contract(self):
        return {**super().get_gateway_contract(), "control_version":RUNTIME_CONTROL_VERSION}

    def get_adapter_contract(self):
        return {**super().get_adapter_contract(), "control_version":RUNTIME_CONTROL_VERSION}

    def create_request(self, payload):
        self._ensure_open()
        return {**super().create_request(payload), "control_version":RUNTIME_CONTROL_VERSION}

    def authorize_execution(self, payload):
        self._ensure_open()
        return {**super().authorize_execution(payload), "control_version":RUNTIME_CONTROL_VERSION}

    def _fresh_authorization(self, intake):
        guard = getattr(self._local, "guard", None)
        action = lambda: ExecutionAdapterService._fresh_authorization(self, intake, _runtime=guard)
        return guard.bounded_call(action) if guard else action()

    @staticmethod
    def runtime_response(item, *, created=False):
        return {"control_version":RUNTIME_CONTROL_VERSION, "created":created,
            "historical_record":not created, "execution_authorized":False, "authorization_current":False,
            "usable_for_dispatch":False, "replay_performs_io":False, "target_network_io_performed":False,
            "specialist_raw_target_access":False, "runtime_self_certification":False,
            "terminal":item["state"] in TERMINAL,
            "retry_eligible_by_result":ExecutionRuntimeRepository.retryable(item),
            "recovery_eligible_by_result":ExecutionRuntimeRepository.recoverable_aborted(item), **item}

    def get_attempt(self, identity):
        item = self.repository.get_attempt(identity)
        if item is None:
            raise ExecutionSourceNotFound("runtime attempt not found")
        return self.runtime_response(item)

    def invoke_tool(self, payload):
        # Legacy adapter intake is routed through the same durable lifecycle.
        intake = normalize_adapter_intake(payload)
        return self.start_execution({**intake, "schema_version":START_SCHEMA})

    def start_execution(self, payload, *, retry=False):
        intake = normalize_start(payload, retry=retry)
        self._ensure_open()
        with self._adapter_lock:
            existing = self.repository.find_runtime_intake(intake)
            if existing:
                return self.runtime_response(existing)
            stored = self.repository.get(intake["execution_id"])
            if stored is None:
                raise ExecutionSourceNotFound("execution request not found")
            envelope = stored["envelope"]
            if envelope["integrity"]["canonical_sha256"] != intake["envelope_sha256"]:
                raise ExecutionRequestIntegrityError("runtime envelope hash mismatch")
            auth = self._fresh_authorization(adapter_intake(intake))
            self._ensure_open()
            invocation, created = self.repository.reserve_adapter(adapter_intake(intake), auth["authorization_id"],
                final_check=lambda authorization: self._final_admission_check(envelope, authorization),
                runtime_context={"runtime_intake":intake, "owner_id":self.owner_id})
            if invocation["record"]["status"] != "RESERVED":
                raise ExecutionSourceRejected(";".join(invocation["record"]["reason_codes"]))
            identity = attempt_id(invocation["invocation_id"])
            item = self.repository.get_attempt(identity)
            if not created:
                return self.runtime_response(item)
            claim = invocation["record"]
            deadlines = [parse_time(claim["controls"]["deadline"], "deadline")]
            deadlines += [parse_time(v, "lifetime_deadline") for v in claim["lifetime_deadlines"].values()]
            seconds = (min(deadlines) - self.clock()).total_seconds()
            guard = RuntimeResources(time.monotonic() + min(seconds, claim["controls"]["limits"]["timeout_seconds"]),
                ready=lambda worker:self.repository.append_event(identity, "RUNNING", "RUNNING", utc_timestamp(self.clock()),
                    {"native_worker_ready":True, "sandbox_backend":worker.backend, "worker_pid":worker.process.pid}, self.owner_id),
                boundary=lambda:self._runtime_boundary(identity))
            guard.last_supervision = time.monotonic()
            worker = Thread(target=self._execute, args=(identity, guard, claim, envelope), daemon=True,
                            name="apts-execution-" + identity)
            monitor = Thread(target=self._supervise, args=(identity, guard, claim, envelope), daemon=True)
            watchdog = Thread(target=self._watchdog, args=(guard,), daemon=True)
            with self._runtime_lock:
                self._handles[identity] = (guard, worker, monitor, watchdog)
                if self._closed:
                    guard.stop("ABORTED", "RUNTIME_SHUTDOWN")
            monitor.start(); watchdog.start(); worker.start()
            return self.runtime_response(item, created=True)

    def _runtime_boundary(self, identity):
        item = self.repository.get_attempt(identity)
        if item is None or item["record"]["owner_id"] != self.owner_id or item["state"] != "RUNNING":
            raise RuntimeStopped("RUNTIME_ATTEMPT_NOT_RUNNING_WITH_CURRENT_OWNER")
        stop = self.repository.requested_stop(identity)
        if stop:
            raise RuntimeStopped(stop[1])

    def _execute(self, identity, guard, claim, envelope):
        self._local.guard = guard
        try:
            try:
                guard.check()
                self.repository.append_event(identity, "DISPATCHED", "DISPATCHED", utc_timestamp(self.clock()),
                    {"owner_id":self.owner_id}, self.owner_id)
            except ExecutionSourceRejected:
                stopped = self.repository.requested_stop(identity)
                guard.stop(*(stopped or ("ABORTED", "RUNTIME_DISPATCH_BLOCKED")))
            result = self._run_reserved(claim, envelope, runtime=guard)
            try:
                guard.check()
            except RuntimeStopped:
                pass
            guard.finish()
            if guard.cleanup_errors or guard._closers:
                raise ExecutionRepositoryError("RUNTIME_RESOURCE_CLEANUP_NOT_PROVEN")
            state = guard.state or (result["status"] if result["status"] != "BLOCKED" else "FAILED")
            reason = guard.reason or (result["reason_codes"][0] if result["reason_codes"] else "ADAPTER_PRIMITIVE_COMPLETED")
            self.repository.finalize(identity, result, state, reason, utc_timestamp(self.clock()), self.owner_id,
                                     diagnostics=dict(guard.diagnostics) or None)
        except BaseException as exc:
            logging.getLogger(__name__).exception('Runtime finalization failed attempt=%s', identity)
            guard.stop("ABORTED", "RUNTIME_PERSISTENCE_OR_SUPERVISION_FAILURE")
            with self._runtime_lock:
                # Keep the durable nonterminal claim consumed; health is degraded.
                self._failures[identity] = type(exc).__name__
        finally:
            guard.finish()
            self._local.guard = None
            with self._runtime_lock:
                self._handles.pop(identity, None)

    def _watchdog(self, guard):
        while not guard.done.wait(POLL_SECONDS):
            try:
                guard.check()
            except RuntimeStopped:
                return
            age = time.monotonic() - guard.last_supervision
            if age > HEARTBEAT_TIMEOUT_SECONDS:
                # Record why liveness was lost before aborting: the supervisor's
                # own stack (the frame most likely blocked on a source read) and
                # the age, so a heartbeat loss can be distinguished from a stall.
                guard.record_diagnostic("last_supervision_age_seconds", round(age, 6))
                frame = sys._current_frames().get(guard.supervisor_ident)
                if frame is not None:
                    guard.record_diagnostic("supervisor_stack",
                        [line.rstrip() for line in traceback.format_stack(frame)][-12:])
                logging.getLogger(__name__).error(
                    "Runtime heartbeat lost age=%.3fs diagnostics=%s", age, guard.diagnostics)
                guard.stop("ABORTED", "RUNTIME_HEARTBEAT_LOST")
                return

    def _probe_authority(self, claim, envelope, pending, guard):
        # Non-blocking: skip this cycle if another probe holds the lock.
        if not self._authorization_lock.acquire(blocking=False):
            pending.put((True, None))
            return
        try:
            with guard.authorization():
                auth = ExecutionAdapterService._fresh_authorization(self, claim["intake"], _runtime=guard)
                guard.check_authorization()
                self._final_admission_check(envelope, auth)
                adapter = select_adapter(envelope["execution_request"])
                fresh = compile_runtime_policy(auth, adapter, self.clock())
                if (claim["registry_sha256"] != registry_sha256()
                    or {k:v for k,v in fresh.items() if k != "deadline"} != {k:v for k,v in claim["controls"].items() if k != "deadline"}):
                    raise ExecutionSourceRejected("RUNTIME_POLICY_OR_REGISTRY_CHANGED")
                pending.put((True, auth))
        except BaseException as exc:
            pending.put((False, type(exc).__name__))
        finally:
            self._authorization_lock.release()

    def _probe_source(self, envelope, pending, guard, started):
        # Read the authority/context sources in a monitored worker so a stalled
        # repository surfaces as a bounded, dedicated terminal reason instead of
        # freezing the supervisor and tripping the liveness watchdog. Mirrors
        # _current_context exactly, but times each source read for diagnostics.
        try:
            with guard.authorization():
                durations = {}
                t0 = time.monotonic()
                mission = self.mission_source.current_context(envelope["execution_request"]["mission_id"])
                durations["mission_source_seconds"] = round(time.monotonic() - t0, 6)
                t1 = time.monotonic()
                mission["pentest_context"] = self.proposal_source.current_context(envelope)
                durations["proposal_source_seconds"] = round(time.monotonic() - t1, 6)
                guard.check_authorization()
                pending.put((True, (mission, round(time.monotonic() - started, 6), durations)))
        except BaseException as exc:
            pending.put((False, (type(exc).__name__, traceback.format_exc()[-2000:],
                                 round(time.monotonic() - started, 6))))

    def _supervise(self, identity, guard, claim, envelope):
        guard.supervisor_ident = get_ident()
        last_heartbeat = last_probe = time.monotonic()
        pending = source_pending = None
        probe_started = source_started = None
        last_authority_id = claim["authorization_id"]
        try:
            while not guard.done.wait(POLL_SECONDS):
                guard.check_authorization()
                item = self.repository.get_attempt(identity)
                stop = self.repository.requested_stop(identity)
                guard.check_authorization()
                if stop:
                    guard.stop(*stop)
                    return
                if item["record"]["owner_id"] != self.owner_id or item["state"] in TERMINAL:
                    guard.stop("ABORTED", "RUNTIME_OWNER_OR_STATE_CHANGED")
                    return
                current_time = time.monotonic()
                guard.last_supervision = current_time
                if self.clock() < parse_time(claim["reserved_at"], "reserved_at"):
                    guard.stop("ABORTED", "RUNTIME_CLOCK_MOVED_BACKWARDS")
                    return
                deadlines = [parse_time(claim["controls"]["deadline"], "deadline")]
                deadlines += [parse_time(v, "lifetime_deadline") for v in claim["lifetime_deadlines"].values()]
                guard.tighten_deadline(current_time + (min(deadlines)-self.clock()).total_seconds())
                # Cadence: launch a bounded source read only when nothing else is
                # already in flight. The loop keeps updating last_supervision each
                # cycle, so a slow source no longer looks like a heartbeat loss.
                if (current_time - last_probe >= REVALIDATE_SECONDS
                        and source_pending is None and pending is None):
                    source_pending = queue.Queue(maxsize=1)
                    source_started = last_probe = time.monotonic()
                    Thread(target=self._probe_source, args=(envelope, source_pending, guard, source_started),
                           daemon=True).start()
                guard.check_authorization()
                if source_pending is not None:
                    try:
                        sok, svalue = source_pending.get_nowait()
                    except queue.Empty:
                        if current_time - source_started > SOURCE_READ_TIMEOUT_SECONDS:
                            guard.record_diagnostic("source_read_timed_out_seconds",
                                                    round(current_time - source_started, 6))
                            guard.stop("ABORTED", "RUNTIME_SOURCE_READ_TIMEOUT")
                            return
                    else:
                        source_pending = None
                        if not sok:
                            guard.record_diagnostic("source_read_error", svalue[0])
                            guard.record_diagnostic("source_read_traceback", svalue[1])
                            guard.record_diagnostic("source_read_seconds", svalue[2])
                            guard.stop("ABORTED", "RUNTIME_SOURCE_UNREADABLE")
                            return
                        current, source_seconds, source_durations = svalue
                        guard.record_diagnostic("source_read_seconds", source_seconds)
                        guard.record_diagnostic("source_read_component_seconds", source_durations)
                        guard.check_authorization()
                        if canonical_json(current) != canonical_json(claim["authorization_record"]["evaluation"]["current_context"]):
                            guard.stop("ABORTED", "RUNTIME_SOURCE_CHANGED_OR_REVOKED")
                            return
                        # Source confirmed current: now launch the Governance probe
                        # with its own timeout, measured from its own launch.
                        pending = queue.Queue(maxsize=1)
                        probe_started = time.monotonic()
                        Thread(target=self._probe_authority, args=(claim, envelope, pending, guard), daemon=True).start()
                guard.check_authorization()
                if pending is not None:
                    try:
                        ok, value = pending.get_nowait()
                    except queue.Empty:
                        if current_time - probe_started > REVALIDATION_PROBE_TIMEOUT_SECONDS:
                            guard.stop("ABORTED", "RUNTIME_GOVERNANCE_REVALIDATION_STALE")
                            return
                    else:
                        pending = None
                        if ok and value is None:
                            pass  # Lock was busy; retry next cycle.
                        elif not ok:
                            guard.stop("ABORTED", "RUNTIME_GOVERNANCE_REVALIDATION_FAILED")
                            return
                        else:
                            last_authority_id = value["authorization_id"]
                            guard.tighten_deadline(time.monotonic() + (parse_time(value["valid_until"], "valid_until") - self.clock()).total_seconds())
                if item["state"] == "RUNNING" and current_time - last_heartbeat >= HEARTBEAT_SECONDS:
                    self.repository.append_event(identity, "RUNNING", "HEARTBEAT", utc_timestamp(self.clock()),
                        {"owner_id":self.owner_id, "authorization_id":last_authority_id,
                         "supervisor_monotonic_elapsed_seconds":round(current_time-last_heartbeat,6)}, self.owner_id)
                    last_heartbeat = current_time
        except RuntimeStopped:
            return
        except ExecutionRequestConflict:
            if not guard.done.is_set():
                guard.stop("ABORTED", "RUNTIME_EVENT_CONFLICT")
        except BaseException:
            if not guard.done.is_set():
                guard.stop("ABORTED", "RUNTIME_SUPERVISION_INTEGRITY_FAILURE")

    def control(self, payload, *, kill=False):
        intake = normalize_command(payload, kill=kill)
        self._ensure_open()
        record, created = self.repository.append_command(intake, "KILL" if kill else "CANCEL", utc_timestamp(self.clock()))
        with self._runtime_lock:
            for target in record["target_attempts"]:
                handle = self._handles.get(target["attempt_id"])
                if handle and target["state"] not in TERMINAL:
                    handle[0].stop("ABORTED" if kill else "CANCELLED", "MISSION_EMERGENCY_KILL" if kill else "OPERATOR_CANCELLED")
        return {"control_version":RUNTIME_CONTROL_VERSION, "created":created, "record":record,
                "execution_authorized":False, "target_network_io_performed":False,
                "terminal_confirmation_requires_attempt_read":True}

    def close(self):
        with self._runtime_lock:
            if self._closed:
                return
            self._closed = True
            handles = list(self._handles.values())
        for guard, _, _, _ in handles:
            guard.stop("ABORTED", "RUNTIME_SHUTDOWN")
        # Admission may still be completing external authorization. It checks
        # _closed before reserving, so it cannot launch after this fence.
        with self._adapter_lock:
            pass
        with self._runtime_lock:
            handles = list(self._handles.values())
        for guard, _, _, _ in handles:
            guard.stop("ABORTED", "RUNTIME_SHUTDOWN")
        for _, worker, monitor, watchdog in handles:
            worker.join(timeout=6)
            monitor.join(timeout=0.2); watchdog.join(timeout=0.2)
            if worker.is_alive():
                raise ExecutionRepositoryError("RUNTIME_OWNER_CANNOT_RELEASE_WHILE_WORKER_ACTIVE")
        self._owner_lock.close()

    def reject_execution(self):
        return {"status":"rejected", "control_version":RUNTIME_CONTROL_VERSION,
            "error_code":"STAGE6_5_RUNTIME_GATEWAY_ROUTE_REQUIRED", "execution_authorized":False,
            "message":"Use /api/execution/runtime/attempts with an immutable ExecutionRequest reference.",
            "specialist_raw_target_access":False, "next_stage":"6.6"}
