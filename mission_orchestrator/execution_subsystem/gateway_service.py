from __future__ import annotations

from threading import RLock
from typing import Any
from uuid import uuid4

from .authorization_contract import (
    AUTHORIZATION_BOUNDARIES, AUTHORIZATION_INTAKE_SCHEMA, parse_time, utc_timestamp,
    validate_authoritative_decision,
)
from .authorization_service import ExecutionAuthorizationService
from .authorization_source import local_execution_checks
from .execution_contract import ExecutionRequestValidationError, ExecutionSourceNotFound, ExecutionSourceRejected, canonical_json
from .gateway_contract import (
    ADMITTED, EXECUTION_GATEWAY_CONTROL_VERSION, canonical_execution_gateway_contract,
    normalize_gateway_intake,
)
from .gateway_repository import ExecutionGatewayRepository


class ExecutionGatewayService(ExecutionAuthorizationService):
    def __init__(self, repository=None, proposal_source=None, mission_source=None, governance_client=None, *, clock=None):
        if repository is not None and not isinstance(repository, ExecutionGatewayRepository):
            raise ExecutionRequestValidationError("Stage 6.3 requires a gateway repository")
        super().__init__(repository or ExecutionGatewayRepository(), proposal_source, mission_source, governance_client, clock=clock)
        self._gateway_lock = RLock()

    def health(self):
        health = super().health()
        contract = canonical_execution_gateway_contract()
        health.update({"control_version": EXECUTION_GATEWAY_CONTROL_VERSION,
                       "supported_controls": [*health["supported_controls"], EXECUTION_GATEWAY_CONTROL_VERSION],
                       "stage6_3_schema_version": contract["schema_version"],
                       "stage6_3_contract_sha256": contract["integrity"]["canonical_sha256"],
                       "stage6_3_predecessor_control": contract["predecessor"]["control"],
                       "stage6_3_predecessor_contract_sha256": contract["predecessor"]["contract_sha256"],
                       "controlled_execution_gateway_enabled": True, "central_execution_policy_enforcement_enabled": True,
                       "gateway_admission_enabled": True, "gateway_admission_is_dispatch_authority": False,
                       "registered_adapter_count": 0, "target_dispatch_enabled": False,
                       "fresh_revalidation_required_before_target_dispatch": True, "next_stage": "6.4"})
        return health

    def get_gateway_contract(self):
        return {"status": "declared", "control_version": EXECUTION_GATEWAY_CONTROL_VERSION,
                "contract": canonical_execution_gateway_contract(), "read_only": True, "runtime_self_certification": False}

    def get_contract(self):
        return {**super().get_contract(), "control_version": EXECUTION_GATEWAY_CONTROL_VERSION}

    def create_request(self, payload):
        return {**super().create_request(payload), "control_version": EXECUTION_GATEWAY_CONTROL_VERSION}

    def get_authorization_contract(self):
        return {**super().get_authorization_contract(), "control_version": EXECUTION_GATEWAY_CONTROL_VERSION}

    def authorize_execution(self, payload):
        return {**super().authorize_execution(payload), "control_version": EXECUTION_GATEWAY_CONTROL_VERSION}

    @staticmethod
    def audit_response(stored):
        return {**ExecutionAuthorizationService.audit_response(stored), "control_version": EXECUTION_GATEWAY_CONTROL_VERSION}

    @staticmethod
    def gateway_response(stored, *, created=False, governance_query=False):
        return {"control_version": EXECUTION_GATEWAY_CONTROL_VERSION, "created": created,
                "historical_record": not created,
                "gateway_admitted": created and stored["record"]["status"] == ADMITTED,
                "authorization_current": False, "execution_authorized": False, "usable_for_dispatch": False,
                "fresh_revalidation_required_before_target_dispatch": True,
                "governance_query_performed": governance_query, **AUTHORIZATION_BOUNDARIES, **stored}

    def _final_admission_check(self, envelope, authorization):
        current = self._current_context(envelope)
        if canonical_json(current) != canonical_json(authorization["evaluation"]["current_context"]):
            raise ExecutionSourceRejected("Mission or Pentest context changed before gateway admission")
        now = self.clock()
        if not parse_time(authorization["received_at"], "received_at") <= now < parse_time(authorization["valid_until"], "valid_until"):
            raise ExecutionSourceRejected("gateway authorization expired or clock moved backwards")
        validate_authoritative_decision(authorization["policy_decision"], authorization["evaluation"], now)
        checks = local_execution_checks(envelope["execution_request"], current, current["pentest_context"], now)
        if any(value != "PASS" for value in checks.values()):
            raise ExecutionSourceRejected("current scope/RoE/risk/target/technique failed before gateway admission")
        return utc_timestamp(now)

    def submit_execution(self, payload: Any):
        intake = normalize_gateway_intake(payload)
        with self._gateway_lock:
            old = self.repository.find_gateway_intake(intake)
            if old is not None:
                return self.gateway_response(old)
            stored_request = self.repository.get(intake["execution_id"])
            if stored_request is None:
                raise ExecutionSourceNotFound("gateway execution request is unavailable")
            envelope = stored_request["envelope"]
            if envelope["integrity"]["canonical_sha256"] != intake["envelope_sha256"]:
                raise ExecutionSourceRejected("gateway request hash does not match the stored envelope")
            if envelope["intake"].get("source_type") in {"STAGE5_2_RECON_ACTION_REQUEST", "STAGE5_3_ENUMERATION_ACTION_PROPOSAL", "WPT_GOVERNED_INTAKE"}:
                # Do not admit specialist actions that the Stage 6.4 server-owned
                # registry cannot execute exactly. This is capability validation
                # only; adapter invocation and all target I/O remain downstream.
                from .tool_registry import select_adapter
                select_adapter(envelope["execution_request"])
            # New uncommitted submissions always get new server-owned identities.
            # A crash between authorization and admission leaves audit only; retry revalidates.
            nonce = uuid4().hex
            authorization = self.authorize_execution({
                "schema_version": AUTHORIZATION_INTAKE_SCHEMA, "revalidation_id": "eauthreq-gateway-" + nonce,
                "idempotency_key": "idem-gateway-auth-" + nonce, "execution_id": intake["execution_id"],
                "envelope_sha256": intake["envelope_sha256"], "requested_by": intake["requested_by"]})
            if not authorization["created"] or not authorization["governance_query_performed"]:
                raise ExecutionSourceRejected("cached authorization cannot enter the gateway")
            stored, created = self.repository.append_gateway(intake, authorization["authorization_id"],
                final_check=lambda record: self._final_admission_check(envelope, record))
            return self.gateway_response(stored, created=created, governance_query=True)

    def reject_execution(self):
        return {"status": "rejected", "control_version": EXECUTION_GATEWAY_CONTROL_VERSION,
                "error_code": "STAGE6_3_AUTHORIZED_ADAPTER_REQUIRED",
                "message": "Submit immutable requests through /api/execution/gateway/submissions. Target dispatch requires Stage 6.4 adapters and fresh revalidation.",
                "execution_authorized": False, "next_stage": "6.4", **AUTHORIZATION_BOUNDARIES}
