from __future__ import annotations

from threading import RLock
import time
from uuid import uuid4

from .adapter_contract import (ADAPTER_CONTROL_VERSION, RESULT_DOMAIN, canonical_adapter_contract,
                               normalize_adapter_intake)
from .adapter_policy import compile_runtime_policy, _wpt_enumeration_context
from .adapter_repository import ExecutionAdapterRepository
from .condition_signal import condition_signal_from_adapter_collection
from .authorization_contract import AUTHORIZATION_INTAKE_SCHEMA, parse_time, utc_timestamp
from .authorization_service import ExecutionAuthorizationService
from .credential_leases import CredentialLeaseStore
from .execution_contract import (ExecutionRequestIntegrityError, ExecutionRequestValidationError,
                                 ExecutionSourceNotFound, ExecutionSourceRejected, canonical_json, with_integrity)
from .gateway_service import ExecutionGatewayService
from .sandbox_runtime import ResourceSandbox
from .target_broker import TargetBroker
from .adapter_contract import bounded_web_profile_contract
from .tool_registry import ADAPTERS, registry_sha256, select_adapter


class ExecutionAdapterService(ExecutionGatewayService):
    def __init__(self, repository=None, proposal_source=None, mission_source=None, governance_client=None,
                 *, clock=None, broker=None, credential_store=None):
        if repository is not None and not isinstance(repository, ExecutionAdapterRepository):
            raise ExecutionRequestValidationError("Stage 6.4 requires an adapter repository")
        super().__init__(repository or ExecutionAdapterRepository(), proposal_source, mission_source, governance_client, clock=clock)
        self.broker = broker or TargetBroker()
        self.credential_store = credential_store or CredentialLeaseStore()
        self._adapter_lock = RLock()

    def health(self):
        result = super().health()
        contract = canonical_adapter_contract()
        result.update({"control_version": ADAPTER_CONTROL_VERSION, "supported_controls": [*result["supported_controls"], ADAPTER_CONTROL_VERSION],
            "stage6_4_schema_version": contract["schema_version"], "stage6_4_contract_sha256": contract["integrity"]["canonical_sha256"],
            "stage6_4_predecessor_control": contract["predecessor"]["control"],
            "stage6_4_predecessor_contract_sha256": contract["predecessor"]["contract_sha256"],
            "registered_adapter_count": len(ADAPTERS), "adapter_registry_sha256": registry_sha256(),
            "authorized_tool_adapters_enabled": True, "target_dispatch_enabled": True,
            "sandbox_profile": "FIXED_WORKER_BROKER_V1", "sandbox_ready_required_before_target_io": True,
            "arbitrary_code_supported": False, "worker_raw_target_access": False,
            "bounded_web_profile_collection":bounded_web_profile_contract(),
            "legacy_gateway_new_admissions_enabled": False, "next_stage": "6.5"})
        return result

    def get_adapter_contract(self):
        return {"control_version": ADAPTER_CONTROL_VERSION, "status": "declared", "read_only": True,
                "runtime_self_certification": False, "contract": canonical_adapter_contract()}

    def get_contract(self):
        return {**super().get_contract(), "control_version": ADAPTER_CONTROL_VERSION}

    def get_gateway_contract(self):
        return {**super().get_gateway_contract(), "control_version": ADAPTER_CONTROL_VERSION}

    def get_authorization_contract(self):
        return {**super().get_authorization_contract(), "control_version": ADAPTER_CONTROL_VERSION}

    def create_request(self, payload):
        return {**super().create_request(payload), "control_version": ADAPTER_CONTROL_VERSION}

    def authorize_execution(self, payload):
        return {**super().authorize_execution(payload), "control_version": ADAPTER_CONTROL_VERSION}

    @staticmethod
    def audit_response(stored):
        return {**ExecutionGatewayService.audit_response(stored), "control_version": ADAPTER_CONTROL_VERSION}

    @staticmethod
    def gateway_response(stored, **kwargs):
        return {**ExecutionGatewayService.gateway_response(stored, **kwargs), "control_version": ADAPTER_CONTROL_VERSION}

    def submit_execution(self, payload):
        # Existing Stage 6.3 receipts stay readable/replayable. The v4 SQL trigger
        # also prevents a still-running legacy process from adding old budgets.
        from .gateway_contract import normalize_gateway_intake
        intake = normalize_gateway_intake(payload)
        old = self.repository.find_gateway_intake(intake)
        if old:
            return self.gateway_response(old)
        raise ExecutionSourceRejected("STAGE6_4_USE_GATEWAY_TOOL_INVOCATIONS_FOR_NEW_ADMISSION")

    def _fresh_authorization(self, intake, *, _runtime=None):
        nonce = uuid4().hex
        response = ExecutionAuthorizationService.authorize_execution(self, {
            "schema_version": AUTHORIZATION_INTAKE_SCHEMA, "revalidation_id": "eauthreq-adapter-" + nonce,
            "idempotency_key": "idem-adapter-auth-" + nonce, "execution_id": intake["execution_id"],
            "envelope_sha256": intake["envelope_sha256"], "requested_by": intake["requested_by"]}, _runtime=_runtime)
        if not response["created"] or not response["governance_query_performed"]:
            raise ExecutionSourceRejected("ADAPTER_CACHED_AUTHORIZATION_FORBIDDEN")
        return response["record"]

    @staticmethod
    def adapter_response(item, *, created=False):
        result = item["result"]
        return {"control_version": ADAPTER_CONTROL_VERSION, "created": created, "historical_record": not created,
                "execution_authorized": False, "authorization_current": False, "usable_for_dispatch": False,
                "replay_performs_io": False, "invocation_incomplete": item["record"]["status"] == "RESERVED" and result is None,
                "target_network_io_performed": bool(created and result and result["semantics"]["target_network_io_performed"]),
                "specialist_raw_target_access": False, **item}

    def invoke_tool(self, payload):
        intake = normalize_adapter_intake(payload)
        with self._adapter_lock:
            old = self.repository.find_adapter_intake(intake)
            if old:
                return self.adapter_response(old)
            stored = self.repository.get(intake["execution_id"])
            if stored is None:
                raise ExecutionSourceNotFound("execution request not found")
            envelope = stored["envelope"]
            if envelope["integrity"]["canonical_sha256"] != intake["envelope_sha256"]:
                raise ExecutionRequestIntegrityError("adapter envelope hash mismatch")
            authorization = self._fresh_authorization(intake)
            item, created = self.repository.reserve_adapter(intake, authorization["authorization_id"],
                final_check=lambda auth: self._final_admission_check(envelope, auth))
        if not created or item["record"]["status"] != "RESERVED":
            return self.adapter_response(item, created=created)
        # Durable reservation is committed before the worker or target is touched.
        # A crash now is ambiguous and consumes the identity; no replay dispatch.
        result = self._run_reserved(item["record"], envelope)
        item = self.repository.append_adapter_result(result)
        return self.adapter_response(item, created=True)

    def _run_reserved(self, claim, envelope, *, runtime=None):
        controls = claim["controls"]
        request = envelope["execution_request"]
        adapter = select_adapter(request)
        boundary = None
        pinned = None
        backend = None
        observation = None
        collection_raw = None
        lease_metadata = None
        header = None
        io_attempted = False
        status, reasons = "BLOCKED", []
        remaining = (min([parse_time(controls["deadline"], "deadline"), *[parse_time(v, "lifetime_deadline") for v in claim["lifetime_deadlines"].values()]]) - self.clock()).total_seconds()
        deadline = time.monotonic() + min(remaining, controls["limits"]["timeout_seconds"])

        def before_io():
            nonlocal boundary, io_attempted, header, lease_metadata, deadline
            boundary = self._fresh_authorization(claim["intake"])
            self._final_admission_check(envelope, boundary)
            if claim["registry_sha256"] != registry_sha256():
                raise ExecutionSourceRejected("ADAPTER_REGISTRY_CHANGED")
            fresh = compile_runtime_policy(boundary, adapter, self.clock())
            if {k:v for k,v in fresh.items() if k != "deadline"} != {k:v for k,v in controls.items() if k != "deadline"}:
                raise ExecutionSourceRejected("RUNTIME_POLICY_CHANGED_REQUIRES_NEW_REVIEW")
            deadline = min(deadline, time.monotonic() + (parse_time(fresh["deadline"], "deadline") - self.clock()).total_seconds())
            if time.monotonic() >= deadline:
                raise TimeoutError("adapter authorization deadline expired")
            current = self._current_context(envelope)
            if canonical_json(current) != canonical_json(boundary["evaluation"]["current_context"]):
                raise ExecutionSourceRejected("SOURCE_CHANGED_AT_TARGET_BOUNDARY")
            self.broker.validate_pin(request, current, adapter, pinned)
            if controls["credential_lease_id"]:
                header, lease_metadata = self.credential_store.acquire(controls["credential_lease_id"], request, adapter, self.clock())
                if not pinned.tls:
                    raise ExecutionSourceRejected("CREDENTIALS_REQUIRE_TLS")
                deadline = min(deadline, time.monotonic() + (parse_time(lease_metadata["expires_at"], "expires_at") - self.clock()).total_seconds())
            # Verify the claim and check for a completed result immediately before
            # connect. Only this created reservation can reach this callback.
            persisted = self.repository.get_adapter_invocation(claim["invocation_id"])
            if persisted is None or persisted["record"] != claim or persisted["result"] is not None:
                raise ExecutionSourceRejected("DURABLE_ADAPTER_CLAIM_CHANGED")
            if runtime:
                runtime.tighten_deadline(deadline)
                runtime.before_target_io()
            io_attempted = True
            return deadline

        try:
            if remaining <= 0:
                raise TimeoutError("reserved authorization expired")
            with ResourceSandbox(controls["limits"], **({"runtime": runtime} if runtime else {})) as worker:
                backend = worker.backend
                if runtime:
                    runtime.worker_ready(worker)
                pinned = self.broker.pin(request, claim["authorization_record"]["evaluation"]["current_context"], adapter,
                    deadline=deadline, **({"runtime": runtime} if runtime else {}))
                # The header is acquired inside before_io. A closure passes it to
                # the broker only after the fresh authority has approved the lease.
                if adapter.operation in {"WEB_PROFILE_FINGERPRINT", "WEB_PROFILE_ENUMERATION"} and controls.get("web_profile_version")==2:
                    from .web_profile_collection import collect_profile
                    def validate_child(url,child):
                        self.broker.validate_profile_pin(request,self._current_context(envelope),adapter,pinned,url,child)
                    raw=collect_profile(self.broker,adapter,pinned,request["target"]["target_value"],controls["limits"],
                        controls["network_request_cost"],deadline=deadline,before_io=before_io,validate_child=validate_child,runtime=runtime,
                        enumeration_context=(_wpt_enumeration_context(request) if adapter.operation=="WEB_PROFILE_ENUMERATION" else None))
                else:
                    raw = self.broker.observe(adapter, pinned, controls["limits"], deadline=deadline,
                        before_io=before_io, authorization_header=lambda: header, **({"runtime": runtime} if runtime else {}))
                if adapter.operation in {"WEB_PROFILE_FINGERPRINT", "WEB_PROFILE_ENUMERATION"}:
                    raw = {**raw, "target": request["target"]["target_value"]}
                    collection_raw = raw
                observation = worker.parse(adapter.operation, raw, deadline=deadline)
                if adapter.operation in {"WEB_PROFILE_FINGERPRINT", "WEB_PROFILE_ENUMERATION"} and observation["target"] != request["target"]["target_value"]:
                    raise ExecutionSourceRejected("WEB_FINGERPRINT_TARGET_BINDING_MISMATCH")
                status = "SUCCEEDED"
        except TimeoutError:
            status, reasons = "TIMEOUT", ["ADAPTER_WALL_TIMEOUT"]
        except ExecutionSourceRejected as exc:
            status, reasons = "BLOCKED", [str(exc)]
        except Exception as exc:
            # Persist bounded failure metadata, never raw target response/secrets.
            status, reasons = "FAILED", ["ADAPTER_FAILURE:" + type(exc).__name__]
        finally:
            header = None
        # Adaptive degradation (Component A): derive a hash-bound condition signal
        # from the sealed collection evidence. Best-effort and fully defensive —
        # any failure yields None and never affects the attempt's status or seal.
        condition_signal = (
            condition_signal_from_adapter_collection(
                collection_raw, attempt_ref=claim["invocation_id"], execution_id=claim["execution_id"])
            if collection_raw is not None else None)
        return with_integrity({"schema_version": "apts-execution-adapter-result-v1", "control_version": ADAPTER_CONTROL_VERSION,
            "invocation_id": claim["invocation_id"], "claim_sha256": claim["integrity"]["canonical_sha256"],
            **{k: claim[k] for k in ("execution_id", "mission_id", "task_id", "pentest_id", "pentest_task_id")},
            "boundary_authorization_id": None if boundary is None else boundary["authorization_id"], "boundary_authorization_record": boundary,
            "adapter_id": adapter.adapter_id, "operation": adapter.operation, "registry_sha256": registry_sha256(),
            "pinned_target": None if pinned is None else pinned.definition(), "sandbox_backend": backend,
            "controls": controls, "credential_lease": lease_metadata, "credential_lease_consumed": bool(controls["credential_lease_id"]),
            "status": status, "reason_codes": reasons, "observation": observation, "condition_signal": condition_signal, "sensitive_output_retained": False,
            "completed_at": utc_timestamp(self.clock()),
            "semantics": {"target_network_io_performed": io_attempted, "tool_invocation_performed": backend is not None,
                          "specialist_raw_target_access": False, "authorization_minted_locally": False,
                          "action_result_created": False, "vep_created": False, "vulnerability_confirmed": False}}, RESULT_DOMAIN)

    def reject_execution(self):
        return {"status": "rejected", "control_version": ADAPTER_CONTROL_VERSION,
                "error_code": "STAGE6_4_GATEWAY_ADAPTER_ROUTE_REQUIRED", "execution_authorized": False,
                "message": "Use /api/execution/gateway/tool-invocations with an immutable ExecutionRequest reference.",
                "specialist_raw_target_access": False, "next_stage": "6.5"}
