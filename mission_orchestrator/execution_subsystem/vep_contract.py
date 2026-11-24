"""Stage 6.7 canonical VEPs: reproducible evidence summaries, never execution authority."""
from __future__ import annotations

import base64
import ipaddress
import json

from .adapter_contract import verify_adapter_claim, verify_adapter_result
from .authorization_contract import parse_time, verify_authorization_record
from .evidence_contract import (EVIDENCE_CONTROL_VERSION, KINDS, LINK_FIELDS,
    MAX_ATTEMPT_BYTES, canonical_evidence_contract, verify_artifact, verify_evidence, verify_session)
from .evidence_collector import safe_worker_messages
from .execution_contract import (ExecutionRequestIntegrityError, ExecutionRequestValidationError,
    canonical_json, require_id, require_object, require_sha, sha256_hex,
    verify_canonical_action_envelope, with_integrity)
from .runtime_contract import TERMINAL, adapter_intake, verify_attempt, verify_command, verify_event
from .tool_registry import select_adapter
from .vep_source import selected, verify_source_snapshot

VEP_CONTROL_VERSION = "stage6.7-vep-construction-integrity"
CONTRACT_SCHEMA = "apts-stage6.7-vep-construction-integrity-v1"
VEP_SCHEMA = "apts-validation-evidence-package-v1"
INTAKE_SCHEMA = "apts-execution-vep-construction-v1"
EXPORT_SCHEMA = "apts-vep-offline-export-v1"
CONTRACT_DOMAIN = "APTS_STAGE6_7_VEP_CONSTRUCTION_INTEGRITY_V1"
VEP_DOMAIN = "APTS_VALIDATION_EVIDENCE_PACKAGE_V1"
MAX_VEP_BYTES = 2097152
MAX_SOURCE_BYTES = 1048576
MAX_EVENTS = 4096
MAX_EXPORT_BYTES = MAX_VEP_BYTES + MAX_ATTEMPT_BYTES * 2
INTAKE_FIELDS = {"schema_version", "attempt_id", "envelope_sha256", "evidence_sha256", "expected_head_sha256"}
SNAPSHOT_FIELDS = {"envelope", "attempt", "claim", "events", "adapter_result", "session", "commands", "authorizations"}
SEMANTICS = {"vep_created":True, "execution_authorized":False, "authorization_current":False,
    "usable_for_dispatch":False, "replay_performs_io":False, "target_network_io_performed":False,
    "additional_target_io":False, "vulnerability_confirmed":False, "impact_confirmed":False,
    "finding_persisted_to_pentest":False, "cleanup_verified":False, "cti_feedback_written":False}
SECTION_FIELDS = ("finding", "hypothesis", "validation_method", "execution_references", "observed_result",
    "evidence", "affected_asset", "impact", "confidence", "provenance", "timestamps", "limitations",
    "semantics", "source_snapshot", "execution_snapshot")


def vep_json_schema():
    """Structural interchange schema; relational verification also requires verify_vep()."""
    from .execution_contract import ID_PATTERN, SHA_PATTERN
    names = {"schema_version", "control_version", *LINK_FIELDS, "finding_id", "vep_id",
        *SECTION_FIELDS, "integrity_hashes", "integrity"}
    properties = {k:{"type":"object"} for k in SECTION_FIELDS}
    properties.update({k:{"type":"string", "pattern":ID_PATTERN} for k in (*LINK_FIELDS, "finding_id", "vep_id")})
    properties.update({"schema_version":{"const":VEP_SCHEMA}, "control_version":{"const":VEP_CONTROL_VERSION},
        "semantics":{"const":SEMANTICS}, "integrity_hashes":{"type":"object", "additionalProperties":False,
            "required":list(SECTION_FIELDS), "properties":{k:{"type":"string", "pattern":SHA_PATTERN} for k in SECTION_FIELDS}},
        "integrity":{"type":"object", "additionalProperties":False,
            "required":["algorithm", "canonicalization", "hash_domain", "canonical_sha256"], "properties":{
                "algorithm":{"const":"SHA-256"}, "canonicalization":{"const":"UTF8_SORTED_JSON_V1"},
                "hash_domain":{"const":VEP_DOMAIN}, "canonical_sha256":{"type":"string", "pattern":SHA_PATTERN}}}})
    return {"$schema":"https://json-schema.org/draft/2020-12/schema", "type":"object", "additionalProperties":False,
        "required":sorted(names), "properties":properties,
        "description":"Canonical VEP structure. Use verify_vep for exact nested fields, lineage, timestamps and derived semantics; use verify_vep_export for retained artifact bytes."}


