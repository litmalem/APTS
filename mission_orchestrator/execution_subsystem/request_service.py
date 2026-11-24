from __future__ import annotations

from typing import Any

from .execution_contract import (
    EXECUTION_REQUEST_CONTROL_VERSION, EXECUTION_REQUEST_NEXT_STAGE, REQUEST_SEMANTICS,
    ExecutionRequestValidationError, ExecutionSourceUnavailable,
    canonical_execution_request_contract, canonical_execution_request_definition,
    normalize_execution_request_intake,
)
from .proposal_source import PentestProposalSource
from .request_repository import ExecutionRequestRepository


class ExecutionRequestService:
    def __init__(self, repository: ExecutionRequestRepository | None = None,
                 proposal_source: PentestProposalSource | None = None) -> None:
        self.repository = repository or ExecutionRequestRepository()
        self.proposal_source = proposal_source or PentestProposalSource()
        same_path = self.repository.sqlite_path == self.proposal_source.sqlite_path
        same_file = (self.repository.sqlite_path.exists() and self.proposal_source.sqlite_path.exists()
                     and self.repository.sqlite_path.samefile(self.proposal_source.sqlite_path))
        if same_path or same_file:
            raise ExecutionRequestValidationError("execution and Pentest repositories must use separate databases")

    def health(self) -> dict[str, Any]:
        level = self.repository.migration_level()
        try:
            pentest_level = self.proposal_source.migration_level()
            ready = True
        except ExecutionSourceUnavailable:
            pentest_level, ready = None, False
        definition = canonical_execution_request_definition()
        return {
            "status": "ok" if ready else "degraded", "component": "EXECUTION_SUBSYSTEM",
            "control_version": EXECUTION_REQUEST_CONTROL_VERSION,
            "execution_repository_migration_level": level,
            "pentest_repository_migration_level": pentest_level,
            "stage6_1_schema_version": definition["schema_version"],
            "stage6_1_request_schema_version": definition["request_schema_version"],
            "stage6_1_envelope_schema_version": definition["envelope_schema_version"],
            "stage6_1_contract_sha256": definition["contract_sha256"],
            "stage6_1_predecessor_control": definition["predecessor_control"],
            "proposal_source_ready": ready, "pentest_source_read_only": True,
            "execution_request_creation_enabled": True, **REQUEST_SEMANTICS,
            "next_stage": EXECUTION_REQUEST_NEXT_STAGE,
        }

    def get_contract(self) -> dict[str, Any]:
        return {"status": "declared", "control_version": EXECUTION_REQUEST_CONTROL_VERSION,
                "definition": canonical_execution_request_definition(),
                "contract": canonical_execution_request_contract(), "read_only": True,
                "runtime_self_certification": False, **REQUEST_SEMANTICS}

    def create_request(self, payload: Any) -> dict[str, Any]:
        intake = normalize_execution_request_intake(payload)
        existing = self.repository.find_intake(intake)
        if existing is not None:
            return {"control_version": EXECUTION_REQUEST_CONTROL_VERSION, "created": False, **existing}
        envelope = self.proposal_source.build_envelope(intake)
        stored, created = self.repository.append(envelope)
        return {"control_version": EXECUTION_REQUEST_CONTROL_VERSION, "created": created, **stored}

    def reject_execution(self) -> dict[str, Any]:
        return {"status": "rejected", "control_version": EXECUTION_REQUEST_CONTROL_VERSION,
                "error_code": "STAGE6_1_AUTHORIZATION_AND_EXECUTION_NOT_ENABLED",
                "message": "Stage 6.1 creates canonical requests only. Stage 6.2 authoritative revalidation and later execution gateway/adapters are required.",
                "next_stage": EXECUTION_REQUEST_NEXT_STAGE, **REQUEST_SEMANTICS}
