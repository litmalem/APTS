"""Operator-configured leases; secrets never cross the worker or audit boundary."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re

from .authorization_contract import parse_time
from .execution_contract import ExecutionSourceRejected, ExecutionRequestValidationError, require_id


@dataclass(frozen=True, repr=False)
class CredentialLease:
    lease_id: str
    mission_id: str
    execution_id: str
    target: dict
    adapter_id: str
    issued_at: str
    expires_at: str
    secret_environment: str
    revoked: bool


class CredentialLeaseStore:
    def __init__(self, config_path=None):
        self.config_path = None if config_path is None else Path(config_path).resolve()

    def acquire(self, lease_id, request, adapter, now):
        if self.config_path is None:
            raise ExecutionSourceRejected("CREDENTIAL_LEASE_UNAVAILABLE")
        try:
            def unique(pairs):
                out = {}
                for key, value in pairs:
                    if key in out:
                        raise ValueError("duplicate")
                    out[key] = value
                return out
            if self.config_path.stat().st_size > 65536:
                raise ValueError("oversized")
            records = json.loads(self.config_path.read_text(encoding="utf-8"), object_pairs_hook=unique)
            if not isinstance(records, list) or len(records) > 100:
                raise ValueError("invalid lease store")
            leases = [CredentialLease(**item) for item in records]
            if len({l.lease_id for l in leases}) != len(leases):
                raise ValueError("duplicate lease")
            lease = next((l for l in leases if l.lease_id == lease_id), None)
            if lease is None:
                raise ValueError("missing")
            require_id(lease.lease_id, "lease_id", "credlease-")
            if (type(lease.revoked) is not bool or lease.revoked
                    or lease.mission_id != request["mission_id"] or lease.execution_id != request["execution_id"]
                    or lease.target != request["target"] or lease.adapter_id != adapter.adapter_id
                    or not parse_time(lease.issued_at, "issued_at") <= now < parse_time(lease.expires_at, "expires_at")
                    or not re.fullmatch(r"APTS_CRED_[A-Z0-9_]{1,80}", lease.secret_environment)):
                raise ValueError("invalid scope/validity")
            secret = os.environ.get(lease.secret_environment)
            if not secret or len(secret) > 4096 or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", secret):
                raise ValueError("invalid secret")
            metadata = {"lease_id": lease.lease_id, "issued_at": lease.issued_at, "expires_at": lease.expires_at,
                        "scope_verified": True, "secret_persisted": False}
            return "Bearer " + secret, metadata
        except (OSError, ValueError, TypeError, KeyError, ExecutionRequestValidationError) as exc:
            raise ExecutionSourceRejected("CREDENTIAL_LEASE_INVALID_OR_REVOKED") from exc
