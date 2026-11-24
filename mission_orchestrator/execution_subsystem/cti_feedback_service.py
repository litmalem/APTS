"""Compose the existing Execution runtime with the bounded CTI knowledge pipeline."""
from __future__ import annotations

from .authorization_contract import utc_timestamp
from .cleanup_service import ExecutionCleanupService
from .cti_feedback_contract import CONTROL_VERSION, SEMANTICS, canonical_feedback_contract
from .cti_feedback_repository import ExecutionCTIFeedbackRepository, ReadOnlyExecutionFeedbackSource
from .cti_knowledge_repository import CTIKnowledgeRepository
from .execution_contract import ExecutionRequestValidationError
from .runtime_service import ExecutionRuntimeService


class ExecutionCTIFeedbackService(ExecutionCleanupService):
    def __init__(self, repository=None, *args, knowledge_repository=None, **kwargs):
        repository = repository or ExecutionCTIFeedbackRepository()
        if not isinstance(repository, ExecutionCTIFeedbackRepository):
            raise ExecutionRequestValidationError("Stage 6.9 requires an Execution CTI feedback repository")
        self.knowledge_repository = knowledge_repository or CTIKnowledgeRepository()
        if self.knowledge_repository.sqlite_path.resolve() == repository.sqlite_path.resolve():
            raise ExecutionRequestValidationError("CTI knowledge and Execution require separate database files")
        self.knowledge_repository.initialize()
        super().__init__(repository, *args, **kwargs)
        self.feedback_source = ReadOnlyExecutionFeedbackSource(repository.sqlite_path)

    def health(self):
        value = super().health()
        self.knowledge_repository.initialize()
        contract = canonical_feedback_contract()
        value.update({"control_version":CONTROL_VERSION, "supported_controls":[*value["supported_controls"], CONTROL_VERSION],
            "stage6_9_schema_version":contract["schema_version"],
            "stage6_9_contract_sha256":contract["integrity"]["canonical_sha256"],
            "stage6_9_predecessor_contract_sha256":contract["predecessor"]["contract_sha256"],
            "cti_feedback_enabled":True, "vep_cti_feedback_enabled":True,
            "cti_knowledge_pipeline_enabled":True, "cti_knowledge_repository_migration_level":1,
            "cti_knowledge_source_read_only":True, "cti_feedback_caller_verdict_supported":False,
            "cti_feedback_automatic_confirmation":False, "cti_feedback_additional_target_io":False,
            "cti_feedback_external_vulndesk_writes":False, "cti_feedback_mission_write_owner":"MISSION_ORCHESTRATOR",
            "cti_feedback_mission_handoff_enabled":True, "next_stage":"6.10"})
        return value

    def get_feedback_contract(self):
        return {"control_version":CONTROL_VERSION, "status":"declared", "read_only":True,
            "runtime_self_certification":False, "contract":canonical_feedback_contract()}

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

    def get_cleanup_contract(self):
        return {**super().get_cleanup_contract(), "control_version":CONTROL_VERSION}

    def create_request(self, payload):
        return {**super().create_request(payload), "control_version":CONTROL_VERSION}

    def authorize_execution(self, payload):
        return {**super().authorize_execution(payload), "control_version":CONTROL_VERSION}

    def control(self, payload, *, kill=False):
        return {**super().control(payload, kill=kill), "control_version":CONTROL_VERSION}

    @staticmethod
    def post_action_response(value, *, created=False):
        return {**ExecutionCleanupService.post_action_response(value, created=created), "control_version":CONTROL_VERSION}

    @staticmethod
    def feedback_response(value, *, created=False):
        return {"control_version":CONTROL_VERSION, "status":"FEEDBACK_RECORDED", "created":created,
            "feedback_id":value["feedback_id"], "feedback_sha256":value["integrity"]["canonical_sha256"],
            "knowledge_id":value["knowledge_id"], "attempt_id":value["attempt_id"], "feedback":value,
            "hypothesis_outcome":value["assessment"]["hypothesis_outcome"],
            "review_required":value["mission_signal"]["review_required"], "read_only":not created,
            "verification_status":"VERIFIED_INTERNAL_LINEAGE", "runtime_self_certification":False, **SEMANTICS}

    def create_feedback(self, payload):
        self._ensure_open()
        value, created = self.repository.create_feedback(payload, utc_timestamp(self.clock()))
        return self.feedback_response(value, created=created)

    def get_feedback(self, identity, attempt_id):
        return self.feedback_response(self.repository.get_feedback(identity, attempt_id))

    def export_feedback(self, identity, attempt_id):
        return self.repository.get_feedback(identity, attempt_id, export=True)

    def list_feedback(self, execution_id, limit=100):
        values = self.repository.list_feedback(execution_id, limit)
        return {"control_version":CONTROL_VERSION, "read_only":True, "count":len(values),
            "feedback":[self.feedback_response(v) for v in values], **SEMANTICS}

    @staticmethod
    def knowledge_response(value, *, created=False):
        return {"control_version":CONTROL_VERSION, "status":"KNOWLEDGE_UPDATED", "created":created,
            "knowledge_id":value["knowledge_id"], "revision_id":value["revision_id"], "revision":value["revision"],
            "knowledge_sha256":value["integrity"]["canonical_sha256"], "knowledge":value,
            "read_only":not created, "cti_feedback_knowledge_written":True, "runtime_self_certification":False, **SEMANTICS}

    def update_knowledge(self, payload):
        self._ensure_open()
        value, created = self.knowledge_repository.import_feedback(payload, self.feedback_source, utc_timestamp(self.clock()))
        return self.knowledge_response(value, created=created)

    def get_knowledge(self, knowledge_id, mission_id, revision=None):
        exported = self.export_knowledge(knowledge_id, mission_id, revision)
        return self.knowledge_response(exported["revisions"][-1]["record"])

    def export_knowledge(self, knowledge_id, mission_id, revision=None):
        return self.knowledge_repository.export_knowledge(knowledge_id, mission_id, through=revision)

    def list_knowledge(self, mission_id, limit=100):
        values = self.knowledge_repository.list_knowledge(mission_id, limit)
        return {"control_version":CONTROL_VERSION, "read_only":True, "count":len(values),
            "knowledge":[self.knowledge_response(v) for v in values], **SEMANTICS}

    @staticmethod
    def runtime_response(item, *, created=False):
        return {**ExecutionRuntimeService.runtime_response(item, created=created), "control_version":CONTROL_VERSION}

    def reject_execution(self):
        return {**super().reject_execution(), "control_version":CONTROL_VERSION,
            "error_code":"STAGE6_9_EXACT_EVIDENCE_BOUND_FEEDBACK_REQUIRED", "next_stage":"6.10"}
