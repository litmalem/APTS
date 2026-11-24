from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from threading import Lock

from fastapi.testclient import TestClient
import pytest

from app import main
from app.approval_auth import AUTH_MODE, REGISTRY_SCHEMA, ApprovalAccessError, ApprovalPrincipal, authenticate_approval
from app.models import ApprovalDecisionInput
from app.repositories import GovernanceRepository
from app.utils import sha256_json
from test_execution_revalidation_stage6_4 import ctx, request

TOKEN = "a" * 48


def registry_entry(**changes):
    return {"principal_id": "human-security-01", "principal_type": "HUMAN", "roles": ["SECURITY_APPROVER"],
            "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(), "enabled": True, **changes}


@pytest.fixture
def api(ctx, tmp_path, monkeypatch):
    service, repo, evaluation = ctx
    repo.constraint["requires_approval"] = 1
    review = service.evaluate_authorization(request(evaluation))
    path = tmp_path / "principals.json"
    path.write_text(json.dumps({"schema_version": REGISTRY_SCHEMA, "principals": [registry_entry()]}))
    monkeypatch.setattr(main, "service", service)
    from app import approval_auth
    monkeypatch.setattr(approval_auth, "settings", replace(approval_auth.settings, approval_principals_file=str(path)))
    # Do not enter application lifespan: no outbox delivery or production DB access.
    client = TestClient(main.app)
    return client, service, repo, evaluation, review, path


def post(api, payload=None, authorization="Bearer " + TOKEN):
    client, _, _, _, review, _ = api
    return client.post(f"/api/governance/approvals/{review['approval_request_id']}/decision",
                       json=payload or {"decision": "APPROVE", "reason": "Reviewed synthetic lab action"},
                       headers={"Authorization": authorization} if authorization is not None else {})


def assert_unconsumed(api):
    _, _, repo, _, _, _ = api
    assert repo.approvals[0]["status"] == "PENDING"
    assert len(repo.decisions) == 1
    assert not repo.approval_decisions


@pytest.mark.parametrize("header", [None, "", "Basic " + TOKEN, "Bearer x", "Bearer " + "z" * 48,
                                   "Bearer " + TOKEN + " extra"])
def test_unauthenticated_or_unknown_caller_cannot_decide(api, header):
    response = post(api, authorization=header)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert_unconsumed(api)


@pytest.mark.parametrize("changes,status", [({"roles": ["VIEWER"]}, 403), ({"principal_type": "AGENT"}, 403),
                                           ({"principal_type": "SERVICE"}, 403), ({"enabled": False}, 401)])
def test_server_registered_unauthorized_caller_or_role_cannot_decide(api, changes, status):
    api[-1].write_text(json.dumps({"schema_version": REGISTRY_SCHEMA, "principals": [registry_entry(**changes)]}))
    assert post(api).status_code == status
    assert_unconsumed(api)


@pytest.mark.parametrize("claim", [{"approver_id": "someone-else"}, {"approver_role": "ADMIN"},
                                   {"approver_role": "security_approver"}])
def test_payload_cannot_impersonate_another_identity_or_role(api, claim):
    assert post(api, {"decision": "APPROVE", "reason": "Review", **claim}).status_code == 403
    assert_unconsumed(api)


@pytest.mark.parametrize("extra", ["human_approval_granted", "required_approver_role", "principal", "roles", "caller"])
def test_payload_authority_overrides_are_rejected(api, extra):
    assert post(api, {"decision": "APPROVE", "reason": "Review", extra: True}).status_code == 422
    assert_unconsumed(api)


@pytest.mark.parametrize("reason", ["", "   "])
def test_empty_approval_reason_is_rejected(api, reason):
    assert post(api, {"decision": "APPROVE", "reason": reason}).status_code == 422
    assert_unconsumed(api)


@pytest.mark.parametrize("expiry", [None, "invalid", datetime.now(timezone.utc) - timedelta(seconds=10),
                                    (datetime.now(timezone.utc) - timedelta(seconds=10)).replace(tzinfo=None)])
def test_expired_or_missing_expiry_is_rejected_without_mutation(api, expiry):
    api[2].approvals[0]["expires_at"] = expiry
    assert post(api).status_code == 409
    assert_unconsumed(api)


@pytest.mark.parametrize("expiry", ["aware", "naive", "iso_z"])
def test_valid_expiry_formats_support_the_legitimate_approval_path(api, expiry):
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    api[2].approvals[0]["expires_at"] = {"aware": future, "naive": future.replace(tzinfo=None),
                                       "iso_z": future.isoformat().replace("+00:00", "Z")}[expiry]
    assert post(api).status_code == 200


@pytest.mark.parametrize("legacy_assertions", [False, True])
def test_legitimate_approval_is_identity_bound_and_hash_bound(api, legacy_assertions):
    payload = {"decision": "APPROVE", "reason": "Reviewed synthetic lab action"}
    if legacy_assertions:
        payload.update(approver_id="human-security-01", approver_role="SECURITY_APPROVER")
    response = post(api, payload)
    assert response.status_code == 200
    body = response.json()
    proof, final = body["approval"], body["policy_decision"]
    assert proof["approver_id"] == "human-security-01"
    assert proof["approver_role"] == "SECURITY_APPROVER"
    assert proof["authentication_mode"] == AUTH_MODE
    assert proof["decision_hash"] == sha256_json({k: v for k, v in proof.items() if k != "decision_hash"})
    assert final["decision"] == "ALLOW"
    assert final["approval_request_id"] == api[4]["approval_request_id"]
    assert final["human_approval"] == proof
    assert final["execution_revalidation"]["human_approval_verified"] is True
    core = {k: v for k, v in final.items() if k not in {"decision_hash", "governance_event_id"}}
    assert final["decision_hash"] == sha256_json(core) == api[2].decisions[-1]["decision_hash"]
    assert api[2].approvals[0]["status"] == "APPROVED"
    assert api[1].audit.items[-1][1]["actor_id"] == "human-security-01"
    assert TOKEN not in json.dumps(body)


def test_legitimate_human_denial_is_final_and_cannot_be_replayed(api):
    response = post(api, {"decision": "DENY", "reason": "Declined synthetic lab action"})
    assert response.status_code == 200
    assert response.json()["policy_decision"]["decision"] == "DENY"
    assert response.json()["policy_decision"]["human_approval"] == response.json()["approval"]
    assert api[2].approvals[0]["status"] == "DENIED"
    assert post(api).status_code == 409
    assert len(api[2].approval_decisions) == 1


def test_approval_cannot_be_replayed(api):
    assert post(api).status_code == 200
    assert post(api).status_code == 409
    assert len(api[2].approval_decisions) == 1
    assert len(api[2].decisions) == 2


@pytest.mark.parametrize("change", ["emergency", "scope_expired", "out_of_scope", "policy_disabled", "policy_expired",
                                    "risk_ceiling", "hard_deny", "revoked", "missing_scope", "scope_mission"])
def test_authorized_approval_cannot_override_current_hard_denies(api, change):
    repo = api[2]
    if change == "emergency": repo.emergency["active"] = 1
    elif change == "scope_expired": repo.scope["valid_until"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif change == "out_of_scope": repo.scope["targets"] = []
    elif change == "policy_disabled": repo.policy["status"] = "DISABLED"
    elif change == "policy_expired": repo.policy["effective_until"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif change == "risk_ceiling": repo.constraint["max_risk_level"] = "LOW"
    elif change == "hard_deny": repo.constraint["effect"] = "DENY"
    elif change == "revoked": repo.old["decision_status"] = "REVOKED"
    elif change == "missing_scope": repo.scope["scope_contract_id"] = "different-scope"
    elif change == "scope_mission": repo.scope["mission_id"] = "different-mission"
    response = post(api)
    assert response.status_code == 200
    assert response.json()["policy_decision"]["decision"] == "DENY"


def test_role_requirement_changed_since_review_requires_new_review(api):
    api[2].constraint["constraints"]["required_approver_role"] = "SENIOR_APPROVER"
    assert post(api).status_code == 409
    assert_unconsumed(api)


@pytest.mark.parametrize("change", ["authorization_mission", "authorization_status", "approval_mission"])
def test_approval_is_bound_to_reviewed_authorization(api, change):
    repo = api[2]
    if change == "authorization_mission": repo.authorizations[0]["mission_id"] = "other"
    elif change == "authorization_status": repo.authorizations[0]["request_status"] = "ALLOW"
    else: repo.approvals[0]["mission_id"] = "other"
    assert post(api).status_code == 409
    assert_unconsumed(api)


def test_direct_service_flag_cannot_claim_human_approval(ctx):
    service, repo, evaluation = ctx
    with pytest.raises(ApprovalAccessError):
        service.evaluate_authorization(request(evaluation), human_approval_granted=True)
    assert not repo.decisions and not repo.authorizations


def test_direct_service_decision_requires_a_verified_principal(api):
    with pytest.raises(ApprovalAccessError) as exc:
        api[1].decide_approval(api[4]["approval_request_id"], ApprovalDecisionInput(decision="APPROVE", reason="Review"))
    assert exc.value.status_code == 401
    assert_unconsumed(api)


def test_revoking_credential_takes_effect_without_restart(api):
    api[-1].write_text(json.dumps({"schema_version": REGISTRY_SCHEMA, "principals": [registry_entry(enabled=False)]}))
    assert post(api).status_code == 401
    assert_unconsumed(api)


@pytest.mark.parametrize("data", ["not-json", {}, {"schema_version": "wrong", "principals": []},
                                  {"schema_version": REGISTRY_SCHEMA, "principals": [registry_entry(), registry_entry()]},
                                  {"schema_version": REGISTRY_SCHEMA, "principals": [registry_entry(roles=[[]])]}])
def test_malformed_registry_fails_closed(api, data):
    api[-1].write_text(data if isinstance(data, str) else json.dumps(data))
    assert post(api).status_code == 503
    assert_unconsumed(api)


def test_unconfigured_registry_fails_closed(api, monkeypatch):
    from app import approval_auth
    monkeypatch.setattr(approval_auth, "settings", replace(approval_auth.settings, approval_principals_file=""))
    assert post(api).status_code == 503
    assert_unconsumed(api)


def test_failed_policy_persistence_rolls_back_approval_consumption(api, monkeypatch):
    def fail(row): raise RuntimeError("injected write failure")
    monkeypatch.setattr(api[2], "insert_policy_decision", fail)
    with pytest.raises(RuntimeError, match="injected write failure"):
        api[1].decide_approval(api[4]["approval_request_id"], ApprovalDecisionInput(decision="APPROVE", reason="Review"),
                              principal=ApprovalPrincipal("human-security-01", frozenset({"SECURITY_APPROVER"}), "HUMAN"))
    assert_unconsumed(api)


class TransactionDb:
    """Execute the repository's SQL protocol, including locking and rollback."""
    def __init__(self):
        self.lock = Lock()
        self.state = "PENDING"
        self.records = []
        self.rowcount = 0
        self.fail_insert = False
        self.expired = False
    @contextmanager
    def connect(self):
        with self.lock:
            before = self.state, deepcopy(self.records)
            try: yield self
            except Exception:
                self.state, self.records = before
                raise
    def cursor(self): return self
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, values):
        if "UPDATE gov_approval_requests" in sql:
            for guard in ["AND status='PENDING'", "expires_at > UTC_TIMESTAMP()", "required_approver_role=",
                          "authorization_request_id=", "mission_id="]:
                assert guard in sql
            self.rowcount = int(self.state == "PENDING" and not self.expired)
            if self.rowcount: self.state = values["status"]
        else:
            assert "INSERT INTO gov_approval_decisions" in sql
            if self.fail_insert: raise RuntimeError("insert failed")
            self.records.append(dict(values))


def approval_row():
    return {"approval_decision_id": "decision-test", "approval_request_id": "approval-test",
            "approver_id": "human-security-01", "approver_role": "SECURITY_APPROVER", "decision": "APPROVE",
            "reason": "Review", "decision_hash": "a" * 64, "mission_id": "mission-test", "authorization_request_id": "request-test"}


def test_repository_allows_only_one_concurrent_decision():
    db = TransactionDb()
    repo = GovernanceRepository(db)
    def consume(index):
        try:
            repo.insert_approval_decision({**approval_row(), "approval_decision_id": f"decision-{index}"})
            return "accepted"
        except ApprovalAccessError as exc:
            assert exc.status_code == 409
            return "rejected"
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(consume, range(4)))
    assert outcomes.count("accepted") == 1
    assert outcomes.count("rejected") == 3
    assert len(db.records) == 1 and db.state == "APPROVED"


def test_repository_rolls_back_consumption_when_evidence_insert_fails():
    db = TransactionDb()
    db.fail_insert = True
    with pytest.raises(RuntimeError, match="insert failed"):
        GovernanceRepository(db).insert_approval_decision(approval_row())
    assert db.state == "PENDING" and not db.records


def test_repository_rechecks_expiry_during_atomic_consumption():
    db = TransactionDb()
    db.expired = True
    with pytest.raises(ApprovalAccessError):
        GovernanceRepository(db).insert_approval_decision(approval_row())
    assert db.state == "PENDING" and not db.records


def test_nested_database_operations_share_one_transaction(monkeypatch):
    from app.db import Db
    import app.db as module
    class Connection:
        def __init__(self): self.commits = self.rollbacks = self.closes = 0
        def commit(self): self.commits += 1
        def rollback(self): self.rollbacks += 1
        def close(self): self.closes += 1
    connection = Connection()
    monkeypatch.setattr(module.pymysql, "connect", lambda **kwargs: connection)
    db = Db({"host": "synthetic"})
    with db.connect() as outer:
        with db.connect() as inner:
            assert inner is outer
        assert connection.commits == 0
    assert (connection.commits, connection.rollbacks, connection.closes) == (1, 0, 1)
    with pytest.raises(RuntimeError):
        with db.connect():
            with db.connect(): raise RuntimeError("rollback")
    assert (connection.commits, connection.rollbacks, connection.closes) == (1, 1, 2)