def intake_json_schema():
    from .execution_contract import ID_PATTERN, SHA_PATTERN
    return {"$schema":"https://json-schema.org/draft/2020-12/schema", "type":"object",
        "additionalProperties":False, "required":sorted(INTAKE_FIELDS), "properties":{
            "schema_version":{"const":INTAKE_SCHEMA}, "attempt_id":{"type":"string", "pattern":ID_PATTERN},
            **{k:{"type":"string", "pattern":SHA_PATTERN} for k in INTAKE_FIELDS - {"schema_version", "attempt_id"}}}}


def normalize_vep_intake(payload):
    obj = require_object(payload, INTAKE_FIELDS, "VEP construction intake")
    if obj["schema_version"] != INTAKE_SCHEMA:
        raise ExecutionRequestValidationError("unsupported VEP construction schema")
    return {"schema_version":INTAKE_SCHEMA, "attempt_id":require_id(obj["attempt_id"], "attempt_id", "xattempt-"),
        **{k:require_sha(obj[k], k) for k in INTAKE_FIELDS - {"schema_version", "attempt_id"}}}


def canonical_vep_contract():
    return with_integrity({"schema_version":CONTRACT_SCHEMA, "control_version":VEP_CONTROL_VERSION,
        "predecessor":{"control":EVIDENCE_CONTROL_VERSION,
            "contract_sha256":canonical_evidence_contract()["integrity"]["canonical_sha256"]},
        "repository":{"migration_level":7, "mission_migration":53, "pentest_migration":16,
            "backend":"EXECUTION_SQLITE", "append_only":True, "one_vep_per_terminal_attempt":True,
            "atomic_insert":True, "historical_source_snapshot_retained":True},
        "construction":{"mode":"EXPLICIT_EXACT_TERMINAL_REFERENCES", "caller_summary_supported":False,
            "caller_evidence_upload_supported":False, "required_sources":["VERIFIED_PENTEST_SNAPSHOT",
                "EXACT_EXECUTION_ENVELOPE", "TERMINAL_RUNTIME_CHAIN", "SEALED_STAGE6_6_CAPTURE"],
            "partial_capture":"PRESERVE_GAPS_AND_UNCERTAINTY", "legacy_capture":"REJECT_NO_BACKFILL",
            "finding_identity":"PACKAGE_LOCAL_UNCONFIRMED_CANDIDATE", "automatic_vulnerability_confirmation":False,
            "source_status":"HISTORICAL_NOT_CURRENT_AUTHORIZATION", "idempotency":"EXACT_ATTEMPT_MANIFEST"},
        "integrity":{"canonicalization":"UTF8_SORTED_JSON_V1", "algorithm":"SHA-256",
            "domain_separated":True, "section_hashes":list(SECTION_FIELDS), "exact_artifact_bytes_verified":True,
            "export":"SELF_CONTAINED_CANONICAL_JSON_WITH_CAPTURED_BLOBS", "digital_signature":False,
            "artifact_payload_policy":"EXACT_STAGE6_6_ALLOWLIST_JSON",
            "meaning":"INTERNAL_CONSISTENCY_AND_LINEAGE_NOT_INDEPENDENT_AUTHENTICITY"},
        "limits":{"max_vep_bytes":MAX_VEP_BYTES, "max_source_bytes":MAX_SOURCE_BYTES,
            "max_runtime_events":MAX_EVENTS, "max_export_bytes":MAX_EXPORT_BYTES},
        "boundaries":{"mission_pentest_writes":False, "governance_revalidation_for_construction":False,
            "target_io_for_construction":False, "hashes_are_authorization":False,
            "cleanup_enabled":False, "cti_feedback_enabled":False},
        "intake_schema":intake_json_schema(), "semantics":dict(SEMANTICS),
        "runtime_self_certification":False, "next_stage":"6.8"}, CONTRACT_DOMAIN)


