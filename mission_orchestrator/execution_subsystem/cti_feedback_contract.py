"""Evidence-bound CTI feedback and knowledge revisions, without new execution authority."""
from __future__ import annotations

from copy import deepcopy

from .authorization_contract import parse_time
from .cleanup_contract import canonical_cleanup_contract, verify_post_action_export
from .execution_contract import (ExecutionRequestIntegrityError, ExecutionRequestValidationError,
    canonical_json, require_id, require_object, require_sha, sha256_hex, with_integrity)
from .vep_source import selected

CONTROL_VERSION = "stage6.9-closed-loop-cti-pentest-integration"
CONTRACT_SCHEMA = "apts-stage6.9-closed-loop-cti-pentest-integration-v1"
INTAKE_SCHEMA = "apts-cti-pentest-feedback-intake-v1"
FEEDBACK_SCHEMA = "apts-cti-pentest-feedback-v1"
EXPORT_SCHEMA = "apts-cti-pentest-feedback-export-v1"
UPDATE_SCHEMA = "apts-cti-knowledge-update-intake-v1"
KNOWLEDGE_SCHEMA = "apts-cti-knowledge-revision-v1"
KNOWLEDGE_EXPORT_SCHEMA = "apts-cti-knowledge-revision-export-v1"
FEEDBACK_DOMAIN = "APTS_CTI_PENTEST_FEEDBACK_V1"
KNOWLEDGE_DOMAIN = "APTS_CTI_KNOWLEDGE_REVISION_V1"
CONTRACT_DOMAIN = "APTS_STAGE6_9_CLOSED_LOOP_CTI_PENTEST_V1"
MAX_FEEDBACK_BYTES = 65536
MAX_EXPORT_BYTES = 16777216
MAX_REVISIONS = 1000
INTAKE_FIELDS = {"schema_version", "attempt_id", "vep_id", "vep_sha256", "post_action_id", "post_action_sha256"}
UPDATE_FIELDS = {"schema_version", "feedback_id", "feedback_sha256", "attempt_id", "expected_revision", "expected_head_sha256"}
SEMANTICS = {"execution_authorized":False, "authorization_current":False, "usable_for_dispatch":False,
    "additional_target_io":False, "vulnerability_confirmed":False, "hypothesis_rejected":False,
    "impact_confirmed":False, "active_plan_mutated":False, "mission_completed":False,
    "automatic_execution_retry":False, "external_vulndesk_written":False}


def _check(condition, reason):
    if not condition:
        raise ExecutionRequestIntegrityError(reason)


def normalize_intake(payload):
    value = require_object(payload, INTAKE_FIELDS, "CTI feedback intake")
    if value["schema_version"] != INTAKE_SCHEMA:
        raise ExecutionRequestValidationError("unsupported CTI feedback schema")
    return {"schema_version":INTAKE_SCHEMA,
        "attempt_id":require_id(value["attempt_id"], "attempt_id", "xattempt-"),
        "vep_id":require_id(value["vep_id"], "vep_id", "xvep-"),
        "post_action_id":require_id(value["post_action_id"], "post_action_id", "xcleanup-"),
        **{k:require_sha(value[k], k) for k in ("vep_sha256", "post_action_sha256")}}


def normalize_update(payload):
    value = require_object(payload, UPDATE_FIELDS, "CTI knowledge update intake")
    if value["schema_version"] != UPDATE_SCHEMA:
        raise ExecutionRequestValidationError("unsupported CTI knowledge update schema")
    revision = value["expected_revision"]
    if type(revision) is not int or not 0 <= revision < MAX_REVISIONS:
        raise ExecutionRequestValidationError("expected_revision must be an integer from 0 to 999")
    head = value["expected_head_sha256"]
    if revision == 0:
        if head is not None:
            raise ExecutionRequestValidationError("genesis knowledge head must be null")
    else:
        head = require_sha(head, "expected_head_sha256")
    return {"schema_version":UPDATE_SCHEMA,
        "feedback_id":require_id(value["feedback_id"], "feedback_id", "ctifb-"),
        "attempt_id":require_id(value["attempt_id"], "attempt_id", "xattempt-"),
        "feedback_sha256":require_sha(value["feedback_sha256"], "feedback_sha256"),
        "expected_revision":revision, "expected_head_sha256":head}


