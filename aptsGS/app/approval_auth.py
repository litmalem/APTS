"""Human identities and roles originate in a server-owned credential registry."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import re

from fastapi import Header, HTTPException

from .config import settings

AUTH_MODE = "SERVER_PRINCIPAL_REGISTRY_BEARER_SHA256_V1"
REGISTRY_SCHEMA = "apts-gss-human-approval-principals-v1"


class ApprovalAccessError(RuntimeError):
    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ApprovalPrincipal:
    principal_id: str
    roles: frozenset[str]
    principal_type: str


def authenticate_approval(authorization: str | None, registry_path: str) -> ApprovalPrincipal:
    if not authorization:
        raise ApprovalAccessError("HUMAN_APPROVAL_AUTHENTICATION_REQUIRED", 401)
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", parts[1]):
        raise ApprovalAccessError("INVALID_APPROVAL_CREDENTIAL", 401)
    if not registry_path:
        raise ApprovalAccessError("HUMAN_APPROVAL_PRINCIPALS_NOT_CONFIGURED", 503)
    try:
        data = json.loads(Path(registry_path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {"schema_version", "principals"}:
            raise ValueError("registry shape")
        if data["schema_version"] != REGISTRY_SCHEMA or not isinstance(data["principals"], list):
            raise ValueError("registry schema")
        ids, hashes = set(), set()
        for item in data["principals"]:
            if not isinstance(item, dict) or set(item) != {"principal_id", "principal_type", "roles", "token_sha256", "enabled"}:
                raise ValueError("principal shape")
            pid, token_hash, roles = item["principal_id"], item["token_sha256"], item["roles"]
            if not isinstance(pid, str) or not pid.strip() or pid != pid.strip() or len(pid) > 255:
                raise ValueError("principal id")
            if not isinstance(token_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", token_hash):
                raise ValueError("credential digest")
            if (not isinstance(roles, list) or not roles or len(set(roles)) != len(roles)
                    or any(not isinstance(r, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", r) for r in roles)):
                raise ValueError("principal roles")
            if item["principal_type"] not in {"HUMAN", "AGENT", "SERVICE"} or type(item["enabled"]) is not bool:
                raise ValueError("principal attributes")
            if pid in ids or token_hash in hashes:
                raise ValueError("duplicate principal or credential")
            ids.add(pid)
            hashes.add(token_hash)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ApprovalAccessError("HUMAN_APPROVAL_PRINCIPALS_UNAVAILABLE", 503) from exc

    digest = hashlib.sha256(parts[1].encode("ascii")).hexdigest()
    matched = None
    for item in data["principals"]:
        if hmac.compare_digest(digest, item["token_sha256"]):
            matched = item
    if matched is None or not matched["enabled"]:
        raise ApprovalAccessError("INVALID_APPROVAL_CREDENTIAL", 401)
    if matched["principal_type"] != "HUMAN":
        raise ApprovalAccessError("HUMAN_APPROVER_REQUIRED")
    return ApprovalPrincipal(matched["principal_id"], frozenset(matched["roles"]), matched["principal_type"])


def require_human_approver(authorization: str | None = Header(default=None)) -> ApprovalPrincipal:
    try:
        # Read on every request so disabling a principal takes effect immediately.
        return authenticate_approval(authorization, settings.approval_principals_file)
    except ApprovalAccessError as exc:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        raise HTTPException(status_code=exc.status_code, detail=str(exc), headers=headers) from exc