def verify_vep_contract(value):
    try:
        return canonical_json(value) == canonical_json(canonical_vep_contract())
    except (TypeError, ValueError, RecursionError):
        return False


def _check(condition, reason):
    if not condition:
        raise ExecutionRequestIntegrityError(reason)


def verify_execution_snapshot(snapshot, manifest):
    """Pure verification of historical records, including exact terminal and blob references."""
    try:
        _check(set(snapshot) == SNAPSHOT_FIELDS and verify_evidence(manifest), "invalid VEP execution snapshot fields")
        envelope, attempt, claim, events, result, session = (snapshot[k] for k in
            ("envelope", "attempt", "claim", "events", "adapter_result", "session"))
        _check(verify_canonical_action_envelope(envelope) and verify_attempt(attempt)
            and verify_adapter_claim(claim) and verify_session(session), "invalid VEP source records")
        req = envelope["execution_request"]
        _check(claim["status"] == "RESERVED" and adapter_intake(attempt["runtime_intake"]) == claim["intake"]
            and attempt["claim_sha256"] == claim["integrity"]["canonical_sha256"]
            and claim["authorization_record"]["evaluation"]["execution_request"] == req
            and claim["envelope_sha256"] == envelope["integrity"]["canonical_sha256"]
            and session["claim_sha256"] == attempt["claim_sha256"]
            and session["envelope_sha256"] == claim["envelope_sha256"]
            and session["enrolled_at"] == claim["reserved_at"] == attempt["authorized_at"], "VEP claim/envelope/session mismatch")
        for key in LINK_FIELDS:
            _check(session[key] == attempt[key] == manifest[key], "VEP cross-attempt identity mismatch")
        for key in ("mission_id", "pentest_id", "task_id", "execution_id"):
            _check(req[key] == attempt[key] == claim[key], "VEP cross-scope identity mismatch")
        _check(attempt["pentest_task_id"] == claim["pentest_task_id"] == envelope["source_binding"]["pentest_task_id"]
            and manifest["session_sha256"] == session["integrity"]["canonical_sha256"]
            and session["attempt_sha256"] == manifest["attempt_sha256"] == attempt["integrity"]["canonical_sha256"]
            and manifest["claim_sha256"] == attempt["claim_sha256"]
            and manifest["envelope_sha256"] == claim["envelope_sha256"], "VEP capture binding mismatch")
        _check(isinstance(events, list) and 2 <= len(events) <= MAX_EVENTS, "VEP event quota or terminal chain missing")
        commands, authorizations = snapshot["commands"], snapshot["authorizations"]
        _check(isinstance(commands, list) and all(verify_command(c) for c in commands), "invalid VEP commands")
        _check(isinstance(authorizations, list) and all(verify_authorization_record(a) for a in authorizations), "invalid VEP heartbeat authorizations")
        command_map = {c["command_id"]:c for c in commands}
        auth_map = {a["authorization_id"]:a for a in authorizations}
        _check(len(command_map) == len(commands) and len(auth_map) == len(authorizations), "duplicate VEP runtime sources")
        used_commands, used_auth = set(), set()
        before, previous, at = None, None, parse_time(attempt["authorized_at"], "authorized_at")
        for i, event in enumerate(events, 1):
            _check(verify_event(event) and event["event_sequence"] == i and before not in TERMINAL
                and event["attempt_id"] == attempt["attempt_id"] and event["attempt_sha256"] == attempt["integrity"]["canonical_sha256"]
                and event["state_before"] == before and event["previous_event_sha256"] == previous,
                "VEP event sequence or parent mismatch")
            current = parse_time(event["occurred_at"], "occurred_at")
            _check(current >= at, "VEP event timestamp reversal")
            if event["event_type"] == "STOP_REQUESTED":
                cmd = command_map[event["data"]["command_id"]]
                used_commands.add(cmd["command_id"])
                _check(cmd["integrity"]["canonical_sha256"] == event["data"]["command_sha256"]
                    and cmd["mission_id"] == attempt["mission_id"]
                    and any(t["attempt_id"] == attempt["attempt_id"] and t["attempt_sha256"] == attempt["integrity"]["canonical_sha256"]
                        for t in cmd["target_attempts"]), "VEP stop command mismatch")
            else:
                _check(event["actor"] == attempt["owner_id"] or event["data"].get("recovery_owner_fenced") is True,
                    "VEP event producer mismatch")
            if event["event_type"] == "RUNNING":
                _check(event["data"].get("native_worker_ready") is True
                    and type(event["data"].get("worker_pid")) is int and event["data"]["worker_pid"] > 0
                    and event["data"].get("sandbox_backend") in {"SECCOMP_RLIMIT", "JOB_OBJECT_FIXED_WORKER"}, "VEP native readiness mismatch")
            if event["event_type"] == "HEARTBEAT":
                auth = auth_map[event["data"]["authorization_id"]]
                used_auth.add(auth["authorization_id"])
                _check(auth["execution_id"] == attempt["execution_id"] and auth["decision"] == "ALLOW"
                    and auth["intake"]["envelope_sha256"] == claim["envelope_sha256"], "VEP heartbeat binding mismatch")
            before, previous, at = event["state_after"], event["integrity"]["canonical_sha256"], current
        _check(used_commands == set(command_map) and used_auth == set(auth_map), "extraneous VEP runtime records")
        terminal = events[-1]
        _check(events[0]["occurred_at"] == attempt["authorized_at"]
            and events[0]["data"].get("evidence_contract_sha256") == session["contract_sha256"]
            and before in TERMINAL and manifest["state"] == before
            and manifest["runtime_event_count"] == len(events) and manifest["terminal_event_id"] == terminal["event_id"]
            and manifest["terminal_event_sha256"] == previous and manifest["sealed_at"] == terminal["occurred_at"]
            and manifest["authorized_at"] == attempt["authorized_at"]
            and manifest["started_at"] == next((e["occurred_at"] for e in events if e["event_type"] == "RUNNING"), None),
            "VEP terminal binding mismatch")
        uncertain = terminal["data"].get("target_io_uncertain") is True
        _check(manifest["target_io_uncertain"] == uncertain, "VEP uncertainty mismatch")
        if terminal["data"].get("recovery_owner_fenced") is True:
            _check(before == "ABORTED" and uncertain and result is None
                and terminal["data"].get("adapter_result_sha256") is None, "invalid VEP recovery claim")
        else:
            _check(result is not None and terminal["data"].get("resources_closed") is True, "VEP terminal result missing")
        if result is not None:
            _check(verify_adapter_result(result) and result["claim_sha256"] == attempt["claim_sha256"]
                and result["invocation_id"] == attempt["invocation_id"] and result["execution_id"] == attempt["execution_id"]
                and result["controls"] == claim["controls"] and result["registry_sha256"] == claim["registry_sha256"]
                and result["adapter_id"] == claim["controls"]["adapter_id"] and result["operation"] == claim["controls"]["operation"]
                and terminal["data"]["adapter_result_sha256"] == result["integrity"]["canonical_sha256"]
                and result["semantics"]["vulnerability_confirmed"] is False, "VEP adapter result mismatch")
            _check(all(result[k] == attempt[k] for k in ("mission_id", "pentest_id", "pentest_task_id", "task_id")),
                "VEP adapter result scope mismatch")
            if result["observation"] is not None:
                message = {"result":result["observation"], "backend":result["sandbox_backend"]}
                _check(safe_worker_messages(canonical_json(message).encode("utf-8"))["messages"] == [message],
                    "VEP observation exceeds fixed-adapter semantics")
            boundary = result["boundary_authorization_record"]
            if result["boundary_authorization_id"] is not None:
                _check(verify_authorization_record(boundary)
                    and boundary["authorization_id"] == result["boundary_authorization_id"]
                    and boundary["execution_id"] == attempt["execution_id"]
                    and boundary["intake"]["envelope_sha256"] == claim["envelope_sha256"]
                    and (not result["semantics"]["target_network_io_performed"] or boundary["decision"] == "ALLOW"), "VEP historical boundary mismatch")
            else:
                _check(boundary is None and result["semantics"]["target_network_io_performed"] is False, "VEP target I/O without historical authority")
            _check(before != "SUCCEEDED" or result["status"] == "SUCCEEDED", "VEP success inflation")
        _check(manifest["adapter_result_sha256"] == (None if result is None else result["integrity"]["canonical_sha256"])
            and manifest["boundary_authorization_id"] == (None if result is None else result["boundary_authorization_id"]), "VEP evidence/result mismatch")
        by_kind = {a["kind"]:a for a in manifest["artifacts"]}
        _check({"TOOL_IDENTITY", "ACTION_PARAMETERS", "BEFORE_STATE", "AFTER_STATE"} <= set(by_kind), "VEP required evidence missing")
        _check(before != "SUCCEEDED" or set(by_kind) == set(KINDS), "VEP successful capture incomplete")
        coverage = {}
        for kind in KINDS:
            if kind in by_kind:
                coverage[kind] = "PRESENT" if by_kind[kind]["capture_complete"] else "PARTIAL"
            elif uncertain:
                coverage[kind] = "NOT_DURABLY_CAPTURED_BEFORE_CRASH"
            elif kind in {"STDOUT", "STDERR"} and result and not result["semantics"]["tool_invocation_performed"]:
                coverage[kind] = "NOT_PRODUCED"
            elif kind in {"NETWORK_OBSERVATION", "TARGET_RESPONSE"} and result and not result["semantics"]["target_network_io_performed"]:
                coverage[kind] = "NO_TARGET_IO"
            else:
                coverage[kind] = "NOT_OBSERVED"
        coverage.update({"SCREENSHOTS":"NOT_SUPPORTED_BY_CURRENT_FIXED_ADAPTERS", "TARGET_BEFORE_STATE":"NOT_MEASURED", "TARGET_AFTER_STATE":"NOT_MEASURED"})
        partial = any(v in {"PARTIAL", "NOT_OBSERVED", "NOT_DURABLY_CAPTURED_BEFORE_CRASH"} for v in coverage.values())
        _check(manifest["coverage"] == coverage and manifest["capture_status"] ==
            ("RECOVERED_PARTIAL" if uncertain else "PARTIAL" if partial else "CAPTURED"), "VEP evidence coverage inflation")
        for artifact in by_kind.values():
            _check(parse_time(session["enrolled_at"], "enrolled_at") <= parse_time(artifact["captured_at"], "captured_at") <= at,
                "VEP artifact timestamp outside capture window")
        return True
    except (KeyError, TypeError, ValueError, RuntimeError, RecursionError):
        return False