def feedback_intake_json_schema():
    from .execution_contract import ID_PATTERN, SHA_PATTERN
    return {"$schema":"https://json-schema.org/draft/2020-12/schema", "type":"object", "additionalProperties":False,
        "required":sorted(INTAKE_FIELDS), "properties":{"schema_version":{"const":INTAKE_SCHEMA},
            **{k:{"type":"string", "pattern":ID_PATTERN} for k in ("attempt_id", "vep_id", "post_action_id")},
            **{k:{"type":"string", "pattern":SHA_PATTERN} for k in ("vep_sha256", "post_action_sha256")}}}


def knowledge_intake_json_schema():
    from .execution_contract import ID_PATTERN, SHA_PATTERN
    return {"$schema":"https://json-schema.org/draft/2020-12/schema", "type":"object", "additionalProperties":False,
        "required":sorted(UPDATE_FIELDS), "properties":{"schema_version":{"const":UPDATE_SCHEMA},
            **{k:{"type":"string", "pattern":ID_PATTERN} for k in ("feedback_id", "attempt_id")},
            "feedback_sha256":{"type":"string", "pattern":SHA_PATTERN},
            "expected_revision":{"type":"integer", "minimum":0, "maximum":999},
            "expected_head_sha256":{"type":["string", "null"], "pattern":SHA_PATTERN}},
        "allOf":[{"if":{"properties":{"expected_revision":{"const":0}}},
            "then":{"properties":{"expected_head_sha256":{"type":"null"}}},
            "else":{"properties":{"expected_head_sha256":{"type":"string"}}}}]}


def canonical_feedback_contract():
    return with_integrity({"schema_version":CONTRACT_SCHEMA, "control_version":CONTROL_VERSION,
        "predecessor":{"control":canonical_cleanup_contract()["control_version"],
            "contract_sha256":canonical_cleanup_contract()["integrity"]["canonical_sha256"]},
        "flow":["CTI", "PIP", "PENTEST", "VEP", "POST_ACTION", "CTI_KNOWLEDGE_REVISION", "MISSION_ADAPTATION"],
        "repository":{"execution_migration":9, "cti_feedback_migration":1, "mission_migration":53,
            "pentest_migration":16, "separate_knowledge_database":True,
            "feedback_append_only":True, "one_feedback_per_attempt":True,
            "knowledge_revision_cas":True, "retry_requires_identical_intake":True},
        "feedback":{"sources":["EXACT_VEP", "VERIFIED_RETAINED_BYTES", "EXACT_POST_ACTION"],
            "caller_evidence_or_verdict":False, "historical_provenance":True,
            "outcomes":["CONFIRMED", "REJECTED", "INCONCLUSIVE"],
            "current_adapter_outcome":"INCONCLUSIVE", "failure_is_hypothesis_rejection":False,
            "confidence":"PRESERVE_HYPOTHESIS_PRIOR; DERIVE_OBSERVATION_QUALITY_SEPARATELY",
            "risk":"PRESERVE_ESTIMATE; NO_CVSS_OR_VALIDATED_RISK_WITHOUT_SUFFICIENT_EVIDENCE",
            "attack_graph":"APPEND_OBSERVATION_ANNOTATION; NEVER_PROMOTE_CONDITIONAL_EDGES",
            "blocked_cleanup":"IMPORT_AS_REVIEW_REQUIRED; PRESERVE_BLOCKING_REASONS"},
        "mission":{"consumer":"TRUSTED_READ_ONLY_CTI_KNOWLEDGE_SOURCE",
            "write_owner":"MISSION_ORCHESTRATOR", "handoff":"EXISTING_STAGE3_7_1_CTICHANGE_ADAPTATION_EPISODE",
            "current_mission_and_plan_cas_required":True, "scope_and_pip_binding_required":True,
            "replanning":"EXISTING_CLASSIFICATION_ELIGIBILITY_GOVERNANCE_SNAPSHOT_CANDIDATE_COMMIT_GATES",
            "automatic_plan_activation":False, "terminal_reopening":False},
        "limits":{"max_feedback_bytes":MAX_FEEDBACK_BYTES, "max_export_bytes":MAX_EXPORT_BYTES,
            "max_revisions_per_subject":MAX_REVISIONS},
        "intake_schema":feedback_intake_json_schema(), "knowledge_intake_schema":knowledge_intake_json_schema(),
        "semantics":dict(SEMANTICS), "runtime_self_certification":False, "next_stage":"6.10"}, CONTRACT_DOMAIN)


