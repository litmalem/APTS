from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

from .authorization_contract import (
    AUTHORIZATION_BOUNDARIES, EXECUTION_AUTHORIZATION_CONTROL_VERSION,
    canonical_execution_authorization_contract, normalize_authorization_intake,
    build_evaluation, make_authorization_record, utc_timestamp, validate_authoritative_decision,
)
from .authorization_repository import ExecutionAuthorizationRepository
from .authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource, local_execution_checks
from .execution_contract import (
    ExecutionRequestIntegrityError, ExecutionRequestValidationError,
    ExecutionSourceNotFound, ExecutionSourceRejected, ExecutionSourceUnavailable,
    canonical_json,
)
from .governance_client import ExecutionGovernanceClient
from .request_service import ExecutionRequestService


class ExecutionAuthorizationService(ExecutionRequestService):
    def __init__(self, repository: ExecutionAuthorizationRepository | None = None,
                 proposal_source: ExecutionAuthorizationProposalSource | None = None,
                 mission_source: MissionAuthorizationSource | None = None,
                 governance_client: ExecutionGovernanceClient | None = None,
                 *, clock: Callable[[], datetime] | None = None):
        super().__init__(repository or ExecutionAuthorizationRepository(), proposal_source or ExecutionAuthorizationProposalSource())
        self.mission_source = mission_source or MissionAuthorizationSource()
        paths = [self.repository.sqlite_path, self.proposal_source.sqlite_path, self.mission_source.sqlite_path]
        for index, one in enumerate(paths):
            for two in paths[index + 1:]:
                if one == two or (one.exists() and two.exists() and one.samefile(two)):
                    raise ExecutionRequestValidationError("Mission, Pentest and execution databases must be distinct")
        self.governance_client = governance_client or ExecutionGovernanceClient()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._authorization_lock = RLock()

    def health(self) -> dict[str, Any]:
        health = super().health()
        try:
            level = self.mission_source.migration_level()
            ready = True
        except ExecutionSourceUnavailable:
            level, ready = None, False
        contract = canonical_execution_authorization_contract()
        health.update({
            "control_version": EXECUTION_AUTHORIZATION_CONTROL_VERSION,
            "status": "ok" if ready and health["proposal_source_ready"] else "degraded",
            "supported_controls": [health["control_version"], EXECUTION_AUTHORIZATION_CONTROL_VERSION],
            "stage6_2_schema_version": contract["schema_version"],
            "stage6_2_contract_sha256": contract["integrity"]["canonical_sha256"],
            "stage6_2_predecessor_control": contract["predecessor"]["control"],
            "stage6_2_predecessor_contract_sha256": contract["predecessor"]["contract_sha256"],
            "supported_execution_request_sources": contract["source"]["supported_source_types"],
            "mission_source_ready": ready, "mission_source_read_only": True,
            "mission_repository_migration_level": level,
            "authoritative_execution_authorization_gate_enabled": True,
            "authorization_authority": "EXTERNAL_APTS_GSS",
            "governance_control_plane_io_enabled": True,
            "gss_attestation_schema_version": contract["gss_attestation_schema_version"],
            "gss_availability": "VERIFIED_ON_EACH_REVALIDATION",
            "runtime_self_certification": False, "next_stage": "6.3", **AUTHORIZATION_BOUNDARIES,
        })
        # Health describes capabilities; only a fresh POST reports query activity.
        health.pop("external_network_io_performed", None)
        return health

    def get_contract(self) -> dict[str, Any]:
        result = super().get_contract()
        result["control_version"] = EXECUTION_AUTHORIZATION_CONTROL_VERSION
        return result

    def get_authorization_contract(self) -> dict[str, Any]:
        return {"status": "declared", "control_version": EXECUTION_AUTHORIZATION_CONTROL_VERSION,
                "contract": canonical_execution_authorization_contract(),
                "read_only": True, "runtime_self_certification": False}

    def create_request(self, payload: Any) -> dict[str, Any]:
        result = super().create_request(payload)
        result["control_version"] = EXECUTION_AUTHORIZATION_CONTROL_VERSION
        return result

    @staticmethod
    def audit_response(stored: dict[str, Any]) -> dict[str, Any]:
        return {"control_version": EXECUTION_AUTHORIZATION_CONTROL_VERSION, "created": False,
                "historical_record": True, "authorization_current": False, "execution_authorized": False,
                "usable_for_dispatch": False, "fresh_revalidation_required": True,
                "governance_query_performed": False, **stored}

    def _current_context(self, envelope: dict[str, Any]) -> dict[str, Any]:
        mission = self.mission_source.current_context(envelope["execution_request"]["mission_id"])
        mission["pentest_context"] = self.proposal_source.current_context(envelope)
        return mission

    def authorize_execution(self, payload: Any, *, _runtime=None) -> dict[str, Any]:
        intake = normalize_authorization_intake(payload)
        with self._authorization_lock:
            if _runtime:
                _runtime.check_authorization()
            old = self.repository.find_authorization_intake(intake)
            if old is not None:
                return self.audit_response(old)
            stored = self.repository.get(intake["execution_id"])
            if stored is None:
                raise ExecutionSourceNotFound("execution request not found")
            envelope = stored["envelope"]
            if envelope["integrity"]["canonical_sha256"] != intake["envelope_sha256"]:
                raise ExecutionRequestIntegrityError("authorization envelope hash mismatch")
            current = self._current_context(envelope)
            now = self.clock()
            submitted = utc_timestamp(now)
            checks = local_execution_checks(envelope["execution_request"], current, current["pentest_context"], now)
            if any(value != "PASS" for value in checks.values()):
                failed = ",".join(key for key, value in checks.items() if value != "PASS")
                raise ExecutionSourceRejected("current local execution restrictions failed: " + failed)
            evaluation = build_evaluation(envelope, intake, current, checks, nonce=uuid4().hex, submitted_at=submitted)
            req = envelope["execution_request"]
            gov = current["governance_authority"]
            if _runtime:
                _runtime.check_authorization()
            policy_decision = self.governance_client.evaluate_authorization({
                "mission_id": req["mission_id"], "scope_contract_id": gov["governance_scope_contract_id"],
                "subject_component": "EXECUTION_SUBSYSTEM", "action_class": req["action"]["action_class"],
                "action_name": "AUTHORIZE_TARGET_EXECUTION", "resource_type": req["target"]["target_type"],
                "resource_value": req["target"]["target_value"],
                "context": {"authorization_purpose": "STAGE6_2_EXECUTION_REVALIDATION",
                            "execution_authorization_evaluation": evaluation},
                "evidence_refs": [x["evidence_id"] for x in req["evidence_basis"]],
                "requested_by": intake["requested_by"],
            })
            if _runtime:
                _runtime.check_authorization()
            received = utc_timestamp(self.clock())
            record = make_authorization_record(evaluation, policy_decision, received_at=received)
            if canonical_json(self._current_context(envelope)) != canonical_json(current):
                raise ExecutionSourceRejected("Mission or Pentest context changed during Governance revalidation")
            validate_authoritative_decision(policy_decision, evaluation, self.clock())
            if _runtime:
                _runtime.check_authorization()
            stored, created = self.repository.append_authorization(record)
            if not created:
                return self.audit_response(stored)
            return {"control_version": EXECUTION_AUTHORIZATION_CONTROL_VERSION,
                    "created": True, "historical_record": False,
                    "authorization_current": record["decision"] == "ALLOW",
                    "execution_authorized": record["decision"] == "ALLOW",
                    "usable_for_dispatch": False, "fresh_revalidation_required": True,
                    "governance_query_performed": True, **stored}

    def reject_execution(self) -> dict[str, Any]:
        return {"status": "rejected", "control_version": EXECUTION_AUTHORIZATION_CONTROL_VERSION,
                "error_code": "STAGE6_2_EXECUTION_GATEWAY_NOT_ENABLED",
                "message": "Execution authorization is a gate snapshot. Stage 6.3 gateway and later tool adapters are required for dispatch.",
                "execution_authorized": False, "next_stage": "6.3", **AUTHORIZATION_BOUNDARIES}