def _core(source, snapshot, manifest, constructed_at):
    _check(verify_execution_snapshot(snapshot, manifest), "invalid VEP execution/evidence lineage")
    envelope, attempt, claim, result = (snapshot[k] for k in ("envelope", "attempt", "claim", "adapter_result"))
    _check(len(canonical_json(source).encode("utf-8")) <= MAX_SOURCE_BYTES, "VEP source byte quota exceeded")
    _check(verify_source_snapshot(source, envelope), "invalid VEP Pentest snapshot")
    _check(parse_time(constructed_at, "constructed_at") >= parse_time(manifest["sealed_at"], "sealed_at"), "VEP construction predates terminal capture")
    proposal, validation, path = selected(source, envelope)
    hypothesis = source["hypothesis"]
    req = envelope["execution_request"]
    finding_id = "xvepfind-" + sha256_hex({"mission_id":req["mission_id"], "pentest_id":req["pentest_id"],
        "pentest_task_id":attempt["pentest_task_id"], "target":req["target"], "hypothesis_ref":hypothesis["identity"]["record_id"]})[:32]
    core = {"schema_version":VEP_SCHEMA, "control_version":VEP_CONTROL_VERSION,
        **{k:attempt[k] for k in LINK_FIELDS}, "finding_id":finding_id,
        "finding":{"identity_scope":"PACKAGE_LOCAL", "status":"UNCONFIRMED_CANDIDATE",
            "source_hypothesis_ref":hypothesis["identity"]["record_id"], "persisted_to_pentest":False},
        "hypothesis":{"reference_id":hypothesis["identity"]["record_id"], "canonical_sha256":hypothesis["integrity"]["canonical_sha256"],
            "statement":hypothesis["data"]["statement"], "source_status":hypothesis["data"]["status"]},
        "validation_method":{"validation_task_id":validation["validation_task_id"],
            "validation_task_sha256":validation["integrity"]["canonical_sha256"],
            "action":req["action"], "adapter_id":claim["controls"]["adapter_id"],
            "operation":claim["controls"]["operation"], "parameters":req["parameters"],
            "meaning":"FIXED_ADAPTER_OBSERVATION_NOT_VULNERABILITY_TEST_VERDICT"},
        "execution_references":{"envelope_sha256":envelope["integrity"]["canonical_sha256"],
            "attempt_sha256":attempt["integrity"]["canonical_sha256"], "claim_sha256":attempt["claim_sha256"],
            "terminal_event_id":manifest["terminal_event_id"], "terminal_event_sha256":manifest["terminal_event_sha256"],
            "adapter_result_sha256":manifest["adapter_result_sha256"], "attempt_number":attempt["attempt_number"],
            "retry_of_attempt_id":attempt["retry_of_attempt_id"]},
        "observed_result":{"runtime_state":manifest["state"], "adapter_status":None if result is None else result["status"],
            "observation":None if result is None else result["observation"], "capture_status":manifest["capture_status"],
            "target_io_uncertain":manifest["target_io_uncertain"],
            "target_io_observed":None if result is None else result["semantics"]["target_network_io_performed"],
            "validation_verdict":"INCONCLUSIVE_FOR_VULNERABILITY_CONFIRMATION"},
        "evidence":manifest, "affected_asset":req["target"],
        "impact":{"estimated_impact":req["parameters"]["estimated_impact"],
            "basis":"SOURCE_PROPOSAL_ESTIMATE", "observed_security_impact":None, "confirmed":False},
        "confidence":{"source_hypothesis":hypothesis["data"]["confidence"],
            "meaning":"SOURCE_HYPOTHESIS_CONFIDENCE", "validated_vulnerability_confidence":None,
            "evidence_capture_status":manifest["capture_status"]},
        "provenance":{"producer":"EXECUTION_SUBSYSTEM", "source_mode":"VERIFIED_HISTORICAL_SNAPSHOT",
            "pentest_migration":16, "mission_migration":53,
            "exploitation_run_id":source["output"]["exploitation_run_id"],
            "exploit_action_proposal_id":proposal["exploit_action_proposal_id"], "attack_path_id":path["attack_path_id"],
            "source_snapshot_sha256":source["integrity"]["canonical_sha256"],
            "authorization_id":claim["authorization_id"], "boundary_authorization_id":manifest["boundary_authorization_id"],
            "authorization_is_historical":True,
            "contract_sha256":canonical_vep_contract()["integrity"]["canonical_sha256"],
            "evidence_contract_sha256":canonical_evidence_contract()["integrity"]["canonical_sha256"]},
        "timestamps":{"authorized_at":manifest["authorized_at"], "started_at":manifest["started_at"],
            "sealed_at":manifest["sealed_at"], "constructed_at":constructed_at},
        "limitations":{"coverage":manifest["coverage"], "raw_target_bytes_retained":False,
            "target_state_measured":False, "screenshots_supported":False,
            "hashes_prove":"INTERNAL_CONSISTENCY_NOT_INDEPENDENT_AUTHENTICITY",
            "cleanup":"NOT_VERIFIED_STAGE6_8", "cti_feedback":"NOT_WRITTEN_STAGE6_9"},
        "semantics":dict(SEMANTICS), "source_snapshot":source, "execution_snapshot":snapshot}
    core["integrity_hashes"] = {k:sha256_hex(core[k]) for k in SECTION_FIELDS}
    core["vep_id"] = "xvep-" + sha256_hex({"attempt_id":attempt["attempt_id"],
        "evidence_sha256":manifest["integrity"]["canonical_sha256"],
        "source_sha256":source["integrity"]["canonical_sha256"], "contract_sha256":core["provenance"]["contract_sha256"]})[:32]
    return core


