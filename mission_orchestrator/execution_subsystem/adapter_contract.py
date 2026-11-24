from __future__ import annotations

from .execution_contract import (
    ExecutionRequestValidationError, canonical_json, require_id, require_object, require_sha,
    require_text, sha256_hex, verify_integrity, with_integrity,
)
from .gateway_contract import EXECUTION_GATEWAY_CONTROL_VERSION, canonical_execution_gateway_contract
from .tool_registry import adapter_definitions, registry_sha256, wpt_capability_profile_definitions, legacy_adapter_definitions, legacy_registry_sha256
from .adapter_policy import RUNTIME_CONSTRAINTS, DEFAULT_LIMITS

ADAPTER_CONTROL_VERSION = "stage6.4-authorized-tool-adapters-sandboxing"
ADAPTER_CONTRACT_SCHEMA = "apts-stage6.4-authorized-tool-adapters-sandboxing-v1"
ADAPTER_INTAKE_SCHEMA = "apts-execution-adapter-intake-v1"
CLAIM_DOMAIN = "APTS_EXECUTION_ADAPTER_CLAIM_V1"
RESULT_DOMAIN = "APTS_EXECUTION_ADAPTER_RESULT_V1"
CONTRACT_DOMAIN = "APTS_STAGE6_4_AUTHORIZED_ADAPTERS_SANDBOXING_CONTRACT_V1"
INTAKE_FIELDS = {"schema_version", "invocation_request_id", "idempotency_key", "execution_id", "envelope_sha256", "requested_by"}


def normalize_adapter_intake(payload):
    obj = require_object(payload, INTAKE_FIELDS, "adapter intake")
    if obj["schema_version"] != ADAPTER_INTAKE_SCHEMA:
        raise ExecutionRequestValidationError("unsupported adapter intake schema")
    return {"schema_version": ADAPTER_INTAKE_SCHEMA,
            "invocation_request_id": require_id(obj["invocation_request_id"], "invocation_request_id", "toolreq-"),
            "idempotency_key": require_id(obj["idempotency_key"], "idempotency_key"),
            "execution_id": require_id(obj["execution_id"], "execution_id", "exec-"),
            "envelope_sha256": require_sha(obj["envelope_sha256"], "envelope_sha256"),
            "requested_by": require_text(obj["requested_by"], "requested_by", 200)}


def adapter_intake_json_schema():
    from .execution_contract import ID_PATTERN, SHA_PATTERN
    properties = {k: {"type": "string", "pattern": ID_PATTERN} for k in INTAKE_FIELDS}
    properties.update({"schema_version": {"const": ADAPTER_INTAKE_SCHEMA},
                       "envelope_sha256": {"type": "string", "pattern": SHA_PATTERN},
                       "requested_by": {"type": "string", "minLength": 1, "maxLength": 200}})
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
            "additionalProperties": False, "required": sorted(INTAKE_FIELDS), "properties": properties}


def canonical_adapter_contract():
    return with_integrity({"schema_version": ADAPTER_CONTRACT_SCHEMA, "control_version": ADAPTER_CONTROL_VERSION,
        "predecessor": {"control": EXECUTION_GATEWAY_CONTROL_VERSION,
                        "contract_sha256": canonical_execution_gateway_contract()["integrity"]["canonical_sha256"]},
        "repository": {"migration_level": 4, "mission_migration": 53, "pentest_migration": 16,
                       "immutable_claims_and_results": True},
        "adapters": legacy_adapter_definitions(), "registry_sha256": legacy_registry_sha256(),
        "registered_capability_profiles": legacy_wpt_capability_profiles(),
        "policy": {"runtime_constraints": list(RUNTIME_CONSTRAINTS), "default_limits": dict(DEFAULT_LIMITS),
                   "unknown_controls_fail_closed": True, "credentials_from_server_lease_only": True},
        "sandbox": {"profile": "FIXED_WORKER_BROKER_V1", "arbitrary_code_supported": False,
                    "shell_supported": False, "worker_target_access": False,
                    "linux_backend": "SECCOMP_RLIMIT", "windows_backend": "JOB_OBJECT_FIXED_WORKER",
                    "windows_untrusted_code_containment": False,
                    "target_io_owner": "TRUSTED_GATEWAY_BROKER", "fresh_gss_at_io_boundary": True,
                    "single_pinned_endpoint": True, "redirects": False, "proxies": False},
        "idempotency": {"replay_performs_io": False, "one_reservation_per_execution": True,
                        "crash_without_result_blocks_reexecution": True, "automatic_retry": False},
        "recon_action_boundary": {"stage6_3_gateway_admission_required": True,
                                  "admission_must_bind_exact_execution_request": True,
                                  "adapter_selection_from_server_registry_only": True,
                                  "caller_selected_adapter_or_command_allowed": False},
        "boundaries": {"specialist_raw_target_access": False, "authorization_minted_locally": False,
                       "mission_pentest_writes": False, "vep_created": False,
                       "runtime_lifecycle_stage": "6.5", "full_evidence_repository_stage": "6.6"},
        "intake_schema": adapter_intake_json_schema(), "runtime_self_certification": False, "next_stage": "6.5"}, CONTRACT_DOMAIN)


