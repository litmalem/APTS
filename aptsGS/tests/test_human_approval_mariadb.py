"""Opt-in real MariaDB verification, always in a newly named isolated schema."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from fastapi.testclient import TestClient
import pymysql
from pymysql.constants import CLIENT
import pytest

from app import main, approval_auth
from app.approval_auth import ApprovalPrincipal, REGISTRY_SCHEMA
from app.db import Db
from app.governance_service import GovernanceService
from app.models import ApprovalDecisionInput, AuthorizationRequest, ScopeContractCreate
from app.repositories import GovernanceRepository

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "m" * 48


@pytest.fixture
def database(tmp_path):
    config_path = os.getenv("GSS_TEST_DB_CONFIG")
    if not config_path:
        pytest.fail("This opt-in suite needs GSS_TEST_DB_CONFIG for an isolated test database")
    config = json.loads(Path(config_path).read_text())
    prefix = config.pop("database", "")
    if not re.fullmatch(r"gss_approval_test_[A-Za-z0-9_]{1,25}", prefix):
        pytest.fail("database name must start with gss_approval_test_ and have a short safe suffix")
    if config.get("host", "127.0.0.1") not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("Only a local isolated MariaDB server is permitted")
    name = prefix + "_" + uuid.uuid4().hex[:12]
    conn = pymysql.connect(**config, autocommit=True, client_flag=CLIENT.MULTI_STATEMENTS)
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE `{name}`")
            cur.execute(f"USE `{name}`")
            dump = os.getenv("GSS_TEST_SCHEMA_DUMP")
            schema = Path(dump).read_text() if dump else (ROOT / "sql/01_governance_schema.sql").read_text()
            # All CREATE/USE statements in the supplied GSS schema target only
            # the schema created above. The original user dump is read-only.
            schema = schema.replace("apts_governance", name)
            cur.execute(schema)
            while cur.nextset(): pass
            seed = (ROOT / "sql/02_seed_default_policies.sql").read_text().replace("apts_governance", name)
            cur.execute(seed)
            while cur.nextset(): pass
            # The supplied export is schema-only. Initialize only this fresh
            # synthetic test schema, as the shipped schema bootstrap does.
            cur.execute("INSERT INTO gov_emergency_state (singleton_id,active,reason,version) VALUES (1,0,'ISOLATED_TEST_INITIALIZED',1) ON DUPLICATE KEY UPDATE singleton_id=VALUES(singleton_id)")
        yield GovernanceRepository(Db({**config, "database": name}))
    finally:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE `{name}`")
        conn.close()


@pytest.fixture
def api(database, tmp_path, monkeypatch):
    service = GovernanceService(database)
    scope = service.create_scope_contract(ScopeContractCreate(
        mission_id="synthetic-approval-mission", name="Isolated approval acceptance", created_by="test-operator", approved_by="test-scope-owner",
        targets=[{"target_type": "IP", "target_value": "127.0.0.1", "environment": "LAB"}],
        action_constraints=[{"action_class": "VULNERABILITY_VALIDATION", "effect": "REVIEW", "max_risk_level": "HIGH",
                             "requires_approval": True, "constraints": {"required_approver_role": "SECURITY_APPROVER"}}],
    ))
    review = service.evaluate_authorization(AuthorizationRequest(
        mission_id="synthetic-approval-mission", scope_contract_id=scope["scope_contract_id"],
        subject_component="SYNTHETIC_AGENT", action_class="VULNERABILITY_VALIDATION", action_name="SAFE_VALIDATE",
        resource_type="IP", resource_value="127.0.0.1", context={"environment": "LAB", "reversible": True},
        requested_by="synthetic-requester",
    ))
    assert review["decision"] == "REVIEW", review["reason_codes"]
    path = tmp_path / "principals.json"
    path.write_text(json.dumps({"schema_version": REGISTRY_SCHEMA, "principals": [{
        "principal_id": "verified-human", "principal_type": "HUMAN", "roles": ["SECURITY_APPROVER"],
        "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest(), "enabled": True}]}))
    monkeypatch.setattr(main, "service", service)
    monkeypatch.setattr(approval_auth, "settings", replace(approval_auth.settings, approval_principals_file=str(path)))
    return TestClient(main.app), service, database, review, path


def post(api, decision="APPROVE", header="Bearer " + TOKEN, **extra):
    return api[0].post(f"/api/governance/approvals/{api[3]['approval_request_id']}/decision",
        json={"decision": decision, "reason": "Synthetic lab review", **extra},
        headers={"Authorization": header} if header else {})


def counts(repo):
    return {table: repo.db.fetch_one(f"SELECT COUNT(*) AS n FROM {table}")["n"] for table in
            ("gov_approval_decisions", "gov_policy_decisions", "gov_risk_assessments", "gov_audit_log", "gov_event_outbox")}


@pytest.mark.parametrize("kind", ["missing_caller", "wrong_role", "agent", "spoofed_identity"])
def test_real_database_rejects_unauthorized_without_mutation(api, kind):
    before = counts(api[2])
    data = json.loads(api[-1].read_text())
    if kind == "wrong_role": data["principals"][0]["roles"] = ["VIEWER"]
    if kind == "agent": data["principals"][0]["principal_type"] = "AGENT"
    api[-1].write_text(json.dumps(data))
    response = post(api, header=None if kind == "missing_caller" else "Bearer " + TOKEN,
                    **({"approver_id": "impostor"} if kind == "spoofed_identity" else {}))
    assert response.status_code == (401 if kind == "missing_caller" else 403)
    assert counts(api[2]) == before
    assert api[2].get_approval_request(api[3]["approval_request_id"])["status"] == "PENDING"


@pytest.mark.parametrize("decision,result,state", [("APPROVE", "ALLOW", "APPROVED"), ("DENY", "DENY", "DENIED")])
def test_real_database_legitimate_decision_and_replay(api, decision, result, state):
    response = post(api, decision)
    assert response.status_code == 200
    assert response.json()["policy_decision"]["decision"] == result
    approval_id = api[3]["approval_request_id"]
    assert api[2].get_approval_request(approval_id)["status"] == state
    row = api[2].db.fetch_one("SELECT * FROM gov_approval_decisions WHERE approval_request_id=%(id)s", {"id": approval_id})
    assert row["approver_id"] == "verified-human" and row["approver_role"] == "SECURITY_APPROVER"
    assert row["decision_hash"] == response.json()["approval"]["decision_hash"]
    assert post(api).status_code == 409
    assert counts(api[2])["gov_approval_decisions"] == 1


def test_real_database_concurrent_approval_has_exactly_one_winner(api):
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: post(api), range(4)))
    assert sorted(response.status_code for response in responses) == [200, 409, 409, 409]
    assert counts(api[2])["gov_approval_decisions"] == 1
    assert counts(api[2])["gov_policy_decisions"] == 2


def test_real_database_failed_policy_write_rolls_back_all_evidence(api, monkeypatch):
    before = counts(api[2])
    def fail(row): raise RuntimeError("synthetic policy write failure")
    monkeypatch.setattr(api[2], "insert_policy_decision", fail)
    with pytest.raises(RuntimeError, match="synthetic policy write failure"):
        api[1].decide_approval(api[3]["approval_request_id"], ApprovalDecisionInput(decision="APPROVE", reason="Synthetic review"),
            principal=ApprovalPrincipal("verified-human", frozenset({"SECURITY_APPROVER"}), "HUMAN"))
    assert counts(api[2]) == before
    assert api[2].get_approval_request(api[3]["approval_request_id"])["status"] == "PENDING"


def test_real_database_expired_approval_is_not_consumed(api):
    api[2].db.execute("UPDATE gov_approval_requests SET expires_at=%(expiry)s WHERE approval_request_id=%(id)s",
        {"expiry": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=5), "id": api[3]["approval_request_id"]})
    before = counts(api[2])
    assert post(api).status_code == 409
    assert counts(api[2]) == before


def test_real_database_approval_keeps_emergency_stop_authoritative(api):
    api[2].db.execute("UPDATE gov_emergency_state SET active=1")
    response = post(api)
    assert response.status_code == 200
    assert response.json()["policy_decision"]["decision"] == "DENY"
    assert "EMERGENCY_STOP_ACTIVE" in response.json()["policy_decision"]["reason_codes"]
