from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urlparse


@dataclass(frozen=True)
class ScopeMatch:
    matched: bool
    reason: str
    matched_target_id: Optional[str] = None


def _normalize_host(value: str) -> str:
    value = (value or "").strip().lower().rstrip(".")
    if "://" in value:
        parsed = urlparse(value)
        return (parsed.hostname or "").lower().rstrip(".")
    if "/" in value and not value.startswith("/"):
        # May be CIDR; caller handles CIDR before this branch matters.
        return value
    return value.split(":", 1)[0]


class ScopeMatcher:
    """Deterministic target/source boundary matcher."""

    def subsystem_capability_allowed(self, resource_value: str, action_constraint: Optional[dict]) -> ScopeMatch:
        """Match an exact subsystem capability from an explicit delegation constraint.

        Delegation resources are identifiers such as ``PENTEST:pentest.recon``;
        they are never interpreted as URLs or target names.
        """
        resource = (resource_value or "").strip()
        if not resource or resource.count(":") != 1:
            return ScopeMatch(False, "INVALID_SUBSYSTEM_CAPABILITY")
        subsystem_id, capability_id = resource.split(":", 1)
        if (not subsystem_id or subsystem_id != subsystem_id.upper()
                or not capability_id or any(ch.isspace() for ch in resource)):
            return ScopeMatch(False, "INVALID_SUBSYSTEM_CAPABILITY")
        constraints = (action_constraint or {}).get("constraints") or {}
        allowed = constraints.get("allowed_capabilities")
        if not isinstance(allowed, list) or resource not in allowed:
            return ScopeMatch(False, "SUBSYSTEM_CAPABILITY_NOT_ALLOWLISTED")
        return ScopeMatch(True, "SUBSYSTEM_CAPABILITY_ALLOWLIST_MATCH")

    def target_in_scope(self, resource_value: str, targets: Iterable[dict]) -> ScopeMatch:
        resource = (resource_value or "").strip()
        if not resource:
            return ScopeMatch(False, "EMPTY_RESOURCE")

        resource_host = _normalize_host(resource)
        try:
            resource_ip = ipaddress.ip_address(resource_host)
        except ValueError:
            resource_ip = None

        for row in targets:
            if not bool(row.get("allowed")):
                continue
            target_type = str(row.get("target_type") or "").upper()
            target_value = str(row.get("target_value") or "").strip()
            target_id = row.get("scope_target_id")

            if target_type == "CIDR":
                try:
                    network = ipaddress.ip_network(target_value, strict=False)
                    if resource_ip is not None and resource_ip in network:
                        return ScopeMatch(True, "CIDR_MATCH", target_id)
                except ValueError:
                    continue

            elif target_type == "IP":
                if resource_host == _normalize_host(target_value):
                    return ScopeMatch(True, "IP_MATCH", target_id)

            elif target_type in {"HOST", "DOMAIN"}:
                target_host = _normalize_host(target_value)
                if target_host.startswith("*."):
                    suffix = target_host[1:]
                    if resource_host.endswith(suffix) and resource_host != suffix.lstrip("."):
                        return ScopeMatch(True, "DOMAIN_WILDCARD_MATCH", target_id)
                elif resource_host == target_host:
                    return ScopeMatch(True, "HOST_MATCH", target_id)

            elif target_type == "URL":
                if resource.rstrip("/") == target_value.rstrip("/"):
                    return ScopeMatch(True, "URL_MATCH", target_id)

            elif target_type in {"APPLICATION", "OTHER"}:
                if resource == target_value:
                    return ScopeMatch(True, "EXACT_MATCH", target_id)

        return ScopeMatch(False, "RESOURCE_OUT_OF_SCOPE")

    def source_allowed(self, source_id: str, sources: Iterable[dict]) -> ScopeMatch:
        wanted = (source_id or "").strip().lower()
        for row in sources:
            if not bool(row.get("allowed")):
                continue
            current = str(row.get("source_id") or "").strip().lower()
            if wanted == current:
                return ScopeMatch(True, "SOURCE_ALLOWLIST_MATCH", row.get("scope_source_id"))
        return ScopeMatch(False, "SOURCE_NOT_ALLOWLISTED")