def build_vep(source, snapshot, manifest, constructed_at):
    value = with_integrity(_core(source, snapshot, manifest, constructed_at), VEP_DOMAIN)
    _check(len(canonical_json(value).encode("utf-8")) <= MAX_VEP_BYTES, "VEP byte quota exceeded")
    return value


def verify_vep(value):
    try:
        expected = build_vep(value["source_snapshot"], value["execution_snapshot"], value["evidence"], value["timestamps"]["constructed_at"])
        return canonical_json(expected) == canonical_json(value)
    except (KeyError, TypeError, ValueError, RuntimeError, RecursionError):
        return False


def _verify_payloads(snapshot, manifest, pairs):
    req, claim, result = snapshot["envelope"]["execution_request"], snapshot["claim"], snapshot["adapter_result"]
    payloads = {a["kind"]:(a, json.loads(raw)) for a,raw in pairs}
    for kind, (descriptor, payload) in payloads.items():
        _check(isinstance(payload, dict), "VEP artifact must be an allowlisted JSON object")
        if kind == "TOOL_IDENTITY":
            _check(set(payload) == {"adapter", "registry_sha256", "fixed_worker", "worker_source_sha256", "python_version", "shell", "arbitrary_command"}
                and payload["adapter"] == select_adapter(req).definition() and payload["registry_sha256"] == claim["registry_sha256"]
                and payload["fixed_worker"] == "sandbox_worker.py" and payload["shell"] is False and payload["arbitrary_command"] is False
                and isinstance(payload["python_version"], list) and len(payload["python_version"]) == 3
                and all(type(n) is int and n >= 0 for n in payload["python_version"]), "VEP tool payload mismatch")
            require_sha(payload["worker_source_sha256"], "worker_source_sha256")
        elif kind == "ACTION_PARAMETERS":
            _check(payload == {"action":req["action"], "target":req["target"], "operation":claim["controls"]["operation"],
                "parameters":{"validation_task_id":req["parameters"]["validation_task_id"],
                    "estimated_impact":req["parameters"]["estimated_impact"], "expected_evidence_sha256":sha256_hex(req["parameters"]["expected_evidence"])},
                "parameters_sha256":sha256_hex(req["parameters"]), "credential_lease_id":claim["controls"]["credential_lease_id"],
                "authorization_header_retained":False, "controls":claim["controls"], "envelope_sha256":claim["envelope_sha256"]}, "VEP action payload mismatch")
        elif kind == "BEFORE_STATE":
            _check(payload == {"runtime_state":"AUTHORIZED", "authorization_id":claim["authorization_id"],
                "current_context_sha256":sha256_hex(claim["authorization_record"]["evaluation"]["current_context"]),
                "target_state_measured":False}, "VEP before-state payload mismatch")
        elif kind == "STDOUT":
            _check(set(payload) == {"stream", "messages", "omitted_line_count", "raw_retained"}
                and payload["stream"] == "stdout" and payload["raw_retained"] is False
                and type(payload["omitted_line_count"]) is int and payload["omitted_line_count"] >= 0
                and isinstance(payload["messages"], list), "VEP stdout payload mismatch")
            raw_messages = b"\n".join(canonical_json(m).encode("utf-8") for m in payload["messages"])
            _check(safe_worker_messages(raw_messages)["messages"] == payload["messages"], "VEP stdout outside fixed-worker allowlist")
        elif kind == "STDERR":
            _check(set(payload) == {"stream", "raw_retained", "captured_bytes", "exit_code"}
                and payload["stream"] == "stderr" and payload["raw_retained"] is False
                and type(payload["captured_bytes"]) is int and payload["captured_bytes"] == descriptor["captured_size_bytes"]
                and (payload["exit_code"] is None or type(payload["exit_code"]) is int), "VEP stderr payload mismatch")
        elif kind == "NETWORK_OBSERVATION":
            _check(set(payload) == {"connected", "peer_ip", "response_bytes", "response_sha256", "byte_limit_reached", "observation_complete"}
                and type(payload["connected"]) is bool and type(payload["byte_limit_reached"]) is bool
                and type(payload["observation_complete"]) is bool and payload["observation_complete"] == descriptor["capture_complete"]
                and type(payload["response_bytes"]) is int and payload["response_bytes"] >= 0
                and str(ipaddress.ip_address(payload["peer_ip"])) == payload["peer_ip"], "VEP network payload mismatch")
            require_sha(payload["response_sha256"], "response_sha256")
        elif kind == "TARGET_RESPONSE":
            _check(set(payload) == {"http_status", "response_bytes", "response_sha256", "raw_retained"}
                and payload["raw_retained"] is False and type(payload["response_bytes"]) is int
                and payload["response_bytes"] == descriptor["captured_size_bytes"]
                and payload["response_sha256"] == descriptor["captured_sha256"]
                and (payload["http_status"] is None or type(payload["http_status"]) is int and 100 <= payload["http_status"] <= 599),
                "VEP target response payload mismatch")
        elif kind == "RESULT":
            _check(result is not None and payload == {"status":result["status"], "adapter_result_sha256":result["integrity"]["canonical_sha256"],
                "observation":result["observation"], "semantics":result["semantics"]}, "VEP result payload mismatch")
        elif kind == "AFTER_STATE":
            _check(payload == {"runtime_state":manifest["state"], "terminal_event_sha256":manifest["terminal_event_sha256"],
                "target_io_uncertain":manifest["target_io_uncertain"], "target_state_measured":False}, "VEP after-state payload mismatch")
    if result is not None and result["observation"]:
        from .evidence_contract import observation_network_binding
        observation = observation_network_binding(result["observation"])
        for kind in ("NETWORK_OBSERVATION", "TARGET_RESPONSE"):
            payload = payloads[kind][1]
            _check(all(payload[k] == observation[k] for k in ("response_bytes", "response_sha256")), "VEP observation/payload digest mismatch")
        _check(all(payloads["NETWORK_OBSERVATION"][1][k] == observation[k] for k in ("connected", "peer_ip", "byte_limit_reached"))
            and payloads["TARGET_RESPONSE"][1]["http_status"] == observation["http_status"], "VEP observation/payload metadata mismatch")
    return True


def verify_vep_export(value):
    try:
        if (set(value) != {"schema_version", "vep", "artifacts", "semantics"} or value["schema_version"] != EXPORT_SCHEMA
            or value["semantics"] != SEMANTICS or len(canonical_json(value).encode("utf-8")) > MAX_EXPORT_BYTES
            or not verify_vep(value["vep"])):
            return False
        refs = value["vep"]["evidence"]["artifacts"]
        artifacts = value["artifacts"]
        if not isinstance(artifacts, list) or len(artifacts) != len(refs):
            return False
        pairs = []
        for ref, blob in zip(refs, artifacts):
            if set(blob) != {"artifact", "content_base64"} or blob["artifact"] != ref:
                return False
            raw = base64.b64decode(blob["content_base64"], validate=True)
            if not verify_artifact(ref, raw) or canonical_json(json.loads(raw)).encode("utf-8") != raw:
                return False
            pairs.append((ref, raw))
        return _verify_payloads(value["vep"]["execution_snapshot"], value["vep"]["evidence"], pairs)
    except (KeyError, TypeError, ValueError, RuntimeError, RecursionError):
        return False
