"""Administrative archive/restore: visibility operations, never lifecycle transitions."""
from __future__ import annotations

class ArchiveConflict(Exception):
    pass

class ArchiveValidationError(Exception):
    pass

def validate_visibility(value):
    if not isinstance(value, str) or value.upper() not in {"ALL", "ACTIVE", "ARCHIVED"}:
        raise ArchiveValidationError("visibility must be ALL, ACTIVE or ARCHIVED")
    return value.upper()

def validate_archive_payload(value):
    if not isinstance(value, dict) or set(value) != {"expected_state_version", "actor_id", "reason", "idempotency_key"}:
        raise ArchiveValidationError("expected_state_version, actor_id, reason, idempotency_key are required")
    version = value["expected_state_version"]
    if type(version) is not int or version < 1:
        raise ArchiveValidationError("expected_state_version must be a positive integer")
    for key, minimum, maximum in (("actor_id", 3, 128), ("reason", 8, 1000), ("idempotency_key", 8, 128)):
        val = value[key]
        if not isinstance(val, str) or not minimum <= len(val.strip()) <= maximum:
            raise ArchiveValidationError(f"{key} length invalid")
        if any(ord(x) < 32 for x in val):
            raise ArchiveValidationError(f"{key} must not contain control characters")
    return {"expected_state_version": version, "actor_id": value["actor_id"].strip(),
            "reason": value["reason"].strip(), "idempotency_key": value["idempotency_key"].strip()}

def validate_restore_payload(value):
    """Restore uses the same optimistic-concurrency and audit contract as archive."""
    return validate_archive_payload(value)

def validate_purge_request_payload(value):
    if not isinstance(value, dict) or set(value) != {"reason", "idempotency_key"}:
        raise ArchiveValidationError("reason and idempotency_key are required")
    return _validate_purge_fields(value)

def validate_purge_approval_payload(value):
    required = {"request_id", "challenge", "approval_reason", "legal_hold_check", "external_dependency_check"}
    if not isinstance(value, dict) or set(value) != required:
        raise ArchiveValidationError("request_id, challenge, approval_reason, legal_hold_check and external_dependency_check are required")
    fields = _validate_purge_fields({"reason": value["approval_reason"], "idempotency_key": "approval-key-000"})
    request_id, challenge = value["request_id"], value["challenge"]
    if not isinstance(request_id, str) or not 8 <= len(request_id.strip()) <= 128:
        raise ArchiveValidationError("request_id length invalid")
    if not isinstance(challenge, str) or not 8 <= len(challenge.strip()) <= 256:
        raise ArchiveValidationError("challenge length invalid")
    if value["legal_hold_check"] != "CLEAR" or value["external_dependency_check"] != "CLEAR":
        raise ArchiveValidationError("purge approval requires explicit CLEAR legal-hold and external-dependency checks")
    return {"request_id": request_id.strip(), "challenge": challenge.strip(),
            "approval_reason": fields["reason"], "legal_hold_check": "CLEAR",
            "external_dependency_check": "CLEAR"}

def _validate_purge_fields(value):
    result = {}
    for key, minimum, maximum in (("reason", 12, 1000), ("idempotency_key", 8, 128)):
        val = value[key]
        if not isinstance(val, str) or not minimum <= len(val.strip()) <= maximum:
            raise ArchiveValidationError(f"{key} length invalid")
        if any(ord(x) < 32 for x in val):
            raise ArchiveValidationError(f"{key} must not contain control characters")
        result[key] = val.strip()
    return result
