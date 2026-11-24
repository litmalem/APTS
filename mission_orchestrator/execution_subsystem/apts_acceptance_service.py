"""Expose the Stage 6.10 declaration while preserving the Stage 6.9 runtime."""
from .apts_acceptance_contract import CONTROL_VERSION, canonical_apts_acceptance_contract
from .cti_feedback_service import ExecutionCTIFeedbackService
from mission_orchestrator.apts_source_binding import source_location


class APTSAcceptanceService(ExecutionCTIFeedbackService):
    def health(self):
        value = super().health()
        contract = canonical_apts_acceptance_contract()
        value.update({"control_version": CONTROL_VERSION,
            "supported_controls": [*value["supported_controls"], CONTROL_VERSION],
            "stage6_10_schema_version": contract["schema_version"],
            "stage6_10_contract_sha256": contract["integrity"]["canonical_sha256"],
            "stage6_10_predecessor_contract_sha256": contract["predecessor"]["contract_sha256"],
            "full_apts_acceptance_gate_enabled": True,
            "full_apts_acceptance_status": "DECLARED_ONLY",
            "full_apts_acceptance_external_harness_required": True,
            "full_apts_acceptance_new_authority": False,
            "apts_source_locations": {
                "mission": source_location("mission", self.mission_source.sqlite_path),
                "pentest": source_location("pentest", self.proposal_source.sqlite_path),
                "cti_feedback": source_location("cti_feedback", self.knowledge_repository.sqlite_path)},
            "governance_base_url": getattr(self.governance_client, "base_url", "INJECTED_CLIENT"),
            "stage_output": contract["stage_output"], "next_stage": None})
        return value

    def get_apts_acceptance_contract(self):
        return {"control_version": CONTROL_VERSION, "status": "declared", "read_only": True,
            "runtime_self_certification": False, "execution_authorized": False,
            "contract": canonical_apts_acceptance_contract()}

    def reject_execution(self):
        return {**super().reject_execution(), "control_version": CONTROL_VERSION,
            "error_code": "STAGE6_10_EXTERNAL_ACCEPTANCE_REQUIRED", "next_stage": None}
