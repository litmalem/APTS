from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .acquisition_freshness_agent import AcquisitionFreshnessAgent
from .architecture import COMPONENT_BY_KEY, DEPENDENCY_DAG
from .asset_profiling_cpe_resolution_service import AssetProfilingCpeResolutionService
from .attack_mapping_service import AttackMappingService
from .attack_path_reasoning_agent import AttackPathReasoningAgent
from .audit_store import AuditStore
from .common import new_id, to_db_datetime, utcnow_iso
from .contracts import (
    AUTHORIZATION_NOT_REQUIRED_INTERNAL,
    AUTHORIZATION_REQUIRED,
    ContractValidationError,
    PolicyDecisionBinding,
    TaskContract,
)
from .db_adapter import DbAdapter, to_json
from .diagnostics import CtiHealthDiagnostics
from .event_bus import CtiEventBus
from .event_dispatcher import CtiEventDispatcher
from .governance_client import GovernanceClient, GovernanceClientError
from .governance_correlation import CrossSubsystemGovernanceCorrelator
from .integrity_probe import IntegrityViolationProbe
from .lineage_projection import CanonicalLineageProjector
from .normalization_provenance_service import NormalizationProvenanceService
from .pip_assembly_validation_service import PipAssemblyValidationService
from .risk_prioritization_agent import RiskPrioritizationAgent
from .service_registry import ServiceRegistry
from .source_sync_connector import SourceSyncConnector
from .threat_context_service import ThreatContextService
from .vulnerability_correlation_service import VulnerabilityCorrelationService


@dataclass
class RuntimeVersions:
    state_version: int = 1
    plan_version: int = 1
    policy_version: str = "policy-default-1"


@dataclass
class MissionRuntime:
    mission_id: str
    plan_id: str
    versions: RuntimeVersions
    scan_payload: Dict[str, Any]
    mission_context: Dict[str, Any]
    policy_context: Dict[str, Any]
    task_states: Dict[str, str] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    pending_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    task_component: Dict[str, str] = field(default_factory=dict)
    task_output_key: Dict[str, str] = field(default_factory=dict)
    retries: Dict[str, int] = field(default_factory=dict)
    acquisition_actions: int = 0
    acquisition_sources: List[str] = field(default_factory=list)
    pending_reactive: Optional[Dict[str, Any]] = None
    revoked_policy_decisions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    revoked_task_ids: Set[str] = field(default_factory=set)
    status: str = "RUNNING"
    last_error: Optional[str] = None
    terminal_event: threading.Event = field(default_factory=threading.Event)