def verify_feedback_contract(value):
    try:
        return canonical_json(value) == canonical_json(canonical_feedback_contract())
    except (ValueError, TypeError, RecursionError):
        return False


def build_feedback(post_export, at):
    _check(verify_post_action_export(post_export), "CTI feedback requires verified cleanup/VEP/retained bytes")
    report = post_export["report"]
    vep = post_export["vep_export"]["vep"]
    _check(parse_time(at, "created_at") >= parse_time(report["evaluated_at"], "evaluated_at"), "feedback predates post-action")
    source = vep["source_snapshot"]
    _, _, path = selected(source, vep["execution_snapshot"]["envelope"])
    observed = vep["observed_result"]
    quality = ("VERIFIED_OBSERVATION" if observed["runtime_state"] == "SUCCEEDED"
        and observed["capture_status"] == "CAPTURED" and observed["target_io_observed"] is True
        and not observed["target_io_uncertain"] else "INCOMPLETE_OR_UNCERTAIN")
    identity = "ctifb-" + sha256_hex({"attempt_id":vep["attempt_id"],
        "vep_sha256":vep["integrity"]["canonical_sha256"],
        "post_action_sha256":report["integrity"]["canonical_sha256"],
        "contract_sha256":canonical_feedback_contract()["integrity"]["canonical_sha256"]})[:32]
    subject = {"mission_id":vep["mission_id"], "pentest_id":vep["pentest_id"],
        "pentest_task_id":vep["pentest_task_id"], "task_id":vep["task_id"],
        "pip_reference":deepcopy(source["task"]["pip_reference"]),
        "target":deepcopy(vep["affected_asset"]), "hypothesis_ref":vep["hypothesis"]["reference_id"]}
    value = with_integrity({"schema_version":FEEDBACK_SCHEMA, "control_version":CONTROL_VERSION,
        "feedback_id":identity, "attempt_id":vep["attempt_id"], "execution_id":vep["execution_id"],
        "subject":subject, "knowledge_id":"ctik-" + sha256_hex(subject)[:32],
        "source_cti":deepcopy(path["provenance"]["knowledge"]),
        "source_references":{"vep_id":vep["vep_id"], "vep_sha256":vep["integrity"]["canonical_sha256"],
            "post_action_id":report["post_action_id"], "post_action_sha256":report["integrity"]["canonical_sha256"],
            "evidence_sha256":vep["evidence"]["integrity"]["canonical_sha256"],
            "terminal_event_sha256":vep["evidence"]["terminal_event_sha256"],
            "source_snapshot_sha256":source["integrity"]["canonical_sha256"]},
        "assessment":{"hypothesis_outcome":"INCONCLUSIVE", "source_hypothesis_status":vep["hypothesis"]["source_status"],
            "reason":"FIXED_ADAPTER_OBSERVATION_HAS_NO_VULNERABILITY_VERDICT",
            "hypothesis_confidence_before":vep["confidence"]["source_hypothesis"],
            "hypothesis_confidence_after":vep["confidence"]["source_hypothesis"],
            "validated_vulnerability_confidence":None, "observation_quality":quality,
            "risk":{"estimated_impact":vep["impact"]["estimated_impact"], "validated_risk_score":None,
                "risk_score_changed":False, "basis":"UNVALIDATED_SOURCE_ESTIMATE"}},
        "intelligence":{"type":"VALIDATION_OBSERVATION", "observed_result":deepcopy(observed),
            "evidence_reuse":True, "new_target_evidence_created":False},
        "attack_graph_update":{"attack_path_id":path["attack_path_id"],
            "attack_path_sha256":path["integrity"]["canonical_sha256"],
            "operation":"APPEND_OBSERVATION_ANNOTATION", "conditional_edges_preserved":True,
            "annotation":{"feedback_id":identity, "hypothesis_ref":subject["hypothesis_ref"],
                "state":"VALIDATION_STILL_REQUIRED", "observation_quality":quality}},
        "mission_signal":{"trigger_code":"CTI_CHANGE", "trigger_source":"EXTERNAL_SIGNAL",
            "review_required":not report["execution_closed"] or quality != "VERIFIED_OBSERVATION",
            "blocking_reasons":deepcopy(report["blocking_reasons"]),
            "suggested_capability":"validation", "governance_gate_required_for_replan":True},
        "contract_sha256":canonical_feedback_contract()["integrity"]["canonical_sha256"],
        "created_at":at, "semantics":dict(SEMANTICS)}, FEEDBACK_DOMAIN)
    _check(len(canonical_json(value).encode()) <= MAX_FEEDBACK_BYTES, "CTI feedback exceeds byte quota")
    return value


