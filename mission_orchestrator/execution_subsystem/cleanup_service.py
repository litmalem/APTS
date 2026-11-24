from __future__ import annotations

from .authorization_contract import utc_timestamp
from .cleanup_contract import CONTROL_VERSION, SEMANTICS, canonical_cleanup_contract, normalize_intake
from .cleanup_repository import ExecutionCleanupRepository
from .cleanup_resources import RevocableCredentialLeaseStore, rollback_local_resources
from .execution_contract import ExecutionRequestValidationError
from .request_repository import ExecutionRepositoryError
from .runtime_service import ExecutionRuntimeService
from .vep_service import ExecutionVEPService


class ExecutionCleanupService(ExecutionVEPService):
    def __init__(self, repository=None, *args, **kwargs):
        repository = repository or ExecutionCleanupRepository()
        if not isinstance(repository, ExecutionCleanupRepository):
            raise ExecutionRequestValidationError("Stage 6.8 requires a cleanup repository")
        super().__init__(repository, *args, **kwargs)
        self.credential_store = RevocableCredentialLeaseStore(self.credential_store, repository)

    def _run_reserved(self, claim, envelope, *, runtime=None):
        if runtime is None:
            raise ExecutionRequestValidationError("cleanup requires the owned runtime")
        runtime.cleanup_workers = []
        runtime.cleanup_sockets = []
        try:
            result = super()._run_reserved(claim, envelope, runtime=runtime)
        except BaseException:
            rollback_local_resources(runtime)
            raise
        resources = rollback_local_resources(runtime)
        from .runtime_contract import attempt_id
        receipt = self.repository.persist_cleanup(attempt_id(claim["invocation_id"]), self.owner_id,
            result, resources, utc_timestamp(self.clock()))
        if not receipt["local_resources_verified"]:
            raise ExecutionRepositoryError("STAGE6_8_LOCAL_RESOURCE_CLEANUP_NOT_PROVEN")
        return result

    def health(self):
        value = super().health()
        contract = canonical_cleanup_contract()
        value.update({"control_version":CONTROL_VERSION,
            "supported_controls":[*value["supported_controls"], CONTROL_VERSION],
            "stage6_8_schema_version":contract["schema_version"],
            "stage6_8_contract_sha256":contract["integrity"]["canonical_sha256"],
            "stage6_8_predecessor_control":contract["predecessor"]["control"],
            "stage6_8_predecessor_contract_sha256":contract["predecessor"]["contract_sha256"],
            "cleanup_workflow_enabled":True, "local_resource_rollback_enabled":True,
            "durable_local_credential_revocation_enabled":True, "post_action_verification_enabled":True,
            "post_action_report_append_only":True, "post_action_additional_target_io":False,
            "caller_cleanup_attestation_supported":False, "target_rollback_supported":False,
            "issuer_credential_revocation_supported":False, "cleanup_legacy_backfill_supported":False,
            "vep_cleanup_verification_enabled":True, "next_stage":"6.9"})
        return value

    def get_cleanup_contract(self):
        return {"control_version":CONTROL_VERSION, "status":"declared", "read_only":True,
            "runtime_self_certification":False, "contract":canonical_cleanup_contract()}

    def get_contract(self):
        return {**super().get_contract(), "control_version":CONTROL_VERSION}

    def get_authorization_contract(self):
        return {**super().get_authorization_contract(), "control_version":CONTROL_VERSION}

    def get_gateway_contract(self):
        return {**super().get_gateway_contract(), "control_version":CONTROL_VERSION}

    def get_adapter_contract(self):
        return {**super().get_adapter_contract(), "control_version":CONTROL_VERSION}

    def get_runtime_contract(self):
        return {**super().get_runtime_contract(), "control_version":CONTROL_VERSION}

    def get_evidence_contract(self):
        return {**super().get_evidence_contract(), "control_version":CONTROL_VERSION}

    def get_vep_contract(self):
        return {**super().get_vep_contract(), "control_version":CONTROL_VERSION}

    def create_request(self, payload):
        return {**super().create_request(payload), "control_version":CONTROL_VERSION}

    def authorize_execution(self, payload):
        return {**super().authorize_execution(payload), "control_version":CONTROL_VERSION}

    def control(self, payload, *, kill=False):
        return {**super().control(payload, kill=kill), "control_version":CONTROL_VERSION}

    @staticmethod
    def post_action_response(value, *, created=False):
        return {"control_version":CONTROL_VERSION, "status":value["state"], "created":created,
            "post_action_id":value["post_action_id"], "attempt_id":value["attempt_id"],
            "report_sha256":value["integrity"]["canonical_sha256"],
            "execution_closed":value["execution_closed"], "cleanup_verified":value["cleanup_verified"],
            "blocking_reasons":value["blocking_reasons"], "read_only":not created,
            "runtime_self_certification":False, "verification_status":"VERIFIED_INTERNAL_LINEAGE",
            "report":value, **SEMANTICS}

    def complete_post_action(self, payload):
        self._ensure_open()
        intake = normalize_intake(payload)
        value, created = self.repository.complete_post_action(intake, utc_timestamp(self.clock()))
        return self.post_action_response(value, created=created)

    def get_post_action(self, identity, attempt_id):
        return self.post_action_response(self.repository.get_post_action(identity, attempt_id))

    def verify_post_action(self, identity, attempt_id):
        value = self.repository.get_post_action(identity, attempt_id)
        return {k:v for k,v in self.post_action_response(value).items() if k != "report"}

    def export_post_action(self, identity, attempt_id):
        return self.repository.get_post_action(identity, attempt_id, export=True)

    def list_post_actions(self, execution_id, limit=100):
        values = self.repository.list_post_actions(execution_id, limit)
        return {"control_version":CONTROL_VERSION, "execution_id":execution_id, "read_only":True,
            "reports":[self.post_action_response(v) for v in values], "count":len(values), **SEMANTICS}

    def get_cleanup_status(self, attempt_id):
        return {"control_version":CONTROL_VERSION, **self.repository.get_cleanup_status(attempt_id), **SEMANTICS}

    @staticmethod
    def runtime_response(item, *, created=False):
        return {**ExecutionRuntimeService.runtime_response(item, created=created), "control_version":CONTROL_VERSION}

    def reject_execution(self):
        return {**super().reject_execution(), "control_version":CONTROL_VERSION,
            "error_code":"STAGE6_8_EXACT_SERVER_OWNED_POST_ACTION_REQUIRED", "next_stage":"6.9"}
