"""Strict schema for WPT-to-Mission governed job intake.

This contract only admits a request for governance. It never authorizes Stage 6
execution and does not contain caller-supplied scope, limits, or credentials.
"""
from __future__ import annotations

from typing import Any

from .execution_contract import (
    ExecutionRequestValidationError, require_id, require_text,
)

WPT_INTAKE_SCHEMA_VERSION = "apts-wpt-governed-intake-v1"
WPT_INTAKE_SCHEMA_VERSION_V2 = "apts-wpt-governed-intake-v2"
WPT_PROFILE_IDS = {
    "fingerprinting": "wpt.fingerprinting.v1",
    "enumeration": "wpt.bounded-enumeration.v1",
}


def normalize_wpt_intake(payload: Any) -> dict[str, Any]:
    base_fields = {"schema_version", "intake_id", "idempotency_key", "mission_id",
                   "task_id", "target", "profile"}
    provenance_fields = {"recon_target_key", "recon_target_sha256", "recon_target_status", "target_is_observed"}
    if not isinstance(payload, dict):
        raise ExecutionRequestValidationError("WPT intake must be an object")
    version = payload.get("schema_version")
    fields = base_fields | provenance_fields if version == WPT_INTAKE_SCHEMA_VERSION_V2 else base_fields
    if version in ('apts-wpt-governed-intake-v3','apts-wpt-governed-intake-v4'):
        fields = base_fields | {'enumeration_context'}
    if set(payload) != fields:
        raise ExecutionRequestValidationError(
            "WPT intake fields do not match its declared schema version"
        )
    if version not in {WPT_INTAKE_SCHEMA_VERSION, WPT_INTAKE_SCHEMA_VERSION_V2, 'apts-wpt-governed-intake-v3', 'apts-wpt-governed-intake-v4'}:
        raise ExecutionRequestValidationError("unsupported WPT intake schema_version")
    if payload["profile"] not in WPT_PROFILE_IDS:
        raise ExecutionRequestValidationError("profile must be fingerprinting or enumeration")
    target = payload["target"]
    if not isinstance(target, dict) or set(target) != {"target_type", "target_value"}:
        raise ExecutionRequestValidationError("target must contain exactly target_type and target_value")
    target_type = require_text(target["target_type"], "target.target_type", 16).upper()
    if target_type not in {"URL", "IP", "HOST", "DOMAIN"}:
        raise ExecutionRequestValidationError("target.target_type is unsupported for WPT")
    target_value = require_text(target["target_value"], "target.target_value", 2048)
    result = {
        "schema_version": version,
        "intake_id": require_id(payload["intake_id"], "intake_id", "wptreq-"),
        "idempotency_key": require_id(payload["idempotency_key"], "idempotency_key", "idem-"),
        "mission_id": require_id(payload["mission_id"], "mission_id", "mission-gmo-"),
        "task_id": require_id(payload["task_id"], "task_id", "ptask-"),
        "target": {"target_type": target_type, "target_value": target_value},
        "profile": payload["profile"],
    }
    if version in ('apts-wpt-governed-intake-v3','apts-wpt-governed-intake-v4'):
        from .enumeration_followup_contract import normalize_context
        if payload['profile'] != 'enumeration':
            raise ExecutionRequestValidationError('CTI follow-up profile must be enumeration')
        result['enumeration_context'] = normalize_context(payload['enumeration_context'])
        if (version.endswith('-v4')) != ('cpe_candidates' in result['enumeration_context']):
            raise ExecutionRequestValidationError('CTI context fields differ from schema version')
    if version == WPT_INTAKE_SCHEMA_VERSION_V2:
        key = require_id(payload["recon_target_key"], "recon_target_key", "reconscope-")
        digest = require_text(payload["recon_target_sha256"], "recon_target_sha256", 64)
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ExecutionRequestValidationError("recon_target_sha256 must be a lowercase SHA-256 digest")
        if (payload["recon_target_status"] != "READY_FOR_COLLECTION"
                or payload["target_is_observed"] is not False):
            raise ExecutionRequestValidationError("WPT intake provenance must identify an unobserved Recon target")
        result.update(recon_target_key=key, recon_target_sha256=digest,
                      recon_target_status="READY_FOR_COLLECTION", target_is_observed=False)
    return result
