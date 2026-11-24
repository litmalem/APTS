from __future__ import annotations

from .authorization_contract import utc_timestamp
from .evidence_service import ExecutionEvidenceService
from .execution_contract import ExecutionRequestValidationError
from .runtime_service import ExecutionRuntimeService
from .vep_contract import VEP_CONTROL_VERSION, SEMANTICS, canonical_vep_contract, normalize_vep_intake
from .vep_repository import ExecutionVEPRepository
from .vep_source import PentestVEPSource


class ExecutionVEPService(ExecutionEvidenceService):
    def __init__(self, repository=None, *args, **kwargs):
        repository = repository or ExecutionVEPRepository()
        if not isinstance(repository, ExecutionVEPRepository):
            raise ExecutionRequestValidationError("Stage 6.7 requires a VEP repository")
        super().__init__(repository, *args, **kwargs)
        self.vep_source = PentestVEPSource(self.proposal_source.sqlite_path)

    def health(self):
        value = super().health()
        contract = canonical_vep_contract()
        value.update({"control_version":VEP_CONTROL_VERSION,
            "supported_controls":[*value["supported_controls"], VEP_CONTROL_VERSION],
            "stage6_7_schema_version":contract["schema_version"],
            "stage6_7_contract_sha256":contract["integrity"]["canonical_sha256"],
            "stage6_7_predecessor_control":contract["predecessor"]["control"],
            "stage6_7_predecessor_contract_sha256":contract["predecessor"]["contract_sha256"],
            "vep_construction_enabled":True, "vep_repository_append_only":True, "vep_terminal_capture_required":True,
            "vep_integrity_verification_enabled":True, "vep_offline_export_enabled":True,
            "vep_caller_summary_supported":False, "vep_construction_additional_target_io":False,
            "vep_automatic_vulnerability_confirmation":False, "vep_pentest_writes":False,
            "vep_cleanup_verification_enabled":False, "vep_cti_feedback_enabled":False, "next_stage":"6.8"})
        return value

    def get_vep_contract(self):
        return {"control_version":VEP_CONTROL_VERSION, "status":"declared", "read_only":True,
            "runtime_self_certification":False, "contract":canonical_vep_contract()}

    def get_contract(self):
        return {**super().get_contract(), "control_version":VEP_CONTROL_VERSION}

    def get_authorization_contract(self):
        return {**super().get_authorization_contract(), "control_version":VEP_CONTROL_VERSION}

    def get_gateway_contract(self):
        return {**super().get_gateway_contract(), "control_version":VEP_CONTROL_VERSION}

    def get_adapter_contract(self):
        return {**super().get_adapter_contract(), "control_version":VEP_CONTROL_VERSION}

    def get_runtime_contract(self):
        return {**super().get_runtime_contract(), "control_version":VEP_CONTROL_VERSION}

    def get_evidence_contract(self):
        return {**super().get_evidence_contract(), "control_version":VEP_CONTROL_VERSION}

    def create_request(self, payload):
        return {**super().create_request(payload), "control_version":VEP_CONTROL_VERSION}

    def authorize_execution(self, payload):
        return {**super().authorize_execution(payload), "control_version":VEP_CONTROL_VERSION}

    def control(self, payload, *, kill=False):
        return {**super().control(payload, kill=kill), "control_version":VEP_CONTROL_VERSION}

    def get_evidence(self, identity):
        return {**super().get_evidence(identity), "control_version":VEP_CONTROL_VERSION}

    def get_artifact(self, identity, attempt_id):
        return {**super().get_artifact(identity, attempt_id), "control_version":VEP_CONTROL_VERSION}

    def verify_capture(self, identity):
        return {**super().verify_capture(identity), "control_version":VEP_CONTROL_VERSION}

    def list_evidence(self, execution_id, limit=100):
        return {**super().list_evidence(execution_id, limit), "control_version":VEP_CONTROL_VERSION}

    @staticmethod
    def vep_response(value, *, created=False):
        return {"control_version":VEP_CONTROL_VERSION, "vep_id":value["vep_id"], "attempt_id":value["attempt_id"],
            "finding_id":value["finding_id"], "vep_sha256":value["integrity"]["canonical_sha256"],
            "created":created, "historical_record":True, "read_only":not created, "status":"VERIFIED",
            "runtime_self_certification":False, "vep":value, **SEMANTICS}

    def construct_vep(self, payload):
        self._ensure_open()
        intake = normalize_vep_intake(payload)
        envelope, existing = self.repository.construction_context(intake)
        if existing is not None:
            return self.vep_response(existing)
        source = self.vep_source.snapshot(envelope)
        self._ensure_open()
        value, created = self.repository.construct(intake, source, utc_timestamp(self.clock()))
        return self.vep_response(value, created=created)

    def get_vep(self, identity, attempt_id):
        return self.vep_response(self.repository.get_vep(identity, attempt_id))

    def verify_vep_record(self, identity, attempt_id):
        value = self.repository.get_vep(identity, attempt_id)
        return {"control_version":VEP_CONTROL_VERSION, "status":"VERIFIED", "vep_id":identity,
            "attempt_id":attempt_id, "vep_sha256":value["integrity"]["canonical_sha256"],
            "artifact_count":len(value["evidence"]["artifacts"]), "read_only":True,
            "runtime_self_certification":False, **SEMANTICS}

    def export_vep(self, identity, attempt_id):
        return self.repository.get_vep(identity, attempt_id, export=True)

    def list_veps(self, execution_id, limit=100):
        values = self.repository.list_veps(execution_id, limit)
        return {"control_version":VEP_CONTROL_VERSION, "execution_id":execution_id, "read_only":True,
            "veps":[self.vep_response(v) for v in values], "count":len(values), **SEMANTICS}

    @staticmethod
    def runtime_response(item, *, created=False):
        return {**ExecutionRuntimeService.runtime_response(item, created=created), "control_version":VEP_CONTROL_VERSION}

    def reject_execution(self):
        return {**super().reject_execution(), "control_version":VEP_CONTROL_VERSION,
            "error_code":"STAGE6_7_EXACT_SERVER_OWNED_VEP_REQUIRED", "next_stage":"6.8"}
