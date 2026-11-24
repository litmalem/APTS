from __future__ import annotations

from .repositories import GovernanceRepository


class ComplianceService:
    """Deterministic obligation lookup.

    It does not authorize actions. It returns audit/provenance/approval obligations
    attached to the applicable policy set and action class.
    """

    def __init__(self, repo: GovernanceRepository):
        self.repo = repo

    def obligations(self, policy_set_id: str, action_class: str) -> list[dict]:
        return self.repo.list_compliance_obligations(policy_set_id, action_class)
