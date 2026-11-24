"""Stage 3.8.9: deterministic, read-only Mission forensic evidence.

The bundle is a snapshot of existing durable records, not a new authority or a
cryptographic attestation by a separate party. Inconsistent reads are withheld.
"""
from __future__ import annotations

from typing import Any, Mapping

from .canonical import verify_envelope
from .mission_events import verify_event_chain
from .observability_decision_trace import build_decision_governance_evidence_trace
from .observability_diagnostics import (
    SOURCES, build_integrity_gap_consistency_diagnostics,
    verify_integrity_gap_consistency_diagnostics,
)
from .observability_ingestion import normalize_events
from .observability_live_projection import build_live_mission_state_execution_projection
from .observability_trace import (
    build_observability_trace_identity_contract, sha256_hex,
    verify_observability_trace_identity_contract,
)
from .execution_result import verify_execution_result_capture_contract
from .task_evidence_binding import verify_task_evidence_binding_verification_contract

SCHEMA_VERSION = "apts-forensic-query-evidence-bundle-reconstruction-v1"
HASH_DOMAIN = "MISSION_FORENSIC_EVIDENCE_BUNDLE_V1"
QUERY_HASH_DOMAIN = "MISSION_FORENSIC_QUERY_V1"
RECONSTRUCTION_HASH_DOMAIN = "MISSION_FORENSIC_RECONSTRUCTION_V1"
IDENTITY_PREFIX = "fobundle-"

# Every reader is an existing local repository read. The order within each list is
# the repository's durable order; a second read detects concurrent source drift.
SINGLE_READERS = {
    "mission_state": "get_state",
    "scope_contract": "get_current_scope_contract",
    "governance_binding": "get_current_governance_binding",
    "plan_contract": "get_mission_plan",
    "planner_input_snapshot": "get_planner_input_snapshot",
    "task_decomposition": "get_task_decomposition",
    "task_dependency_graph": "get_task_dependency_graph",
    "planner_invocation": "get_planner_invocation",
    "generated_plan": "get_generated_plan",
    "plan_validation": "get_plan_validation",
    "active_plan_version": "get_active_plan_version",
}
LIST_READERS = {
    "state_transitions": "list_state_transitions",
    "scope_versions": "list_scope_contract_versions",
    "governance_versions": "list_governance_binding_versions",
    "governance_operations": "list_governance_operations",
    "authorization_operations": "list_authorization_operations",
    "authorization_bindings": "list_authorization_bindings",
    "mission_commands": "list_mission_commands",
    "routed_tasks": "list_routed_tasks",
    "plan_versions": "list_plan_versions",
    "planned_tasks": "list_planned_tasks",
    "task_dependency_edges": "list_task_dependency_edges",
    "planning_recovery_checkpoints": "list_planning_recovery_checkpoints",
    "task_readiness_projections": "list_task_readiness_projections",
    "task_routing_intents": "list_task_routing_intents",
    "task_routing_eligibility_gates": "list_task_routing_eligibility_gates",
    "route_decisions": "list_task_route_decisions",
    "delegation_authorizations": "list_delegation_authorizations",
    "delegations": "list_task_delegations",
    "delegation_deliveries": "list_delegation_deliveries",
    "delegation_recovery_controls": "list_delegation_recovery_controls",
    "routing_delegation_recovery_checkpoints": "list_routing_delegation_recovery_checkpoints",
    "execution_dispatches": "list_execution_dispatch_contracts",
    "dispatch_eligibility_gates": "list_dispatch_eligibility_gates",
    "pre_dispatch_revalidations": "list_pre_dispatch_revalidations",
    "execution_attempts": "list_execution_attempts",
    "execution_deliveries": "list_execution_deliveries",
    "running_projections": "list_execution_running_projections",
    "result_captures": "list_execution_result_captures",
    "termination_controls": "list_execution_termination_controls",
    "execution_outcome_propagations": "list_execution_outcome_propagations",
    "execution_recovery_checkpoints": "list_execution_recovery_checkpoints",
    "task_outcomes": "list_task_outcomes",
    "task_terminality_eligibility_gates": "list_task_terminality_eligibility_gates",
    "evidence_binding_verifications": "list_task_evidence_binding_verifications",
    "task_completions": "list_task_completions",
    "outcome_aggregations": "list_mission_outcome_aggregations",
    "success_evaluations": "list_mission_success_evaluations",
    "completion_readiness_decisions": "list_completion_readiness_decisions",
    "completion_declarations": "list_verified_completion_declarations",
    "outcome_recovery_checkpoints": "list_outcome_recovery_checkpoints",
    "adaptation_episodes": "list_adaptation_replans",
    "adaptation_trigger_classifications": "list_adaptation_trigger_classifications",
    "replan_eligibility_gates": "list_replan_eligibility_gates",
    "replan_snapshots": "list_replan_snapshots",
    "replan_candidates": "list_replan_candidates",
    "replan_validations": "list_replan_validations",
    "replan_commits": "list_replan_commits",
    "replan_handoffs": "list_replan_handoffs",
    "replan_recovery_checkpoints": "list_replan_recovery_checkpoints",
}
DECISION_SOURCE_KINDS = {
    "route_decisions": "route_decisions",
    "delegation_authorizations": "delegation_authorizations",
    "pre_dispatch_revalidations": "pre_dispatch_revalidations",
    "governance_operations": "governance_operations",
    "authorization_operations": "authorization_operations",
    "evidence_binding_verifications": "evidence_binding_verifications",
    "completion_readiness_decisions": "completion_readiness_decisions",
    "execution_result_captures": "result_captures",
}
LIVE_RECORD_KINDS = {
    "plan_versions": "plan_versions", "planned_tasks": "planned_tasks",
    "readiness_projections": "task_readiness_projections",
    "route_decisions": "route_decisions", "delegations": "delegations",
    "execution_dispatches": "execution_dispatches",
    "execution_attempts": "execution_attempts",
    "running_projections": "running_projections", "result_captures": "result_captures",
    "termination_controls": "termination_controls",
    "task_outcomes": "task_outcomes", "task_completions": "task_completions",
    "adaptation_episodes": "adaptation_episodes", "replan_commits": "replan_commits",
}
QUERY_KINDS = ("events", "tasks", "execution", "decisions", "evidence", "lineage", "integrity")
TASK_KINDS = ("planned_tasks", "task_readiness_projections", "task_routing_intents",
              "task_routing_eligibility_gates", "route_decisions", "delegations",
              "task_outcomes", "task_completions")