def verify_feedback(value, post_export):
    try:
        return canonical_json(value) == canonical_json(build_feedback(post_export, value["created_at"]))
    except (KeyError, ValueError, TypeError, RuntimeError, RecursionError):
        return False


def verify_feedback_export(value):
    try:
        return (set(value) == {"schema_version", "feedback", "post_action_export"}
            and value["schema_version"] == EXPORT_SCHEMA
            and len(canonical_json(value).encode()) <= MAX_EXPORT_BYTES
            and verify_feedback(value["feedback"], value["post_action_export"]))
    except (KeyError, ValueError, TypeError, RuntimeError, RecursionError):
        return False


def build_knowledge(feedback_export, intake, previous, at):
    intake = normalize_update(intake)
    _check(verify_feedback_export(feedback_export), "knowledge update requires verified feedback export")
    feedback = feedback_export["feedback"]
    _check(all(intake[k] == feedback[k] for k in ("feedback_id", "attempt_id"))
        and intake["feedback_sha256"] == feedback["integrity"]["canonical_sha256"], "knowledge source reference mismatch")
    ordinal = 0 if previous is None else previous["revision"]
    prior_hash = None if previous is None else previous["integrity"]["canonical_sha256"]
    _check(intake["expected_revision"] == ordinal and intake["expected_head_sha256"] == prior_hash,
        "knowledge head compare-and-swap mismatch")
    if previous is not None:
        _check(previous["subject"] == feedback["subject"] and previous["knowledge_id"] == feedback["knowledge_id"],
            "knowledge subject changed")
        _check(parse_time(at, "updated_at") >= parse_time(previous["updated_at"], "updated_at"), "knowledge clock moved backwards")
    _check(parse_time(at, "updated_at") >= parse_time(feedback["created_at"], "created_at"), "knowledge update predates feedback")
    value = {"schema_version":KNOWLEDGE_SCHEMA, "control_version":CONTROL_VERSION,
        "knowledge_id":feedback["knowledge_id"], "revision":ordinal+1,
        "previous_revision_sha256":prior_hash, "subject":deepcopy(feedback["subject"]),
        "feedback_id":feedback["feedback_id"], "feedback_sha256":intake["feedback_sha256"],
        "intake":intake, "source_cti":deepcopy(feedback["source_cti"]),
        "assessment":deepcopy(feedback["assessment"]), "intelligence":deepcopy(feedback["intelligence"]),
        "attack_graph_update":deepcopy(feedback["attack_graph_update"]),
        "mission_signal":deepcopy(feedback["mission_signal"]), "updated_at":at,
        "semantics":{**SEMANTICS, "cti_feedback_knowledge_written":True}}
    value["revision_id"] = "ctirev-" + sha256_hex({"knowledge_id":value["knowledge_id"],
        "revision":value["revision"], "feedback_sha256":intake["feedback_sha256"], "previous_sha256":prior_hash})[:32]
    return with_integrity(value, KNOWLEDGE_DOMAIN)


def verify_knowledge_export(value):
    try:
        if (set(value) != {"schema_version", "knowledge_id", "revisions"}
            or value["schema_version"] != KNOWLEDGE_EXPORT_SCHEMA
            or not isinstance(value["revisions"], list) or not 1 <= len(value["revisions"]) <= MAX_REVISIONS
            or len(canonical_json(value).encode()) > MAX_EXPORT_BYTES):
            return False
        previous, seen = None, set()
        for pair in value["revisions"]:
            if set(pair) != {"record", "feedback_export"}:
                return False
            record = pair["record"]
            expected = build_knowledge(pair["feedback_export"], record["intake"], previous, record["updated_at"])
            if (canonical_json(record) != canonical_json(expected) or record["knowledge_id"] != value["knowledge_id"]
                or record["feedback_id"] in seen):
                return False
            seen.add(record["feedback_id"])
            previous = record
        return True
    except (KeyError, ValueError, TypeError, RuntimeError, RecursionError):
        return False
