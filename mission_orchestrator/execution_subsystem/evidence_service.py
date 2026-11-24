from __future__ import annotations

import base64

from .evidence_collector import EvidenceCollector
from .evidence_contract import EVIDENCE_CONTROL_VERSION, canonical_evidence_contract
from .evidence_repository import ExecutionEvidenceRepository
from .execution_contract import ExecutionRequestValidationError, require_id
from .request_repository import ExecutionRepositoryError
from .runtime_contract import attempt_id
from .runtime_service import ExecutionRuntimeService


class ExecutionEvidenceService(ExecutionRuntimeService):
    def __init__(self, repository=None, *args, **kwargs):
        repository = repository or ExecutionEvidenceRepository()
        if not isinstance(repository, ExecutionEvidenceRepository):
            raise ExecutionRequestValidationError("Stage 6.6 requires an evidence repository")
        super().__init__(repository, *args, **kwargs)

    def health(self):
        value = super().health()
        contract = canonical_evidence_contract()
        value.update({"control_version": EVIDENCE_CONTROL_VERSION,
            "supported_controls": [*value["supported_controls"], EVIDENCE_CONTROL_VERSION],
            "stage6_6_schema_version": contract["schema_version"],
            "stage6_6_contract_sha256": contract["integrity"]["canonical_sha256"],
            "stage6_6_predecessor_control": contract["predecessor"]["control"],
            "stage6_6_predecessor_contract_sha256": contract["predecessor"]["contract_sha256"],
            "artifact_evidence_capture_enabled": True, "artifact_repository_append_only": True,
            "artifact_repository_backend": "EXECUTION_SQLITE_BLOBS", "terminal_evidence_atomic": True,
            "caller_evidence_upload_supported": False, "raw_target_bytes_retained": False,
            "evidence_capture_additional_target_io": False, "screenshots_supported": False,
            "target_state_measurement_supported": False, "next_stage": "6.7"})
        return value

    def get_evidence_contract(self):
        return {"control_version": EVIDENCE_CONTROL_VERSION, "status": "declared", "read_only": True,
            "runtime_self_certification": False, "contract": canonical_evidence_contract()}

    def get_recon_execution_result_contract(self):
        from .execution_result_contract import canonical_recon_execution_result_contract
        return {"control_version":"stage6-recon-execution-result-return", "status":"declared",
            "read_only":True, "contract":canonical_recon_execution_result_contract()}

    def get_enumeration_execution_result_contract(self):
        from .execution_result_contract import canonical_enumeration_execution_result_contract
        return {"control_version":"stage6-enumeration-execution-result-return", "status":"declared",
            "read_only":True, "contract":canonical_enumeration_execution_result_contract()}

    def get_contract(self):
        return {**super().get_contract(), "control_version": EVIDENCE_CONTROL_VERSION}

    def get_runtime_contract(self):
        return {**super().get_runtime_contract(), "control_version": EVIDENCE_CONTROL_VERSION}

    def get_authorization_contract(self):
        return {**super().get_authorization_contract(), "control_version": EVIDENCE_CONTROL_VERSION}

    def get_gateway_contract(self):
        return {**super().get_gateway_contract(), "control_version": EVIDENCE_CONTROL_VERSION}

    def get_adapter_contract(self):
        return {**super().get_adapter_contract(), "control_version": EVIDENCE_CONTROL_VERSION}

    def create_request(self, payload):
        return {**super().create_request(payload), "control_version": EVIDENCE_CONTROL_VERSION}

    def authorize_execution(self, payload):
        return {**super().authorize_execution(payload), "control_version": EVIDENCE_CONTROL_VERSION}

    def control(self, payload, *, kill=False):
        return {**super().control(payload, kill=kill), "control_version": EVIDENCE_CONTROL_VERSION}

    @staticmethod
    def runtime_response(item, *, created=False):
        return {**ExecutionRuntimeService.runtime_response(item, created=created),
            "control_version": EVIDENCE_CONTROL_VERSION}

    def _run_reserved(self, claim, envelope, *, runtime=None):
        if runtime is None:
            raise ExecutionRequestValidationError("evidence capture requires the owned runtime")
        capture = EvidenceCollector(self.repository, attempt_id(claim["invocation_id"]), self.owner_id, self.clock)
        runtime.evidence_capture = capture
        result = super()._run_reserved(claim, envelope, runtime=runtime)
        if capture.failed:
            raise ExecutionRepositoryError("EVIDENCE_CAPTURE_PERSISTENCE_FAILED")
        return result

    def get_evidence(self, identity):
        return {"control_version": EVIDENCE_CONTROL_VERSION, **self.repository.get_evidence(identity)}

    def get_artifact(self, identity, attempt_id):
        descriptor, payload = self.repository.get_artifact(identity, attempt_id)
        return {"control_version": EVIDENCE_CONTROL_VERSION, "artifact": descriptor,
            "content_base64": base64.b64encode(payload).decode("ascii"), "read_only": True,
            "execution_authorized": False, "target_network_io_performed": False}

    def verify_capture(self, identity):
        value = self.repository.get_evidence(identity)
        return {"control_version": EVIDENCE_CONTROL_VERSION, "attempt_id": identity,
            "status": "VERIFIED" if value["sealed"] else value["status"],
            "sealed": value["sealed"], "manifest_sha256": value["manifest_sha256"],
            "artifact_count": value["artifact_count"], "read_only": True,
            "execution_authorized": False, "target_network_io_performed": False,
            "runtime_self_certification": False}

    def list_evidence(self, execution_id, limit=100):
        require_id(execution_id, "execution_id", "exec-")
        return {"control_version": EVIDENCE_CONTROL_VERSION, "execution_id": execution_id,
            "captures": [self.get_evidence(i["attempt_id"]) for i in self.repository.list_attempts(execution_id, limit)],
            "execution_authorized": False, "target_network_io_performed": False, "read_only": True}

    def get_recon_execution_results(self, action_id):
        """Expose durable Stage 6 results to Recon by exact Action Request identity."""
        require_id(action_id, "recon_action_id", "rareq-")
        results = self.repository.get_recon_action_attempts(action_id)
        if not results:
            from .execution_contract import ExecutionSourceNotFound
            raise ExecutionSourceNotFound("no Stage 6 runtime result is stored for this Recon Action Request")
        return {"control_version": EVIDENCE_CONTROL_VERSION, "status": "ok",
            "action_id": action_id, "count": len(results), "results": results,
            "latest_result": results[-1], "read_only": True,
            "source": "DURABLE_STAGE6_RUNTIME_AND_STAGE6_6_EVIDENCE",
            "caller_result_accepted": False, "execution_authorized": False,
            "target_network_io_performed": False, "vulnerability_confirmed": False,
            "vep_created": False}

    def get_enumeration_execution_results(self, proposal_ref):
        """Read-only Stage-6 result lookup bound to one persisted Enumeration proposal."""
        require_id(proposal_ref, "enumeration_proposal_ref", "actp-")
        results = self.repository.get_enumeration_proposal_attempts(proposal_ref)
        if not results:
            from .execution_contract import ExecutionSourceNotFound
            raise ExecutionSourceNotFound("no Stage 6 runtime result is stored for this Enumeration proposal")
        return {"control_version": EVIDENCE_CONTROL_VERSION, "status": "ok",
            "proposal_ref": proposal_ref, "count": len(results), "results": results,
            "latest_result": results[-1], "read_only": True,
            "source": "DURABLE_STAGE6_RUNTIME_AND_STAGE6_6_EVIDENCE",
            "caller_result_accepted": False, "execution_authorized": False,
            "target_network_io_performed": False, "vulnerability_confirmed": False,
            "vep_created": False, "source_run_mutated": False}

    def reject_execution(self):
        return {**super().reject_execution(), "control_version": EVIDENCE_CONTROL_VERSION,
            "error_code": "STAGE6_6_SERVER_OWNED_EVIDENCE_AND_RUNTIME_REQUIRED", "next_stage": "6.7"}
