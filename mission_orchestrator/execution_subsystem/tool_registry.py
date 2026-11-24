"""Server-owned, immutable primitive registry. No executable/plugin registration API."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .execution_contract import ExecutionSourceRejected, sha256_hex


@dataclass(frozen=True)
class ToolAdapter:
    adapter_id: str
    family: str
    operation: str
    capability_id: str
    action_class: str
    technique: str
    target_types: tuple[str, ...]
    default_port: int
    credential_support: bool = False

    def definition(self):
        value = asdict(self)
        value["target_types"] = list(self.target_types)
        return value


ADAPTERS = (
    ToolAdapter("scanner.tcp-connect.v1", "SCANNER", "TCP_CONNECT", "reconnaissance", "TARGET_RECON",
                "TCP_CONNECT_SCAN", ("URL", "IP", "HOST", "DOMAIN"), 80),
    ToolAdapter("network.tcp-banner.v1", "NETWORK_TOOL", "TCP_BANNER", "enumeration", "TARGET_RECON",
                "TCP_BANNER_READ", ("URL", "IP", "HOST", "DOMAIN"), 80),
    ToolAdapter("web.http-head.v1", "WEB_TESTING", "HTTP_HEAD", "validation", "VULNERABILITY_VALIDATION",
                "HTTP_HEADER_INSPECTION", ("URL", "IP", "HOST", "DOMAIN"), 80, True),
    ToolAdapter("validation.version-configuration.v1", "EXPLOIT_VALIDATION", "HTTP_HEAD", "exploitation",
                "VULNERABILITY_VALIDATION", "SAFE_VERSION_CONFIGURATION_CONFIRMATION",
                ("URL", "IP", "HOST", "DOMAIN"), 80, True),
    ToolAdapter("evidence.http-metadata.v1", "EVIDENCE_COLLECTOR", "HTTP_HEAD", "validation",
                "VULNERABILITY_VALIDATION", "HTTP_RESPONSE_METADATA", ("URL", "IP", "HOST", "DOMAIN"), 80, True),
    ToolAdapter("web.profile-fingerprint.v1", "WEB_PROFILE", "WEB_PROFILE_FINGERPRINT",
                "web_technology_fingerprinting", "TARGET_RECON", "WEB_TECHNOLOGY_FINGERPRINT",
                ("URL",), 80, False),
    ToolAdapter("web.profile-enumeration.v1", "WEB_PROFILE", "WEB_PROFILE_ENUMERATION",
                "web_surface_enumeration", "TARGET_RECON", "BOUNDED_WEB_SURFACE_ENUMERATION",
                ("URL",), 80, False),
)

# Both profiles execute only through the fixed Stage 6 broker and parser worker.
WPT_CAPABILITY_PROFILES = (
    {
        "profile_id": "wpt.fingerprinting.v1",
        "execution_status": "EXECUTABLE",
        "action": {"action_class": "TARGET_RECON", "capability_id": "web_technology_fingerprinting",
                   "technique": "WEB_TECHNOLOGY_FINGERPRINT"},
        "adapter_id": "web.profile-fingerprint.v1",
        "request_schema": {
            "type": "object", "additionalProperties": False,
            "required": ["target", "profile"],
            "properties": {"target": {"type": "string", "maxLength": 2048},
                           "profile": {"const": "fingerprinting"}},
        },
        "result_schema": {
            "type": "object", "required": ["schema_version", "target", "mode", "observations", "scan_metrics"],
            "properties": {"schema_version": {"const": "web-technology-observation-v4"},
                           "target": {"type": "string"}, "mode": {"const": "fingerprinting"},
                           "observations": {"type": "array"}, "technology_findings": {"type": "array"},
                           "scan_metrics": {"type": "object", "required": ["scan_status", "requests_planned",
                               "responses_received", "response_rate_percent", "request_errors"]}},
        },
        "limits": {"max_requests": 6, "max_response_bytes": 393216,
                   "max_concurrency": 1, "timeout_seconds": 15, "redirects": "SAME_ORIGIN_SCOPE_PREFIX_MAX_2"},
        "required_evidence": ["sealed_stage6_evidence", "target_binding", "mission_task_binding",
                              "action_capability_binding", "execution_id", "result_sha256"],
    },
    {
        "profile_id": "wpt.bounded-enumeration.v1",
        "execution_status": "EXECUTABLE",
        "action": {"action_class": "TARGET_RECON", "capability_id": "web_surface_enumeration",
                   "technique": "BOUNDED_WEB_SURFACE_ENUMERATION"},
        "adapter_id": "web.profile-enumeration.v1",
        "request_schema": {
            "type": "object", "additionalProperties": False,
            "required": ["target", "profile"],
            "properties": {"target": {"type": "string", "maxLength": 2048},
                           "profile": {"const": "enumeration"}},
        },
        "result_schema": {
            "type": "object", "required": ["schema_version", "target", "mode", "observations", "scan_metrics",
                                             "surface_candidates"],
            "properties": {"schema_version": {"const": "web-technology-observation-v4"},
                           "target": {"type": "string"}, "mode": {"const": "enumeration"},
                           "observations": {"type": "array"}, "surface_candidates": {"type": "array"},
                           "scan_metrics": {"type": "object", "required": ["scan_status", "requests_planned",
                               "responses_received", "response_rate_percent", "request_errors"]}},
        },
        "limits": {"max_requests": 9, "max_response_bytes": 262144,
                   "max_concurrency": 1, "timeout_seconds": 30, "redirects": "DENY"},
        "required_evidence": ["sealed_stage6_evidence", "target_binding", "mission_task_binding",
                              "action_capability_binding", "execution_id", "result_sha256"],
    },
)


def wpt_capability_profile_definitions():
    """Return copies of immutable, server-owned WPT capability contracts."""
    from copy import deepcopy
    return deepcopy(list(WPT_CAPABILITY_PROFILES))


def adapter_definitions():
    return [adapter.definition() for adapter in ADAPTERS]


def registry_sha256():
    return sha256_hex(adapter_definitions())


def legacy_adapter_definitions():
    """Historical Stage 6.4 contract; additive adapters never rewrite its hash."""
    return [a.definition() for a in ADAPTERS if a.operation != 'WEB_PROFILE_ENUMERATION']


def legacy_registry_sha256():
    return sha256_hex(legacy_adapter_definitions())


def select_adapter(request):
    action = request["action"]
    candidates = [a for a in ADAPTERS if
                  (a.capability_id, a.action_class, a.technique) ==
                  (action["capability_id"], action["action_class"], action["technique"])
                  and request["target"]["target_type"] in a.target_types]
    if len(candidates) != 1:
        raise ExecutionSourceRejected("NO_EXACT_AUTHORIZED_TOOL_ADAPTER")
    if request["parameters"]["estimated_impact"] not in {"NONE", "LOW"}:
        raise ExecutionSourceRejected("ADAPTER_IMPACT_LIMIT_EXCEEDED")
    return candidates[0]
