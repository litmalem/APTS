"""GOV-PLANE attestation for Stage 6.2-6.4; caller checks never grant authority."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re

from .models import Decision
from .policy_engine import GateResult
from .scope_service import ScopeMatcher

SCHEMA = "apts-gss-execution-revalidation-v1"
CHECKS = ("SCOPE", "ROE", "POLICY", "RISK", "EXPIRY", "REVOCATION", "TARGET", "TECHNIQUE")
EVAL_DOMAIN = "APTS_STAGE6_2_AUTHORIZATION_EVALUATION_V1"
REQUEST_DOMAIN = "APTS_STAGE6_1_EXECUTION_REQUEST_V1"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sealed(value, domain):
    if not isinstance(value, dict):
        return False
    core = {k:v for k,v in value.items() if k != "integrity"}
    return value.get("integrity") == {"algorithm": "SHA-256", "canonicalization": "UTF8_SORTED_JSON_V1", "hash_domain": domain,
                                      "canonical_sha256": digest({"hash_domain": domain, "core": core})}


def instant(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if not isinstance(value, str):
        raise ValueError("invalid execution timestamp")
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("execution timestamp requires timezone")
    return value.astimezone(timezone.utc)


def prepare_execution_evaluation(request):
    purpose = request.context.get("authorization_purpose")
    evaluation = request.context.get("execution_authorization_evaluation")
    if purpose != "STAGE6_2_EXECUTION_REVALIDATION" and evaluation is None:
        return None
    try:
        if (purpose != "STAGE6_2_EXECUTION_REVALIDATION" or request.subject_component != "EXECUTION_SUBSYSTEM"
                or request.action_name != "AUTHORIZE_TARGET_EXECUTION" or not sealed(evaluation, EVAL_DOMAIN)):
            raise ValueError("invalid execution evaluation")
        fields = {"schema_version", "revalidation_id", "nonce", "submitted_at", "intake", "execution_request", "envelope_sha256",
                  "source_binding", "current_context", "local_checks", "required_checks", "integrity"}
        if set(evaluation) != fields or evaluation["schema_version"] != "apts-execution-authorization-evaluation-v1" or evaluation["required_checks"] != list(CHECKS):
            raise ValueError("invalid execution evaluation schema")
        req, ctx = evaluation["execution_request"], evaluation["current_context"]
        if not sealed(req, REQUEST_DOMAIN) or req["schema_version"] != "apts-execution-request-v1":
            raise ValueError("invalid execution request integrity")
        if set(req) != {"schema_version", "execution_id", "mission_id", "task_id", "pentest_id", "proposing_agent", "action", "target", "parameters", "evidence_basis", "authorization_requirement", "integrity"}:
            raise ValueError("invalid execution request shape")
        intake = evaluation["intake"]
        if (intake["execution_id"] != req["execution_id"] or intake["envelope_sha256"] != evaluation["envelope_sha256"]
                or intake["revalidation_id"] != evaluation["revalidation_id"] or intake["requested_by"] != request.requested_by
                or req["mission_id"] != request.mission_id or ctx["mission_id"] != request.mission_id or ctx["mission_state"] != "RUNNING"
                or req["action"]["action_class"] != request.action_class.value
                or req["target"] != {"target_type": request.resource_type, "target_value": request.resource_value}
                or not re.fullmatch(r"[a-f0-9]{32}", evaluation["nonce"])
                or not re.fullmatch(r"[a-f0-9]{64}", evaluation["envelope_sha256"])):
            raise ValueError("execution request correlation mismatch")
        requirement = req["authorization_requirement"]
        if (requirement["authority"] != "EXTERNAL_APTS_GSS" or requirement["revalidation_required"] is not True
                or requirement["required_checks"] != list(CHECKS) or type(requirement["human_review_required"]) is not bool):
            raise ValueError("execution authorization requirement mismatch")
        if not isinstance(req["evidence_basis"], list) or [r["evidence_id"] for r in req["evidence_basis"]] != request.evidence_refs:
            raise ValueError("execution evidence correlation mismatch")
        gov = ctx["governance_authority"]
        if request.scope_contract_id != gov["governance_scope_contract_id"] or gov["authorization_authority"] != "aptsGSS" or gov["authorization_authority_component"] != "GOV-PLANE":
            raise ValueError("execution authority correlation mismatch")
        instant(evaluation["submitted_at"])
        # Ensure every restriction to be evaluated exists; do not trust local_checks.
        sources = [ctx["mission_scope"], ctx["pentest_context"]["boundary"], ctx["pentest_context"]["task"]]
        for source in sources:
            if not isinstance(source["scope"]["targets"], list) or not isinstance(source["constraints"], dict):
                raise ValueError("missing execution source restrictions")
        return evaluation
    except (KeyError, ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Invalid Stage 6 execution evaluation") from exc


def execution_risk_context(evaluation, scope, action_constraint=None):
    """Risk factors come from stored scope and the sealed operation, not caller flags."""
    req = evaluation["execution_request"]
    target_rows = (scope or {}).get("targets", [])
    environment = "PRODUCTION" if any(str(t.get("environment", "")).upper() in {"PROD", "PRODUCTION"} for t in target_rows) else "LAB"
    required_lease = (action_constraint or {}).get("constraints", {}).get("credentials_lease")
    return {"environment": environment, "uses_credentials": req["action"]["action_class"] == "CREDENTIAL_USE" or bool(required_lease),
            "reversible": req["parameters"]["estimated_impact"] in {"NONE", "LOW"}, "blast_radius": 1}


def apply_execution_checks(service, request, evaluation, scope, policy, constraint, emergency, gate, *, now, human_approval_granted):
    req, ctx = evaluation["execution_request"], evaluation["current_context"]
    gov = ctx["governance_authority"]
    matcher = ScopeMatcher()
    checks = {k: "PASS" for k in CHECKS}
    scope_ok = bool(scope and scope.get("status") == "ACTIVE" and scope.get("mission_id") == req["mission_id"]
                    and scope.get("scope_contract_id") == gov["governance_scope_contract_id"]
                    and scope.get("version") == gov["governance_scope_version"]
                    and scope.get("contract_hash") == gov["governance_scope_contract_hash"])
    checks["SCOPE"] = "PASS" if scope_ok else "FAIL"
    target_ok = matcher.target_in_scope(req["target"]["target_value"], (scope or {}).get("targets", [])).matched
    target_ok = target_ok and not matcher.target_in_scope(req["target"]["target_value"], [{**t,"allowed":True} for t in (scope or {}).get("targets", []) if not bool(t.get("allowed"))]).matched
    roe_ok, technique_ok, impact_ok, needs_review = True, True, True, req["authorization_requirement"]["human_review_required"]
    impact_order = {"NONE":0,"LOW":1,"MODERATE":2,"MEDIUM":2,"HIGH":3,"CRITICAL":4,"DESTRUCTIVE":5}
    sources = [ctx["mission_scope"], ctx["pentest_context"]["boundary"], ctx["pentest_context"]["task"]]
    for source in sources:
        scope_part = source["scope"]
        targets = [{**t, "allowed":True} for t in scope_part["targets"]]
        excluded = [{**t, "allowed":True} for t in scope_part.get("excluded_targets", [])]
        target_ok = target_ok and matcher.target_in_scope(req["target"]["target_value"], targets).matched and not matcher.target_in_scope(req["target"]["target_value"], excluded).matched
        roe = source.get("roe", ctx["pentest_context"]["boundary"]["roe"])
        action, technique = req["action"]["action_class"], req["action"]["technique"]
        roe_ok = roe_ok and action in roe["allowed_action_classes"] and action not in roe.get("prohibited_action_classes", [])
        technique_ok = technique_ok and technique not in roe.get("prohibited_techniques", []) and (not roe.get("allowed_techniques") or technique in roe["allowed_techniques"])
        needs_review = needs_review or action in roe.get("human_approval_required_for", [])
        for action_name, flag in (("CREDENTIAL_USE","credential_usage_allowed"),("PERSISTENCE","persistence_allowed"),("DESTRUCTIVE_ACTION","destructive_actions_allowed")):
            if action == action_name:
                roe_ok = roe_ok and roe.get(flag) is True
        limit = source["constraints"].get("impact_limit", source["constraints"].get("risk_threshold"))
        impact_ok = impact_ok and impact_order.get(req["parameters"]["estimated_impact"], 99) <= impact_order.get(limit, -1)
        window = roe.get("allowed_time_window")
        if window:
            roe_ok = roe_ok and instant(window["start_at"]) <= now < instant(window["end_at"])
    c = (constraint or {}).get("constraints", {})
    allowed = c.get("allowed_techniques")
    technique_ok = technique_ok and isinstance(allowed, list) and req["action"]["technique"] in allowed and req["action"]["technique"] not in c.get("prohibited_techniques", [])
    checks["TARGET"] = "PASS" if target_ok else "FAIL"
    checks["ROE"] = "PASS" if roe_ok else "FAIL"
    checks["TECHNIQUE"] = "PASS" if technique_ok else "FAIL"
    policy_ok = bool(policy and policy.get("status") == "ACTIVE" and policy.get("policy_set_id") == gov["policy_set_id"] == (scope or {}).get("policy_set_id")
                     and type(policy.get("version")) is int and policy["version"] >= req["authorization_requirement"]["policy_reference"]["policy_version"]
                     and constraint and str(constraint.get("effect", "DENY")) in {"ALLOW", "REVIEW"})
    for field, lower in (("effective_from", True),("effective_until",False)):
        value = (policy or {}).get(field)
        if value is not None:
            policy_ok = policy_ok and (instant(value) <= now if lower else now < instant(value))
    checks["POLICY"] = "PASS" if policy_ok else "FAIL"
    checks["RISK"] = "PASS" if impact_ok and "RISK_EXCEEDS_SCOPE_LIMIT" not in gate.reason_codes else "FAIL"
    submitted = instant(evaluation["submitted_at"])
    expiry_ok = now-timedelta(seconds=120) <= submitted <= now+timedelta(seconds=5)
    for field, lower in (("valid_from", True),("valid_until",False)):
        value = (scope or {}).get(field)
        if value is not None:
            expiry_ok = expiry_ok and (instant(value) <= now if lower else now < instant(value))
    checks["EXPIRY"] = "PASS" if expiry_ok else "FAIL"
    oldref = req["authorization_requirement"]["policy_reference"]
    old = service.repo.get_policy_decision(oldref["policy_decision_id"])
    revoked = bool(old and old.get("decision_status") == "REVOKED")
    revocation_ok = bool(old and old.get("mission_id") == req["mission_id"] and old.get("decision_hash") == oldref["policy_decision_hash"]
                         and old.get("decision_status") in {"ACTIVE", "EXPIRED"} and not revoked)
    checks["REVOCATION"] = "PASS" if revocation_ok else "FAIL"
    if "FAIL" in checks.values() or revoked or bool(emergency.get("active")):
        gate = GateResult(Decision.DENY, [*gate.reason_codes, *["EXECUTION_CHECK_FAILED:"+k for k,v in checks.items() if v=="FAIL"]], gate.constraints)
    elif gate.decision == Decision.ALLOW and needs_review and not human_approval_granted:
        gate = GateResult(Decision.REVIEW, [*gate.reason_codes,"EXECUTION_HUMAN_APPROVAL_REQUIRED"], gate.constraints, True)
        checks["ROE"] = "REVIEW"
    return gate, {"schema_version": SCHEMA, "evaluation_sha256": evaluation["integrity"]["canonical_sha256"],
        "nonce": evaluation["nonce"], "execution_id": req["execution_id"], "request_sha256": req["integrity"]["canonical_sha256"],
        "envelope_sha256": evaluation["envelope_sha256"], "context_sha256": digest(ctx), "checked_at": now.isoformat(),
        "checks": checks, "revoked": revoked, "emergency_stop": bool(emergency.get("active")),
        "human_approval_verified": bool(human_approval_granted)}