def verify_adapter_contract(value):
    try:
        return canonical_json(value) == canonical_json(canonical_adapter_contract())
    except (ValueError, TypeError, RecursionError):
        return False


def invocation_id(intake):
    return "toolinv-" + sha256_hex(normalize_adapter_intake(intake))[:32]


def verify_adapter_claim(value):
    try:
        from .authorization_contract import verify_authorization_record
        from .adapter_policy import compile_runtime_policy
        from .authorization_contract import parse_time
        from .tool_registry import select_adapter
        intake = normalize_adapter_intake(value["intake"])
        auth = value["authorization_record"]
        if not (verify_integrity(value, CLAIM_DOMAIN) and verify_authorization_record(auth)
                and value["control_version"] == ADAPTER_CONTROL_VERSION and value["invocation_id"] == invocation_id(intake)
                and value["execution_id"] == intake["execution_id"] == auth["execution_id"]
                and value["envelope_sha256"] == intake["envelope_sha256"] == auth["intake"]["envelope_sha256"]
                and value["registry_sha256"] in (registry_sha256(), legacy_registry_sha256())
                and value["status"] in {"RESERVED", "BLOCKED"}):
            return False
        if value["status"] == "RESERVED":
            adapter = select_adapter(auth["evaluation"]["execution_request"])
            if adapter.operation == 'WEB_PROFILE_ENUMERATION' and value['registry_sha256'] != registry_sha256():
                return False
            return value["controls"] == compile_runtime_policy(auth, adapter, parse_time(value["reserved_at"], "reserved_at"), bounded_web=value["controls"].get("web_profile_version")==2,
                separate_network_budget='network_request_budget' in value['controls'])
        return value["controls"] is None and bool(value["reason_codes"])
    except (KeyError, ValueError, TypeError, RuntimeError):
        return False


def verify_adapter_result(value):
    try:
        return (verify_integrity(value, RESULT_DOMAIN) and value["control_version"] == ADAPTER_CONTROL_VERSION
                and value["status"] in {"SUCCEEDED", "FAILED", "TIMEOUT", "BLOCKED"}
                and value["semantics"]["specialist_raw_target_access"] is False
                and value["semantics"]["authorization_minted_locally"] is False
                and value["semantics"]["vep_created"] is False
                and value["sensitive_output_retained"] is False)
    except (KeyError, TypeError, ValueError):
        return False


def legacy_wpt_capability_profiles():
    profiles=wpt_capability_profile_definitions()
    profiles[0]["result_schema"]["properties"]["schema_version"]={"const":"web-technology-observation-v3"}
    profiles[0]["limits"]={"max_requests":1,"max_response_bytes":16384,"max_concurrency":1,"timeout_seconds":5,"redirects":"DENY"}
    profiles[1]['execution_status']='REGISTERED_NOT_EXECUTABLE'
    profiles[1]['limits']['max_requests']=12
    profiles[1]['result_schema']['properties']['schema_version']={'const':'web-technology-observation-v3'}
    return profiles

def bounded_web_profile_contract():
    return {"schema_version":"apts-bounded-web-profile-collection-v2","max_requests":6,
        "fixed_probes":["application_root","favicon.ico"],"max_redirects_per_probe":2,
        "same_origin_required":True,"target_path_prefix_required":True,"fresh_authorization_per_request":True,
        "result_schema":"web-technology-observation-v4"}


def bounded_enumeration_contract():
    # Enumeration probes a fixed base set, optionally extended by a bounded,
    # deterministic set of CTI-derived follow-up paths from CTI_SURFACE_PROBES.
    # The probe set is still closed (never arbitrary) and CTI never grants
    # execution authority; it only shapes the bounded plan inside authorized scope.
    return {'schema_version':'apts-bounded-web-enumeration-v2','max_requests':9,
        'base_probes':['/','/robots.txt','/sitemap.xml','/.well-known/security.txt','/favicon.ico'],
        'cti_derived_probes':True,'cti_probe_registry':'adapters.profile_engine.CTI_SURFACE_PROBES',
        'redirects':False,'target_path_prefix_required':True,'fresh_authorization_per_request':True,
        'result_schema':'web-technology-observation-v4','cti_is_authorization':False}
