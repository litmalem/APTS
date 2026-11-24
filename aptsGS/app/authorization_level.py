"""APTS-AL-025 — time-bounded autonomy-level authorization + incident downgrade.

GOV-PLANE contract (Fase 3). Implements the gap the traceability review flagged:
the platform's L1-L4 Graduated Autonomy level had *no* level-scoped, time-bounded
re-authorization and no incident downgrade path (only per-decision TTLs existed in
`config.py`). This module adds, as pure hash-bound contracts (no I/O, no DB, no
randomness — replayable and tamper-evident, matching the GSS sealing convention):

  * an **authorization-level grant**: who (approver) authorized operating up to which
    L1-L4 level, for which mission/scope, valid_from..valid_until (annual by default);
  * **evaluation**: a request for a level is fail-closed ELIGIBLE only if an ACTIVE,
    unexpired grant authorizes at least that level and no emergency stop is active;
  * **incident downgrade**: HALT/DEGRADE/ESCALATE/TERMINATE/EMERGENCY_STOP lower the
    ceiling and require a fresh human re-authorization to raise it again;
  * **re-authorization**: supersedes an expired/downgraded grant with a new one;
  * a hash-bound **transition record** (ISSUE/DOWNGRADE/REAUTHORIZE/EXPIRE/REVOKE)
    giving tamper-evident level lineage.

No decision here mints authorization or executes; Stage 6 remains the only execution
authority (semantics carry the non-execution invariants, like the pentest subsystem).

INTEGRATION SEAM (not force-wired into the sealed Stage-6 dispatch schema, to avoid a
risky migration of the hash-bound evaluation contract): `level_gate_reason_codes()`
returns DENY reason codes ready to fold into `GovernanceService`'s dispatch gate right
beside the existing `SCOPE_MISSION_MISMATCH` / `NO_ACTIVE_POLICY_SET` guards, once a
repo-backed grant store + a migration are added. See LANGKAH_PERBAIKAN doc Fase 3.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from .utils import sha256_json

SCHEMA_GRANT = "apts-gss-authorization-level-grant-v1"
SCHEMA_DECISION = "apts-gss-authorization-level-decision-v1"
SCHEMA_TRANSITION = "apts-gss-authorization-level-transition-v1"
GRANT_DOMAIN = "APTS_AL025_AUTHORIZATION_LEVEL_GRANT_V1"
DECISION_DOMAIN = "APTS_AL025_AUTHORIZATION_LEVEL_DECISION_V1"
TRANSITION_DOMAIN = "APTS_AL025_AUTHORIZATION_LEVEL_TRANSITION_V1"

# Platform Graduated Autonomy levels L1..L4 (L4 = autonomous). NOT the pentest
# subsystem's L0-L3 per-capability PROPOSAL_GATING_LEVEL scale (see Fase 1).
LEVELS = {1: "L1", 2: "L2", 3: "L3", 4: "L4"}
MIN_LEVEL, MAX_LEVEL = 1, 4

GRANT_ACTIVE = "ACTIVE"
GRANT_DOWNGRADED = "DOWNGRADED"
GRANT_EXPIRED = "EXPIRED"
GRANT_REVOKED = "REVOKED"
GRANT_SUPERSEDED = "SUPERSEDED"

INCIDENT_SIGNALS = {"HALT", "DEGRADE", "ESCALATE", "TERMINATE", "EMERGENCY_STOP"}

# Every decision is advisory wrt execution: it never authorizes or actuates.
_NO_EXECUTION_SEMANTICS = {
    "decision_is_authorization": False,
    "authorization_minted": False,
    "execution_started": False,
    "tool_invocation_performed": False,
    "external_network_io_performed": False,
    "target_actuation": False,
}


class AuthorizationLevelError(ValueError):
    """Raised on malformed input; callers must treat it as fail-closed (deny)."""


# --- sealing (matches the GSS execution-revalidation integrity convention) ----

def _seal(core: Mapping[str, Any], *, domain: str) -> dict[str, Any]:
    body = {k: v for k, v in core.items() if k != "integrity"}
    return {
        **body,
        "integrity": {
            "algorithm": "SHA-256",
            "canonicalization": "UTF8_SORTED_JSON_V1",
            "hash_domain": domain,
            "canonical_sha256": sha256_json({"hash_domain": domain, "core": body}),
        },
    }


def _verify(record: Mapping[str, Any], *, domain: str) -> bool:
    if not isinstance(record, Mapping):
        return False
    integrity = record.get("integrity")
    if not isinstance(integrity, Mapping) or integrity.get("hash_domain") != domain:
        return False
    body = {k: v for k, v in record.items() if k != "integrity"}
    expected = {
        "algorithm": "SHA-256",
        "canonicalization": "UTF8_SORTED_JSON_V1",
        "hash_domain": domain,
        "canonical_sha256": sha256_json({"hash_domain": domain, "core": body}),
    }
    return dict(integrity) == expected


def _instant(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value:
        raise AuthorizationLevelError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuthorizationLevelError(f"{field} is not a valid timestamp") from exc
    if parsed.tzinfo is None:
        raise AuthorizationLevelError(f"{field} requires a timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _check_level(level: Any, field: str) -> int:
    if isinstance(level, bool) or not isinstance(level, int) or level not in LEVELS:
        raise AuthorizationLevelError(f"{field} must be an integer in {sorted(LEVELS)}")
    return level


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthorizationLevelError(f"{field} must be a non-empty string")
    return value


# --- grant lifecycle ----------------------------------------------------------

def build_authorization_level_grant(
    *,
    grant_id: str,
    mission_id: str,
    scope_contract_id: str,
    authorized_level: int,
    approver: str,
    authorization_reference: str,
    valid_from: Any,
    valid_until: Any,
    status: str = GRANT_ACTIVE,
    requires_reauthorization: bool = False,
    predecessor_grant_sha256: str | None = None,
) -> dict[str, Any]:
    """Build a sealed, time-bounded level grant. Fail-closed on bad input."""
    level = _check_level(authorized_level, "authorized_level")
    start = _instant(valid_from, "valid_from")
    end = _instant(valid_until, "valid_until")
    if end <= start:
        raise AuthorizationLevelError("valid_until must be after valid_from")
    if status not in {GRANT_ACTIVE, GRANT_DOWNGRADED, GRANT_EXPIRED, GRANT_REVOKED, GRANT_SUPERSEDED}:
        raise AuthorizationLevelError("unsupported grant status")
    if predecessor_grant_sha256 is not None:
        _require_str(predecessor_grant_sha256, "predecessor_grant_sha256")
    core = {
        "schema_version": SCHEMA_GRANT,
        "grant_id": _require_str(grant_id, "grant_id"),
        "mission_id": _require_str(mission_id, "mission_id"),
        "scope_contract_id": _require_str(scope_contract_id, "scope_contract_id"),
        "authorized_level": level,
        "authorized_level_name": LEVELS[level],
        "approver": _require_str(approver, "approver"),
        "authorization_reference": _require_str(authorization_reference, "authorization_reference"),
        "valid_from": _iso(start),
        "valid_until": _iso(end),
        "status": status,
        "requires_reauthorization": bool(requires_reauthorization),
        "predecessor_grant_sha256": predecessor_grant_sha256,
    }
    return _seal(core, domain=GRANT_DOMAIN)


def verify_authorization_level_grant(grant: Mapping[str, Any]) -> bool:
    return _verify(grant, domain=GRANT_DOMAIN)


def _grant_sha256(grant: Mapping[str, Any]) -> str:
    return grant["integrity"]["canonical_sha256"]


def _transition(
    *,
    transition_type: str,
    from_grant: Mapping[str, Any] | None,
    to_grant: Mapping[str, Any] | None,
    signal: str | None,
    approver: str | None,
    at: datetime,
    reason: str,
) -> dict[str, Any]:
    core = {
        "schema_version": SCHEMA_TRANSITION,
        "transition_type": transition_type,
        "from_grant_sha256": _grant_sha256(from_grant) if from_grant else None,
        "to_grant_sha256": _grant_sha256(to_grant) if to_grant else None,
        "from_level": from_grant["authorized_level"] if from_grant else None,
        "to_level": to_grant["authorized_level"] if to_grant else None,
        "signal": signal,
        "approver": approver,
        "reason": reason,
        "at": _iso(at),
    }
    return _seal(core, domain=TRANSITION_DOMAIN)


def verify_authorization_level_transition(transition: Mapping[str, Any]) -> bool:
    return _verify(transition, domain=TRANSITION_DOMAIN)


def downgrade_on_incident(
    grant: Mapping[str, Any],
    *,
    signal: str,
    to_level: int,
    now: datetime,
    transition_id: str,
    downgraded_grant_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Lower the authorized ceiling in response to an incident signal.

    Returns (downgraded_grant, transition). The new grant keeps the original
    validity window but at ``to_level`` (which must be strictly lower) and sets
    ``requires_reauthorization=True`` so raising the level again needs a fresh
    human-approved grant via :func:`reauthorize_level`. Fail-closed on bad input.
    """
    if not verify_authorization_level_grant(grant):
        raise AuthorizationLevelError("grant integrity verification failed")
    if signal not in INCIDENT_SIGNALS:
        raise AuthorizationLevelError(f"signal must be one of {sorted(INCIDENT_SIGNALS)}")
    target = _check_level(to_level, "to_level")
    current = int(grant["authorized_level"])
    if target >= current:
        raise AuthorizationLevelError("incident downgrade must strictly lower the level")
    downgraded = build_authorization_level_grant(
        grant_id=downgraded_grant_id,
        mission_id=grant["mission_id"],
        scope_contract_id=grant["scope_contract_id"],
        authorized_level=target,
        approver=grant["approver"],
        authorization_reference=grant["authorization_reference"],
        valid_from=grant["valid_from"],
        valid_until=grant["valid_until"],
        status=GRANT_ACTIVE,
        requires_reauthorization=True,
        predecessor_grant_sha256=_grant_sha256(grant),
    )
    transition = _transition(
        transition_type="DOWNGRADE",
        from_grant=grant,
        to_grant=downgraded,
        signal=signal,
        approver=None,
        at=_instant(now, "now"),
        reason=f"incident {signal} lowered level {LEVELS[current]} -> {LEVELS[target]}",
    )
    return downgraded, transition