EXECUTION_KINDS = ("execution_dispatches", "dispatch_eligibility_gates",
                   "pre_dispatch_revalidations", "execution_attempts", "execution_deliveries",
                   "running_projections", "result_captures", "termination_controls",
                   "execution_outcome_propagations", "execution_recovery_checkpoints")
EVIDENCE_KINDS = ("result_captures", "evidence_binding_verifications",
                  "task_outcomes", "completion_declarations")
REFERENCE_KEYS = frozenset(("event_id", "source_event_id", "planned_task_id", "task_id",
                            "execution_attempt_id", "result_capture_id", "task_key"))


def read_forensic_records(repository: Any, mission_id: str, identity: Mapping[str, Any],
                          envelope: Mapping[str, Any], events: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Inventory the Mission's existing contract, state and Stage 3.3–3.7 stores."""
    records: dict[str, Any] = {
        "mission_identity": identity, "mission_envelope": envelope,
        "mission_events": events,
    }
    for name, method in SINGLE_READERS.items():
        records[name] = getattr(repository, method)(mission_id)
    for name, method in LIST_READERS.items():
        records[name] = getattr(repository, method)(mission_id)
    return records


def _assert_bound_sources(mission_id: str, trace_id: str, trace_contract: Mapping[str, Any],
                          diagnostics: Mapping[str, Any], sources: Mapping[str, Any],
                          records: Mapping[str, Any]) -> None:
    if not verify_observability_trace_identity_contract(trace_contract) or (
        trace_contract["identity"]["mission_id"], trace_contract["identity"]["trace_id"]
    ) != (mission_id, trace_id):
        raise ValueError("TRACE_IDENTITY_MISMATCH")
    if not verify_integrity_gap_consistency_diagnostics(diagnostics) or (
        diagnostics["mission_id"], diagnostics["trace_id"]
    ) != (mission_id, trace_id) or diagnostics["status"] != "PASS":
        raise ValueError("DIAGNOSTICS_NOT_PASS")
    if set(sources) != set(SOURCES) or set(records) != (
        {"mission_identity", "mission_envelope", "mission_events"} | set(SINGLE_READERS) | set(LIST_READERS)
    ):
        raise ValueError("SOURCE_INVENTORY_MISMATCH")
    expected_diag = build_integrity_gap_consistency_diagnostics(
        mission_id=mission_id, trace_id=trace_id, source_errors={}, **sources)
    if expected_diag != diagnostics:
        raise ValueError("SOURCE_DIAGNOSTICS_MISMATCH")
    identity, envelope = records["mission_identity"], records["mission_envelope"]
    if identity["mission_id"] != mission_id or not verify_envelope(envelope) or (
        build_observability_trace_identity_contract(identity=identity, envelope=envelope) != trace_contract
    ):
        raise ValueError("CANONICAL_CONTRACT_MISMATCH")
    events = records["mission_events"]
    chain_ok, _ = verify_event_chain(events)
    if not chain_ok or not events or events[0]["event_type"] != "MISSION_REGISTERED" or (
        normalize_events(events, mission_id, trace_id) != sources["normalized_events"]
    ):
        raise ValueError("EVENT_CHAIN_MISMATCH")
    for kind in SINGLE_READERS:
        record = records[kind]
        if record is not None and (not isinstance(record, Mapping) or
                                   record.get("mission_id", mission_id) != mission_id):
            raise ValueError("CROSS_MISSION_RECORD")
    if records["mission_state"] is None:
        raise ValueError("STATE_UNAVAILABLE")
    for kind in LIST_READERS:
        values = records[kind]
        if not isinstance(values, list) or any(
            not isinstance(v, Mapping) or v.get("mission_id", mission_id) != mission_id for v in values
        ):
            raise ValueError("CROSS_MISSION_RECORD")
    state = records["mission_state"]
    transitions = records["state_transitions"]
    version, state_name, last_id = 1, "CREATED", None
    for transition in transitions:
        if (transition["from_state_version"], transition["from_state"]) != (version, state_name) or (
            transition["to_state_version"] != version + 1
        ):
            raise ValueError("STATE_HISTORY_MISMATCH")
        version, state_name, last_id = (transition["to_state_version"], transition["to_state"],
                                         transition["transition_id"])
    if (state["state_version"], state["state"], state["last_transition_id"]) != (
        version, state_name, last_id
    ):
        raise ValueError("STATE_HISTORY_MISMATCH")
    result_by_id = {}
    for result in records["result_captures"]:
        contract = result["execution_result_capture_contract"]
        if (not verify_execution_result_capture_contract(contract) or
            result["canonical_sha256"] != contract["canonical_sha256"] or
            result["result_capture_id"] in result_by_id):
            raise ValueError("EVIDENCE_BINDING_MISMATCH")
        result_by_id[result["result_capture_id"]] = result
    for verification in records["evidence_binding_verifications"]:
        contract = verification["task_evidence_binding_verification_contract"]
        result = result_by_id.get(verification["result_capture_id"])
        if (not verify_task_evidence_binding_verification_contract(contract) or
            verification["canonical_sha256"] != contract["canonical_sha256"] or
            result is None or verification["result_capture_sha256"] != result["canonical_sha256"] or
            verification["evidence_manifest_sha256"] != result["evidence_manifest_sha256"] or
            verification["artifact_manifest_sha256"] != result["artifact_manifest_sha256"]):
            raise ValueError("EVIDENCE_BINDING_MISMATCH")
    decision_sources = {kind: records[source] for kind, source in DECISION_SOURCE_KINDS.items()}
    expected_decisions = build_decision_governance_evidence_trace(
        mission_id=mission_id, trace_id=trace_id, normalized_events=sources["normalized_events"],
        causal_graph=sources["causal_graph"], sources=decision_sources)
    if expected_decisions != sources["decision_trace"]:
        raise ValueError("DECISION_EVIDENCE_BINDING_MISMATCH")
    expected_live = build_live_mission_state_execution_projection(
        mission_id=mission_id, trace_id=trace_id, mission_state=records["mission_state"],
        normalized_events=sources["normalized_events"], causal_graph=sources["causal_graph"],
        **{name: records[kind] for name, kind in LIVE_RECORD_KINDS.items()})
    if expected_live != sources["live_projection"]:
        raise ValueError("LIVE_RECORD_BINDING_MISMATCH")


def _sealed(core: dict[str, Any], domain: str) -> dict[str, Any]:
    return {**core, "integrity": {"hash_domain": domain,
        "canonical_sha256": sha256_hex({"hash_domain": domain, "core": core})}}


def build_forensic_evidence_bundle(*, mission_id: str, trace_id: str,
    trace_contract: Mapping[str, Any], diagnostics: Mapping[str, Any],
    sources: Mapping[str, Any] | None, records: Mapping[str, Any] | None,
    reason_code: str | None = None) -> dict[str, Any]:
    if not verify_observability_trace_identity_contract(trace_contract) or (
        trace_contract["identity"]["mission_id"], trace_contract["identity"]["trace_id"]
    ) != (mission_id, trace_id) or not verify_integrity_gap_consistency_diagnostics(diagnostics) or (
        diagnostics["mission_id"], diagnostics["trace_id"]
    ) != (mission_id, trace_id):
        raise ValueError("unverified forensic identity or diagnostics")
    reason = reason_code
    if diagnostics["status"] != "PASS":
        reason = "OBSERVABILITY_" + diagnostics["status"]
    elif reason is None:
        if sources is None or records is None:
            reason = "RECORD_SOURCE_UNAVAILABLE"
        else:
            try:
                _assert_bound_sources(mission_id, trace_id, trace_contract, diagnostics, sources, records)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                reason = str(exc) if str(exc) in {
                    "TRACE_IDENTITY_MISMATCH", "DIAGNOSTICS_NOT_PASS", "SOURCE_INVENTORY_MISMATCH",
                    "SOURCE_DIAGNOSTICS_MISMATCH", "CANONICAL_CONTRACT_MISMATCH",
                    "EVENT_CHAIN_MISMATCH", "CROSS_MISSION_RECORD", "STATE_UNAVAILABLE",
                    "STATE_HISTORY_MISMATCH", "EVIDENCE_BINDING_MISMATCH",
                    "DECISION_EVIDENCE_BINDING_MISMATCH", "LIVE_RECORD_BINDING_MISMATCH",
                } else "SOURCE_BINDING_FAILED"
    core = {
        "schema_version": SCHEMA_VERSION,
        "bundle_id": IDENTITY_PREFIX + sha256_hex({"hash_domain": HASH_DOMAIN,
            "mission_id": mission_id, "trace_id": trace_id})[:32],
        "mission_id": mission_id, "trace_id": trace_id,
        "status": "WITHHELD" if reason else "VERIFIED",
        "reason_code": reason,
        "trace_contract": trace_contract,
        "diagnostics": diagnostics,
        "sources": None if reason else dict(sources),
        "records": None if reason else dict(records),
        "record_counts": None if reason else {
            kind: len(value) for kind, value in records.items() if isinstance(value, list)},
        "semantics": {
            "read_only": True, "deterministic": True, "restart_stable_for_stable_sources": True,
            "verified_is_external_attestation": False, "authorization_performed": False,
            "governance_query_performed": False, "runtime_probe_performed": False,
            "external_network_io_performed": False, "telemetry_export_performed": False,
            "mission_state_transition_performed": False, "routing_performed": False,
            "delegation_performed": False, "dispatch_performed": False,
            "execution_attempt_created": False, "target_actuation": False,
            "database_migration_added": False, "durable_store_added": False,
        },
    }
    return _sealed(core, HASH_DOMAIN)


def verify_forensic_evidence_bundle(bundle: Mapping[str, Any]) -> bool:
    try:
        core = dict(bundle)
        integrity = core.pop("integrity")
        if (core["schema_version"] != SCHEMA_VERSION or
            core["bundle_id"] != IDENTITY_PREFIX + sha256_hex({"hash_domain": HASH_DOMAIN,
                "mission_id": core["mission_id"], "trace_id": core["trace_id"]})[:32] or
            integrity["hash_domain"] != HASH_DOMAIN or
            integrity["canonical_sha256"] != sha256_hex({"hash_domain": HASH_DOMAIN, "core": core}) or
            any(core["semantics"][key] is not expected for key, expected in (
                ("read_only", True), ("deterministic", True),
                ("verified_is_external_attestation", False),
                ("authorization_performed", False), ("governance_query_performed", False),
                ("runtime_probe_performed", False), ("external_network_io_performed", False),
                ("mission_state_transition_performed", False), ("dispatch_performed", False),
                ("target_actuation", False), ("database_migration_added", False),
                ("durable_store_added", False))) or
            not verify_integrity_gap_consistency_diagnostics(core["diagnostics"]) or
            (core["diagnostics"]["mission_id"], core["diagnostics"]["trace_id"]) !=
                (core["mission_id"], core["trace_id"]) or
            not verify_observability_trace_identity_contract(core["trace_contract"])):
            return False
        if core["status"] == "WITHHELD":
            return (isinstance(core["reason_code"], str) and bool(core["reason_code"]) and
                    core["sources"] is None and core["records"] is None and core["record_counts"] is None)
        if core["status"] != "VERIFIED" or core["reason_code"] is not None:
            return False
        _assert_bound_sources(core["mission_id"], core["trace_id"], core["trace_contract"],
                              core["diagnostics"], core["sources"], core["records"])
        return core["record_counts"] == {
            kind: len(value) for kind, value in core["records"].items() if isinstance(value, list)}
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def _matches(value: Any, reference: str) -> bool:
    if isinstance(value, Mapping):
        return any((key in REFERENCE_KEYS and item == reference) or _matches(item, reference)
                   for key, item in value.items() if key != "payload")
    if isinstance(value, list):
        return any(_matches(item, reference) for item in value)
    return False


def forensic_query(bundle: Mapping[str, Any], *, scope: str, reference: str | None = None) -> dict[str, Any]:
    if scope not in QUERY_KINDS or (reference is not None and (not reference or len(reference) > 256)):
        raise ValueError("invalid forensic query scope or reference")
    if not verify_forensic_evidence_bundle(bundle):
        raise ValueError("unverified forensic evidence bundle")
    data: Any = None
    if bundle["status"] == "VERIFIED":
        records, sources = bundle["records"], bundle["sources"]
        if scope == "events":
            data = {"events": sources["normalized_events"], "timeline_entries": sources["timeline"]["entries"]}
        elif scope == "decisions":
            data = {"entries": sources["decision_trace"]["entries"],
                    "bound_records": {kind: records[source] for kind, source in DECISION_SOURCE_KINDS.items()}}
        elif scope in ("tasks", "execution", "evidence"):
            kinds = {"tasks": TASK_KINDS, "execution": EXECUTION_KINDS,
                     "evidence": EVIDENCE_KINDS}[scope]
            data = {kind: records[kind] for kind in kinds}
        elif scope == "lineage":
            data = {"causal_graph": sources["causal_graph"], "timeline": sources["timeline"]}
        else:
            data = {"diagnostics": bundle["diagnostics"], "record_counts": bundle["record_counts"]}
        if reference is not None and scope == "lineage":
            graph = sources["causal_graph"]
            event_nodes = {n["source_event_id"]: n for n in graph["nodes"] if n["node_type"] == "MISSION_EVENT"}
            selected = set()
            if reference in event_nodes:
                selected.add(event_nodes[reference]["node_id"])
                # Walk the verified DAG backwards to retain both parent and
                # causation ancestry, always in the graph's canonical order.
                while True:
                    parents = {e["source_node_id"] for e in graph["edges"]
                               if e["target_node_id"] in selected}
                    if parents <= selected:
                        break
                    selected.update(parents)
            data = {"source_graph_id": graph["graph_id"],
                    "source_graph_sha256": graph["integrity"]["canonical_sha256"],
                    "nodes": [n for n in graph["nodes"] if n["node_id"] in selected],
                    "edges": [e for e in graph["edges"] if e["source_node_id"] in selected
                              and e["target_node_id"] in selected],
                    "timeline_entries": [e for e in sources["timeline"]["entries"]
                                         if e["causal_node_id"] in selected]}
        elif reference is not None:
            data = {kind: [v for v in values if _matches(v, reference)]
                    if isinstance(values, list) else
                    {subkind: [v for v in subvalues if _matches(v, reference)]
                     for subkind, subvalues in values.items()} if kind == "bound_records" else
                    values if _matches(values, reference) else None
                    for kind, values in data.items()}
    return _sealed({"schema_version": SCHEMA_VERSION, "mission_id": bundle["mission_id"],
                    "trace_id": bundle["trace_id"], "bundle_sha256": bundle["integrity"]["canonical_sha256"],
                    "scope": scope, "reference": reference, "status": bundle["status"],
                    "reason_code": bundle["reason_code"], "result": data,
                    "read_only": True, "authorization_granted": False}, QUERY_HASH_DOMAIN)


def reconstruct_forensic_mission(bundle: Mapping[str, Any]) -> dict[str, Any]:
    if not verify_forensic_evidence_bundle(bundle):
        raise ValueError("unverified forensic evidence bundle")
    result = None
    if bundle["status"] == "VERIFIED":
        sources, records = bundle["sources"], bundle["records"]
        result = {
            "ordering": "VERIFIED_MISSION_EVENT_LEDGER_APPEND_ORDER",
            "event_count": len(sources["normalized_events"]),
            "timeline": sources["timeline"], "causal_graph": sources["causal_graph"],
            "decision_trace": sources["decision_trace"],
            "mission_state": records["mission_state"],
            "state_transitions": records["state_transitions"],
            "live_projection": sources["live_projection"],
            "active_plan_version": records["active_plan_version"],
            "execution_attempts": records["execution_attempts"],
            "task_outcomes": records["task_outcomes"],
            "replan_commits": records["replan_commits"],
            "integrity_findings": bundle["diagnostics"]["findings"],
            "head_event_sha256": sources["normalized_events"][-1]["source_event_sha256"],
        }
    return _sealed({"schema_version": SCHEMA_VERSION, "mission_id": bundle["mission_id"],
                    "trace_id": bundle["trace_id"], "bundle_sha256": bundle["integrity"]["canonical_sha256"],
                    "status": bundle["status"], "reason_code": bundle["reason_code"],
                    "diagnostics": bundle["diagnostics"], "reconstruction": result,
                    "read_only": True, "authorization_granted": False}, RECONSTRUCTION_HASH_DOMAIN)


def canonical_forensic_definition() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "identity_prefix": IDENTITY_PREFIX,
            "query_scopes": list(QUERY_KINDS), "status_values": ["VERIFIED", "WITHHELD"],
            "ordering": "VERIFIED_MISSION_EVENT_LEDGER_APPEND_ORDER",
            "source": "VERIFIED_STAGE3_8_7_DIAGNOSTICS_AND_CROSS_BOUND_DURABLE_RECORDS",
            "evidence_payload_mode": "EXISTING_DURABLE_RECORD_SNAPSHOT",
            "external_attestation": False, "atomic_database_snapshot": False,
            "persistence_mode": "DERIVED_NO_NEW_DURABLE_STORE",
            "database_change_mode": "NO_NEW_DATABASE_MIGRATION", "runtime_side_effects": False}
