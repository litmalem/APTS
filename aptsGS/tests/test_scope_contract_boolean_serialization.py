import json

import pytest

from app.repositories import GovernanceRepository


class FakeDb:
    def __init__(self, requires_approval):
        self.requires_approval = requires_approval

    def fetch_one(self, query, params):
        return {
            "scope_contract_id": params["scope_contract_id"],
            "metadata_json": "{}",
        }

    def fetch_all(self, query, params):
        if "gov_scope_action_constraints" in query:
            return [{
                "action_class": "TARGET_RECON",
                "requires_approval": self.requires_approval,
                "constraints_json": "{}",
            }]
        return []


@pytest.mark.parametrize("stored, expected", [(0, False), (1, True), (False, False), (True, True)])
def test_scope_contract_emits_json_boolean_for_requires_approval(stored, expected):
    repo = GovernanceRepository(db=FakeDb(stored))

    result = repo.get_scope_contract("scope-test")
    value = result["action_constraints"][0]["requires_approval"]

    assert value is expected
    assert json.loads(json.dumps(value)) is expected


def test_scope_contract_rejects_invalid_requires_approval_database_value():
    repo = GovernanceRepository(db=FakeDb(2))

    with pytest.raises(ValueError, match="must be 0 or 1"):
        repo.get_scope_contract("scope-test")