def reauthorize_level(
    previous_grant: Mapping[str, Any],
    *,
    approver: str,
    authorized_level: int,
    authorization_reference: str,
    valid_from: Any,
    valid_until: Any,
    now: datetime,
    grant_id: str,
    transition_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Issue a fresh ACTIVE grant that supersedes an expired/downgraded one.

    This is the explicit human re-authorization path (annual renewal or recovery
    after an incident downgrade). Requires a human ``approver``. Fail-closed.
    """
    if not verify_authorization_level_grant(previous_grant):
        raise AuthorizationLevelError("previous grant integrity verification failed")
    prev_status = previous_grant["status"]
    if prev_status not in {GRANT_DOWNGRADED, GRANT_EXPIRED, GRANT_ACTIVE, GRANT_SUPERSEDED}:
        raise AuthorizationLevelError("previous grant is not re-authorizable")
    new_grant = build_authorization_level_grant(
        grant_id=grant_id,
        mission_id=previous_grant["mission_id"],
        scope_contract_id=previous_grant["scope_contract_id"],
        authorized_level=_check_level(authorized_level, "authorized_level"),
        approver=_require_str(approver, "approver"),
        authorization_reference=_require_str(authorization_reference, "authorization_reference"),
        valid_from=valid_from,
        valid_until=valid_until,
        status=GRANT_ACTIVE,
        requires_reauthorization=False,
        predecessor_grant_sha256=_grant_sha256(previous_grant),
    )
    transition = _transition(
        transition_type="REAUTHORIZE",
        from_grant=previous_grant,
        to_grant=new_grant,
        signal=None,
        approver=approver,
        at=_instant(now, "now"),
        reason=f"human re-authorization to {LEVELS[new_grant['authorized_level']]}",
    )
    return new_grant, transition


# --- evaluation ---------------------------------------------------------------

def _rule(rule_id: str, status: str, reason: str) -> dict[str, Any]:
    return {"rule_id": rule_id, "status": status, "reason": reason}


def evaluate_level_authorization(
    grant: Mapping[str, Any] | None,
    *,
    requested_level: int,
    now: datetime,
    emergency_active: bool = False,
) -> dict[str, Any]:
    """Fail-closed decision: may the platform operate at ``requested_level`` now?

    ELIGIBLE only if a tamper-intact, ACTIVE, unexpired grant authorizes at least
    the requested level and no emergency stop is active. A missing grant is denied.
    """
    requested = _check_level(requested_level, "requested_level")
    at = _instant(now, "now")
    rules: list[dict[str, Any]] = []

    integrity_ok = bool(grant) and verify_authorization_level_grant(grant)
    rules.append(_rule("GRANT-INTEGRITY", "PASS" if integrity_ok else "FAIL",
                       "grant must be present and tamper-intact"))

    status_ok = integrity_ok and grant["status"] == GRANT_ACTIVE
    rules.append(_rule("GRANT-ACTIVE", "PASS" if status_ok else "FAIL",
                       "grant status must be ACTIVE"))

    window_ok = False
    if integrity_ok:
        start = _instant(grant["valid_from"], "valid_from")
        end = _instant(grant["valid_until"], "valid_until")
        window_ok = start <= at < end
    rules.append(_rule("GRANT-WINDOW", "PASS" if window_ok else "FAIL",
                       "now must be within [valid_from, valid_until)"))

    ceiling_ok = integrity_ok and requested <= int(grant["authorized_level"])
    rules.append(_rule("LEVEL-CEILING", "PASS" if ceiling_ok else "FAIL",
                       "requested level must not exceed the authorized level"))

    emergency_ok = not bool(emergency_active)
    rules.append(_rule("EMERGENCY-STOP", "PASS" if emergency_ok else "FAIL",
                       "no emergency stop may be active"))

    failed = [r for r in rules if r["status"] == "FAIL"]
    status = "INELIGIBLE" if failed else "ELIGIBLE"
    core = {
        "schema_version": SCHEMA_DECISION,
        "requested_level": requested,
        "requested_level_name": LEVELS[requested],
        "authorized_level": int(grant["authorized_level"]) if integrity_ok else None,
        "grant_id": grant["grant_id"] if integrity_ok else None,
        "grant_sha256": _grant_sha256(grant) if integrity_ok else None,
        "evaluated_at": _iso(at),
        "status": status,
        "fail_closed": True,
        "rule_results": rules,
        "failed_rule_ids": [r["rule_id"] for r in failed],
        "requires_reauthorization": bool(grant["requires_reauthorization"]) if integrity_ok else True,
        "semantics": dict(_NO_EXECUTION_SEMANTICS),
    }
    return _seal(core, domain=DECISION_DOMAIN)


def verify_level_authorization_decision(decision: Mapping[str, Any]) -> bool:
    return _verify(decision, domain=DECISION_DOMAIN)


def level_gate_reason_codes(
    grant: Mapping[str, Any] | None,
    *,
    requested_level: int,
    now: datetime,
    emergency_active: bool = False,
) -> list[str]:
    """Integration seam for GovernanceService dispatch: DENY reason codes (empty = allow).

    Fold beside the existing `SCOPE_MISSION_MISMATCH` / `NO_ACTIVE_POLICY_SET`
    guards once a repo-backed grant store exists. Never grants authority by itself.
    """
    decision = evaluate_level_authorization(
        grant, requested_level=requested_level, now=now, emergency_active=emergency_active
    )
    if decision["status"] == "ELIGIBLE":
        return []
    return [f"LEVEL_AUTHORIZATION_FAILED:{rid}" for rid in decision["failed_rule_ids"]]


__all__ = [
    "AuthorizationLevelError", "LEVELS", "MIN_LEVEL", "MAX_LEVEL", "INCIDENT_SIGNALS",
    "GRANT_ACTIVE", "GRANT_DOWNGRADED", "GRANT_EXPIRED", "GRANT_REVOKED", "GRANT_SUPERSEDED",
    "build_authorization_level_grant", "verify_authorization_level_grant",
    "evaluate_level_authorization", "verify_level_authorization_decision",
    "downgrade_on_incident", "reauthorize_level", "verify_authorization_level_transition",
    "level_gate_reason_codes",
]