class CtiSubsystemOrchestrator:
    """CTI-A01 event-driven Hybrid Reactive-Deliberative orchestrator.

    Runtime model
    -------------
    * Typed events are published to ``CtiEventBus`` and delivered by
      ``CtiEventDispatcher``.
    * CTI-A02 is part of the runtime: it evaluates source freshness and can call
      the existing VulnDesk NVD/CPE/MITRE sync services through a non-agent
      SourceSyncConnector after a source-acquisition policy ALLOW decision.
    * Deliberative proposals advance the versioned dependency DAG one component
      at a time. Reactive proposals can pre-empt them using deterministic
      precedence rules.
    * The blocking legacy ``run_scan`` API is retained for compatibility, but
      internally it waits for the event-driven mission to reach a terminal state.

    Reasoning remains separated from authority and target execution. Source sync
    is read-only CTI acquisition; no CTI component grants pentest execution
    authorization.
    """

    SERVICE_KEY = "cti_subsystem_orchestrator"
    COMPONENT_ID = "CTI-A01"
    ARCHITECTURE_VERSION = "2026-08-harmonized"
    CONTROL_VERSION = "hybrid-event-driven-2.17-health-diagnostics"

    PIPELINE_ORDER = [
        "normalization_provenance_service",
        "asset_profiling_cpe_resolution_service",
        "vulnerability_correlation_service",
        "attack_mapping_service",
        "attack_path_reasoning_agent",
        "threat_context_service",
        "risk_prioritization_agent",
        "pip_assembly_validation_service",
    ]

    TERMINAL_STATES = {"COMPLETED", "QUALITY_REVIEW", "FAILED", "CANCELLED"}
    ACCEPTED_DEPENDENCY_STATES = {
        "COMPLETED",
        "NOT_REQUIRED",
        "SKIPPED_OPTIONAL",
        "DEFERRED_OPTIONAL",
        "DEGRADED_ALLOWED",
    }

    PRECEDENCE_SCORE = {
        "SAFETY_POLICY": 100,
        "CRITICAL_FAILURE": 90,
        "FRESHNESS_EMERGENCY": 80,
        "MISSION_PRIORITY": 70,
        "RECOVERY": 60,
        "DELIBERATIVE_OPTIMIZATION": 10,
    }

    def __init__(
        self,
        db: Optional[DbAdapter] = None,
        registry: Optional[ServiceRegistry] = None,
        audit: Optional[AuditStore] = None,
        event_bus: Optional[CtiEventBus] = None,
        dispatcher: Optional[CtiEventDispatcher] = None,
        governance_client: Optional[GovernanceClient] = None,
    ):
        self.db = db or DbAdapter()
        self.registry = registry or ServiceRegistry(self.db)
        self.audit = audit or AuditStore(self.db)

        self.acquisition = AcquisitionFreshnessAgent(self.db, self.registry, self.audit)
        self.normalization = NormalizationProvenanceService(self.db, self.registry, self.audit)
        self.asset_cpe = AssetProfilingCpeResolutionService(self.db, self.registry, self.audit)
        self.vulnerability = VulnerabilityCorrelationService(self.db, self.registry, self.audit)
        self.attack_mapping = AttackMappingService(self.db, self.registry, self.audit)
        self.attack_path = AttackPathReasoningAgent(self.db, self.registry, self.audit)
        self.threat_context = ThreatContextService(self.db, self.registry, self.audit)
        self.risk = RiskPrioritizationAgent(self.db, self.registry, self.audit)
        self.pip = PipAssemblyValidationService(self.db, self.registry, self.audit)

        self.event_bus = event_bus or CtiEventBus(self.db)
        self.dispatcher = dispatcher or CtiEventDispatcher(self.event_bus)
        self.governance = governance_client or GovernanceClient()
        # Stage 2.9.1: deterministic read-side projection over persisted Stage 2.8 lineage.
        # Stage 2.9.2 exposes this same projector through a read-only HTTP probe;
        # projection semantics remain owned here rather than duplicated in transport code.
        self.lineage_projector = CanonicalLineageProjector(self.db)
        self.governance_correlator = CrossSubsystemGovernanceCorrelator(self.governance)
        self.integrity_probe = IntegrityViolationProbe()
        self.diagnostics = CtiHealthDiagnostics(self)
        self._runtimes: Dict[str, MissionRuntime] = {}
        # Stage 2.8.6: causal head per TaskContract. A DB fallback is used
        # when live in-memory state has been reconstructed.
        self._task_event_heads: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._register_event_handlers()

    # ------------------------------------------------------------------
    # Public lifecycle API
    # ------------------------------------------------------------------
    def start_dispatcher(self) -> None:
        self.dispatcher.start()

    def stop_dispatcher(self) -> None:
        self.dispatcher.stop()

    def start_mission(self, scan_payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.registry.is_enabled(self.SERVICE_KEY):
            return {"status": "skipped", "message": "CTI Subsystem Orchestrator is disabled"}

        self.registry.update_status(self.SERVICE_KEY, "running")
        mission_id = str(scan_payload.get("mission_id") or new_id("mission"))
        policy_context = dict(scan_payload.get("policy_context") or {})
        # Stage-1 governance integration: CTI source acquisition authorization
        # is external and authoritative. Local policy_context may still impose a
        # stricter DENY, but it can no longer grant an ALLOW by itself.
        policy_context.setdefault("scope_allowed", True)
        policy_context.setdefault("governance_authority", "aptsGSS")
        policy_context.setdefault("governance_mode", "EXTERNAL_AUTHORITATIVE_FAIL_CLOSED")
        versions = RuntimeVersions(
            state_version=1,
            plan_version=1,
            policy_version=str(policy_context.get("policy_version") or "policy-default-1"),
        )
        mission_context = self._mission_context(scan_payload, mission_id)
        plan_id = new_id("plan")
        runtime = MissionRuntime(
            mission_id=mission_id,
            plan_id=plan_id,
            versions=versions,
            scan_payload=dict(scan_payload),
            mission_context=mission_context,
            policy_context=policy_context,
        )
        with self._lock:
            self._runtimes[mission_id] = runtime

        self._create_mission(mission_id, mission_context, policy_context, versions)
        self._create_plan(plan_id, mission_id, versions)
        self._emit_event(
            mission_id,
            "MISSION_STARTED",
            self.COMPONENT_ID,
            {"mission_context": mission_context, "plan_id": plan_id},
            versions,
        )
        return {
            "status": "accepted",
            "mission_id": mission_id,
            "plan_id": plan_id,
            "architecture_version": self.ARCHITECTURE_VERSION,
            "control_version": self.CONTROL_VERSION,
        }

    def run_scan(self, scan_payload: Dict[str, Any]) -> Dict[str, Any]:
        started = self.start_mission(scan_payload)
        if started.get("status") == "skipped":
            return started
        mission_id = started["mission_id"]
        runtime = self._runtime(mission_id)
        timeout = float(scan_payload.get("cti_runtime_timeout_seconds") or 600.0)

        if self.dispatcher.is_running:
            completed = runtime.terminal_event.wait(timeout=max(0.1, timeout))
        else:
            completed = self.dispatcher.run_until(
                lambda: runtime.terminal_event.is_set(),
                timeout_seconds=timeout,
            )
        if not completed:
            self._fail_mission(runtime, f"CTI event-driven mission timeout after {timeout:.1f}s")
            raise TimeoutError(runtime.last_error)
        if runtime.status == "FAILED":
            raise RuntimeError(runtime.last_error or "CTI mission failed")
        return self._response(
            runtime.scan_payload,
            runtime.mission_id,
            runtime.plan_id,
            runtime.versions,
            runtime.outputs,
            runtime.status,
        )

    def get_mission_status(self, mission_id: str) -> Dict[str, Any]:
        runtime = self._runtimes.get(mission_id)
        if runtime:
            return {
                "mission_id": mission_id,
                "status": runtime.status,
                "plan_id": runtime.plan_id,
                "state_version": runtime.versions.state_version,
                "plan_version": runtime.versions.plan_version,
                "policy_version": runtime.versions.policy_version,
                "task_states": dict(runtime.task_states),
                "acquisition_actions": runtime.acquisition_actions,
                "acquisition_sources": list(runtime.acquisition_sources),
                "last_error": runtime.last_error,
            }
        if self.db.table_exists("cti_missions"):
            row = self.db.fetch_one(
                "SELECT * FROM cti_missions WHERE mission_id=%(mission_id)s LIMIT 1",
                {"mission_id": mission_id},
            )
            if row:
                return row
        return {"mission_id": mission_id, "status": "NOT_FOUND"}

    def publish_external_event(
        self,
        mission_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        source_component: str = "EXTERNAL",
        severity: str = "INFO",
    ) -> Dict[str, Any]:
        normalized_type = str(event_type or "UNKNOWN").upper()
        event_payload = dict(payload or {})
        runtime = self._runtimes.get(str(mission_id))
        # Stage 2.8.8 / 2.9.6-H1: authoritative Governance lifecycle events are
        # durable audit/provenance inputs even when the in-memory mission runtime
        # has already terminated or the service has restarted. SCOPE_CHANGED is
        # included because it is authoritative governance provenance, not a CTI
        # operational/reactive trigger. Revocation retains its safety fast-path;
        # the remaining events are accepted as audit-only ingress so the aptsGSS
        # transactional outbox can converge without requiring a live runtime.
        durable_governance_events = {
            "SCOPE_CHANGED",
            "POLICY_DECISION_ISSUED",
            "POLICY_DECISION_REVALIDATED",
            "POLICY_DECISION_REVALIDATION_FAILED",
            "AUTHORIZATION_REVOKED",
        }
        if normalized_type not in durable_governance_events and runtime is None:
            raise KeyError(f"Mission runtime not found: {mission_id}")

        # Stage 2.7 safety fast-path. Governance revocation must be projected to
        # the durable TaskContract index immediately at HTTP ingress, even while
        # the single event-dispatcher thread is busy executing another handler or
        # after the process has lost the in-memory MissionRuntime. The event is
        # still queued normally for reactive lineage/replanning afterwards.
        event_id = new_id("event")
        if normalized_type == "AUTHORIZATION_REVOKED":
            projection = self._project_authorization_revocation(
                runtime,
                mission_id=str(mission_id),
                payload=event_payload,
                source_component=str(source_component or "EXTERNAL"),
                event_id=event_id,
            )
            event_payload["cti_revocation_projection"] = projection

        versions = runtime.versions if runtime is not None else RuntimeVersions()
        # Stage 2.8.6: preserve authoritative external event identity. aptsGSS
        # already places gevent-* in governance_event_id via its outbox.
        upstream_event_id = (
            event_payload.get("upstream_event_id")
            or event_payload.get("governance_event_id")
        )
        return self.event_bus.publish(
            normalized_type,
            source_component=source_component,
            mission_id=mission_id,
            payload=event_payload,
            severity=severity,
            state_version=versions.state_version if runtime is not None else None,
            plan_version=versions.plan_version if runtime is not None else None,
            policy_version=versions.policy_version if runtime is not None else None,
            event_id=event_id,
            upstream_event_id=(
                str(upstream_event_id) if upstream_event_id not in (None, "") else None
            ),
        )

    def recent_events(self, mission_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        return self.event_bus.recent_events(mission_id, limit=limit)

    def project_task_lineage(self, task_id: str) -> Dict[str, Any]:
        """Build canonical Task lineage, correlate Governance, then classify integrity.

        Stage 2.9.5 consumes the Stage 2.9.4 read-only correlation facts and turns
        evidence-backed anomalies into explicit integrity violations. The canonical local
        projection and Governance authority remain unchanged.
        """
        projection = self.lineage_projector.project_task(task_id)
        correlator = getattr(self, "governance_correlator", None)
        if correlator is not None:
            projection = correlator.correlate_task(projection)
        probe = getattr(self, "integrity_probe", None)
        return probe.probe_task(projection) if probe is not None else projection

    def project_mission_lineage(self, mission_id: str) -> Dict[str, Any]:
        """Build mission lineage, correlate authoritative provenance, and probe integrity.

        The Stage 2.9.3 local reconstruction remains canonical. Stage 2.9.4 attaches
        authoritative correlation facts. Stage 2.9.5 classifies those facts together with
        task lifecycle ordering into a read-only violation report.
        """
        projection = self.lineage_projector.project_mission(mission_id)
        correlator = getattr(self, "governance_correlator", None)
        if correlator is not None:
            projection = correlator.correlate_mission(projection)
        probe = getattr(self, "integrity_probe", None)
        return probe.probe_mission(projection) if probe is not None else projection

    def probe_task_integrity(self, task_id: str) -> Dict[str, Any]:
        """Return only the Stage 2.9.5 Task integrity report."""
        lineage = self.project_task_lineage(task_id)
        return dict(lineage.get("integrity_probe") or {})

    def probe_mission_integrity(self, mission_id: str) -> Dict[str, Any]:
        """Return only the Stage 2.9.5 mission integrity report."""
        lineage = self.project_mission_lineage(mission_id)
        return dict(lineage.get("integrity_probe") or {})

    def runtime_diagnostics(self, *, deep: bool = False) -> Dict[str, Any]:
        """Return Stage 2.9.6 runtime readiness/diagnostics without mutating state."""
        return self.diagnostics.snapshot(deep=deep)

    def mission_diagnostics(self, mission_id: str) -> Dict[str, Any]:
        """Return Stage 2.9.6 mission diagnostic summary over canonical lineage."""
        return self.diagnostics.mission_snapshot(mission_id)

    # ------------------------------------------------------------------
    # Event registration / handlers
    # ------------------------------------------------------------------
    def _register_event_handlers(self) -> None:
        self.event_bus.subscribe("MISSION_STARTED", self._on_mission_started, subscriber_id="CTI-A01:mission-start")
        self.event_bus.subscribe("CTI_ACQUISITION_EVALUATE", self._on_acquisition_evaluate, subscriber_id="CTI-A02:acquisition-evaluate")
        self.event_bus.subscribe("SOURCE_SYNC_COMPLETED", self._on_source_sync_completed, subscriber_id="CTI-A01:source-sync-complete")
        self.event_bus.subscribe("SOURCE_SYNC_DEGRADED", self._on_source_sync_degraded, subscriber_id="CTI-A01:source-sync-degraded")
        self.event_bus.subscribe("SOURCE_SYNC_FAILED", self._on_source_sync_failed, subscriber_id="CTI-A01:source-sync-failed")
        self.event_bus.subscribe("PIPELINE_ADVANCE", self._on_pipeline_advance, subscriber_id="CTI-A01:dag-advance")
        self.event_bus.subscribe("TASK_COMPLETED", self._on_task_completed, subscriber_id="CTI-A01:task-completed")
        self.event_bus.subscribe("TASK_FAILED", self._on_task_failed, subscriber_id="CTI-A01:task-failed")
        self.event_bus.subscribe("EVENT_HANDLER_FAILED", self._on_event_handler_failed, subscriber_id="CTI-A01:event-handler-failed")
        for event_type in (
            "SOURCE_DOWN",
            "RATE_LIMIT_REACHED",
            "FRESHNESS_THRESHOLD_EXCEEDED",
            "PARSER_FAILED",
            "TASK_TIMEOUT",
            "HIGH_PRIORITY_REQUEST",
            "POLICY_CHANGED",
            "AUTHORIZATION_REVOKED",
        ):
            self.event_bus.subscribe(event_type, self._on_reactive_trigger, subscriber_id=f"CTI-A01:reactive:{event_type}")

    def _on_mission_started(self, event: Dict[str, Any]) -> None:
        runtime = self._runtime(event.get("mission_id"))
        if runtime.status in self.TERMINAL_STATES:
            return
        auto_acquire = runtime.scan_payload.get("auto_acquire_cti", True)
        if auto_acquire and self.registry.is_enabled("cti_acquisition_freshness_agent"):
            runtime.task_states["cti_acquisition_freshness_agent"] = "PENDING"
            self._emit_event(
                runtime.mission_id,
                "CTI_ACQUISITION_EVALUATE",
                self.COMPONENT_ID,
                {"reason": "MISSION_STARTED"},
                runtime.versions,
            )
        else:
            runtime.task_states["cti_acquisition_freshness_agent"] = "NOT_REQUIRED"
            runtime.outputs["acquisition"] = {"status": "not_required", "reason": "AUTO_ACQUIRE_DISABLED"}
            self._schedule_pipeline_advance(runtime, "ACQUISITION_NOT_REQUIRED")

    def _on_acquisition_evaluate(self, event: Dict[str, Any]) -> None:
        runtime = self._runtime(event.get("mission_id"))
        if runtime.status in self.TERMINAL_STATES:
            return

        max_actions = max(0, int(runtime.scan_payload.get("cti_acquisition_max_actions") or 1))
        force_refresh = bool((event.get("payload") or {}).get("force"))
        effective_max_actions = max_actions + (1 if force_refresh else 0)
        if max_actions == 0 and not force_refresh:
            runtime.task_states["cti_acquisition_freshness_agent"] = "NOT_REQUIRED"
            runtime.outputs["acquisition"] = {"status": "not_required", "reason": "MAX_ACTIONS_ZERO"}
            self._schedule_pipeline_advance(runtime, "ACQUISITION_DISABLED_BY_LIMIT")
            return
        if runtime.acquisition_actions >= effective_max_actions:
            if runtime.task_states.get("cti_acquisition_freshness_agent") not in self.ACCEPTED_DEPENDENCY_STATES:
                runtime.task_states["cti_acquisition_freshness_agent"] = "COMPLETED"
            self._schedule_pipeline_advance(runtime, "ACQUISITION_LIMIT_REACHED")
            return

        objective = {
            "mission_id": runtime.mission_id,
            "acquisition_objective_id": new_id("acqobj"),
            "mission_relevance": runtime.mission_context.get("default_relevance", 0.6),
            "source_set": runtime.scan_payload.get("cti_source_set") or [],
            "priority_overrides": runtime.scan_payload.get("cti_source_priority_overrides") or {},
            "policy_context_id": runtime.versions.policy_version,
        }
        proposal = self.acquisition.propose_next_action(objective)
        if not proposal:
            runtime.task_states["cti_acquisition_freshness_agent"] = (
                "COMPLETED" if runtime.acquisition_actions else "NOT_REQUIRED"
            )
            runtime.outputs.setdefault("acquisition", {})["status"] = "completed" if runtime.acquisition_actions else "not_required"
            self._schedule_pipeline_advance(runtime, "NO_ACQUISITION_PROPOSAL")
            return

        candidate = {
            **proposal,
            "proposal_id": proposal.get("decision_id"),
            "proposal_kind": "RAO",
            "target_component": "cti_acquisition_freshness_agent",
            "target_source_id": proposal.get("source_id"),
            "precedence": "DELIBERATIVE_OPTIMIZATION",
            "priority_utility": self._acquisition_utility(proposal),
            "state_version": runtime.versions.state_version,
            "plan_version": runtime.versions.plan_version,
            "policy_version": runtime.versions.policy_version,
        }
        selected = self._arbitrate(runtime, runtime.pending_reactive, candidate)
        if selected.get("proposal_kind") == "REACTIVE":
            runtime.pending_reactive = None
            self._apply_reactive_action(runtime, selected)
            return

        policy_decision = self._source_policy_decision(runtime, proposal)
        if policy_decision["decision"] != "ALLOW":
            allow_degraded = bool(runtime.scan_payload.get("allow_degraded_acquisition", True))
            runtime.task_states["cti_acquisition_freshness_agent"] = (
                "DEGRADED_ALLOWED" if allow_degraded else "FAILED"
            )
            runtime.outputs["acquisition"] = {
                "status": "denied" if allow_degraded else "failed",
                "proposal": proposal,
                "policy_decision": policy_decision,
                "degraded_allowed": allow_degraded,
            }
            self._set_proposal_status(candidate.get("proposal_id"), "DENIED", guard_decision="DENY")

            if not allow_degraded:
                reason_code = str(
                    policy_decision.get("reason_code")
                    or ((policy_decision.get("reason_codes") or ["SOURCE_ACQUISITION_POLICY_DENIED"])[0])
                )
                self._fail_mission(
                    runtime,
                    f"CTI source acquisition not authorized: {reason_code}",
                )
                return

            self._schedule_pipeline_advance(runtime, "SOURCE_ACQUISITION_POLICY_DENIED")
            return

        task_id = new_id("task")
        # Local workflow admissibility and external authorization are distinct.
        # This local guard may further restrict the task, but it never grants
        # authority.  CTI source acquisition therefore binds the exact aptsGSS
        # PolicyDecision into the committed TaskContract.
        guard = {"decision": "ALLOW", "reasons": [], "checked_at": utcnow_iso()}
        scope_contract_id = (
            runtime.scan_payload.get("scope_contract_id")
            or runtime.policy_context.get("scope_contract_id")
        )
        try:
            policy_binding = PolicyDecisionBinding.from_policy_decision(
                policy_decision,
                expected_mission_id=runtime.mission_id,
                expected_action_class="CTI_SOURCE_READ",
                expected_action_name=str(proposal.get("action_type") or "INCREMENTAL_FETCH"),
                expected_resource_type="CTI_SOURCE",
                expected_resource_value=str(proposal.get("source_id") or ""),
                expected_scope_contract_id=str(scope_contract_id) if scope_contract_id else None,
            )
            task_contract = self._commit_task(
                task_id,
                candidate,
                guard,
                runtime.mission_id,
                runtime.plan_id,
                runtime.versions,
                "cti_acquisition_freshness_agent",
                "SYNC_SELECTED_CTI_SOURCE",
                [proposal.get("source_id")],
                authorization_mode=AUTHORIZATION_REQUIRED,
                policy_decision_binding=policy_binding,
            )
        except ContractValidationError as exc:
            runtime.task_states["cti_acquisition_freshness_agent"] = "FAILED"
            runtime.outputs["acquisition"] = {
                "status": "failed",
                "proposal": proposal,
                "policy_decision": policy_decision,
                "reason_code": "POLICY_DECISION_TASK_BINDING_INVALID",
                "error": str(exc),
            }
            self._set_proposal_status(
                candidate.get("proposal_id"),
                "DENIED",
                guard_decision="DENY",
            )
            self._fail_mission(
                runtime,
                f"PolicyDecision cannot be bound to TaskContract: {exc}",
            )
            return

        # Test-only deterministic barrier for Stage 2.6 negative E2E.
        # Disabled by default and never grants authority. When enabled, it pauses
        # after TaskContract commit and before authoritative revalidation so a
        # test operator can revoke the bound PolicyDecision through aptsGSS.
        if not self._wait_pre_dispatch_test_gate(runtime, task_contract):
            runtime.task_states["cti_acquisition_freshness_agent"] = "DENIED"
            runtime.outputs["acquisition"] = {
                "status": "blocked_pre_dispatch_test_gate",
                "proposal": proposal,
                "policy_decision": policy_decision,
                "reason_code": "PRE_DISPATCH_TEST_GATE_TIMEOUT",
            }
            self._set_proposal_status(
                candidate.get("proposal_id"),
                "DENIED",
                guard_decision="DENY",
            )
            self._fail_mission(
                runtime,
                "Stage 2.6 negative-test gate timed out before release; dispatch remained blocked",
            )
            return

        # Stage 2.6: the TaskContract was valid when committed, but external
        # authority can change before use. Revalidate the exact bound
        # PolicyDecision immediately before dispatch and fail closed on any
        # revocation, expiry, scope/policy drift, hash mismatch, or authority
        # unavailability.
        revalidation = self._pre_dispatch_revalidate(
            runtime,
            task_contract,
            policy_binding,
        )
        if not revalidation.get("valid"):
            runtime.task_states["cti_acquisition_freshness_agent"] = "DENIED"
            runtime.outputs["acquisition"] = {
                "status": "blocked_pre_dispatch",
                "proposal": proposal,
                "policy_decision": policy_decision,
                "pre_dispatch_revalidation": revalidation,
                "reason_code": "PRE_DISPATCH_POLICY_REVALIDATION_FAILED",
            }
            self._set_proposal_status(
                candidate.get("proposal_id"),
                "DENIED",
                guard_decision="DENY",
            )
            reasons = revalidation.get("reason_codes") or ["UNKNOWN_REVALIDATION_FAILURE"]
            self._fail_mission(
                runtime,
                "Pre-dispatch PolicyDecision revalidation blocked task: "
                + ",".join(str(x) for x in reasons),
            )
            return

        runtime.task_component[task_id] = "cti_acquisition_freshness_agent"
        runtime.task_output_key[task_id] = "acquisition"
        if not self._transition_authorized_task_to_running(task_id):
            runtime.task_states["cti_acquisition_freshness_agent"] = "DENIED"
            runtime.outputs["acquisition"] = {
                "status": "blocked_revoked_before_dispatch",
                "proposal": proposal,
                "policy_decision": policy_decision,
                "reason_code": "POLICY_DECISION_REVOKED_AFTER_REVALIDATION",
            }
            self._emit_task_lifecycle_event(
                runtime.mission_id,
                "TASK_DISPATCH_BLOCKED",
                self.COMPONENT_ID,
                {
                    "task_id": task_id,
                    "component": "cti_acquisition_freshness_agent",
                    "policy_decision_id": policy_binding.decision_id,
                    "authorization_request_id": policy_binding.request_id,
                    "reason_codes": ["POLICY_DECISION_REVOKED_AFTER_REVALIDATION"],
                },
                runtime.versions,
                severity="CRITICAL",
                **self._task_lineage_from_contract(
                    task_contract,
                    revalidation_id=revalidation.get("revalidation_id"),
                ),
            )
            self._replan(runtime, "POLICY_DECISION_REVOKED_AFTER_REVALIDATION")
            self._emit_event(
                runtime.mission_id,
                "CTI_ACQUISITION_EVALUATE",
                self.COMPONENT_ID,
                {"reason": "POLICY_DECISION_REVOKED_REAUTHORIZE", "force": True},
                runtime.versions,
            )
            return
        runtime.task_states["cti_acquisition_freshness_agent"] = "RUNNING"
        acquisition_lineage = self._task_lineage_from_contract(
            task_contract,
            revalidation_id=revalidation.get("revalidation_id"),
        )
        self._emit_task_lifecycle_event(
            runtime.mission_id,
            "TASK_DISPATCHED",
            self.COMPONENT_ID,
            {
                "task_id": task_id,
                "component": "cti_acquisition_freshness_agent",
                "source_id": proposal.get("source_id"),
                "proposal_id": task_contract.trace_id,
                "policy_decision_id": policy_binding.decision_id,
                "authorization_request_id": policy_binding.request_id,
            },
            runtime.versions,
            **acquisition_lineage,
        )

        connector = SourceSyncConnector(
            progress_publisher=lambda source_id, payload: self._emit_task_lifecycle_event(
                runtime.mission_id,
                "SOURCE_SYNC_PROGRESS",
                "CTI-INF04",
                {"task_id": task_id, "source_id": source_id, "progress": payload},
                runtime.versions,
                **acquisition_lineage,
            )
        )
        try:
            execution = self.acquisition.execute_authorized(proposal, policy_decision, connector.execute)
            runtime.acquisition_actions += 1
            if proposal.get("source_id") not in runtime.acquisition_sources:
                runtime.acquisition_sources.append(str(proposal.get("source_id")))
            classification = str(execution.get("status") or "FAILED").upper()
            if classification == "SUCCESS":
                self._emit_task_lifecycle_event(
                    runtime.mission_id,
                    "SOURCE_SYNC_COMPLETED",
                    "CTI-A02",
                    {"task_id": task_id, "source_id": proposal.get("source_id"), "execution": execution},
                    runtime.versions,
                    **acquisition_lineage,
                )
            elif classification == "DEGRADED":
                outcome = execution.get("outcome") or {}
                proposal_cfg = (execution.get("proposal") or {}).get("source_sync_config") or {}
                sync_status = str(outcome.get("sync_status") or "").upper()
                bounded_partial = bool(
                    sync_status == "PARTIAL"
                    and proposal_cfg.get("bounded_agent_refresh")
                )
                reason_code = "BOUNDED_SYNC_PARTIAL" if bounded_partial else "DEGRADED_SYNC_OUTCOME"
                self._emit_task_lifecycle_event(
                    runtime.mission_id,
                    "SOURCE_SYNC_DEGRADED",
                    "CTI-A02",
                    {
                        "task_id": task_id,
                        "source_id": proposal.get("source_id"),
                        "classification": classification,
                        "reason_code": reason_code,
                        "execution": execution,
                    },
                    runtime.versions,
                    severity="WARNING",
                    **acquisition_lineage,
                )
            else:
                self._emit_task_lifecycle_event(
                    runtime.mission_id,
                    "SOURCE_SYNC_FAILED",
                    "CTI-A02",
                    {"task_id": task_id, "source_id": proposal.get("source_id"), "classification": classification, "execution": execution},
                    runtime.versions,
                    severity="WARNING" if classification == "RATE_LIMITED" else "ERROR",
                    **acquisition_lineage,
                )
        except Exception as exc:
            runtime.acquisition_actions += 1
            self._emit_task_lifecycle_event(
                runtime.mission_id,
                "SOURCE_SYNC_FAILED",
                "CTI-A02",
                {"task_id": task_id, "source_id": proposal.get("source_id"), "classification": "TRANSIENT", "error": str(exc)},
                runtime.versions,
                severity="ERROR",
                **acquisition_lineage,
            )

    def _on_source_sync_completed(self, event: Dict[str, Any]) -> None:
        runtime = self._runtime(event.get("mission_id"))
        payload = event.get("payload") or {}
        task_id = payload.get("task_id")
        execution = payload.get("execution") or {}
        if task_id and self._task_is_revoked(runtime, str(task_id)):
            self._quarantine_revoked_task_result(
                runtime,
                str(task_id),
                "cti_acquisition_freshness_agent",
                output_key="acquisition",
            )
            return
        if task_id:
            self._update_task(task_id, "COMPLETED", output_refs=[str(payload.get("source_id"))])
        runtime.versions.state_version += 1
        runtime.task_states["cti_acquisition_freshness_agent"] = "COMPLETED"
        runtime.outputs["acquisition"] = {
            "status": "completed",
            "sources": list(runtime.acquisition_sources),
            "actions": runtime.acquisition_actions,
            "last_execution": execution,
        }
        max_actions = max(0, int(runtime.scan_payload.get("cti_acquisition_max_actions") or 1))
        if runtime.acquisition_actions < max_actions:
            self._emit_event(
                runtime.mission_id,
                "CTI_ACQUISITION_EVALUATE",
                self.COMPONENT_ID,
                {"reason": "MULTI_SOURCE_REFRESH"},
                runtime.versions,
            )
        else:
            self._schedule_pipeline_advance(runtime, "SOURCE_SYNC_COMPLETED")

    def _on_source_sync_degraded(self, event: Dict[str, Any]) -> None:
        """Handle non-fatal partial/degraded source acquisition.

        A bounded PARTIAL sync is expected when Governance or source policy
        limits ``max_pages``. It remains an incomplete acquisition, but it must
        not be converted into a source failure or SOURCE_DOWN reactive signal.
        """
        runtime = self._runtime(event.get("mission_id"))
        payload = event.get("payload") or {}
        task_id = payload.get("task_id")
        execution = payload.get("execution") or {}
        source_id = str(payload.get("source_id") or "")
        reason_code = str(payload.get("reason_code") or "DEGRADED_SYNC_OUTCOME")

        if task_id and self._task_is_revoked(runtime, str(task_id)):
            self._quarantine_revoked_task_result(
                runtime,
                str(task_id),
                "cti_acquisition_freshness_agent",
                output_key="acquisition",
            )
            return

        if task_id:
            self._update_task(
                task_id,
                "DEGRADED",
                output_refs=[source_id] if source_id else [],
                error=None,
            )

        runtime.versions.state_version += 1
        allow_degraded = bool(runtime.scan_payload.get("allow_degraded_acquisition", True))
        runtime.task_states["cti_acquisition_freshness_agent"] = (
            "DEGRADED_ALLOWED" if allow_degraded else "FAILED"
        )
        runtime.outputs["acquisition"] = {
            "status": "degraded" if allow_degraded else "failed",
            "sources": list(runtime.acquisition_sources),
            "actions": runtime.acquisition_actions,
            "reason_code": reason_code,
            "last_execution": execution,
        }

        if not allow_degraded:
            self._fail_mission(
                runtime,
                f"CTI source acquisition degraded but degraded acquisition is disabled: {payload}",
            )
            return

        # Do not emit SOURCE_DOWN or increment reactive failure semantics. The
        # acquisition is incomplete but usable, so advance the dependency DAG.
        self._schedule_pipeline_advance(runtime, "SOURCE_SYNC_DEGRADED")

    def _on_source_sync_failed(self, event: Dict[str, Any]) -> None:
        runtime = self._runtime(event.get("mission_id"))
        payload = event.get("payload") or {}
        task_id = payload.get("task_id")
        if task_id and self._task_is_revoked(runtime, str(task_id)):
            self._quarantine_revoked_task_result(
                runtime,
                str(task_id),
                "cti_acquisition_freshness_agent",
                output_key="acquisition",
            )
            return
        if task_id:
            self._update_task(task_id, "FAILED", error=payload.get("error") or str(payload.get("classification") or "SOURCE_SYNC_FAILED"))
        runtime.versions.state_version += 1
        allow_degraded = runtime.scan_payload.get("allow_degraded_acquisition", True)
        runtime.task_states["cti_acquisition_freshness_agent"] = "DEGRADED_ALLOWED" if allow_degraded else "FAILED"
        runtime.outputs["acquisition"] = {
            "status": "degraded" if allow_degraded else "failed",
            "sources": list(runtime.acquisition_sources),
            "actions": runtime.acquisition_actions,
            "failure": payload,
        }
        classification = str(payload.get("classification") or "TRANSIENT").upper()
        reactive_type = "RATE_LIMIT_REACHED" if classification == "RATE_LIMITED" else "SOURCE_DOWN"
        runtime.pending_reactive = self.handle_reactive_event(
            runtime.mission_id,
            {"event_type": reactive_type, "source_id": payload.get("source_id"), "task_id": task_id},
            runtime.versions,
        )
        if not allow_degraded:
            self._fail_mission(runtime, f"CTI source acquisition failed: {payload}")
            return
        self._schedule_pipeline_advance(runtime, "SOURCE_SYNC_DEGRADED")

    def _on_pipeline_advance(self, event: Dict[str, Any]) -> None:
        runtime = self._runtime(event.get("mission_id"))
        if runtime.status in self.TERMINAL_STATES:
            return

        # Normalize absence of raw CTI as an explicit NOT_REQUIRED state. The
        # local NVD/CPE/MITRE source sync updates VulnDesk knowledge tables and
        # does not fabricate RawCTIEnvelope objects.
        if "normalization_provenance_service" not in runtime.task_states:
            raw_envelopes = list(runtime.scan_payload.get("raw_cti_envelopes") or [])
            if not raw_envelopes:
                runtime.task_states["normalization_provenance_service"] = "NOT_REQUIRED"
                runtime.outputs["normalization"] = {"status": "not_required", "results": []}

        next_component = self._next_component(runtime)
        if next_component is None:
            # If all components are in accepted terminal states but PIP did not
            # finalize, the workflow is structurally inconsistent.
            if runtime.task_states.get("pip_assembly_validation_service") in self.ACCEPTED_DEPENDENCY_STATES:
                self._finalize_from_pip(runtime)
            return

        if next_component == "attack_path_reasoning_agent" and not self.registry.is_enabled(next_component):
            runtime.task_states[next_component] = "SKIPPED_OPTIONAL"
            runtime.outputs["attack_path"] = {"status": "skipped", "optional_component": True, "paths": []}
            self._schedule_pipeline_advance(runtime, "OPTIONAL_ATTACK_PATH_DISABLED")
            return

        spec = self._task_spec(runtime, next_component)
        if spec is None:
            self._fail_mission(runtime, f"No task specification for {next_component}")
            return

        proposal = self._deliberative_proposal(
            runtime.mission_id,
            runtime.plan_id,
            runtime.versions,
            next_component,
            spec["task_type"],
            spec["input_refs"],
            runtime=runtime,
        )
        selected = self._arbitrate(runtime, runtime.pending_reactive, proposal)
        if selected.get("proposal_kind") == "REACTIVE":
            runtime.pending_reactive = None
            self._set_proposal_status(proposal.get("proposal_id"), "SUPERSEDED")
            self._apply_reactive_action(runtime, selected)
            return

        if self._proposal_is_stale(proposal, runtime):
            self._set_proposal_status(proposal.get("proposal_id"), "STALE")
            self._replan(runtime, "STALE_DELIBERATIVE_PROPOSAL")
            self._schedule_pipeline_advance(runtime, "STALE_PROPOSAL_REPLANNED")
            return

        guard = self._guard(next_component, runtime.task_states, runtime.policy_context)
        if guard["decision"] == "DENY":
            runtime.task_states[next_component] = "DENIED"
            self._set_proposal_status(proposal.get("proposal_id"), "DENIED", guard_decision="DENY")
            self._fail_mission(runtime, f"Task {next_component} denied by guard: {guard['reasons']}")
            return
        if guard["decision"] == "DEFER":
            self._set_proposal_status(proposal.get("proposal_id"), "DEFERRED", guard_decision="DEFER")
            return

        task_id = new_id("task")
        task_contract = self._commit_task(
            task_id,
            proposal,
            guard,
            runtime.mission_id,
            runtime.plan_id,
            runtime.versions,
            next_component,
            spec["task_type"],
            spec["input_refs"],
        )
        lifecycle_lineage = self._task_lineage_from_contract(task_contract)
        runtime.task_states[next_component] = "RUNNING"
        runtime.task_component[task_id] = next_component
        runtime.task_output_key[task_id] = spec["output_key"]
        self._update_task(task_id, "RUNNING")
        self._emit_task_lifecycle_event(
            runtime.mission_id,
            "TASK_DISPATCHED",
            self.COMPONENT_ID,
            {"task_id": task_id, "component": next_component, "proposal_id": proposal.get("proposal_id")},
            runtime.versions,
            **lifecycle_lineage,
        )

        try:
            result = spec["runner"](task_id)
            runtime.pending_results[task_id] = result
            self._emit_task_lifecycle_event(
                runtime.mission_id,
                "TASK_COMPLETED",
                next_component,
                {"task_id": task_id, "component": next_component, "output_refs": self._output_refs(result)},
                runtime.versions,
                **lifecycle_lineage,
            )
        except Exception as exc:
            self._emit_task_lifecycle_event(
                runtime.mission_id,
                "TASK_FAILED",
                next_component,
                {"task_id": task_id, "component": next_component, "error": str(exc)},
                runtime.versions,
                severity="ERROR",
                **lifecycle_lineage,
            )

    def _on_task_completed(self, event: Dict[str, Any]) -> None:
        runtime = self._runtime(event.get("mission_id"))
        payload = event.get("payload") or {}
        task_id = payload.get("task_id")
        component = payload.get("component") or runtime.task_component.get(task_id)
        if not task_id or not component:
            return
        output_key = runtime.task_output_key.get(task_id) or self._output_key(component)
        if self._task_is_revoked(runtime, str(task_id)):
            self._quarantine_revoked_task_result(
                runtime,
                str(task_id),
                str(component),
                output_key=output_key,
            )
            return
        result = runtime.pending_results.pop(task_id, {})
        runtime.outputs[output_key] = result
        runtime.task_states[component] = "COMPLETED"
        runtime.versions.state_version += 1
        self._update_task(task_id, "COMPLETED", output_refs=self._output_refs(result))

        if component == "pip_assembly_validation_service":
            self._finalize_from_pip(runtime)
            return
        self._schedule_pipeline_advance(runtime, f"{component}:COMPLETED")

    def _on_task_failed(self, event: Dict[str, Any]) -> None:
        runtime = self._runtime(event.get("mission_id"))
        payload = event.get("payload") or {}
        task_id = payload.get("task_id")
        component = payload.get("component") or runtime.task_component.get(task_id)
        error = str(payload.get("error") or "TASK_FAILED")
        if task_id:
            self._update_task(task_id, "FAILED", error=error)
        if not component:
            self._fail_mission(runtime, error)
            return

        runtime.task_states[component] = "FAILED"
        runtime.versions.state_version += 1
        runtime.retries[component] = int(runtime.retries.get(component) or 0) + 1
        max_retries = max(0, int(runtime.scan_payload.get("cti_task_max_retries") or 1))
        if runtime.retries[component] > max_retries:
            self._fail_mission(runtime, f"{component} failed after {runtime.retries[component]} attempt(s): {error}")
            return

        runtime.pending_reactive = self.handle_reactive_event(
            runtime.mission_id,
            {"event_type": "TASK_FAILED", "task_id": task_id, "component": component, "error": error},
            runtime.versions,
        )
        self._schedule_pipeline_advance(runtime, "TASK_FAILED_REACTIVE_ARBITRATION")

    def _on_event_handler_failed(self, event: Dict[str, Any]) -> None:
        mission_id = event.get("mission_id")
        if not mission_id:
            return
        runtime = self._runtimes.get(str(mission_id))
        if runtime is None or runtime.status in self.TERMINAL_STATES:
            return
        payload = event.get("payload") or {}
        self._fail_mission(
            runtime,
            f"Event handler failed for {payload.get('failed_event_type')} "
            f"subscriber={payload.get('subscriber_id')}: {payload.get('error')}",
        )

    def _on_reactive_trigger(self, event: Dict[str, Any]) -> None:
        event_type = str(event.get("event_type") or "").upper()
        payload = dict(event.get("payload") or {})
        mission_id = str(event.get("mission_id") or "")
        runtime = self._runtimes.get(mission_id)

        # Stage 2.7 revocation projection is durable and does not require an
        # in-memory mission. This matters when an aptsGSS outbox retries after a
        # VulnDesk restart. Other reactive events still require live runtime.
        if event_type == "AUTHORIZATION_REVOKED":
            projection = payload.get("cti_revocation_projection")
            if not isinstance(projection, dict):
                projection = self._project_authorization_revocation(
                    runtime,
                    mission_id=mission_id,
                    payload=payload,
                    source_component=str(event.get("source_component") or "EXTERNAL"),
                    event_id=str(event.get("event_id") or new_id("event")),
                )
                payload["cti_revocation_projection"] = projection
            if runtime is None:
                return
            if projection.get("mode") == "GLOBAL_EMERGENCY_STOP":
                runtime.policy_context["scope_allowed"] = False
        else:
            if runtime is None:
                raise KeyError(f"Mission runtime not found: {mission_id}")

        if event_type == "POLICY_CHANGED":
            if isinstance(payload.get("policy_context"), dict):
                runtime.policy_context.update(payload.get("policy_context") or {})
            if payload.get("policy_version"):
                runtime.versions.policy_version = str(payload.get("policy_version"))
        elif event_type == "HIGH_PRIORITY_REQUEST":
            if payload.get("priority") is not None:
                try:
                    runtime.mission_context["priority"] = int(payload.get("priority"))
                except Exception:
                    pass

        # Stage 2.8.6.1: terminalization must stop operational reactions, not
        # durable safety/audit projection. A revocation can race with the
        # pre-dispatch gate: authoritative revalidation may fail the mission
        # before the queued AUTHORIZATION_REVOKED ingress is handled. In that
        # case we still materialize the exact task-level causal chain, but we
        # deliberately do not replan, reschedule, or resurrect the mission.
        if event_type == "AUTHORIZATION_REVOKED" and runtime.status in self.TERMINAL_STATES:
            self._emit_revocation_task_projection_events(
                runtime,
                projection,
                trigger_event_id=str(event.get("event_id") or "") or None,
                upstream_event_id=(
                    str(event.get("upstream_event_id"))
                    if event.get("upstream_event_id") not in (None, "")
                    else None
                ),
            )
            return

        runtime.pending_reactive = self.handle_reactive_event(
            runtime.mission_id,
            {
                "event_type": event_type,
                "trigger_event_id": event.get("event_id"),
                "upstream_event_id": event.get("upstream_event_id"),
                **payload,
            },
            runtime.versions,
        )
        self._schedule_pipeline_advance(runtime, f"REACTIVE:{event_type}")

    # ------------------------------------------------------------------
    # Hybrid Reactive-Deliberative decision functions
    # ------------------------------------------------------------------
    def handle_reactive_event(
        self,
        mission_id: str,
        event: Dict[str, Any],
        versions: Optional[RuntimeVersions] = None,
    ) -> Dict[str, Any]:
        versions = versions or RuntimeVersions()
        event_type = str(event.get("event_type") or "").upper()
        rules = {
            "SOURCE_DOWN": ("PAUSE_SOURCE_AND_REQUEST_REPLAN", "CRITICAL_FAILURE"),
            "RATE_LIMIT_REACHED": ("BACKOFF_AND_REQUEST_REPLAN", "CRITICAL_FAILURE"),
            "FRESHNESS_THRESHOLD_EXCEEDED": ("URGENT_REFRESH_PROPOSAL", "FRESHNESS_EMERGENCY"),
            "PARSER_FAILED": ("ALTERNATE_PARSER_OR_QUARANTINE", "RECOVERY"),
            "TASK_TIMEOUT": ("RETRY_OR_REPLAN", "RECOVERY"),
            "TASK_FAILED": ("RETRY_OR_REPLAN", "RECOVERY"),
            "HIGH_PRIORITY_REQUEST": ("REPRIORITIZE_AND_REPLAN", "MISSION_PRIORITY"),
            "POLICY_CHANGED": ("REVALIDATE_PENDING_PROPOSALS", "SAFETY_POLICY"),
            "AUTHORIZATION_REVOKED": ("HANDLE_GRANULAR_REVOCATION", "SAFETY_POLICY"),
        }
        action, precedence = rules.get(event_type, ("NO_IMMEDIATE_ACTION", "DELIBERATIVE_OPTIMIZATION"))
        proposal = {
            "proposal_id": new_id("reactive"),
            "proposal_kind": "REACTIVE",
            "mission_id": mission_id,
            "event_type": event_type,
            "action_type": action,
            "precedence": precedence,
            "reason_code": event_type or "UNKNOWN_EVENT",
            "event_context": dict(event),
            "priority_utility": float(self.PRECEDENCE_SCORE.get(precedence, 10)),
            "state_version": versions.state_version,
            "plan_version": versions.plan_version,
            "policy_version": versions.policy_version,
            "authority_state": "PROPOSED_NOT_COMMITTED",
            "created_at": utcnow_iso(),
        }
        self._persist_proposal(proposal)
        return proposal

    def _deliberative_proposal(
        self,
        mission_id: str,
        plan_id: str,
        versions: RuntimeVersions,
        component_key: str,
        task_type: str,
        input_refs: List[Any],
        *,
        runtime: Optional[MissionRuntime] = None,
    ) -> Dict[str, Any]:
        proposal = {
            "proposal_id": new_id("delib"),
            "proposal_kind": "DELIBERATIVE",
            "mission_id": mission_id,
            "plan_id": plan_id,
            "action_type": "DISPATCH_TASK",
            "target_component": component_key,
            "task_type": task_type,
            "input_refs": [x for x in input_refs if x],
            "reason_code": "DEPENDENCY_DAG_READY",
            "precedence": "DELIBERATIVE_OPTIMIZATION",
            "priority_utility": self._task_priority_utility(runtime, component_key) if runtime else 0.5,
            "state_version": versions.state_version,
            "plan_version": versions.plan_version,
            "policy_version": versions.policy_version,
            "authority_state": "PROPOSED_NOT_COMMITTED",
            "created_at": utcnow_iso(),
        }
        self._persist_proposal(proposal)
        return proposal

    def _arbitrate(
        self,
        runtime: MissionRuntime,
        reactive: Optional[Dict[str, Any]],
        deliberative: Dict[str, Any],
    ) -> Dict[str, Any]:
        candidates = [deliberative]
        if reactive and reactive.get("action_type") != "NO_IMMEDIATE_ACTION":
            candidates.append(reactive)

        def score(p: Dict[str, Any]) -> Tuple[float, float, str]:
            precedence = self.PRECEDENCE_SCORE.get(str(p.get("precedence") or "DELIBERATIVE_OPTIMIZATION"), 10)
            utility = float(p.get("priority_utility") or 0.0)
            return float(precedence), utility, str(p.get("proposal_id") or "")

        selected = sorted(candidates, key=score, reverse=True)[0]
        self._persist_arbitration_trace(runtime, candidates, selected)
        self._set_proposal_status(selected.get("proposal_id"), "SELECTED")
        return selected

    def _apply_reactive_action(self, runtime: MissionRuntime, proposal: Dict[str, Any]) -> None:
        action = str(proposal.get("action_type") or "NO_IMMEDIATE_ACTION")
        context = proposal.get("event_context") or {}
        component = context.get("component")

        if action == "HANDLE_GRANULAR_REVOCATION":
            self._set_proposal_status(proposal.get("proposal_id"), "COMMITTED", guard_decision="DENY")
            projection = context.get("cti_revocation_projection") or {}

            # Global emergency-stop remains intentionally mission-wide. Exact
            # PolicyDecision revocation below is selective and never flips the
            # whole mission scope merely because one decision was revoked.
            if projection.get("mode") == "GLOBAL_EMERGENCY_STOP":
                runtime.status = "CANCELLED"
                runtime.last_error = "Global emergency stop revoked mission authorization"
                runtime.versions.state_version += 1
                self._update_mission(runtime.mission_id, "CANCELLED", runtime.versions, error=runtime.last_error)
                runtime.terminal_event.set()
                return

            verification_status = str(projection.get("verification_status") or "")
            if not (verification_status.startswith("VERIFIED_REVOKED") or verification_status.startswith("FAIL_CLOSED")):
                self._set_proposal_status(proposal.get("proposal_id"), "NOOP")
                self._emit_event(
                    runtime.mission_id,
                    "AUTHORIZATION_REVOCATION_REJECTED",
                    self.COMPONENT_ID,
                    {
                        "policy_decision_id": projection.get("decision_id") or context.get("decision_id"),
                        "revocation_id": projection.get("revocation_id"),
                        "verification_status": verification_status,
                        "verification_error": projection.get("verification_error"),
                    },
                    runtime.versions,
                    severity="WARNING",
                    causation_event_id=context.get("trigger_event_id"),
                    upstream_event_id=context.get("upstream_event_id"),
                )
                return

            decision_id = projection.get("decision_id") or context.get("decision_id")
            self._emit_revocation_task_projection_events(
                runtime,
                projection,
                trigger_event_id=context.get("trigger_event_id"),
                upstream_event_id=context.get("upstream_event_id"),
            )

            if int(projection.get("active_affected_count") or 0) > 0:
                self._replan(runtime, f"AUTHORIZATION_REVOKED:{decision_id}")
                self._emit_event(
                    runtime.mission_id,
                    "CTI_ACQUISITION_EVALUATE",
                    self.COMPONENT_ID,
                    {"reason": "POLICY_DECISION_REVOKED_REAUTHORIZE", "force": True},
                    runtime.versions,
                )
            return

        if action == "URGENT_REFRESH_PROPOSAL":
            self._set_proposal_status(proposal.get("proposal_id"), "COMMITTED", guard_decision="ALLOW")
            self._replan(runtime, proposal.get("reason_code") or "FRESHNESS_EMERGENCY")
            self._emit_event(
                runtime.mission_id,
                "CTI_ACQUISITION_EVALUATE",
                self.COMPONENT_ID,
                {"reason": "REACTIVE_FRESHNESS_REFRESH", "force": True},
                runtime.versions,
            )
            return

        if action in {
            "PAUSE_SOURCE_AND_REQUEST_REPLAN",
            "BACKOFF_AND_REQUEST_REPLAN",
            "REPRIORITIZE_AND_REPLAN",
            "REVALIDATE_PENDING_PROPOSALS",
        }:
            self._set_proposal_status(proposal.get("proposal_id"), "COMMITTED", guard_decision="ALLOW")
            self._replan(runtime, proposal.get("reason_code") or action)
            self._schedule_pipeline_advance(runtime, f"REACTIVE_APPLIED:{action}")
            return

        if action in {"RETRY_OR_REPLAN", "ALTERNATE_PARSER_OR_QUARANTINE"}:
            self._set_proposal_status(proposal.get("proposal_id"), "COMMITTED", guard_decision="ALLOW")
            self._replan(runtime, proposal.get("reason_code") or action)
            if component:
                runtime.task_states.pop(str(component), None)
            self._schedule_pipeline_advance(runtime, f"REACTIVE_RETRY:{component or 'unknown'}")
            return

        self._set_proposal_status(proposal.get("proposal_id"), "NOOP")
        self._schedule_pipeline_advance(runtime, "REACTIVE_NOOP")

    # ------------------------------------------------------------------
    # Component execution and DAG helpers
    # ------------------------------------------------------------------
    def _next_component(self, runtime: MissionRuntime) -> Optional[str]:
        for component in self.PIPELINE_ORDER:
            state = runtime.task_states.get(component)
            if state in self.ACCEPTED_DEPENDENCY_STATES:
                continue
            if state == "RUNNING":
                return None
            if state in {"FAILED", "DENIED"}:
                return component
            guard = self._guard(component, runtime.task_states, runtime.policy_context)
            if guard["decision"] == "ALLOW":
                return component
        return None

    def _task_spec(self, runtime: MissionRuntime, component: str) -> Optional[Dict[str, Any]]:
        payload = runtime.scan_payload
        mission_id = runtime.mission_id
        outputs = runtime.outputs

        if component == "normalization_provenance_service":
            raw_envelopes = list(payload.get("raw_cti_envelopes") or [])
            for envelope in raw_envelopes:
                envelope.setdefault("mission_id", mission_id)
            return {
                "task_type": "NORMALIZE_RAW_CTI",
                "input_refs": [str(e.get("artifact_id") or e.get("source_id") or "raw-envelope") for e in raw_envelopes],
                "output_key": "normalization",
                "runner": lambda task_id: {
                    "status": "completed",
                    "results": self.normalization.normalize_many(raw_envelopes, task_id=task_id),
                },
            }

        if component == "asset_profiling_cpe_resolution_service":
            return {
                "task_type": "PROFILE_ASSETS_AND_RESOLVE_CPE",
                "input_refs": [str(payload.get("scan_job_id") or payload.get("target_url") or mission_id)] + list(payload.get("evidence_refs") or []),
                "output_key": "asset_cpe",
                "runner": lambda task_id: self.asset_cpe.profile_scan(payload, mission_id),
            }

        asset_profiles = (outputs.get("asset_cpe") or {}).get("asset_profiles") or []
        cpe_claims = (outputs.get("asset_cpe") or {}).get("cpe_claims") or []
        correlations = (outputs.get("vulnerability") or {}).get("correlations") or []
        mappings = (outputs.get("attack_mapping") or {}).get("mappings") or []
        paths = (outputs.get("attack_path") or {}).get("paths") or []
        contexts = (outputs.get("threat_context") or {}).get("contexts") or []

        if component == "vulnerability_correlation_service":
            return {
                "task_type": "CORRELATE_VULNERABILITIES",
                "input_refs": [p.get("asset_profile_id") for p in asset_profiles if p.get("asset_profile_id")],
                "output_key": "vulnerability",
                "runner": lambda task_id: self.vulnerability.correlate(
                    mission_id,
                    asset_profiles,
                    cpe_claims,
                    local_candidates=payload.get("local_vulnerability_candidates") or [],
                ),
            }

        if component == "attack_mapping_service":
            return {
                "task_type": "MAP_TO_MITRE_ATTACK",
                "input_refs": [c.get("correlation_id") for c in correlations if c.get("correlation_id")],
                "output_key": "attack_mapping",
                "runner": lambda task_id: self.attack_mapping.map_correlations(
                    mission_id,
                    correlations,
                    endpoints=payload.get("endpoints") or [],
                ),
            }

        if component == "attack_path_reasoning_agent":
            return {
                "task_type": "PROPOSE_INTELLIGENCE_ATTACK_PATHS",
                "input_refs": [m.get("mapping_id") for m in mappings if m.get("mapping_id")],
                "output_key": "attack_path",
                "runner": lambda task_id: self.attack_path.reason(
                    mission_id,
                    asset_profiles,
                    correlations,
                    mappings,
                    policy_context=runtime.policy_context,
                ),
            }

        if component == "threat_context_service":
            return {
                "task_type": "SYNTHESIZE_THREAT_CONTEXT",
                "input_refs": [m.get("mapping_id") for m in mappings if m.get("mapping_id")],
                "output_key": "threat_context",
                "runner": lambda task_id: self.threat_context.synthesize(
                    mission_id,
                    asset_profiles,
                    correlations,
                    mappings,
                    attack_paths=paths,
                    mission_context=runtime.mission_context,
                ),
            }

        if component == "risk_prioritization_agent":
            return {
                "task_type": "PRIORITIZE_RISK_BDI",
                "input_refs": [c.get("correlation_id") for c in correlations if c.get("correlation_id")],
                "output_key": "risk",
                "runner": lambda task_id: self.risk.prioritize(
                    mission_id,
                    asset_profiles,
                    correlations,
                    attack_mappings=mappings,
                    attack_paths=paths,
                    threat_contexts=contexts,
                    mission_context=runtime.mission_context,
                    policy_context=runtime.policy_context,
                    feedback_context=payload.get("feedback_context") or {},
                    quality_context=self._quality_context(outputs),
                ),
            }

        if component == "pip_assembly_validation_service":
            normalized_results = (outputs.get("normalization") or {}).get("results") or []
            normalized_objects = [
                {
                    "normalized_object_id": r.get("normalized_object_id"),
                    "version": r.get("version"),
                    "canonical_schema_version": r.get("canonical_schema_version"),
                    "object_hash": r.get("object_hash"),
                    "status": r.get("status"),
                    "quality_metrics": r.get("quality_metrics"),
                    "normalized_object": r.get("normalized_object"),
                    "evidence_refs": [
                        (r.get("provenance_record") or {}).get("raw_artifact", {}).get("artifact_id")
                    ] if (r.get("provenance_record") or {}).get("raw_artifact", {}).get("artifact_id") else [],
                }
                for r in normalized_results
            ]
            provenance_records = [r.get("provenance_record") for r in normalized_results if r.get("provenance_record")]
            intentions = (outputs.get("risk") or {}).get("intentions") or []
            return {
                "task_type": "ASSEMBLE_AND_VALIDATE_PIP",
                "input_refs": [i.get("intention_id") for i in intentions if i.get("intention_id")],
                "output_key": "pip",
                "runner": lambda task_id: self.pip.build(
                    mission_id=mission_id,
                    mission_binding=self._mission_binding(payload, mission_id, runtime.policy_context, asset_profiles),
                    asset_profiles=asset_profiles,
                    cpe_claims=cpe_claims,
                    vulnerability_correlations=correlations,
                    attack_mappings=mappings,
                    attack_paths=paths,
                    threat_contexts=contexts,
                    risk_priorities=intentions,
                    normalized_objects=normalized_objects,
                    provenance_records=provenance_records,
                    assumptions_and_gaps=payload.get("assumptions_and_gaps") or [],
                    policy_context=runtime.policy_context,
                ),
            }
        return None

    def _guard(self, component_key: str, task_states: Dict[str, str], policy_context: Dict[str, Any]) -> Dict[str, Any]:
        reasons: List[str] = []
        if policy_context.get("scope_allowed") is False:
            reasons.append("POLICY_SCOPE_DENIED")
        if not self.registry.is_enabled(component_key):
            reasons.append("COMPONENT_DISABLED")
        for dep in DEPENDENCY_DAG.get(component_key, []):
            state = task_states.get(dep)
            if dep == "normalization_provenance_service" and state == "NOT_REQUIRED":
                continue
            if dep == "attack_path_reasoning_agent" and state in {"SKIPPED_OPTIONAL", "DEFERRED_OPTIONAL"}:
                continue
            if state not in self.ACCEPTED_DEPENDENCY_STATES:
                reasons.append(f"DEPENDENCY_NOT_READY:{dep}:{state}")
        if "POLICY_SCOPE_DENIED" in reasons or "COMPONENT_DISABLED" in reasons:
            decision = "DENY"
        elif reasons:
            decision = "DEFER"
        else:
            decision = "ALLOW"
        return {"decision": decision, "reasons": reasons, "checked_at": utcnow_iso()}

    # ------------------------------------------------------------------
    # Reactive replanning / stale-plan control
    # ------------------------------------------------------------------
    def _proposal_is_stale(self, proposal: Dict[str, Any], runtime: MissionRuntime) -> bool:
        return any([
            int(proposal.get("state_version") or 0) != int(runtime.versions.state_version),
            int(proposal.get("plan_version") or 0) != int(runtime.versions.plan_version),
            str(proposal.get("policy_version") or "") != str(runtime.versions.policy_version or ""),
        ])

    def _replan(self, runtime: MissionRuntime, reason: str) -> None:
        old_plan_id = runtime.plan_id
        if self.db.table_exists("cti_plans"):
            self.db.execute(
                """
                UPDATE cti_plans
                   SET status='INVALIDATED', invalidated_reason=%(reason)s, updated_at=CURRENT_TIMESTAMP
                 WHERE plan_id=%(plan_id)s
                """,
                {"plan_id": old_plan_id, "reason": reason},
            )
        runtime.versions.plan_version += 1
        runtime.versions.state_version += 1
        runtime.plan_id = new_id("plan")
        self._create_plan(runtime.plan_id, runtime.mission_id, runtime.versions)
        self._update_mission(runtime.mission_id, "REPLANNING", runtime.versions)
        self._emit_event(
            runtime.mission_id,
            "PLAN_REPLANNED",
            self.COMPONENT_ID,
            {"old_plan_id": old_plan_id, "new_plan_id": runtime.plan_id, "reason": reason},
            runtime.versions,
        )
        runtime.status = "RUNNING"
        self._update_mission(runtime.mission_id, "RUNNING", runtime.versions)

    # ------------------------------------------------------------------
    # Stage 2.7 granular PolicyDecision revocation
    # ------------------------------------------------------------------
    def _ensure_stage27_schema(self) -> None:
        if not self.db.table_exists("cti_task_contracts"):
            return
        has_column = getattr(self.db, "has_column", None)
        if callable(has_column) and not has_column("cti_task_contracts", "revocation_status"):
            raise ContractValidationError(
                "Stage 2.7 database migration is missing: run "
                "sql_update_cti_harmonized/06_granular_policydecision_revocation.sql"
            )

    def _tasks_for_policy_decision(self, mission_id: str, decision_id: str) -> List[Dict[str, Any]]:
        if not self.db.table_exists("cti_task_contracts"):
            return []
        self._ensure_stage27_schema()
        fetch_all = getattr(self.db, "fetch_all", None)
        if not callable(fetch_all):
            return []
        return fetch_all(
            """
            SELECT task_id, mission_id, assigned_component, task_type, status,
                   trace_id, authorization_mode, policy_decision_id, authorization_request_id,
                   policy_decision_hash, scope_contract_id, scope_version, policy_set_id,
                   pre_dispatch_revalidation_id, revocation_status, revoked_at
              FROM cti_task_contracts
             WHERE mission_id=%(mission_id)s
               AND policy_decision_id=%(decision_id)s
               AND authorization_mode='REQUIRED'
             ORDER BY id
            """,
            {"mission_id": mission_id, "decision_id": decision_id},
        )

    def _persist_revocation_ledger(self, projection: Dict[str, Any], payload: Dict[str, Any]) -> None:
        if not self.db.table_exists("cti_policy_decision_revocations"):
            return
        self.db.execute(
            """
            INSERT INTO cti_policy_decision_revocations
                (revocation_id, governance_event_id, local_event_id, decision_id, request_id,
                 mission_id, decision_hash, decision_status, revocation_scope, reason,
                 revoked_by, source_component, verification_status, verification_error,
                 affected_task_count, active_affected_count, payload_json,
                 revoked_at, received_at, verified_at)
            VALUES
                (%(revocation_id)s, %(governance_event_id)s, %(local_event_id)s,
                 %(decision_id)s, %(request_id)s, %(mission_id)s, %(decision_hash)s,
                 %(decision_status)s, %(revocation_scope)s, %(reason)s, %(revoked_by)s,
                 %(source_component)s, %(verification_status)s, %(verification_error)s,
                 %(affected_task_count)s, %(active_affected_count)s, %(payload_json)s,
                 %(revoked_at)s, CURRENT_TIMESTAMP, %(verified_at)s)
            ON DUPLICATE KEY UPDATE
                local_event_id=VALUES(local_event_id),
                verification_status=VALUES(verification_status),
                verification_error=VALUES(verification_error),
                affected_task_count=VALUES(affected_task_count),
                active_affected_count=VALUES(active_affected_count),
                payload_json=VALUES(payload_json),
                verified_at=VALUES(verified_at),
                updated_at=CURRENT_TIMESTAMP
            """,
            {
                "revocation_id": projection.get("revocation_id"),
                "governance_event_id": projection.get("governance_event_id"),
                "local_event_id": projection.get("local_event_id"),
                "decision_id": projection.get("decision_id"),
                "request_id": projection.get("request_id"),
                "mission_id": projection.get("mission_id"),
                "decision_hash": projection.get("decision_hash"),
                "decision_status": projection.get("decision_status"),
                "revocation_scope": projection.get("mode"),
                "reason": projection.get("reason"),
                "revoked_by": projection.get("revoked_by"),
                "source_component": projection.get("source_component"),
                "verification_status": projection.get("verification_status"),
                "verification_error": projection.get("verification_error"),
                "affected_task_count": projection.get("affected_task_count") or 0,
                "active_affected_count": projection.get("active_affected_count") or 0,
                "payload_json": to_json(payload),
                "revoked_at": to_db_datetime(projection.get("revoked_at")),
                "verified_at": to_db_datetime(projection.get("verified_at")),
            },
        )

    def _project_authorization_revocation(
        self,
        runtime: Optional[MissionRuntime],
        *,
        mission_id: str,
        payload: Dict[str, Any],
        source_component: str,
        event_id: str,
    ) -> Dict[str, Any]:
        """Project one governance revocation into exact TaskContract bindings.

        The event is a trigger, not the source of truth. For a decision-scoped
        revocation we retrieve current authoritative state from aptsGSS. If that
        verification is temporarily unavailable, already-bound tasks fail closed.
        Unrelated decisions are never invalidated.
        """
        event_payload = dict(payload or {})
        governance_event_id = str(event_payload.get("governance_event_id") or "") or None
        revocation_id = str(event_payload.get("revocation_id") or governance_event_id or event_id)
        reason = str(event_payload.get("reason") or "AUTHORIZATION_REVOKED")
        revoked_at = str(event_payload.get("revoked_at") or utcnow_iso())

        if bool(event_payload.get("emergency_stop")) or str(event_payload.get("revocation_scope") or "").upper() == "GLOBAL_EMERGENCY_STOP":
            projection = {
                "mode": "GLOBAL_EMERGENCY_STOP",
                "revocation_id": revocation_id,
                "governance_event_id": governance_event_id,
                "local_event_id": event_id,
                "mission_id": mission_id,
                "decision_id": None,
                "request_id": None,
                "decision_hash": None,
                "decision_status": None,
                "reason": reason,
                "revoked_by": event_payload.get("revoked_by"),
                "revoked_at": revoked_at,
                "source_component": source_component,
                "verification_status": "GLOBAL_EMERGENCY_STOP",
                "verification_error": None,
                "verified_at": utcnow_iso(),
                "affected_task_count": 0,
                "active_affected_count": 0,
                "tasks": [],
            }
            self._persist_revocation_ledger(projection, event_payload)
            return projection

        decision_id = str(event_payload.get("decision_id") or "").strip()
        if not decision_id:
            projection = {
                "mode": "POLICY_DECISION",
                "revocation_id": revocation_id,
                "governance_event_id": governance_event_id,
                "local_event_id": event_id,
                "mission_id": mission_id,
                "decision_id": None,
                "request_id": event_payload.get("request_id"),
                "decision_hash": event_payload.get("decision_hash"),
                "decision_status": event_payload.get("decision_status"),
                "reason": reason,
                "revoked_by": event_payload.get("revoked_by"),
                "revoked_at": revoked_at,
                "source_component": source_component,
                "verification_status": "REJECTED_MISSING_DECISION_ID",
                "verification_error": "AUTHORIZATION_REVOKED event has no decision_id",
                "verified_at": None,
                "affected_task_count": 0,
                "active_affected_count": 0,
                "tasks": [],
            }
            self._persist_revocation_ledger(projection, event_payload)
            return projection

        verification_status = "UNVERIFIED"
        verification_error = None
        verified_at = None
        authoritative: Dict[str, Any] = {}
        try:
            authoritative = self.governance.get_policy_decision(
                decision_id,
                expected_mission_id=mission_id,
                expected_scope_contract_id=(
                    str(event_payload.get("scope_contract_id"))
                    if event_payload.get("scope_contract_id") not in (None, "")
                    else None
                ),
            )
            authoritative_status = str(authoritative.get("decision_status") or "").upper()
            verified_at = utcnow_iso()
            if authoritative_status == "REVOKED":
                verification_status = "VERIFIED_REVOKED"
                supplied_hash = str(event_payload.get("decision_hash") or "").lower()
                authoritative_hash = str(authoritative.get("decision_hash") or "").lower()
                if supplied_hash and authoritative_hash and supplied_hash != authoritative_hash:
                    verification_status = "VERIFIED_REVOKED_EVENT_HASH_MISMATCH"
            else:
                verification_status = f"REJECTED_AUTHORITATIVE_STATUS_{authoritative_status or 'UNKNOWN'}"
        except GovernanceClientError as exc:
            verification_status = "FAIL_CLOSED_GOVERNANCE_UNAVAILABLE"
            verification_error = str(exc)

        tasks = self._tasks_for_policy_decision(mission_id, decision_id)
        should_invalidate = verification_status.startswith("VERIFIED_REVOKED") or verification_status.startswith("FAIL_CLOSED")
        projected_tasks: List[Dict[str, Any]] = []
        active_affected = 0

        authoritative_hash = str(authoritative.get("decision_hash") or event_payload.get("decision_hash") or "") or None
        decision_status = str(authoritative.get("decision_status") or event_payload.get("decision_status") or "") or None
        request_id = authoritative.get("request_id") or event_payload.get("request_id")
        verified_flag = 1 if verification_status.startswith("VERIFIED_REVOKED") else 0

        for task in tasks:
            prior_status = str(task.get("status") or "").upper()
            task_id = str(task.get("task_id") or "")
            if prior_status in {"COMMITTED", "RUNNING"}:
                active_affected += 1
            projected_tasks.append({
                "task_id": task_id,
                "assigned_component": task.get("assigned_component"),
                "prior_status": prior_status,
                "trace_id": task.get("trace_id"),
                "proposal_id": task.get("trace_id"),
                "policy_decision_id": task.get("policy_decision_id") or decision_id,
                "authorization_request_id": task.get("authorization_request_id") or request_id,
                "revalidation_id": task.get("pre_dispatch_revalidation_id"),
                "binding_hash_matches": (
                    not authoritative_hash
                    or str(task.get("policy_decision_hash") or "").lower() == authoritative_hash.lower()
                ),
            })
            if not should_invalidate:
                continue
            self.db.execute(
                """
                UPDATE cti_task_contracts
                   SET revocation_id=%(revocation_id)s,
                       revocation_event_id=%(revocation_event_id)s,
                       revocation_status=%(revocation_status)s,
                       revocation_reason=%(revocation_reason)s,
                       revoked_by=%(revoked_by)s,
                       revocation_decision_status=%(decision_status)s,
                       revocation_decision_hash=%(decision_hash)s,
                       revoked_at=%(revoked_at)s,
                       revocation_received_at=COALESCE(revocation_received_at,CURRENT_TIMESTAMP),
                       revocation_verified_at=CASE WHEN %(verified)s=1 THEN %(verified_at)s ELSE revocation_verified_at END,
                       dispatch_blocked_at=CASE WHEN status='COMMITTED' THEN COALESCE(dispatch_blocked_at,CURRENT_TIMESTAMP) ELSE dispatch_blocked_at END,
                       finished_at=CASE WHEN status='COMMITTED' THEN COALESCE(finished_at,CURRENT_TIMESTAMP) ELSE finished_at END,
                       status=CASE
                           WHEN status='COMMITTED' THEN 'BLOCKED_REVOKED'
                           WHEN status='RUNNING' THEN 'REVOCATION_PENDING_STOP'
                           ELSE status
                       END,
                       error_text=CASE
                           WHEN status IN ('COMMITTED','RUNNING') THEN %(error_text)s
                           ELSE error_text
                       END,
                       updated_at=CURRENT_TIMESTAMP
                 WHERE task_id=%(task_id)s
                   AND policy_decision_id=%(decision_id)s
                """,
                {
                    "task_id": task_id,
                    "decision_id": decision_id,
                    "revocation_id": revocation_id,
                    "revocation_event_id": governance_event_id or event_id,
                    "revocation_status": verification_status,
                    "revocation_reason": reason,
                    "revoked_by": event_payload.get("revoked_by"),
                    "decision_status": decision_status or "REVOKED",
                    "decision_hash": authoritative_hash,
                    "revoked_at": to_db_datetime(revoked_at),
                    "verified": verified_flag,
                    "verified_at": to_db_datetime(verified_at),
                    "error_text": f"Authorization revoked for PolicyDecision {decision_id}: {reason}",
                },
            )

        projection = {
            "mode": "POLICY_DECISION",
            "revocation_id": revocation_id,
            "governance_event_id": governance_event_id,
            "local_event_id": event_id,
            "mission_id": mission_id,
            "decision_id": decision_id,
            "request_id": request_id,
            "decision_hash": authoritative_hash,
            "decision_status": decision_status,
            "reason": reason,
            "revoked_by": event_payload.get("revoked_by"),
            "revoked_at": revoked_at,
            "source_component": source_component,
            "verification_status": verification_status,
            "verification_error": verification_error,
            "verified_at": verified_at,
            "affected_task_count": len(tasks),
            "active_affected_count": active_affected if should_invalidate else 0,
            "tasks": projected_tasks,
        }
        self._persist_revocation_ledger(projection, event_payload)

        if runtime is not None and should_invalidate:
            with self._lock:
                runtime.revoked_policy_decisions[decision_id] = dict(projection)
                for task in projected_tasks:
                    task_id = str(task.get("task_id") or "")
                    prior_status = str(task.get("prior_status") or "").upper()
                    component = str(task.get("assigned_component") or "")
                    if task_id:
                        runtime.revoked_task_ids.add(task_id)
                    if component and prior_status == "COMMITTED":
                        runtime.task_states[component] = "DENIED"
                    elif component and prior_status == "RUNNING":
                        runtime.task_states[component] = "REVOCATION_PENDING_STOP"
        return projection

    def _emit_revocation_task_projection_events(
        self,
        runtime: MissionRuntime,
        projection: Dict[str, Any],
        *,
        trigger_event_id: Optional[str],
        upstream_event_id: Optional[str],
    ) -> int:
        """Materialize task-level revocation causality without changing authority.

        Stage 2.8.6.1 uses this helper both for normal reactive handling and
        terminal-mission audit projection. Operational replanning remains in
        ``_apply_reactive_action``; this helper only emits durable task events.
        """
        verification_status = str(projection.get("verification_status") or "")
        if not (
            verification_status.startswith("VERIFIED_REVOKED")
            or verification_status.startswith("FAIL_CLOSED")
        ):
            return 0

        decision_id = projection.get("decision_id")
        emitted = 0
        for task in projection.get("tasks") or []:
            task_id = task.get("task_id")
            prior_status = str(task.get("prior_status") or "").upper()
            component_key = task.get("assigned_component")
            event_payload = {
                "task_id": task_id,
                "component": component_key,
                "policy_decision_id": decision_id,
                "revocation_id": projection.get("revocation_id"),
                "verification_status": projection.get("verification_status"),
                "reason": projection.get("reason"),
            }
            revocation_lineage = self._task_lineage_from_snapshot(task)
            revoked_event_id = self._emit_task_lifecycle_event(
                runtime.mission_id,
                "TASK_AUTHORIZATION_REVOKED",
                self.COMPONENT_ID,
                event_payload,
                runtime.versions,
                severity="CRITICAL" if prior_status in {"COMMITTED", "RUNNING"} else "WARNING",
                causation_event_id=trigger_event_id,
                upstream_event_id=upstream_event_id,
                **revocation_lineage,
            )
            emitted += 1
            if prior_status == "COMMITTED":
                self._emit_task_lifecycle_event(
                    runtime.mission_id,
                    "TASK_DISPATCH_BLOCKED",
                    self.COMPONENT_ID,
                    {**event_payload, "reason_codes": ["POLICY_DECISION_REVOKED"]},
                    runtime.versions,
                    severity="CRITICAL",
                    causation_event_id=revoked_event_id,
                    upstream_event_id=upstream_event_id,
                    **revocation_lineage,
                )
                emitted += 1
            elif prior_status == "RUNNING":
                self._emit_task_lifecycle_event(
                    runtime.mission_id,
                    "TASK_REVOCATION_STOP_REQUESTED",
                    self.COMPONENT_ID,
                    event_payload,
                    runtime.versions,
                    severity="CRITICAL",
                    causation_event_id=revoked_event_id,
                    upstream_event_id=upstream_event_id,
                    **revocation_lineage,
                )
                emitted += 1
        return emitted

    def _task_revocation_snapshot(self, task_id: str) -> Dict[str, Any]:
        if not self.db.table_exists("cti_task_contracts"):
            return {}
        self._ensure_stage27_schema()
        fetch_one = getattr(self.db, "fetch_one", None)
        if not callable(fetch_one):
            return {}
        row = fetch_one(
            """
            SELECT task_id, status, policy_decision_id, revocation_id,
                   revocation_status, revocation_reason, revoked_at
              FROM cti_task_contracts
             WHERE task_id=%(task_id)s
             LIMIT 1
            """,
            {"task_id": task_id},
        )
        return dict(row or {})

    def _task_is_revoked(self, runtime: MissionRuntime, task_id: str) -> bool:
        if task_id in runtime.revoked_task_ids:
            return True
        row = self._task_revocation_snapshot(task_id)
        status = str(row.get("revocation_status") or "").upper()
        return status.startswith("VERIFIED_REVOKED") or status.startswith("FAIL_CLOSED")

    def _transition_authorized_task_to_running(self, task_id: str) -> bool:
        """Atomic COMMITTED->RUNNING transition guarded by Stage 2.7 revocation state."""
        if not self.db.table_exists("cti_task_contracts"):
            return True
        self._ensure_stage27_schema()
        affected = self.db.execute(
            """
            UPDATE cti_task_contracts
               SET status='RUNNING',
                   started_at=COALESCE(started_at,CURRENT_TIMESTAMP),
                   updated_at=CURRENT_TIMESTAMP
             WHERE task_id=%(task_id)s
               AND status='COMMITTED'
               AND (revocation_status IS NULL OR revocation_status='')
               AND revoked_at IS NULL
            """,
            {"task_id": task_id},
        )
        return int(affected or 0) > 0

    def _finalize_revoked_task(self, task_id: str, *, error: Optional[str] = None) -> None:
        if not self.db.table_exists("cti_task_contracts"):
            return
        self._ensure_stage27_schema()
        self.db.execute(
            """
            UPDATE cti_task_contracts
               SET status='CANCELLED_REVOKED',
                   error_text=COALESCE(%(error)s,error_text),
                   finished_at=COALESCE(finished_at,CURRENT_TIMESTAMP),
                   updated_at=CURRENT_TIMESTAMP
             WHERE task_id=%(task_id)s
               AND revocation_status IS NOT NULL
            """,
            {"task_id": task_id, "error": error},
        )

    def _quarantine_revoked_task_result(
        self,
        runtime: MissionRuntime,
        task_id: str,
        component: str,
        *,
        output_key: Optional[str] = None,
    ) -> None:
        snapshot = self._task_revocation_snapshot(task_id)
        reason = snapshot.get("revocation_reason") or "PolicyDecision revoked"
        self._finalize_revoked_task(task_id, error=str(reason))
        runtime.pending_results.pop(task_id, None)
        runtime.task_states[component] = "DENIED"
        if output_key:
            runtime.outputs[output_key] = {
                "status": "revoked",
                "task_id": task_id,
                "policy_decision_id": snapshot.get("policy_decision_id"),
                "revocation_id": snapshot.get("revocation_id"),
                "reason": reason,
                "result_accepted": False,
            }
        self._emit_event(
            runtime.mission_id,
            "TASK_RESULT_QUARANTINED",
            self.COMPONENT_ID,
            {
                "task_id": task_id,
                "component": component,
                "policy_decision_id": snapshot.get("policy_decision_id"),
                "revocation_id": snapshot.get("revocation_id"),
                "reason": reason,
            },
            runtime.versions,
            severity="CRITICAL",
        )

    # ------------------------------------------------------------------
    # Stage 2.6 pre-dispatch authorization revalidation
    # ------------------------------------------------------------------
    def _wait_pre_dispatch_test_gate(
        self,
        runtime: MissionRuntime,
        contract: TaskContract,
    ) -> bool:
        """Optional deterministic barrier for Stage 2.6 negative E2E tests.

        Production behavior is unchanged because the gate is disabled unless
        ``CTI_STAGE26_NEGATIVE_TEST_GATE`` is explicitly set to a truthy value.
        When enabled, the externally-authorized acquisition task pauses after
        TaskContract commit and before authoritative revalidation. The operator
        releases it by creating a mission-specific file:

        ``.stage26-release-<mission_id>.gate``

        The default gate directory is the VulnDesk project root. A custom
        directory can be supplied with ``CTI_STAGE26_NEGATIVE_TEST_GATE_DIR``.
        ``CTI_STAGE26_NEGATIVE_TEST_GATE_TIMEOUT_SECONDS`` defaults to 300.

        The barrier is strictly test-only: it neither changes nor grants
        authorization. Timeout returns ``False`` so the caller fails closed.
        """
        enabled = str(os.getenv("CTI_STAGE26_NEGATIVE_TEST_GATE") or "").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            return True

        if contract.authorization_mode != AUTHORIZATION_REQUIRED:
            return True

        raw_timeout = str(
            os.getenv("CTI_STAGE26_NEGATIVE_TEST_GATE_TIMEOUT_SECONDS") or "300"
        ).strip()
        try:
            timeout_seconds = max(0.1, float(raw_timeout))
        except ValueError:
            timeout_seconds = 300.0

        raw_gate_dir = str(os.getenv("CTI_STAGE26_NEGATIVE_TEST_GATE_DIR") or "").strip()
        gate_dir = (
            Path(raw_gate_dir).expanduser().resolve()
            if raw_gate_dir
            else Path(__file__).resolve().parent.parent
        )
        gate_dir.mkdir(parents=True, exist_ok=True)
        release_file = gate_dir / f".stage26-release-{runtime.mission_id}.gate"

        # A mission-specific stale release file must not bypass the barrier.
        try:
            release_file.unlink(missing_ok=True)
        except OSError:
            pass

        self._emit_event(
            runtime.mission_id,
            "PRE_DISPATCH_TEST_GATE_WAITING",
            self.COMPONENT_ID,
            {
                "task_id": contract.task_id,
                "release_file": str(release_file),
                "timeout_seconds": timeout_seconds,
                "test_only": True,
            },
            runtime.versions,
            severity="WARNING",
        )

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if release_file.exists():
                try:
                    release_file.unlink(missing_ok=True)
                except OSError:
                    pass
                self._emit_event(
                    runtime.mission_id,
                    "PRE_DISPATCH_TEST_GATE_RELEASED",
                    self.COMPONENT_ID,
                    {
                        "task_id": contract.task_id,
                        "release_file": str(release_file),
                        "test_only": True,
                    },
                    runtime.versions,
                    severity="WARNING",
                )
                return True
            time.sleep(0.2)

        self._emit_event(
            runtime.mission_id,
            "PRE_DISPATCH_TEST_GATE_TIMEOUT",
            self.COMPONENT_ID,
            {
                "task_id": contract.task_id,
                "release_file": str(release_file),
                "timeout_seconds": timeout_seconds,
                "test_only": True,
            },
            runtime.versions,
            severity="CRITICAL",
        )
        return False

    def _pre_dispatch_revalidate(
        self,
        runtime: MissionRuntime,
        contract: TaskContract,
        binding: PolicyDecisionBinding,
    ) -> Dict[str, Any]:
        """Revalidate external authority after commit and immediately before use.

        A committed TaskContract is necessary but not sufficient for dispatch.
        This method asks the independent Governance Plane to validate the exact
        bound decision/request/hash against current decision lifecycle, scope,
        policy, request dimensions, and emergency-stop state.  Transport errors
        are converted into an INVALID result so dispatch remains fail-closed.
        """
        if contract.authorization_mode != AUTHORIZATION_REQUIRED:
            return {
                "status": "NOT_REQUIRED",
                "valid": True,
                "execution_authorized": False,
                "reason_codes": ["INTERNAL_TASK_NO_EXTERNAL_AUTHORITY_REQUIRED"],
                "task_id": contract.task_id,
                "checked_at": utcnow_iso(),
            }

        try:
            result = self.governance.revalidate_policy_decision(
                task_id=contract.task_id,
                decision_id=binding.decision_id,
                request_id=binding.request_id,
                mission_id=contract.mission_id,
                decision_hash=binding.decision_hash,
                scope_contract_id=binding.scope_contract_id,
                scope_version=binding.scope_version,
                policy_set_id=binding.policy_set_id,
                policy_version=binding.policy_version,
                subject_component=binding.subject_component,
                action_class=str(binding.action_class or ""),
                action_name=str(binding.action_name or ""),
                resource_type=str(binding.resource_type or ""),
                resource_value=str(binding.resource_value or ""),
                requested_by=self.COMPONENT_ID,
            )
        except GovernanceClientError as exc:
            result = {
                "revalidation_id": None,
                "status": "ERROR",
                "valid": False,
                "execution_authorized": False,
                "reason_codes": ["GOVERNANCE_REVALIDATION_UNAVAILABLE_FAIL_CLOSED"],
                "decision_id": binding.decision_id,
                "request_id": binding.request_id,
                "mission_id": contract.mission_id,
                "decision_hash": binding.decision_hash,
                "decision_status": binding.decision_status,
                "checked_at": utcnow_iso(),
                "authority": "aptsGSS",
                "authority_component": "GOV-PLANE",
                "error": str(exc),
            }

        valid = bool(result.get("valid")) and bool(result.get("execution_authorized"))
        result = dict(result)
        result["valid"] = valid
        result["task_id"] = contract.task_id

        self._persist_pre_dispatch_revalidation(contract.task_id, result)
        if valid:
            decision_event_id = self._emit_task_lifecycle_event(
                runtime.mission_id,
                "TASK_AUTHORIZATION_REVALIDATED",
                self.COMPONENT_ID,
                {
                    "task_id": contract.task_id,
                    "component": contract.assigned_component,
                    "policy_decision_id": binding.decision_id,
                    "authorization_request_id": binding.request_id,
                    "revalidation": result,
                },
                runtime.versions,
                upstream_event_id=result.get("governance_event_id"),
                **self._task_lineage_from_contract(
                    contract,
                    revalidation_id=result.get("revalidation_id"),
                ),
            )
        else:
            decision_event_id = self._emit_task_lifecycle_event(
                runtime.mission_id,
                "TASK_DISPATCH_BLOCKED",
                self.COMPONENT_ID,
                {
                    "task_id": contract.task_id,
                    "component": contract.assigned_component,
                    "policy_decision_id": binding.decision_id,
                    "authorization_request_id": binding.request_id,
                    "reason_codes": list(result.get("reason_codes") or []),
                    "revalidation": result,
                },
                runtime.versions,
                severity="CRITICAL",
                upstream_event_id=result.get("governance_event_id"),
                **self._task_lineage_from_contract(
                    contract,
                    revalidation_id=result.get("revalidation_id"),
                ),
            )

        self._persist_decision_audit_trace(
            mission_id=runtime.mission_id,
            versions=runtime.versions,
            decision_type="PRE_DISPATCH_REVALIDATION",
            lineage_trace_id=str(contract.trace_id),
            proposal_id=str(contract.trace_id),
            task_id=str(contract.task_id),
            policy_decision_id=binding.decision_id,
            authorization_request_id=binding.request_id,
            revalidation_id=(
                str(result.get("revalidation_id"))
                if result.get("revalidation_id") not in (None, "")
                else None
            ),
            observations={
                "authorization_mode": contract.authorization_mode,
                "assigned_component": contract.assigned_component,
                "task_type": contract.task_type,
            },
            selected_action={
                "action": "DISPATCH" if valid else "BLOCK_DISPATCH",
                "event_id": decision_event_id,
            },
            policy_decision={
                "authority": binding.authority,
                "authority_component": binding.authority_component,
                "decision_id": binding.decision_id,
                "request_id": binding.request_id,
                "decision_hash": binding.decision_hash,
                "decision_status": binding.decision_status,
                "scope_contract_id": binding.scope_contract_id,
                "scope_version": binding.scope_version,
                "policy_set_id": binding.policy_set_id,
                "policy_version": binding.policy_version,
                "governance_event_id": result.get("governance_event_id"),
            },
            execution_outcome={
                "event_id": decision_event_id,
                "event_type": "TASK_AUTHORIZATION_REVALIDATED" if valid else "TASK_DISPATCH_BLOCKED",
                "valid": valid,
                "revalidation": result,
                "upstream_event_id": result.get("governance_event_id"),
            },
            upstream_event_id=result.get("governance_event_id"),
            downstream_event_ref=decision_event_id,
            reason_code=(
                "PRE_DISPATCH_AUTHORIZATION_VALID"
                if valid else "PRE_DISPATCH_AUTHORIZATION_BLOCKED"
            ),
        )
        return result

    def _persist_pre_dispatch_revalidation(self, task_id: str, result: Dict[str, Any]) -> None:
        if not self.db.table_exists("cti_task_contracts"):
            return

        # Migration 05 adds these columns.  Fail fast on a real DbAdapter when
        # the migration has not been applied; test doubles without has_column
        # remain supported for isolated unit tests.
        has_column = getattr(self.db, "has_column", None)
        if callable(has_column) and not has_column("cti_task_contracts", "pre_dispatch_revalidation_status"):
            raise ContractValidationError(
                "Stage 2.6 database migration is missing: run "
                "sql_update_cti_harmonized/05_pre_dispatch_policydecision_revalidation.sql"
            )

        valid = bool(result.get("valid")) and bool(result.get("execution_authorized"))
        status = str(result.get("status") or ("VALID" if valid else "INVALID")).upper()
        reasons = [str(x) for x in (result.get("reason_codes") or [])]
        error_text = None if valid else "Pre-dispatch authorization blocked: " + ",".join(reasons)
        self.db.execute(
            """
            UPDATE cti_task_contracts
               SET pre_dispatch_revalidation_id=%(revalidation_id)s,
                   pre_dispatch_governance_event_id=%(governance_event_id)s,
                   pre_dispatch_revalidation_status=%(revalidation_status)s,
                   pre_dispatch_reason_codes_json=%(reason_codes_json)s,
                   pre_dispatch_decision_status=%(decision_status)s,
                   pre_dispatch_decision_hash=%(decision_hash)s,
                   pre_dispatch_scope_version=%(scope_version)s,
                   pre_dispatch_policy_version=%(policy_version)s,
                   pre_dispatch_revalidated_at=%(revalidated_at)s,
                   dispatch_authorized_at=CASE WHEN %(valid)s=1 THEN %(revalidated_at)s ELSE dispatch_authorized_at END,
                   dispatch_blocked_at=CASE WHEN %(valid)s=0 THEN %(revalidated_at)s ELSE dispatch_blocked_at END,
                   status=CASE
                       WHEN %(valid)s=1 THEN status
                       WHEN revocation_status LIKE 'VERIFIED_REVOKED%%'
                         OR revocation_status LIKE 'FAIL_CLOSED%%'
                         OR revoked_at IS NOT NULL
                       THEN 'BLOCKED_REVOKED'
                       ELSE 'BLOCKED_AUTHORIZATION'
                   END,
                   error_text=CASE
                       WHEN %(valid)s=1 THEN error_text
                       WHEN revocation_status LIKE 'VERIFIED_REVOKED%%'
                         OR revocation_status LIKE 'FAIL_CLOSED%%'
                         OR revoked_at IS NOT NULL
                       THEN COALESCE(error_text,%(error_text)s)
                       ELSE %(error_text)s
                   END,
                   updated_at=CURRENT_TIMESTAMP
             WHERE task_id=%(task_id)s
            """,
            {
                "task_id": task_id,
                "revalidation_id": result.get("revalidation_id"),
                "governance_event_id": result.get("governance_event_id"),
                "revalidation_status": status,
                "reason_codes_json": to_json(reasons),
                "decision_status": result.get("decision_status"),
                "decision_hash": result.get("decision_hash"),
                "scope_version": result.get("current_scope_version", result.get("scope_version")),
                "policy_version": result.get("current_policy_version", result.get("policy_version")),
                "revalidated_at": to_db_datetime(result.get("checked_at")) or to_db_datetime(utcnow_iso()),
                "valid": 1 if valid else 0,
                "error_text": error_text,
            },
        )

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def _commit_task(
        self,
        task_id: str,
        proposal: Dict[str, Any],
        guard: Dict[str, Any],
        mission_id: str,
        plan_id: str,
        versions: RuntimeVersions,
        component_key: str,
        task_type: str,
        input_refs: List[Any],
        *,
        authorization_mode: str = AUTHORIZATION_NOT_REQUIRED_INTERNAL,
        policy_decision_binding: Optional[PolicyDecisionBinding] = None,
    ) -> TaskContract:
        priority = int(round(float(proposal.get("priority_utility") or 0.5) * 100))
        contract = TaskContract(
            task_id=task_id,
            mission_id=mission_id,
            plan_id=plan_id,
            assigned_component=component_key,
            task_type=task_type,
            priority=priority,
            input_refs=[x for x in input_refs if x],
            local_guard=dict(guard),
            plan_version=versions.plan_version,
            policy_version=str(versions.policy_version or ""),
            state_version=versions.state_version,
            trace_id=str(proposal["proposal_id"]),
            authorization_mode=authorization_mode,
            governance=policy_decision_binding,
        )
        # Validate the complete contract before changing proposal state.  This
        # prevents a proposal from becoming COMMITTED when required authority
        # is absent, stale, malformed, or belongs to another mission/resource.
        contract.validate()

        if self.db.table_exists("cti_action_proposals"):
            self.db.execute(
                """
                UPDATE cti_action_proposals
                   SET status='COMMITTED', guard_decision=%(guard_decision)s,
                       committed_task_id=%(task_id)s, updated_at=CURRENT_TIMESTAMP
                 WHERE proposal_id=%(proposal_id)s
                """,
                {"guard_decision": guard["decision"], "task_id": task_id, "proposal_id": proposal["proposal_id"]},
            )
        governance = policy_decision_binding.as_dict() if policy_decision_binding else {}
        if self.db.table_exists("cti_task_contracts"):
            self.db.execute(
                """
                INSERT INTO cti_task_contracts
                    (task_id, mission_id, plan_id, assigned_component, task_type, priority,
                     input_refs_json, constraints_json, deadline, timeout_seconds, retry_policy_json,
                     success_criteria_json, plan_version, policy_version, state_version, trace_id,
                     authorization_mode, authorization_authority, authorization_authority_component,
                     authorization_governance_event_id, policy_decision_id, authorization_request_id, policy_decision_hash,
                     authorization_decision, authorization_status, authorization_valid_from,
                     authorization_valid_until, scope_contract_id, scope_version, policy_set_id,
                     approval_request_id, governance_action_class, governance_action_name,
                     governance_resource_type, governance_resource_value, governance_subject_component,
                     governance_reason_codes_json, governance_constraints_json, governance_request_json,
                     authorization_bound_at, status, created_at)
                VALUES
                    (%(task_id)s, %(mission_id)s, %(plan_id)s, %(assigned_component)s,
                     %(task_type)s, %(priority)s, %(input_refs_json)s, %(constraints_json)s, NULL, 300,
                     %(retry_policy_json)s, %(success_criteria_json)s, %(plan_version)s,
                     %(policy_version)s, %(state_version)s, %(trace_id)s,
                     %(authorization_mode)s, %(authorization_authority)s, %(authorization_authority_component)s,
                     %(authorization_governance_event_id)s, %(policy_decision_id)s, %(authorization_request_id)s, %(policy_decision_hash)s,
                     %(authorization_decision)s, %(authorization_status)s, %(authorization_valid_from)s,
                     %(authorization_valid_until)s, %(scope_contract_id)s, %(scope_version)s, %(policy_set_id)s,
                     %(approval_request_id)s, %(governance_action_class)s, %(governance_action_name)s,
                     %(governance_resource_type)s, %(governance_resource_value)s, %(governance_subject_component)s,
                     %(governance_reason_codes_json)s, %(governance_constraints_json)s, %(governance_request_json)s,
                     CURRENT_TIMESTAMP, 'COMMITTED', CURRENT_TIMESTAMP)
                """,
                {
                    "task_id": task_id,
                    "mission_id": mission_id,
                    "plan_id": plan_id,
                    "assigned_component": component_key,
                    "task_type": task_type,
                    "priority": priority,
                    "input_refs_json": to_json(contract.input_refs),
                    "constraints_json": to_json({
                        "authority_boundary": COMPONENT_BY_KEY.get(component_key).authority_boundary
                        if COMPONENT_BY_KEY.get(component_key) else None,
                        "local_guard": guard,
                    }),
                    "retry_policy_json": to_json(contract.retry_policy),
                    "success_criteria_json": to_json(contract.success_criteria),
                    "plan_version": versions.plan_version,
                    "policy_version": versions.policy_version,
                    "state_version": versions.state_version,
                    "trace_id": proposal["proposal_id"],
                    "authorization_mode": authorization_mode,
                    "authorization_authority": governance.get("authority"),
                    "authorization_authority_component": governance.get("authority_component"),
                    "authorization_governance_event_id": governance.get("governance_event_id"),
                    "policy_decision_id": governance.get("decision_id"),
                    "authorization_request_id": governance.get("request_id"),
                    "policy_decision_hash": governance.get("decision_hash"),
                    "authorization_decision": governance.get("decision"),
                    "authorization_status": governance.get("decision_status"),
                    "authorization_valid_from": to_db_datetime(governance.get("valid_from")),
                    "authorization_valid_until": to_db_datetime(governance.get("valid_until")),
                    "scope_contract_id": governance.get("scope_contract_id"),
                    "scope_version": governance.get("scope_version"),
                    "policy_set_id": governance.get("policy_set_id"),
                    "approval_request_id": governance.get("approval_request_id"),
                    "governance_action_class": governance.get("action_class"),
                    "governance_action_name": governance.get("action_name"),
                    "governance_resource_type": governance.get("resource_type"),
                    "governance_resource_value": governance.get("resource_value"),
                    "governance_subject_component": governance.get("subject_component"),
                    "governance_reason_codes_json": to_json(governance.get("reason_codes") or []),
                    "governance_constraints_json": to_json(governance.get("constraints") or {}),
                    "governance_request_json": to_json({
                        "action_class": governance.get("action_class"),
                        "action_name": governance.get("action_name"),
                        "resource_type": governance.get("resource_type"),
                        "resource_value": governance.get("resource_value"),
                        "subject_component": governance.get("subject_component"),
                    }) if governance else None,
                },
            )

        # Stage 2.8.4 -- a successful TaskContract commit becomes an explicit
        # lineage event.  The event carries only stable references/metadata; the
        # authoritative PolicyDecision remains owned by aptsGSS and the full
        # binding remains in cti_task_contracts.
        commit_event_id = self._emit_event(
            mission_id,
            "TASK_COMMITTED",
            self.COMPONENT_ID,
            {
                "task_id": task_id,
                "proposal_id": str(proposal["proposal_id"]),
                "plan_id": plan_id,
                "component": component_key,
                "task_type": task_type,
                "authorization_mode": authorization_mode,
                "policy_decision_id": governance.get("decision_id"),
                "authorization_request_id": governance.get("request_id"),
                "scope_contract_id": governance.get("scope_contract_id"),
                "scope_version": governance.get("scope_version"),
                "policy_set_id": governance.get("policy_set_id"),
                "policy_version": (
                    str(governance.get("policy_version"))
                    if governance.get("policy_version") is not None
                    else str(contract.policy_version or "")
                ),
                "status": "COMMITTED",
            },
            versions,
            trace_id=contract.trace_id,
            proposal_id=str(proposal["proposal_id"]),
            task_id=task_id,
            policy_decision_id=governance.get("decision_id"),
            authorization_request_id=governance.get("request_id"),
            upstream_event_id=governance.get("governance_event_id"),
        )
        self._remember_task_event(task_id, commit_event_id)
        self._persist_decision_audit_trace(
            mission_id=mission_id,
            versions=versions,
            decision_type="TASK_COMMIT",
            lineage_trace_id=str(contract.trace_id),
            proposal_id=str(proposal["proposal_id"]),
            task_id=task_id,
            policy_decision_id=governance.get("decision_id"),
            authorization_request_id=governance.get("request_id"),
            observations={
                "local_guard": guard,
                "authorization_mode": authorization_mode,
                "assigned_component": component_key,
                "task_type": task_type,
            },
            selected_action={
                "task_id": task_id,
                "proposal_id": str(proposal["proposal_id"]),
                "assigned_component": component_key,
                "task_type": task_type,
                "status": "COMMITTED",
            },
            policy_decision=(
                {
                    "authority": governance.get("authority"),
                    "authority_component": governance.get("authority_component"),
                    "decision_id": governance.get("decision_id"),
                    "request_id": governance.get("request_id"),
                    "decision_hash": governance.get("decision_hash"),
                    "decision_status": governance.get("decision_status"),
                    "scope_contract_id": governance.get("scope_contract_id"),
                    "scope_version": governance.get("scope_version"),
                    "policy_set_id": governance.get("policy_set_id"),
                    "policy_version": governance.get("policy_version"),
                    "governance_event_id": governance.get("governance_event_id"),
                }
                if governance else None
            ),
            execution_outcome={
                "status": "COMMITTED",
                "event_type": "TASK_COMMITTED",
                "event_id": commit_event_id,
                "upstream_event_id": governance.get("governance_event_id"),
            },
            upstream_event_id=governance.get("governance_event_id"),
            downstream_event_ref=commit_event_id,
            reason_code="TASK_CONTRACT_COMMITTED",
        )
        return contract

    def _persist_proposal(self, proposal: Dict[str, Any]) -> None:
        if not self.db.table_exists("cti_action_proposals"):
            return
        self.db.execute(
            """
            INSERT INTO cti_action_proposals
                (proposal_id, mission_id, proposal_kind, action_type, target_component,
                 target_source_id, reason_code, priority_utility, state_version, plan_version,
                 policy_version, valid_until, evidence_refs_json, proposal_json, status, created_at)
            VALUES
                (%(proposal_id)s, %(mission_id)s, %(proposal_kind)s, %(action_type)s,
                 %(target_component)s, %(target_source_id)s, %(reason_code)s,
                 %(priority_utility)s, %(state_version)s, %(plan_version)s, %(policy_version)s,
                 NULL, '[]', %(proposal_json)s, 'PROPOSED', CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
                proposal_json=VALUES(proposal_json), priority_utility=VALUES(priority_utility),
                state_version=VALUES(state_version), plan_version=VALUES(plan_version),
                policy_version=VALUES(policy_version), status=VALUES(status), updated_at=CURRENT_TIMESTAMP
            """,
            {
                "proposal_id": proposal.get("proposal_id") or proposal.get("decision_id"),
                "mission_id": proposal.get("mission_id"),
                "proposal_kind": proposal.get("proposal_kind") or "DELIBERATIVE",
                "action_type": proposal.get("action_type"),
                "target_component": proposal.get("target_component"),
                "target_source_id": proposal.get("target_source_id") or proposal.get("source_id"),
                "reason_code": proposal.get("reason_code"),
                "priority_utility": proposal.get("priority_utility"),
                "state_version": proposal.get("state_version"),
                "plan_version": proposal.get("plan_version"),
                "policy_version": proposal.get("policy_version") or proposal.get("policy_context_id"),
                "proposal_json": to_json(proposal),
            },
        )

    def _set_proposal_status(self, proposal_id: Optional[str], status: str, guard_decision: Optional[str] = None) -> None:
        if not proposal_id or not self.db.table_exists("cti_action_proposals"):
            return
        self.db.execute(
            """
            UPDATE cti_action_proposals
               SET status=%(status)s,
                   guard_decision=COALESCE(%(guard_decision)s, guard_decision),
                   updated_at=CURRENT_TIMESTAMP
             WHERE proposal_id=%(proposal_id)s
            """,
            {"proposal_id": proposal_id, "status": status, "guard_decision": guard_decision},
        )

    def _persist_decision_audit_trace(
        self,
        *,
        mission_id: str,
        versions: RuntimeVersions,
        decision_type: str,
        lineage_trace_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
        task_id: Optional[str] = None,
        policy_decision_id: Optional[str] = None,
        authorization_request_id: Optional[str] = None,
        revalidation_id: Optional[str] = None,
        observations: Any = None,
        candidate_actions: Any = None,
        score_breakdown: Any = None,
        selected_action: Any = None,
        policy_decision: Any = None,
        execution_outcome: Any = None,
        upstream_event_id: Optional[str] = None,
        downstream_event_ref: Optional[str] = None,
        reason_code: Optional[str] = None,
        component_id: Optional[str] = None,
        trace_prefix: str = "dtrace",
    ) -> str:
        """Persist one immutable decision row and its audit-to-event pointer.

        Stage 2.8.7 keeps two identities deliberately separate:
        ``trace_id`` is the unique decision-trace row identity, while
        ``lineage_trace_id`` is the stable proposal/TaskContract lineage root.
        The audit row points back to the decision row through ``trace_id`` and
        forward to the concrete CTI event through ``downstream_event_ref``.
        """
        decision_trace_id = new_id(trace_prefix)
        # Stage 2.8.7.1 -- component_id columns store the canonical architecture
        # identifier (for example CTI-S02), not the potentially longer Python
        # service key (for example asset_profiling_cpe_resolution_service).
        # The full source/service key remains available in observations_json.
        raw_component = str(component_id or self.COMPONENT_ID)
        component_def = COMPONENT_BY_KEY.get(raw_component)
        component = component_def.component_id if component_def is not None else raw_component
        if self.db.table_exists("cti_decision_traces"):
            self.db.execute(
                """
                INSERT INTO cti_decision_traces
                    (trace_id, lineage_trace_id, mission_id, proposal_id, task_id,
                     policy_decision_id, authorization_request_id, revalidation_id, upstream_event_id,
                     component_id, decision_type, state_version, plan_version, policy_version,
                     observations_json, candidate_actions_json, score_breakdown_json,
                     selected_action_json, policy_decision_json, execution_outcome_json,
                     algorithm_version, config_version, created_at)
                VALUES
                    (%(trace_id)s, %(lineage_trace_id)s, %(mission_id)s, %(proposal_id)s,
                     %(task_id)s, %(policy_decision_id)s, %(authorization_request_id)s,
                     %(revalidation_id)s, %(upstream_event_id)s, %(component_id)s, %(decision_type)s,
                     %(state_version)s, %(plan_version)s, %(policy_version)s,
                     %(observations)s, %(candidate_actions)s, %(score_breakdown)s,
                     %(selected_action)s, %(policy_decision)s, %(execution_outcome)s,
                     %(algorithm_version)s, %(config_version)s, CURRENT_TIMESTAMP)
                """,
                {
                    "trace_id": decision_trace_id,
                    "lineage_trace_id": lineage_trace_id,
                    "mission_id": mission_id,
                    "proposal_id": proposal_id,
                    "task_id": task_id,
                    "policy_decision_id": policy_decision_id,
                    "authorization_request_id": authorization_request_id,
                    "revalidation_id": revalidation_id,
                    "upstream_event_id": upstream_event_id,
                    "component_id": component,
                    "decision_type": str(decision_type or "UNKNOWN").upper(),
                    "state_version": versions.state_version,
                    "plan_version": versions.plan_version,
                    "policy_version": versions.policy_version,
                    "observations": to_json(observations) if observations is not None else None,
                    "candidate_actions": to_json(candidate_actions) if candidate_actions is not None else None,
                    "score_breakdown": to_json(score_breakdown) if score_breakdown is not None else None,
                    "selected_action": to_json(selected_action) if selected_action is not None else None,
                    "policy_decision": to_json(policy_decision) if policy_decision is not None else None,
                    "execution_outcome": to_json(execution_outcome) if execution_outcome is not None else None,
                    "algorithm_version": self.CONTROL_VERSION,
                    "config_version": self.ARCHITECTURE_VERSION,
                },
            )

        self.audit.append(
            mission_id=mission_id,
            component_id=component,
            event_type=f"orchestration.decision.{str(decision_type or 'unknown').lower()}",
            reason_code=reason_code or str(decision_type or "DECISION_TRACE"),
            input_snapshot=observations,
            candidate_alternatives=candidate_actions,
            selected_output={
                "decision_trace_id": decision_trace_id,
                "decision_type": str(decision_type or "UNKNOWN").upper(),
                "lineage_trace_id": lineage_trace_id,
                "proposal_id": proposal_id,
                "task_id": task_id,
                "policy_decision_id": policy_decision_id,
                "authorization_request_id": authorization_request_id,
                "revalidation_id": revalidation_id,
                "upstream_event_id": upstream_event_id,
                "selected_action": selected_action,
                "execution_outcome": execution_outcome,
            },
            evidence_refs=[],
            versions={
                "architecture": self.ARCHITECTURE_VERSION,
                "control": self.CONTROL_VERSION,
                "state_version": versions.state_version,
                "plan_version": versions.plan_version,
                "policy_version": versions.policy_version,
            },
            upstream_event_ref=upstream_event_id,
            downstream_event_ref=downstream_event_ref,
            trace_id=decision_trace_id,
        )
        return decision_trace_id

    def _persist_arbitration_trace(
        self,
        runtime: MissionRuntime,
        candidates: List[Dict[str, Any]],
        selected: Dict[str, Any],
    ) -> None:
        selected_proposal_id = selected.get("proposal_id")
        self._persist_decision_audit_trace(
            mission_id=runtime.mission_id,
            versions=runtime.versions,
            decision_type="ARBITRATION",
            lineage_trace_id=str(selected_proposal_id) if selected_proposal_id not in (None, "") else None,
            proposal_id=str(selected_proposal_id) if selected_proposal_id not in (None, "") else None,
            observations={"task_states": runtime.task_states},
            candidate_actions=candidates,
            score_breakdown=[
                {
                    "proposal_id": p.get("proposal_id"),
                    "precedence": p.get("precedence"),
                    "precedence_score": self.PRECEDENCE_SCORE.get(
                        str(p.get("precedence") or "DELIBERATIVE_OPTIMIZATION"), 10
                    ),
                    "utility": p.get("priority_utility"),
                }
                for p in candidates
            ],
            selected_action=selected,
            reason_code=str(selected.get("reason_code") or "ARBITRATION_SELECTED"),
            trace_prefix="arb",
        )

    def _create_mission(self, mission_id: str, mission_context: Dict[str, Any], policy_context: Dict[str, Any], versions: RuntimeVersions) -> None:
        if not self.db.table_exists("cti_missions"):
            return
        self.db.execute(
            """
            INSERT INTO cti_missions
                (mission_id, objective_json, asset_scope_json, intelligence_requirements_json,
                 priority_level, policy_context_json, status, state_version, plan_version,
                 policy_version, started_at, created_at)
            VALUES
                (%(mission_id)s, %(objective_json)s, %(asset_scope_json)s,
                 %(requirements_json)s, %(priority_level)s, %(policy_context_json)s,
                 'RUNNING', %(state_version)s, %(plan_version)s, %(policy_version)s,
                 CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
                objective_json=VALUES(objective_json), asset_scope_json=VALUES(asset_scope_json),
                intelligence_requirements_json=VALUES(intelligence_requirements_json),
                priority_level=VALUES(priority_level), policy_context_json=VALUES(policy_context_json),
                status='RUNNING', state_version=state_version+1, plan_version=VALUES(plan_version),
                policy_version=VALUES(policy_version), updated_at=CURRENT_TIMESTAMP
            """,
            {
                "mission_id": mission_id,
                "objective_json": to_json(mission_context.get("objective") or {}),
                "asset_scope_json": to_json(mission_context.get("asset_scope") or []),
                "requirements_json": to_json(mission_context.get("intelligence_requirements") or []),
                "priority_level": mission_context.get("priority") or 50,
                "policy_context_json": to_json(policy_context),
                "state_version": versions.state_version,
                "plan_version": versions.plan_version,
                "policy_version": versions.policy_version,
            },
        )

    def _update_mission(
        self,
        mission_id: str,
        status: str,
        versions: RuntimeVersions,
        *,
        readiness: Optional[str] = None,
        pip_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        if not self.db.table_exists("cti_missions"):
            return
        self.db.execute(
            """
            UPDATE cti_missions
               SET status=%(status)s, state_version=%(state_version)s,
                   plan_version=%(plan_version)s, policy_version=%(policy_version)s,
                   pip_readiness=%(readiness)s, latest_pip_id=%(pip_id)s,
                   last_error=%(error)s,
                   finished_at=CASE WHEN %(status)s IN ('COMPLETED','DEGRADED','FAILED','CANCELLED') THEN CURRENT_TIMESTAMP ELSE finished_at END,
                   updated_at=CURRENT_TIMESTAMP
             WHERE mission_id=%(mission_id)s
            """,
            {
                "mission_id": mission_id,
                "status": status,
                "state_version": versions.state_version,
                "plan_version": versions.plan_version,
                "policy_version": versions.policy_version,
                "readiness": readiness,
                "pip_id": pip_id,
                "error": error,
            },
        )

    def _create_plan(self, plan_id: str, mission_id: str, versions: RuntimeVersions) -> None:
        if not self.db.table_exists("cti_plans"):
            return
        dag = {
            "plan_id": plan_id,
            "plan_version": versions.plan_version,
            "dependency_dag": DEPENDENCY_DAG,
            "strategy": "EVENT_DRIVEN_VERSIONED_DEPENDENCY_DAG_INCREMENTAL_RECOMPUTATION",
            "control_architecture": "HYBRID_REACTIVE_DELIBERATIVE",
        }
        self.db.execute(
            """
            INSERT INTO cti_plans
                (plan_id, mission_id, plan_version, plan_json, status, created_at)
            VALUES
                (%(plan_id)s, %(mission_id)s, %(plan_version)s, %(plan_json)s, 'ACTIVE', CURRENT_TIMESTAMP)
            """,
            {"plan_id": plan_id, "mission_id": mission_id, "plan_version": versions.plan_version, "plan_json": to_json(dag)},
        )

    @staticmethod
    def _task_lineage_from_contract(
        contract: TaskContract,
        *,
        revalidation_id: Optional[Any] = None,
    ) -> Dict[str, Optional[str]]:
        """Return first-class lineage identifiers for one committed TaskContract.

        Stage 2.8.5 deliberately propagates business lineage only.  Causal and
        cross-subsystem event links remain the responsibility of Stage 2.8.6.
        ``proposal_id`` is the TaskContract trace root established in 2.8.1.
        """
        governance = contract.governance
        return {
            "trace_id": str(contract.trace_id),
            "proposal_id": str(contract.trace_id),
            "task_id": str(contract.task_id),
            "policy_decision_id": governance.decision_id if governance else None,
            "authorization_request_id": governance.request_id if governance else None,
            "revalidation_id": (
                str(revalidation_id) if revalidation_id not in (None, "") else None
            ),
        }

    @staticmethod
    def _task_lineage_from_snapshot(task: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """Return task lineage from a durable TaskContract projection/snapshot."""
        trace_id = task.get("trace_id")
        proposal_id = task.get("proposal_id") or trace_id
        revalidation_id = task.get("revalidation_id") or task.get("pre_dispatch_revalidation_id")
        return {
            "trace_id": str(trace_id) if trace_id not in (None, "") else None,
            "proposal_id": str(proposal_id) if proposal_id not in (None, "") else None,
            "task_id": str(task.get("task_id")) if task.get("task_id") not in (None, "") else None,
            "policy_decision_id": (
                str(task.get("policy_decision_id"))
                if task.get("policy_decision_id") not in (None, "") else None
            ),
            "authorization_request_id": (
                str(task.get("authorization_request_id"))
                if task.get("authorization_request_id") not in (None, "") else None
            ),
            "revalidation_id": (
                str(revalidation_id) if revalidation_id not in (None, "") else None
            ),
        }

    def _remember_task_event(self, task_id: Optional[Any], event_id: Optional[Any]) -> None:
        if task_id in (None, "") or event_id in (None, ""):
            return
        self._task_event_heads[str(task_id)] = str(event_id)

    def _task_event_head(self, task_id: Optional[Any]) -> Optional[str]:
        """Return the latest known event for one TaskContract causal chain."""
        if task_id in (None, ""):
            return None
        key = str(task_id)
        cached = self._task_event_heads.get(key)
        if cached:
            return cached
        try:
            if (
                hasattr(self.db, "table_exists")
                and self.db.table_exists("cti_events")
                and hasattr(self.db, "fetch_one")
            ):
                row = self.db.fetch_one(
                    "SELECT event_id FROM cti_events WHERE task_id=%(task_id)s ORDER BY id DESC LIMIT 1",
                    {"task_id": key},
                )
                if row and row.get("event_id"):
                    self._task_event_heads[key] = str(row["event_id"])
                    return self._task_event_heads[key]
        except Exception:
            pass
        return None

    def _emit_task_lifecycle_event(
        self,
        mission_id: str,
        event_type: str,
        source_component: str,
        payload: Dict[str, Any],
        versions: RuntimeVersions,
        *,
        severity: str = "INFO",
        causation_event_id: Optional[str] = None,
        upstream_event_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
        task_id: Optional[str] = None,
        policy_decision_id: Optional[str] = None,
        authorization_request_id: Optional[str] = None,
        revalidation_id: Optional[str] = None,
    ) -> str:
        """Emit a task event and advance the per-task causal head.

        Without an explicit parent, the previous event for the same task is the
        direct cause. Safety events may override the parent with a governance
        ingress event.
        """
        parent = causation_event_id or self._task_event_head(task_id)
        event_id = self._emit_event(
            mission_id, event_type, source_component, payload, versions,
            severity=severity, trace_id=trace_id, causation_event_id=parent,
            upstream_event_id=upstream_event_id, proposal_id=proposal_id,
            task_id=task_id, policy_decision_id=policy_decision_id,
            authorization_request_id=authorization_request_id,
            revalidation_id=revalidation_id,
        )
        self._remember_task_event(task_id, event_id)

        # Stage 2.8.7 -- materialize decision/audit lineage for durable task
        # outcomes and safety enforcement. Progress/dispatch events remain pure
        # lifecycle events; commit and pre-dispatch revalidation have richer
        # dedicated traces at their decision points.
        decision_type = {
            "TASK_COMPLETED": "TASK_RESULT",
            "TASK_FAILED": "TASK_RESULT",
            "SOURCE_SYNC_COMPLETED": "TASK_RESULT",
            "SOURCE_SYNC_DEGRADED": "TASK_RESULT",
            "SOURCE_SYNC_FAILED": "TASK_RESULT",
            "TASK_AUTHORIZATION_REVOKED": "AUTHORIZATION_REVOCATION",
            "TASK_DISPATCH_BLOCKED": "DISPATCH_BLOCK",
            "TASK_REVOCATION_STOP_REQUESTED": "REVOCATION_STOP",
        }.get(str(event_type or "").upper())
        if decision_type:
            self._persist_decision_audit_trace(
                mission_id=mission_id,
                versions=versions,
                decision_type=decision_type,
                lineage_trace_id=trace_id,
                proposal_id=proposal_id,
                task_id=task_id,
                policy_decision_id=policy_decision_id,
                authorization_request_id=authorization_request_id,
                revalidation_id=revalidation_id,
                observations={
                    "causation_event_id": parent,
                    "upstream_event_id": upstream_event_id,
                    "source_component": source_component,
                    "severity": severity,
                },
                selected_action={
                    "event_type": str(event_type or "").upper(),
                    "event_id": event_id,
                    "task_id": task_id,
                },
                policy_decision=(
                    {
                        "decision_id": policy_decision_id,
                        "request_id": authorization_request_id,
                        "revalidation_id": revalidation_id,
                    }
                    if policy_decision_id or authorization_request_id or revalidation_id
                    else None
                ),
                execution_outcome={
                    "event_id": event_id,
                    "event_type": str(event_type or "").upper(),
                    "causation_event_id": parent,
                    "upstream_event_id": upstream_event_id,
                    "payload": payload,
                },
                upstream_event_id=upstream_event_id,
                downstream_event_ref=event_id,
                reason_code=str(
                    payload.get("reason_code")
                    or ((payload.get("reason_codes") or [None])[0])
                    or str(event_type or "").upper()
                ),
                component_id=source_component,
            )
        return event_id

    def _emit_event(
        self,
        mission_id: str,
        event_type: str,
        source_component: str,
        payload: Dict[str, Any],
        versions: RuntimeVersions,
        *,
        severity: str = "INFO",
        trace_id: Optional[str] = None,
        causation_event_id: Optional[str] = None,
        upstream_event_id: Optional[str] = None,
        proposal_id: Optional[str] = None,
        task_id: Optional[str] = None,
        policy_decision_id: Optional[str] = None,
        authorization_request_id: Optional[str] = None,
        revalidation_id: Optional[str] = None,
    ) -> str:
        event = self.event_bus.publish(
            event_type,
            source_component=source_component,
            mission_id=mission_id,
            payload=payload,
            severity=severity,
            state_version=versions.state_version,
            plan_version=versions.plan_version,
            policy_version=versions.policy_version,
            trace_id=trace_id,
            causation_event_id=causation_event_id,
            upstream_event_id=upstream_event_id,
            proposal_id=proposal_id,
            task_id=task_id,
            policy_decision_id=policy_decision_id,
            authorization_request_id=authorization_request_id,
            revalidation_id=revalidation_id,
        )
        return str(event.get("event_id"))

    def _update_task(self, task_id: str, status: str, output_refs: Optional[List[str]] = None, error: Optional[str] = None) -> None:
        if not self.db.table_exists("cti_task_contracts"):
            return
        self.db.execute(
            """
            UPDATE cti_task_contracts
               SET status=%(status)s, output_refs_json=%(output_refs_json)s, error_text=%(error)s,
                   started_at=CASE WHEN %(status)s='RUNNING' THEN COALESCE(started_at,CURRENT_TIMESTAMP) ELSE started_at END,
                   finished_at=CASE WHEN %(status)s IN ('COMPLETED','DEGRADED','FAILED','CANCELLED') THEN CURRENT_TIMESTAMP ELSE finished_at END,
                   updated_at=CURRENT_TIMESTAMP
             WHERE task_id=%(task_id)s
            """,
            {"task_id": task_id, "status": status, "output_refs_json": to_json(output_refs or []), "error": error},
        )

    # ------------------------------------------------------------------
    # Finalization / failure
    # ------------------------------------------------------------------
    def _finalize_from_pip(self, runtime: MissionRuntime) -> None:
        pip_artifact = (runtime.outputs.get("pip") or {}).get("pip")
        readiness = (pip_artifact or {}).get("readiness") or "REJECTED"
        final_status = "QUALITY_REVIEW" if readiness == "REJECTED" else "COMPLETED"
        runtime.status = final_status
        runtime.versions.state_version += 1
        self._update_mission(
            runtime.mission_id,
            final_status,
            runtime.versions,
            readiness=readiness,
            pip_id=(pip_artifact or {}).get("pip_id"),
        )
        self._emit_event(
            runtime.mission_id,
            "PIP_READY" if final_status == "COMPLETED" else "PIP_QUALITY_REVIEW",
            self.COMPONENT_ID,
            {"readiness": readiness, "pip_id": (pip_artifact or {}).get("pip_id")},
            runtime.versions,
        )
        self.audit.append(
            mission_id=runtime.mission_id,
            component_id=self.COMPONENT_ID,
            event_type="orchestration.completed",
            reason_code="PIP_READY" if final_status == "COMPLETED" else "PIP_HARD_GATE_FAILED",
            input_snapshot={"scan_job_id": runtime.scan_payload.get("scan_job_id"), "target_url": runtime.scan_payload.get("target_url")},
            candidate_alternatives=None,
            selected_output={"status": final_status, "readiness": readiness, "pip_id": (pip_artifact or {}).get("pip_id")},
            evidence_refs=[],
            versions={
                "architecture": self.ARCHITECTURE_VERSION,
                "control": self.CONTROL_VERSION,
                "state_version": runtime.versions.state_version,
                "plan_version": runtime.versions.plan_version,
                "policy_version": runtime.versions.policy_version,
            },
        )
        self.registry.update_status(self.SERVICE_KEY, "idle")
        runtime.terminal_event.set()

    def _fail_mission(self, runtime: MissionRuntime, error: str) -> None:
        runtime.status = "FAILED"
        runtime.last_error = str(error)
        runtime.versions.state_version += 1
        self._update_mission(runtime.mission_id, "FAILED", runtime.versions, error=runtime.last_error)
        self._emit_event(
            runtime.mission_id,
            "MISSION_FAILED",
            self.COMPONENT_ID,
            {"error": runtime.last_error},
            runtime.versions,
            severity="ERROR",
        )
        self.registry.update_status(self.SERVICE_KEY, "error", runtime.last_error)
        runtime.terminal_event.set()

    # ------------------------------------------------------------------
    # Small pure helpers
    # ------------------------------------------------------------------
    def _runtime(self, mission_id: Optional[str]) -> MissionRuntime:
        if not mission_id:
            raise KeyError("Event has no mission_id")
        with self._lock:
            runtime = self._runtimes.get(str(mission_id))
        if runtime is None:
            raise KeyError(f"Mission runtime not found: {mission_id}")
        return runtime

    def _schedule_pipeline_advance(self, runtime: MissionRuntime, reason: str) -> None:
        self._emit_event(
            runtime.mission_id,
            "PIPELINE_ADVANCE",
            self.COMPONENT_ID,
            {"reason": reason, "task_states": dict(runtime.task_states)},
            runtime.versions,
        )

    def _source_policy_decision(self, runtime: MissionRuntime, proposal: Dict[str, Any]) -> Dict[str, Any]:
        """Obtain authoritative CTI-source authorization from aptsGSS.

        Local mission policy may only make the result more restrictive. It can
        never manufacture an ALLOW. If aptsGSS is disabled, unreachable, times
        out, or returns an invalid response, acquisition is denied fail-closed.
        """
        source_id = str(proposal.get("source_id") or "")

        if runtime.policy_context.get("source_acquisition_allowed") is False:
            return self._local_source_denial(
                runtime,
                source_id,
                "LOCAL_SOURCE_ACQUISITION_DISABLED",
            )

        allowed_sources = set(runtime.policy_context.get("allowed_cti_sources") or [])
        if allowed_sources and source_id not in allowed_sources:
            return self._local_source_denial(
                runtime,
                source_id,
                "LOCAL_SOURCE_NOT_ALLOWED",
            )

        scope_contract_id = (
            runtime.scan_payload.get("scope_contract_id")
            or runtime.policy_context.get("scope_contract_id")
        )
        context = {
            "environment": runtime.scan_payload.get("environment")
            or runtime.policy_context.get("environment")
            or "LAB",
            "reversible": True,
            "blast_radius": 1,
            "read_only": True,
            "target_actuation": False,
            "proposal_id": proposal.get("decision_id"),
            "acquisition_objective_id": proposal.get("acquisition_objective_id"),
            "reason_code": proposal.get("reason_code"),
            "expected_request_cost": proposal.get("expected_request_cost"),
            "expected_freshness_gain": proposal.get("expected_freshness_gain"),
        }
        evidence_refs = [
            str(ref)
            for ref in (proposal.get("evidence_refs") or [])
            if ref not in (None, "")
        ]

        try:
            decision = self.governance.evaluate_cti_source_read(
                mission_id=runtime.mission_id,
                scope_contract_id=str(scope_contract_id) if scope_contract_id else None,
                source_id=source_id,
                action_name=str(proposal.get("action_type") or "INCREMENTAL_FETCH"),
                context=context,
                evidence_refs=evidence_refs,
                requested_by="CTI-A02",
            )
        except GovernanceClientError as exc:
            return {
                "decision": "DENY",
                "reason_code": "GOVERNANCE_UNAVAILABLE_FAIL_CLOSED",
                "reason_codes": ["GOVERNANCE_UNAVAILABLE_FAIL_CLOSED"],
                "source_id": source_id,
                "policy_version": runtime.versions.policy_version,
                "scope_contract_id": scope_contract_id,
                "execution_authorized": False,
                "target_actuation": False,
                "authority": "aptsGSS",
                "authority_component": "GOV-PLANE",
                "governance_error": str(exc),
                "checked_at": utcnow_iso(),
            }

        remote_policy_version = decision.get("policy_version")
        if remote_policy_version is not None:
            runtime.versions.policy_version = str(remote_policy_version)
        decision.setdefault("source_id", source_id)
        decision.setdefault("reason_code", (decision.get("reason_codes") or [decision.get("decision")])[0])
        decision["execution_authorized"] = str(decision.get("decision") or "").upper() == "ALLOW"
        decision["target_actuation"] = False
        decision.setdefault("decision_status", "ACTIVE")
        decision.setdefault("authorization_request", {
            "mission_id": runtime.mission_id,
            "scope_contract_id": str(scope_contract_id) if scope_contract_id else None,
            "subject_component": "CTI-A02",
            "action_class": "CTI_SOURCE_READ",
            "action_name": str(proposal.get("action_type") or "INCREMENTAL_FETCH"),
            "resource_type": "CTI_SOURCE",
            "resource_value": source_id,
            "requested_by": "CTI-A02",
        })
        decision.setdefault("checked_at", utcnow_iso())
        return decision

    @staticmethod
    def _local_source_denial(runtime: MissionRuntime, source_id: str, reason_code: str) -> Dict[str, Any]:
        return {
            "decision": "DENY",
            "reason_code": reason_code,
            "reason_codes": [reason_code],
            "source_id": source_id,
            "policy_version": runtime.versions.policy_version,
            "scope_contract_id": runtime.scan_payload.get("scope_contract_id")
            or runtime.policy_context.get("scope_contract_id"),
            "execution_authorized": False,
            "target_actuation": False,
            "authority": "LOCAL_RESTRICTIVE_PRECHECK",
            "checked_at": utcnow_iso(),
        }

    @staticmethod
    def _acquisition_utility(proposal: Dict[str, Any]) -> float:
        comps = proposal.get("score_components") or {}
        positive = sum(float(comps.get(k) or 0.0) for k in ("mission_relevance", "freshness_due", "criticality", "change_signal", "recovery_need", "health"))
        negative = sum(float(comps.get(k) or 0.0) for k in ("rate_pressure", "cost"))
        return max(0.0, min(1.0, (positive - 0.5 * negative) / 6.0))

    @staticmethod
    def _task_priority_utility(runtime: Optional[MissionRuntime], component: str) -> float:
        if runtime is None:
            return 0.5
        mission_priority = max(0.0, min(1.0, float(runtime.mission_context.get("priority") or 50) / 100.0))
        critical_path_bonus = 0.15 if component in {"vulnerability_correlation_service", "risk_prioritization_agent", "pip_assembly_validation_service"} else 0.05
        retry_penalty = min(0.2, 0.05 * float(runtime.retries.get(component) or 0))
        return round(max(0.0, min(1.0, 0.35 + 0.45 * mission_priority + critical_path_bonus - retry_penalty)), 6)

    @staticmethod
    def _output_key(component: str) -> str:
        return {
            "normalization_provenance_service": "normalization",
            "asset_profiling_cpe_resolution_service": "asset_cpe",
            "vulnerability_correlation_service": "vulnerability",
            "attack_mapping_service": "attack_mapping",
            "attack_path_reasoning_agent": "attack_path",
            "threat_context_service": "threat_context",
            "risk_prioritization_agent": "risk",
            "pip_assembly_validation_service": "pip",
            "cti_acquisition_freshness_agent": "acquisition",
        }.get(component, component)

    @staticmethod
    def _output_refs(result: Dict[str, Any]) -> List[str]:
        refs: List[str] = []
        for key in ("normalized_object_id", "asset_profile_id", "correlation_id", "mapping_id", "path_id", "context_id", "intention_id", "pip_id"):
            if result.get(key):
                refs.append(str(result[key]))
        for collection in ("results", "asset_profiles", "cpe_claims", "correlations", "mappings", "paths", "contexts", "intentions"):
            for row in result.get(collection) or []:
                if isinstance(row, dict):
                    for key in ("normalized_object_id", "asset_profile_id", "resolution_id", "correlation_id", "mapping_id", "path_id", "context_id", "intention_id"):
                        if row.get(key):
                            refs.append(str(row[key]))
                            break
        if isinstance(result.get("pip"), dict) and result["pip"].get("pip_id"):
            refs.append(str(result["pip"]["pip_id"]))
        return list(dict.fromkeys(refs))

    @staticmethod
    def _mission_context(scan_payload: Dict[str, Any], mission_id: str) -> Dict[str, Any]:
        target = scan_payload.get("target_url")
        asset_scope = scan_payload.get("asset_scope") or ([target] if target else [a.get("asset_id") for a in scan_payload.get("assets") or [] if a.get("asset_id")])
        return {
            "mission_id": mission_id,
            "objective": scan_payload.get("mission_objective") or {"type": "PENTEST_INTELLIGENCE_ENRICHMENT", "target_url": target},
            "asset_scope": asset_scope,
            "time_window": scan_payload.get("time_window"),
            "intelligence_requirements": scan_payload.get("intelligence_requirements") or [
                "asset_profile", "cpe_resolution", "vulnerability_applicability", "attack_mapping", "threat_context", "risk_priority", "pip"
            ],
            "priority": int(scan_payload.get("mission_priority") or 50),
            "high_priority_assets": scan_payload.get("high_priority_assets") or [],
            "high_priority_vulnerabilities": scan_payload.get("high_priority_vulnerabilities") or [],
            "default_relevance": scan_payload.get("mission_relevance", 0.6),
        }

    @staticmethod
    def _mission_binding(
        scan_payload: Dict[str, Any],
        mission_id: str,
        policy_context: Dict[str, Any],
        asset_profiles: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        explicit_scope = list(scan_payload.get("asset_scope") or [])
        if not explicit_scope and scan_payload.get("target_url"):
            explicit_scope = [scan_payload.get("target_url")]
        if not explicit_scope:
            for asset in asset_profiles or []:
                candidate = asset.get("asset_id") or asset.get("asset_profile_id") or asset.get("target_url") or asset.get("hostname") or asset.get("ip_address")
                if candidate and candidate not in explicit_scope:
                    explicit_scope.append(str(candidate))
        return {
            "mission_id": mission_id,
            "external_scan_job_id": scan_payload.get("scan_job_id"),
            "wpt_binding": dict(scan_payload.get("wpt_binding") or {}),
            "target_url": scan_payload.get("target_url"),
            "target_urls": scan_payload.get("target_urls") or [],
            "asset_scope": explicit_scope,
            "scope_allowed": policy_context.get("scope_allowed", True),
            "policy_version": policy_context.get("policy_version") or policy_context.get("version") or "policy-default-1",
        }

    @staticmethod
    def _quality_context(outputs: Dict[str, Any]) -> Dict[str, Any]:
        normalized = outputs.get("normalization", {}).get("results") or []
        cpe = outputs.get("asset_cpe", {}).get("cpe_claims") or []
        correlations = outputs.get("vulnerability", {}).get("correlations") or []
        return {
            "normalization_verified_ratio": (sum(1 for r in normalized if r.get("status") == "verified") / len(normalized)) if normalized else 1.0,
            "cpe_resolved_ratio": (sum(1 for r in cpe if r.get("status") in {"VERIFIED", "PROBABLE"}) / len(cpe)) if cpe else 0.0,
            "correlation_verified_ratio": (sum(1 for r in correlations if r.get("symbolic_result") == "TRUE") / len(correlations)) if correlations else 0.0,
        }

    def _response(
        self,
        scan_payload: Dict[str, Any],
        mission_id: str,
        plan_id: str,
        versions: RuntimeVersions,
        outputs: Dict[str, Any],
        final_status: str,
    ) -> Dict[str, Any]:
        asset_cpe = outputs.get("asset_cpe") or {}
        correlations = outputs.get("vulnerability", {}).get("correlations") or []
        mappings = outputs.get("attack_mapping", {}).get("mappings") or []
        contexts = outputs.get("threat_context", {}).get("contexts") or []
        paths = outputs.get("attack_path", {}).get("paths") or []
        intentions = outputs.get("risk", {}).get("intentions") or []
        pip_artifact = outputs.get("pip", {}).get("pip")

        mappings_by_corr: Dict[str, List[Dict[str, Any]]] = {}
        for mapping in mappings:
            mappings_by_corr.setdefault(str(mapping.get("correlation_id") or ""), []).append(mapping)
        contexts_by_mapping: Dict[str, List[Dict[str, Any]]] = {}
        for context in contexts:
            contexts_by_mapping.setdefault(str(context.get("mapping_id") or ""), []).append(context)

        vulnerability_candidates: List[Dict[str, Any]] = []
        for corr in correlations:
            item = dict(corr)
            attack_context = []
            for mapping in mappings_by_corr.get(str(corr.get("correlation_id") or ""), []):
                mapped = dict(mapping)
                mapped["threat_context"] = contexts_by_mapping.get(str(mapping.get("mapping_id") or ""), [])
                mapped["final_confidence"] = min(float(corr.get("confidence") or 0.5), float(mapping.get("confidence") or 0.5))
                mapped["context_label"] = "verified_mapping" if mapping.get("verification_state") == "VERIFIED" else "provisional_mapping"
                attack_context.append(mapped)
            item["attack_context"] = attack_context
            item["external_key"] = f"{corr.get('asset_id')}|{corr.get('cve_id')}|{corr.get('correlation_id')}"
            vulnerability_candidates.append(item)

        official_cpe_candidates = []
        seen = set()
        for claim in asset_cpe.get("cpe_claims") or []:
            candidate = claim.get("source_candidate") or {}
            uri = candidate.get("cpe23_uri") or claim.get("cpe23_formatted")
            if uri and uri not in seen:
                seen.add(uri)
                official_cpe_candidates.append(candidate or {"cpe23_uri": uri})

        return {
            "status": "completed" if final_status == "COMPLETED" else "quality_review",
            "mission_status": final_status,
            "mission_id": mission_id,
            "plan_id": plan_id,
            "architecture_version": self.ARCHITECTURE_VERSION,
            "control_version": self.CONTROL_VERSION,
            "runtime_model": "EVENT_DRIVEN_HYBRID_REACTIVE_DELIBERATIVE",
            "state_version": versions.state_version,
            "plan_version": versions.plan_version,
            "policy_version": versions.policy_version,
            "external_scan_job_id": scan_payload.get("scan_job_id"),
            "target_url": scan_payload.get("target_url"),
            "generated_at": utcnow_iso(),
            "component_outputs": outputs,
            "acquisition": outputs.get("acquisition") or {},
            "asset_profiles": asset_cpe.get("asset_profiles") or [],
            "cpe_resolution_claims": asset_cpe.get("cpe_claims") or [],
            "enrichment_requirements": asset_cpe.get("enrichment_requirements") or [],
            "vulnerability_correlations": correlations,
            "attack_mappings": mappings,
            "attack_paths": paths,
            "threat_contexts": contexts,
            "risk_priorities": intentions,
            "pentest_intelligence_package": pip_artifact,
            "official_cpe_candidates": official_cpe_candidates,
            "cpe_candidates": official_cpe_candidates,
            "vulnerability_candidates": vulnerability_candidates,
            "summary": {
                "acquisition_actions": (outputs.get("acquisition") or {}).get("actions", 0),
                "acquisition_sources": (outputs.get("acquisition") or {}).get("sources", []),
                "assets": len(asset_cpe.get("asset_profiles") or []),
                "cpe_claims": len(asset_cpe.get("cpe_claims") or []),
                "vulnerability_correlations": len(correlations),
                "attack_mappings": len(mappings),
                "attack_paths": len(paths),
                "threat_contexts": len(contexts),
                "risk_priorities": len(intentions),
                "pip_readiness": (pip_artifact or {}).get("readiness"),
            },
            "notes": [
                "CTI-A01 now advances the dependency DAG through typed events and deterministic reactive-deliberative arbitration.",
                "CTI-A02 is connected to the existing NVD CVE, NVD CPE and MITRE ATT&CK source sync adapters.",
                "Reasoning does not imply authority; no CTI component grants target execution authorization.",
                "Vulnerability applicability does not imply exploitability.",
                "Attack paths are intelligence proposals only and are not executable commands.",
                "PIP validation objectives are decision-support records, not pentest execution instructions.",
            ],
        }
