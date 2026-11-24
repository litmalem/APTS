from __future__ import annotations

import json
import mimetypes
import time
from pathlib import Path
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .errors import MissionCTIFeedbackNotFound, MissionCTIFeedbackRejected, MissionCTIFeedbackUnavailable

from .errors import (
    MissionAuthorizationBindingNotFound,
    MissionAuthorizationConflict,
    MissionAuthorizationFailClosed,
    MissionGovernanceBindingConflict,
    MissionGovernanceBindingNotFound,
    MissionGovernanceProtocolError,
    MissionGovernanceUnavailable,
    MissionIdempotencyConflict,
    MissionIllegalTransition,
    MissionNotFound,
    MissionScopeContractConflict,
    MissionScopeContractNotFound,
    MissionStateConflict,
    MissionValidationError,
    MissionValidationPipelineError,
    MissionTaskConflict,
    MissionTaskNotFound,
    MissionTaskRoutingFailClosed,
    MissionSubsystemProtocolError,
    MissionSubsystemUnavailable,
    MissionConcurrencyConflict,
    MissionCommandConflict,
    MissionCommandNotFound,
    MissionLifecycleGuardRejected,
    MissionVersionObservationUnavailable,
    MissionRepositoryIntegrityError,
    MissionEventNotFound,
    MissionEventIntegrityError,
    MissionPlanContractConflict,
    MissionPlanContractNotFound,
    MissionPlanContractGuardRejected,
    MissionPlannerInputSnapshotConflict,
    MissionPlannerInputSnapshotNotFound,
    MissionPlannerInputSnapshotGuardRejected,
    MissionTaskDecompositionConflict,
    MissionTaskDecompositionNotFound,
    MissionTaskDecompositionGuardRejected,
    MissionPlannedTaskNotFound,
    MissionTaskDependencyGraphConflict,
    MissionTaskDependencyGraphNotFound,
    MissionTaskDependencyGraphGuardRejected,
    MissionPlannerGenerationConflict,
    MissionPlannerGenerationNotFound,
    MissionPlannerGenerationGuardRejected,
    MissionPlanValidationConflict,
    MissionPlanValidationNotFound,
    MissionPlanValidationGuardRejected,
    MissionPlanVersioningConflict,
    MissionPlanVersioningNotFound,
    MissionPlanVersioningGuardRejected,
    MissionTaskReadinessProjectionConflict,
    MissionTaskReadinessProjectionNotFound,
    MissionTaskReadinessProjectionGuardRejected,
    MissionTaskRoutingIntentConflict,
    MissionTaskRoutingIntentNotFound,
    MissionTaskRoutingIntentGuardRejected,
    MissionTaskRoutingEligibilityConflict,
    MissionTaskRoutingEligibilityNotFound,
    MissionTaskRoutingEligibilityGuardRejected,
    MissionTaskRouteSelectionConflict,
    MissionTaskRouteSelectionNotFound,
    MissionTaskRouteSelectionGuardRejected,
    MissionDelegationAuthorizationConflict,
    MissionDelegationAuthorizationNotFound,
    MissionDelegationAuthorizationGuardRejected,
    MissionTaskDelegationConflict,
    MissionTaskDelegationNotFound,
    MissionTaskDelegationGuardRejected,
    MissionDelegationDeliveryConflict,
    MissionDelegationDeliveryNotFound,
    MissionDelegationDeliveryGuardRejected,
    MissionDelegationRecoveryControlConflict,
    MissionDelegationRecoveryControlNotFound,
    MissionDelegationRecoveryControlGuardRejected,
    MissionRoutingDelegationRecoveryConflict,
    MissionRoutingDelegationRecoveryNotFound,
    MissionRoutingDelegationRecoveryGuardRejected,
    MissionExecutionDispatchConflict,
    MissionExecutionDispatchNotFound,
    MissionExecutionDispatchGuardRejected,
    MissionDispatchEligibilityConflict,
    MissionDispatchEligibilityNotFound,
    MissionDispatchEligibilityGuardRejected,
    MissionPreDispatchGovernanceConflict,
    MissionPreDispatchGovernanceNotFound,
    MissionPreDispatchGovernanceGuardRejected,
    MissionExecutionAttemptConflict,
    MissionExecutionAttemptNotFound,
    MissionExecutionAttemptGuardRejected,
    MissionExecutionDeliveryConflict,
    MissionExecutionDeliveryNotFound,
    MissionExecutionDeliveryGuardRejected,
    MissionExecutionRunningProjectionConflict,
    MissionExecutionRunningProjectionNotFound,
    MissionExecutionRunningProjectionGuardRejected,
    MissionExecutionResultCaptureConflict,
    MissionExecutionResultCaptureNotFound,
    MissionExecutionResultCaptureGuardRejected,
    MissionExecutionTerminationControlConflict,
    MissionExecutionTerminationControlNotFound,
    MissionExecutionTerminationControlGuardRejected,
    MissionExecutionOutcomePropagationConflict,
    MissionExecutionOutcomePropagationNotFound,
    MissionExecutionOutcomePropagationGuardRejected,
    MissionExecutionRecoveryConflict,
    MissionExecutionRecoveryNotFound,
    MissionExecutionRecoveryGuardRejected,
    MissionTaskOutcomeConflict,
    MissionTaskOutcomeNotFound,
    MissionTaskOutcomeGuardRejected,
    MissionTaskTerminalityEligibilityConflict,
    MissionTaskTerminalityEligibilityNotFound,
    MissionTaskTerminalityEligibilityGuardRejected,
    MissionTaskEvidenceBindingConflict,
    MissionTaskEvidenceBindingNotFound,
    MissionTaskEvidenceBindingGuardRejected,
    MissionTaskCompletionConflict,
    MissionTaskCompletionNotFound,
    MissionTaskCompletionGuardRejected,
    MissionOutcomeAggregationConflict,
    MissionOutcomeAggregationNotFound,
    MissionOutcomeAggregationGuardRejected,
    MissionSuccessEvaluationConflict,
    MissionSuccessEvaluationNotFound,
    MissionSuccessEvaluationGuardRejected,
    MissionCompletionReadinessConflict,
    MissionCompletionReadinessNotFound,
    MissionCompletionReadinessGuardRejected,
    MissionVerifiedCompletionConflict,
    MissionVerifiedCompletionNotFound,
    MissionVerifiedCompletionGuardRejected,
    MissionOutcomeRecoveryConflict,
    MissionOutcomeRecoveryNotFound,
    MissionOutcomeRecoveryGuardRejected,
    MissionAdaptationReplanConflict,
    MissionAdaptationReplanNotFound,
    MissionAdaptationReplanGuardRejected,
    MissionAdaptationTriggerClassificationConflict,
    MissionAdaptationTriggerClassificationNotFound,
    MissionAdaptationTriggerClassificationGuardRejected,
    MissionReplanEligibilityGovernanceConflict,
    MissionReplanEligibilityGovernanceNotFound,
    MissionReplanEligibilityGovernanceGuardRejected,
    MissionReplanSnapshotConflict,
    MissionReplanSnapshotNotFound,
    MissionReplanSnapshotGuardRejected,
    MissionReplanCandidateConflict,
    MissionReplanCandidateNotFound,
    MissionReplanCandidateGuardRejected,
    MissionReplanValidationConflict,
    MissionReplanValidationNotFound,
    MissionReplanValidationGuardRejected,
    MissionReplanCommitConflict,
    MissionReplanCommitNotFound,
    MissionReplanCommitGuardRejected,
    MissionReplanHandoffConflict,
    MissionReplanHandoffNotFound,
    MissionReplanHandoffGuardRejected,
    MissionReplanRecoveryConflict,
    MissionReplanRecoveryNotFound,
    MissionReplanRecoveryGuardRejected,
    MissionPlanningRecoveryConflict,
    MissionPlanningRecoveryNotFound,
    MissionPlanningRecoveryGuardRejected,
    SubsystemRegistryIntegrityError,
    SubsystemNotFound,
    SubsystemCapabilityNotFound,
)
from .service import CanonicalMissionService


class MissionOrchestratorHandler(BaseHTTPRequestHandler):
    service = None
    server_version = "APTSMissionOrchestrator/3.9.10"

    def log_message(self, fmt, *args):
        if os.getenv("MISSION_HTTP_QUIET", "0") != "1":
            super().log_message(fmt, *args)

    def _json_response(self, status_code: int, payload):
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _static_response(self, status_code: int, raw: bytes, content_type: str):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def _sse_mission_events(self, mission_id: str, parsed_url):
        query = parse_qs(parsed_url.query)
        def one(name, default=None):
            values = query.get(name)
            return values[0] if values else default
        after_event_id = one("after") or self.headers.get("Last-Event-ID") or None
        once = str(one("once", "0")).strip().lower() in {"1", "true", "yes"}
        try:
            limit = int(one("limit", "200"))
        except ValueError as exc:
            raise MissionValidationError("SSE limit must be an integer") from exc
        poll_seconds = max(0.25, min(float(os.getenv("MISSION_SSE_POLL_SECONDS", "1.0")), 10.0))
        max_seconds = max(5.0, min(float(os.getenv("MISSION_SSE_MAX_SECONDS", "55")), 300.0))
        # Preflight before headers so normal API error handling is still available.
        snapshot = self._service().get_mission_event_stream_snapshot(
            mission_id, after_event_id=after_event_id, limit=limit
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Connection", "close" if once else "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def emit(event_name: str, data, event_id: str | None = None):
            raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            parts = []
            if event_id:
                parts.append(f"id: {event_id}")
            if event_name:
                parts.append(f"event: {event_name}")
            parts.append(f"data: {raw}")
            self.wfile.write(("\n".join(parts) + "\n\n").encode("utf-8"))
            self.wfile.flush()

        try:
            self.wfile.write(b"retry: 1500\n\n")
            emit("stream_ready", {
                "mission_id": mission_id,
                "read_only": True,
                "after_event_id": after_event_id,
                "history_event_count": snapshot.get("history_event_count", 0),
            })
            cursor = after_event_id
            for event in snapshot.get("events") or []:
                cursor = event.get("event_id") or cursor
                emit("mission_event", event, cursor)
            if snapshot.get("latest_event_id") and not cursor:
                cursor = snapshot["latest_event_id"]
            if once:
                emit("stream_end", {"mission_id": mission_id, "latest_event_id": snapshot.get("latest_event_id")})
                self.close_connection = True
                return
            started = time.monotonic()
            last_heartbeat = started
            while time.monotonic() - started < max_seconds:
                time.sleep(poll_seconds)
                snapshot = self._service().get_mission_event_stream_snapshot(
                    mission_id, after_event_id=cursor, limit=limit
                )
                for event in snapshot.get("events") or []:
                    cursor = event.get("event_id") or cursor
                    emit("mission_event", event, cursor)
                now = time.monotonic()
                if now - last_heartbeat >= 15.0:
                    self.wfile.write(f": heartbeat {int(now)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last_heartbeat = now
            emit("stream_rotate", {"mission_id": mission_id, "latest_event_id": cursor})
            self.close_connection = True
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            try:
                emit("stream_error", {"mission_id": mission_id, "message": str(exc)})
            except Exception:
                pass

    def _serve_console_asset(self, path: str):
        console_root = Path(__file__).resolve().parents[1] / "mission_web"
        relative = "index.html" if path in {"/ui", "/ui/"} else path[len("/ui/"):]
        if not relative or relative.endswith("/"):
            relative += "index.html"
        candidate = (console_root / relative).resolve()
        try:
            candidate.relative_to(console_root.resolve())
        except ValueError:
            return self._json_response(404, {"status": "error", "code": "MISSION_CONSOLE_ASSET_NOT_FOUND"})
        if not candidate.is_file():
            return self._json_response(404, {"status": "error", "code": "MISSION_CONSOLE_ASSET_NOT_FOUND"})
        content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        return self._static_response(200, candidate.read_bytes(), content_type)

    def _read_json(self, *, strict=False):
        if strict and (self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1):
            raise MissionValidationError("CTI intake requires one Content-Length and no Transfer-Encoding")
        try:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError as exc:
            raise MissionValidationError("Content-Length must be an integer") from exc
        if content_length <= 0:
            raise MissionValidationError("JSON request body is required")
        max_body = int(os.getenv("MISSION_MAX_BODY_BYTES", "1048576"))
        if content_length > max_body:
            raise MissionValidationError(f"request body exceeds {max_body} bytes")
        raw = self.rfile.read(content_length)
        try:
            if strict:
                def unique(pairs):
                    value = {}
                    for key, item in pairs:
                        if key in value:
                            raise ValueError("duplicate JSON key")
                        value[key] = item
                    return value
                def finite(token):
                    raise ValueError("nonfinite JSON number")
                return json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=finite)
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise MissionValidationError("request body must be valid UTF-8 JSON") from exc

    def _service(self):
        if self.service is None:
            raise RuntimeError("MissionOrchestratorHandler.service not configured")
        return self.service

    def _wpt_service(self):
        service = getattr(self, "wpt_intake_service", None)
        if service is None:
            from execution_subsystem.wpt_intake_service import WPTIntakeService
            service = WPTIntakeService()
            self.wpt_intake_service = service
        return service

    def _authorize_wpt_request(self):
        service = self._wpt_service()
        if not getattr(service, "configured", False):
            self._json_response(503, {"status": "unavailable", "error": "WPT intake authentication is not configured"})
            return None
        if not service.authenticate(self.headers.get("Authorization")):
            self._json_response(401, {"status": "unauthorized", "error": "valid WPT bearer token required"})
            return None
        return service

    def _handle_error(self, exc: Exception):
        if isinstance(exc, MissionCTIFeedbackNotFound):
            return self._json_response(404, {"status":"error", "code":"MISSION_CTI_FEEDBACK_NOT_FOUND", "message":str(exc)})
        if isinstance(exc, MissionCTIFeedbackRejected):
            return self._json_response(409, {"status":"error", "code":"MISSION_CTI_FEEDBACK_REJECTED", "message":str(exc)})
        if isinstance(exc, MissionCTIFeedbackUnavailable):
            return self._json_response(503, {"status":"error", "code":"MISSION_CTI_FEEDBACK_UNAVAILABLE", "message":str(exc)})
        if isinstance(exc, MissionValidationPipelineError):
            return self._json_response(
                400,
                {
                    "status": "error",
                    "code": "MISSION_VALIDATION_FAILED",
                    "validation_phase": exc.phase,
                    "validation_check_id": exc.check_id,
                    "message": str(exc),
                    "persistence_performed": False,
                    "authority_query_performed": False,
                    "planning_performed": False,
                    "target_action_performed": False,
                },
            )
        if isinstance(exc, MissionValidationError):
            return self._json_response(400, {"status": "error", "code": "MISSION_CONTRACT_INVALID", "message": str(exc)})
        if isinstance(exc, MissionIdempotencyConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_IDEMPOTENCY_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionScopeContractConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_SCOPE_CONTRACT_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionScopeContractNotFound):
            mission_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_SCOPE_CONTRACT_NOT_FOUND", "mission_id": mission_id})
        if isinstance(exc, MissionGovernanceBindingConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_GOVERNANCE_BINDING_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionGovernanceBindingNotFound):
            mission_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_GOVERNANCE_BINDING_NOT_FOUND", "mission_id": mission_id})
        if isinstance(exc, MissionAuthorizationConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_AUTHORIZATION_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionAuthorizationBindingNotFound):
            binding_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_AUTHORIZATION_BINDING_NOT_FOUND", "authorization_binding_id": binding_id})
        if isinstance(exc, MissionAuthorizationFailClosed):
            return self._json_response(403, {"status": "error", "code": "MISSION_AUTHORIZATION_FAIL_CLOSED", "message": str(exc)})
        if isinstance(exc, MissionGovernanceUnavailable):
            return self._json_response(503, {"status": "error", "code": "GOVERNANCE_AUTHORITY_UNAVAILABLE", "message": str(exc)})
        if isinstance(exc, MissionGovernanceProtocolError):
            return self._json_response(502, {"status": "error", "code": "GOVERNANCE_AUTHORITY_PROTOCOL_ERROR", "message": str(exc)})
        if isinstance(exc, MissionTaskConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_TASK_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionTaskNotFound):
            task_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_TASK_NOT_FOUND", "task_id": task_id})
        if isinstance(exc, MissionTaskRoutingFailClosed):
            return self._json_response(403, {"status": "error", "code": "MISSION_TASK_ROUTING_FAIL_CLOSED", "message": str(exc)})
        if isinstance(exc, MissionSubsystemUnavailable):
            return self._json_response(503, {"status": "error", "code": "MISSION_SUBSYSTEM_UNAVAILABLE", "message": str(exc)})
        if isinstance(exc, MissionSubsystemProtocolError):
            return self._json_response(502, {"status": "error", "code": "MISSION_SUBSYSTEM_PROTOCOL_ERROR", "message": str(exc)})
        if isinstance(exc, MissionConcurrencyConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_VERSION_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionCommandConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_COMMAND_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionCommandNotFound):
            command_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_COMMAND_NOT_FOUND", "command_id": command_id})
        if isinstance(exc, MissionLifecycleGuardRejected):
            return self._json_response(409, {"status": "error", "code": "MISSION_LIFECYCLE_GUARD_REJECTED", "message": str(exc)})
        if isinstance(exc, MissionVersionObservationUnavailable):
            return self._json_response(503, {"status": "error", "code": "MISSION_VERSION_OBSERVATION_UNAVAILABLE", "message": str(exc)})
        if isinstance(exc, MissionEventNotFound):
            event_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_EVENT_NOT_FOUND", "event_id": event_id})
        if isinstance(exc, MissionEventIntegrityError):
            return self._json_response(503, {"status": "error", "code": "MISSION_EVENT_INTEGRITY_ERROR", "message": str(exc)})
        if isinstance(exc, MissionPlanContractConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_PLAN_CONTRACT_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionPlanContractGuardRejected):
            return self._json_response(409, {"status": "error", "code": "MISSION_PLAN_CONTRACT_GUARD_REJECTED", "message": str(exc)})
        if isinstance(exc, MissionPlanContractNotFound):
            mission_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_PLAN_CONTRACT_NOT_FOUND", "mission_id": mission_id})
        if isinstance(exc, MissionPlannerInputSnapshotConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_PLANNER_INPUT_SNAPSHOT_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionPlannerInputSnapshotGuardRejected):
            return self._json_response(409, {"status": "error", "code": "MISSION_PLANNER_INPUT_SNAPSHOT_GUARD_REJECTED", "message": str(exc)})
        if isinstance(exc, MissionPlannerInputSnapshotNotFound):
            mission_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_PLANNER_INPUT_SNAPSHOT_NOT_FOUND", "mission_id": mission_id})
        if isinstance(exc, MissionTaskDecompositionConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_TASK_DECOMPOSITION_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionTaskDecompositionGuardRejected):
            return self._json_response(409, {"status": "error", "code": "MISSION_TASK_DECOMPOSITION_GUARD_REJECTED", "message": str(exc)})
        if isinstance(exc, MissionTaskDecompositionNotFound):
            mission_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_TASK_DECOMPOSITION_NOT_FOUND", "mission_id": mission_id})
        if isinstance(exc, MissionPlannedTaskNotFound):
            planned_task_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_PLANNED_TASK_NOT_FOUND", "planned_task_id": planned_task_id})
        if isinstance(exc, MissionTaskDependencyGraphConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_TASK_DEPENDENCY_GRAPH_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionTaskDependencyGraphGuardRejected):
            return self._json_response(409, {"status": "error", "code": "MISSION_TASK_DEPENDENCY_GRAPH_GUARD_REJECTED", "message": str(exc)})
        if isinstance(exc, MissionTaskDependencyGraphNotFound):
            mission_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_TASK_DEPENDENCY_GRAPH_NOT_FOUND", "mission_id": mission_id})
        if isinstance(exc, MissionPlannerGenerationConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_PLANNER_GENERATION_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionPlannerGenerationGuardRejected):
            return self._json_response(409, {"status": "error", "code": "MISSION_PLANNER_GENERATION_GUARD_REJECTED", "message": str(exc)})
        if isinstance(exc, MissionPlannerGenerationNotFound):
            mission_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_PLANNER_GENERATION_NOT_FOUND", "mission_id": mission_id})
        if isinstance(exc, MissionPlanValidationConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_PLAN_VALIDATION_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionPlanValidationGuardRejected):
            return self._json_response(409, {"status": "error", "code": "MISSION_PLAN_VALIDATION_GUARD_REJECTED", "message": str(exc)})
        if isinstance(exc, MissionPlanValidationNotFound):
            mission_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_PLAN_VALIDATION_NOT_FOUND", "mission_id": mission_id})
        if isinstance(exc, MissionPlanVersioningConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_PLAN_VERSIONING_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionPlanVersioningGuardRejected):
            return self._json_response(409, {"status": "error", "code": "MISSION_PLAN_VERSIONING_GUARD_REJECTED", "message": str(exc)})
        if isinstance(exc, MissionPlanVersioningNotFound):
            mission_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_PLAN_VERSIONING_NOT_FOUND", "mission_id": mission_id})
        if isinstance(exc, MissionTaskReadinessProjectionConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_TASK_READINESS_PROJECTION_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionTaskReadinessProjectionGuardRejected):
            return self._json_response(409, {"status": "error", "code": "MISSION_TASK_READINESS_PROJECTION_GUARD_REJECTED", "message": str(exc)})
        if isinstance(exc, MissionTaskReadinessProjectionNotFound):
            mission_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_TASK_READINESS_PROJECTION_NOT_FOUND", "mission_id": mission_id})
        if isinstance(exc, MissionTaskRoutingIntentConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_TASK_ROUTING_INTENT_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionTaskRoutingIntentGuardRejected):
            return self._json_response(409, {"status": "error", "code": "MISSION_TASK_ROUTING_INTENT_GUARD_REJECTED", "message": str(exc)})
        if isinstance(exc, MissionTaskRoutingIntentNotFound):
            routing_intent_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_TASK_ROUTING_INTENT_NOT_FOUND", "routing_intent_id": routing_intent_id})
        if isinstance(exc, MissionTaskRoutingEligibilityConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_TASK_ROUTING_ELIGIBILITY_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionTaskRoutingEligibilityGuardRejected):
            return self._json_response(409, {"status": "error", "code": "MISSION_TASK_ROUTING_ELIGIBILITY_GUARD_REJECTED", "message": str(exc)})
        if isinstance(exc, MissionTaskRoutingEligibilityNotFound):
            eligibility_gate_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_TASK_ROUTING_ELIGIBILITY_NOT_FOUND", "eligibility_gate_id": eligibility_gate_id})
        if isinstance(exc, MissionTaskRouteSelectionConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_TASK_ROUTE_SELECTION_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionTaskRouteSelectionGuardRejected):
            return self._json_response(409, {"status": "error", "code": "MISSION_TASK_ROUTE_SELECTION_GUARD_REJECTED", "message": str(exc)})
        if isinstance(exc, MissionTaskRouteSelectionNotFound):
            route_decision_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_TASK_ROUTE_SELECTION_NOT_FOUND", "route_decision_id": route_decision_id})
        if isinstance(exc, MissionDelegationAuthorizationConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_DELEGATION_AUTHORIZATION_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionDelegationAuthorizationGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_DELEGATION_AUTHORIZATION_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionDelegationAuthorizationNotFound):
            authorization_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_DELEGATION_AUTHORIZATION_NOT_FOUND","delegation_authorization_id":authorization_id})
        if isinstance(exc, MissionTaskDelegationConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_TASK_DELEGATION_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionTaskDelegationGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_TASK_DELEGATION_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionTaskDelegationNotFound):
            delegation_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_TASK_DELEGATION_NOT_FOUND","delegation_id":delegation_id})
        if isinstance(exc, MissionDelegationDeliveryConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_DELEGATION_DELIVERY_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionDelegationDeliveryGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_DELEGATION_DELIVERY_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionDelegationDeliveryNotFound):
            receipt_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_DELEGATION_DELIVERY_NOT_FOUND","delivery_receipt_id":receipt_id})
        if isinstance(exc, MissionDelegationRecoveryControlConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_DELEGATION_RECOVERY_CONTROL_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionDelegationRecoveryControlGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_DELEGATION_RECOVERY_CONTROL_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionDelegationRecoveryControlNotFound):
            control_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_DELEGATION_RECOVERY_CONTROL_NOT_FOUND","recovery_control_id":control_id})
        if isinstance(exc, MissionRoutingDelegationRecoveryConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_ROUTING_DELEGATION_RECOVERY_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionRoutingDelegationRecoveryGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_ROUTING_DELEGATION_RECOVERY_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionRoutingDelegationRecoveryNotFound):
            checkpoint_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_ROUTING_DELEGATION_RECOVERY_NOT_FOUND","checkpoint_id":checkpoint_id})
        if isinstance(exc, MissionExecutionDispatchConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_EXECUTION_DISPATCH_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionExecutionDispatchGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_EXECUTION_DISPATCH_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionExecutionDispatchNotFound):
            execution_dispatch_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_EXECUTION_DISPATCH_NOT_FOUND","execution_dispatch_id":execution_dispatch_id})
        if isinstance(exc, MissionDispatchEligibilityConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_DISPATCH_ELIGIBILITY_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionDispatchEligibilityGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_DISPATCH_ELIGIBILITY_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionDispatchEligibilityNotFound):
            dispatch_eligibility_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_DISPATCH_ELIGIBILITY_NOT_FOUND","dispatch_eligibility_id":dispatch_eligibility_id})
        if isinstance(exc, MissionPreDispatchGovernanceConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_PRE_DISPATCH_GOVERNANCE_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionPreDispatchGovernanceGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_PRE_DISPATCH_GOVERNANCE_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionPreDispatchGovernanceNotFound):
            revalidation_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_PRE_DISPATCH_GOVERNANCE_REVALIDATION_NOT_FOUND","pre_dispatch_revalidation_id":revalidation_id})
        if isinstance(exc, MissionExecutionAttemptConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_EXECUTION_ATTEMPT_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionExecutionAttemptGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_EXECUTION_ATTEMPT_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionExecutionAttemptNotFound):
            execution_attempt_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_EXECUTION_ATTEMPT_NOT_FOUND","execution_attempt_id":execution_attempt_id})
        if isinstance(exc, MissionExecutionDeliveryConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_EXECUTION_DELIVERY_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionExecutionDeliveryGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_EXECUTION_DELIVERY_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionExecutionDeliveryNotFound):
            execution_delivery_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_EXECUTION_DELIVERY_NOT_FOUND","execution_delivery_id":execution_delivery_id})
        if isinstance(exc, MissionExecutionRunningProjectionConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_EXECUTION_RUNNING_PROJECTION_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionExecutionRunningProjectionGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_EXECUTION_RUNNING_PROJECTION_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionExecutionRunningProjectionNotFound):
            running_projection_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_EXECUTION_RUNNING_PROJECTION_NOT_FOUND","running_projection_id":running_projection_id})
        if isinstance(exc, MissionExecutionResultCaptureConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_EXECUTION_RESULT_CAPTURE_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionExecutionResultCaptureGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_EXECUTION_RESULT_CAPTURE_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionExecutionResultCaptureNotFound):
            result_capture_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_EXECUTION_RESULT_CAPTURE_NOT_FOUND","result_capture_id":result_capture_id})
        if isinstance(exc, MissionExecutionTerminationControlConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_EXECUTION_TERMINATION_CONTROL_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionExecutionTerminationControlGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_EXECUTION_TERMINATION_CONTROL_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionExecutionTerminationControlNotFound):
            control_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_EXECUTION_TERMINATION_CONTROL_NOT_FOUND","termination_control_id":control_id})
        if isinstance(exc, MissionExecutionOutcomePropagationConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_EXECUTION_OUTCOME_PROPAGATION_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionExecutionOutcomePropagationGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_EXECUTION_OUTCOME_PROPAGATION_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionExecutionOutcomePropagationNotFound):
            propagation_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_EXECUTION_OUTCOME_PROPAGATION_NOT_FOUND","outcome_propagation_id":propagation_id})
        if isinstance(exc, MissionExecutionRecoveryConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_EXECUTION_RECOVERY_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionExecutionRecoveryGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_EXECUTION_RECOVERY_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionExecutionRecoveryNotFound):
            checkpoint_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_EXECUTION_RECOVERY_NOT_FOUND","checkpoint_id":checkpoint_id})
        if isinstance(exc, MissionTaskOutcomeConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_TASK_OUTCOME_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionTaskOutcomeGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_TASK_OUTCOME_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionTaskOutcomeNotFound):
            task_outcome_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_TASK_OUTCOME_NOT_FOUND","task_outcome_id":task_outcome_id})
        if isinstance(exc, MissionTaskTerminalityEligibilityConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_TASK_TERMINALITY_ELIGIBILITY_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionTaskTerminalityEligibilityGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_TASK_TERMINALITY_ELIGIBILITY_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionTaskTerminalityEligibilityNotFound):
            gate_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_TASK_TERMINALITY_ELIGIBILITY_NOT_FOUND","eligibility_gate_id":gate_id})
        if isinstance(exc, MissionTaskEvidenceBindingConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_TASK_EVIDENCE_BINDING_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionTaskEvidenceBindingGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_TASK_EVIDENCE_BINDING_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionTaskEvidenceBindingNotFound):
            verification_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_TASK_EVIDENCE_BINDING_NOT_FOUND","verification_id":verification_id})
        if isinstance(exc, MissionTaskCompletionConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_TASK_COMPLETION_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionTaskCompletionGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_TASK_COMPLETION_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionTaskCompletionNotFound):
            task_completion_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_TASK_COMPLETION_NOT_FOUND","task_completion_id":task_completion_id})
        if isinstance(exc, MissionOutcomeAggregationConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_OUTCOME_AGGREGATION_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionOutcomeAggregationGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_OUTCOME_AGGREGATION_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionOutcomeAggregationNotFound):
            aggregation_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_OUTCOME_AGGREGATION_NOT_FOUND","aggregation_id":aggregation_id})
        if isinstance(exc, MissionSuccessEvaluationConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_SUCCESS_EVALUATION_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionSuccessEvaluationGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_SUCCESS_EVALUATION_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionSuccessEvaluationNotFound):
            evaluation_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_SUCCESS_EVALUATION_NOT_FOUND","evaluation_id":evaluation_id})
        if isinstance(exc, MissionCompletionReadinessConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_COMPLETION_READINESS_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionCompletionReadinessGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_COMPLETION_READINESS_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionCompletionReadinessNotFound):
            readiness_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_COMPLETION_READINESS_NOT_FOUND","readiness_id":readiness_id})
        if isinstance(exc, MissionVerifiedCompletionConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_VERIFIED_COMPLETION_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionVerifiedCompletionGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_VERIFIED_COMPLETION_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionVerifiedCompletionNotFound):
            declaration_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_VERIFIED_COMPLETION_NOT_FOUND","declaration_id":declaration_id})
        if isinstance(exc, MissionOutcomeRecoveryConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_OUTCOME_RECOVERY_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionOutcomeRecoveryGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_OUTCOME_RECOVERY_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionOutcomeRecoveryNotFound):
            checkpoint_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_OUTCOME_RECOVERY_NOT_FOUND","checkpoint_id":checkpoint_id})
        if isinstance(exc, MissionAdaptationReplanConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_ADAPTATION_REPLAN_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionAdaptationReplanGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_ADAPTATION_REPLAN_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionAdaptationReplanNotFound):
            adaptation_episode_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_ADAPTATION_REPLAN_NOT_FOUND","adaptation_episode_id":adaptation_episode_id})
        if isinstance(exc, MissionAdaptationTriggerClassificationConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_ADAPTATION_TRIGGER_CLASSIFICATION_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionAdaptationTriggerClassificationGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_ADAPTATION_TRIGGER_CLASSIFICATION_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionAdaptationTriggerClassificationNotFound):
            classification_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_ADAPTATION_TRIGGER_CLASSIFICATION_NOT_FOUND","classification_id":classification_id})
        if isinstance(exc, MissionReplanEligibilityGovernanceConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_REPLAN_ELIGIBILITY_GOVERNANCE_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionReplanEligibilityGovernanceGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_REPLAN_ELIGIBILITY_GOVERNANCE_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionReplanEligibilityGovernanceNotFound):
            gate_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_REPLAN_ELIGIBILITY_GOVERNANCE_NOT_FOUND","eligibility_gate_id":gate_id})
        if isinstance(exc, MissionReplanSnapshotConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_REPLAN_SNAPSHOT_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionReplanSnapshotGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_REPLAN_SNAPSHOT_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionReplanSnapshotNotFound):
            snapshot_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_REPLAN_SNAPSHOT_NOT_FOUND","replan_snapshot_id":snapshot_id})
        if isinstance(exc, MissionReplanCandidateConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_REPLAN_CANDIDATE_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionReplanCandidateGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_REPLAN_CANDIDATE_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionReplanCandidateNotFound):
            candidate_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_REPLAN_CANDIDATE_NOT_FOUND","replan_candidate_id":candidate_id})
        if isinstance(exc, MissionReplanValidationConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_REPLAN_VALIDATION_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionReplanValidationGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_REPLAN_VALIDATION_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionReplanValidationNotFound):
            validation_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_REPLAN_VALIDATION_NOT_FOUND","replan_validation_id":validation_id})
        if isinstance(exc, MissionReplanCommitConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_REPLAN_COMMIT_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionReplanCommitGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_REPLAN_COMMIT_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionReplanCommitNotFound):
            commit_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_REPLAN_COMMIT_NOT_FOUND","replan_commit_id":commit_id})
        if isinstance(exc, MissionReplanHandoffConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_REPLAN_HANDOFF_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionReplanHandoffGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_REPLAN_HANDOFF_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionReplanHandoffNotFound):
            handoff_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_REPLAN_HANDOFF_NOT_FOUND","replan_handoff_id":handoff_id})
        if isinstance(exc, MissionReplanRecoveryConflict):
            return self._json_response(409, {"status":"error","code":"MISSION_REPLAN_RECOVERY_CONFLICT","message":str(exc)})
        if isinstance(exc, MissionReplanRecoveryGuardRejected):
            return self._json_response(409, {"status":"error","code":"MISSION_REPLAN_RECOVERY_GUARD_REJECTED","message":str(exc)})
        if isinstance(exc, MissionReplanRecoveryNotFound):
            checkpoint_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status":"error","code":"MISSION_REPLAN_RECOVERY_NOT_FOUND","checkpoint_id":checkpoint_id})
        if isinstance(exc, MissionPlanningRecoveryConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_PLANNING_RECOVERY_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionPlanningRecoveryGuardRejected):
            return self._json_response(409, {"status": "error", "code": "MISSION_PLANNING_RECOVERY_GUARD_REJECTED", "message": str(exc)})
        if isinstance(exc, MissionPlanningRecoveryNotFound):
            mission_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_PLANNING_RECOVERY_NOT_FOUND", "mission_id": mission_id})
        if isinstance(exc, SubsystemRegistryIntegrityError):
            return self._json_response(503, {"status": "error", "code": "SUBSYSTEM_REGISTRY_INTEGRITY_ERROR", "message": str(exc)})
        if isinstance(exc, SubsystemNotFound):
            subsystem_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "SUBSYSTEM_NOT_FOUND", "subsystem_id": subsystem_id})
        if isinstance(exc, SubsystemCapabilityNotFound):
            capability_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "SUBSYSTEM_CAPABILITY_NOT_FOUND", "capability_id": capability_id})
        if isinstance(exc, MissionRepositoryIntegrityError):
            return self._json_response(503, {"status": "error", "code": "MISSION_REPOSITORY_INTEGRITY_ERROR", "message": str(exc)})
        if isinstance(exc, MissionStateConflict):
            return self._json_response(409, {"status": "error", "code": "MISSION_STATE_VERSION_CONFLICT", "message": str(exc)})
        if isinstance(exc, MissionIllegalTransition):
            return self._json_response(409, {"status": "error", "code": "MISSION_STATE_TRANSITION_ILLEGAL", "message": str(exc)})
        if isinstance(exc, MissionNotFound):
            mission_id = exc.args[0] if exc.args else "unknown"
            return self._json_response(404, {"status": "error", "code": "MISSION_NOT_FOUND", "mission_id": mission_id})
        try:
            from execution_subsystem.execution_contract import (
                ExecutionRequestConflict, ExecutionRequestIntegrityError, ExecutionRequestValidationError,
                ExecutionSourceNotFound, ExecutionSourceRejected, ExecutionSourceUnavailable,
            )
            if isinstance(exc, ExecutionRequestValidationError):
                return self._json_response(400, {"status": "invalid", "error": str(exc)})
            if isinstance(exc, ExecutionSourceNotFound):
                return self._json_response(404, {"status": "not_found", "error": str(exc)})
            if isinstance(exc, (ExecutionRequestConflict, ExecutionRequestIntegrityError, ExecutionSourceRejected)):
                return self._json_response(409, {"status": "rejected", "error": str(exc)})
            if isinstance(exc, ExecutionSourceUnavailable):
                return self._json_response(503, {"status": "unavailable", "error": str(exc)})
        except ImportError:
            pass
        body = {"status": "error", "code": "INTERNAL_ERROR", "message": str(exc)}
        if os.getenv("MISSION_HTTP_DEBUG", "0") == "1":
            body["traceback"] = traceback.format_exc()
        return self._json_response(500, body)

    def do_GET(self):
        try:
            parsed_url = urlparse(self.path)
            path = parsed_url.path.rstrip("/") or "/"
            wpt_parts = [part for part in path.split("/") if part]
            if path == "/api/wpt/intakes":
                try:
                    query = parse_qs(parsed_url.query, keep_blank_values=True, strict_parsing=True)
                except ValueError as exc:
                    raise MissionValidationError("malformed WPT intake query") from exc
                if (set(query) - {"mission_id", "task_id", "limit"}
                        or len(query.get("mission_id", [])) != 1
                        or len(query.get("task_id", [])) != 1
                        or len(query.get("limit", [])) > 1
                        or not query["mission_id"][0] or not query["task_id"][0]):
                    raise MissionValidationError("WPT intake query requires one mission_id and task_id")
                try:
                    limit = int(query.get("limit", ["50"])[0])
                except ValueError as exc:
                    raise MissionValidationError("WPT intake limit must be an integer") from exc
                if not 1 <= limit <= 200:
                    raise MissionValidationError("WPT intake limit must be between 1 and 200")
                service = self._authorize_wpt_request()
                if service is None:
                    return
                records = service.list_for_task(query["mission_id"][0], query["task_id"][0], limit=limit)
                return self._json_response(200, {"status": "ok", "count": len(records),
                                                 "intakes": records,
                                                 "execution_authorized": False,
                                                 "target_io_performed": False})
            if len(wpt_parts) == 5 and wpt_parts[:3] == ["api", "wpt", "intakes"] and wpt_parts[4] == "recon-handoff":
                if parsed_url.query:
                    return self._json_response(400, {"status": "invalid", "error": "WPT handoff route forbids query parameters"})
                service = self._authorize_wpt_request()
                if service is None:
                    return
                item = service.get_handoff(wpt_parts[3])
                return self._json_response(200 if item else 404, item or {"status": "not_found"})
            if parsed_url.path == "/ui" or parsed_url.path.startswith("/ui/"):
                return self._serve_console_asset(parsed_url.path)
            if path == "/health":
                return self._json_response(200, self._service().health())
            if path == "/api/dashboard/summary":
                return self._json_response(200, self._service().get_dashboard_summary())
            if path == "/api/operator/attention":
                query = parse_qs(parsed_url.query)
                try:
                    limit = int((query.get("limit") or ["50"])[0])
                except ValueError as exc:
                    raise MissionValidationError("limit must be an integer") from exc
                return self._json_response(200, self._service().get_operator_attention(limit=limit))
            if path == "/api/operator/attention/advanced":
                query = parse_qs(parsed_url.query)
                try:
                    limit = int((query.get("limit") or ["100"])[0])
                except ValueError as exc:
                    raise MissionValidationError("limit must be an integer") from exc
                return self._json_response(200, self._service().get_operator_attention_advanced(limit=limit))
            if path == "/api/mission-comparison":
                query = parse_qs(parsed_url.query)
                left = (query.get("left") or [None])[0]
                right = (query.get("right") or [None])[0]
                if not left or not right:
                    raise MissionValidationError("mission comparison requires left and right mission ids")
                return self._json_response(200, self._service().compare_missions(left, right))
            if path == "/api/missions":
                query = parse_qs(parsed_url.query)
                def one(name, default=None):
                    values = query.get(name)
                    return values[0] if values else default
                try:
                    limit = int(one("limit", "50"))
                    offset = int(one("offset", "0"))
                except ValueError as exc:
                    raise MissionValidationError("limit and offset must be integers") from exc
                terminal_raw = one("terminal")
                terminal = None
                if terminal_raw is not None:
                    normalized = terminal_raw.strip().lower()
                    if normalized in {"1", "true", "yes"}:
                        terminal = True
                    elif normalized in {"0", "false", "no"}:
                        terminal = False
                    else:
                        raise MissionValidationError("terminal must be true or false")
                return self._json_response(
                    200,
                    self._service().list_missions(
                        state=one("state"),
                        source_system=one("source_system"),
                        query=one("q"),
                        terminal=terminal,
                        visibility=one("visibility", "ALL"),
                        limit=limit,
                        offset=offset,
                    ),
                )
            if path == "/api/observability/trace-contract":
                return self._json_response(200, self._service().get_observability_trace_contract_definition())

            # Stage 3.4.1 canonical subsystem registry read-model API.
            # These endpoints expose only the persisted canonical registry and capability
            # contracts; they do not resolve runtime endpoints, probe health, select a
            # route, query Governance, delegate work, dispatch actions, or actuate targets.
            if path == "/api/subsystem-registry-definition":
                return self._json_response(200, self._service().get_subsystem_registry_definition())
            if path == "/api/subsystem-registry":
                return self._json_response(200, self._service().get_subsystem_registry())
            if path == "/api/subsystems":
                return self._json_response(200, self._service().list_subsystems())

            parts = [p for p in path.split("/") if p]
            if (
                len(parts) == 5
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "events"
                and parts[4] == "stream"
            ):
                return self._sse_mission_events(parts[2], parsed_url)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "plan-diff":
                query = parse_qs(parsed_url.query)
                try:
                    from_version = int((query.get("from") or [""])[0])
                    to_version = int((query.get("to") or [""])[0])
                except ValueError as exc:
                    raise MissionValidationError("plan diff requires integer from and to versions") from exc
                return self._json_response(200, self._service().get_plan_version_diff(
                    parts[2], from_version=from_version, to_version=to_version
                ))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "evidence-browser":
                query = parse_qs(parsed_url.query)
                try:
                    limit = int((query.get("limit") or ["250"])[0])
                except ValueError as exc:
                    raise MissionValidationError("evidence-browser limit must be an integer") from exc
                return self._json_response(200, self._service().get_evidence_browser(parts[2], limit=limit))
            if len(parts) == 4 and parts[:2] == ["api", "missions"] and parts[3] == "cti-pentest-feedback-contract":
                if parsed_url.query:
                    raise MissionValidationError("Mission CTI contract forbids query overrides")
                return self._json_response(200, self._service().get_cti_pentest_feedback_contract(parts[2]))
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "subsystems":
                return self._json_response(200, self._service().get_subsystem(parts[2]))
            if (
                len(parts) == 4
                and parts[0] == "api"
                and parts[1] == "subsystems"
                and parts[3] == "capabilities"
            ):
                return self._json_response(200, self._service().list_subsystem_capabilities(parts[2]))
            if (
                len(parts) == 5
                and parts[0] == "api"
                and parts[1] == "subsystems"
                and parts[3] == "capabilities"
            ):
                return self._json_response(200, self._service().get_subsystem_capability(parts[2], parts[4]))
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "missions":
                return self._json_response(200, self._service().get_mission(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "envelope":
                return self._json_response(200, self._service().get_envelope(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "canonical-contract":
                return self._json_response(200, self._service().get_canonical_mission_contract(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "plan-contract":
                return self._json_response(200, self._service().get_mission_plan_contract(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "plan-contract-definition":
                return self._json_response(200, self._service().get_mission_plan_contract_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "planner-input-snapshot":
                return self._json_response(200, self._service().get_planner_input_snapshot(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "planner-input-snapshot-definition":
                return self._json_response(200, self._service().get_planner_input_snapshot_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-decomposition":
                return self._json_response(200, self._service().get_task_decomposition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-decomposition-definition":
                return self._json_response(200, self._service().get_task_decomposition_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "planned-tasks":
                return self._json_response(200, self._service().list_planned_tasks(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "planned-tasks":
                return self._json_response(200, self._service().get_planned_task(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-dependency-graph":
                return self._json_response(200, self._service().get_task_dependency_graph(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-dependency-graph-definition":
                return self._json_response(200, self._service().get_task_dependency_graph_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "planner-generation-definition":
                return self._json_response(200, self._service().get_planner_generation_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "plan-validation":
                return self._json_response(200, self._service().get_plan_validation(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "plan-validation-definition":
                return self._json_response(200, self._service().get_plan_validation_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "plan-versions":
                return self._json_response(200, self._service().get_plan_version_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "plan-versions" and parts[4] == "active":
                return self._json_response(200, self._service().get_active_plan_version(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "plan-versioning-definition":
                return self._json_response(200, self._service().get_plan_versioning_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-readiness-projection":
                return self._json_response(200, self._service().get_active_task_readiness_projection(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-readiness-projections":
                return self._json_response(200, self._service().get_task_readiness_projection_history(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-readiness-projection-definition":
                return self._json_response(200, self._service().get_task_readiness_projection_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-routing-intents":
                return self._json_response(200, self._service().get_task_routing_intent_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-routing-intents":
                return self._json_response(200, self._service().get_task_routing_intent(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-routing-intent-definition":
                return self._json_response(200, self._service().get_task_routing_intent_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-routing-eligibility-gates":
                return self._json_response(200, self._service().get_task_routing_eligibility_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-routing-eligibility-gates":
                return self._json_response(200, self._service().get_task_routing_eligibility(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-routing-eligibility-definition":
                return self._json_response(200, self._service().get_task_routing_eligibility_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-route-decisions":
                return self._json_response(200, self._service().get_task_route_selection_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-route-decisions":
                return self._json_response(200, self._service().get_task_route_selection_decision(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-route-selection-definition":
                return self._json_response(200, self._service().get_task_route_selection_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-delegation-authorizations":
                return self._json_response(200, self._service().get_task_delegation_authorization_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-delegation-authorizations":
                return self._json_response(200, self._service().get_task_delegation_authorization(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-delegation-authorization-definition":
                return self._json_response(200, self._service().get_task_delegation_authorization_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-delegations":
                return self._json_response(200, self._service().get_task_delegation_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-delegations":
                return self._json_response(200, self._service().get_task_delegation(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-delegation-definition":
                return self._json_response(200, self._service().get_task_delegation_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "delegation-deliveries":
                return self._json_response(200, self._service().get_delegation_delivery_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "delegation-deliveries":
                return self._json_response(200, self._service().get_delegation_delivery(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "delegation-delivery-definition":
                return self._json_response(200, self._service().get_delegation_delivery_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "delegation-recovery-controls":
                return self._json_response(200, self._service().get_delegation_recovery_control_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "delegation-recovery-controls":
                return self._json_response(200, self._service().get_delegation_recovery_control(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "delegation-recovery-control-definition":
                return self._json_response(200, self._service().get_delegation_recovery_control_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-dispatch-contracts":
                return self._json_response(200, self._service().get_execution_dispatch_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-dispatch-contracts":
                return self._json_response(200, self._service().get_execution_dispatch_contract(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-dispatch-contract-definition":
                return self._json_response(200, self._service().get_execution_dispatch_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "dispatch-eligibility-gates":
                return self._json_response(200, self._service().get_dispatch_eligibility_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "dispatch-eligibility-gates":
                return self._json_response(200, self._service().get_dispatch_eligibility_gate(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "dispatch-eligibility-definition":
                return self._json_response(200, self._service().get_dispatch_eligibility_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "pre-dispatch-governance-revalidations":
                return self._json_response(200, self._service().get_pre_dispatch_revalidation_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "pre-dispatch-governance-revalidations":
                return self._json_response(200, self._service().get_pre_dispatch_revalidation(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "pre-dispatch-governance-revalidation-definition":
                return self._json_response(200, self._service().get_pre_dispatch_revalidation_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-attempts":
                return self._json_response(200, self._service().get_execution_attempt_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-attempts":
                return self._json_response(200, self._service().get_execution_attempt(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-attempt-definition":
                return self._json_response(200, self._service().get_execution_attempt_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-deliveries":
                return self._json_response(200, self._service().get_execution_delivery_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-deliveries":
                return self._json_response(200, self._service().get_execution_delivery(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-delivery-definition":
                return self._json_response(200, self._service().get_execution_delivery_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-running-projections":
                return self._json_response(200, self._service().get_execution_running_projection_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-running-projections":
                return self._json_response(200, self._service().get_execution_running_projection(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-running-projection-definition":
                return self._json_response(200, self._service().get_execution_running_projection_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-result-captures":
                return self._json_response(200, self._service().get_execution_result_capture_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-result-captures":
                return self._json_response(200, self._service().get_execution_result_capture(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-result-capture-definition":
                return self._json_response(200, self._service().get_execution_result_capture_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-termination-controls":
                return self._json_response(200, self._service().get_execution_termination_control_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-termination-controls":
                return self._json_response(200, self._service().get_execution_termination_control(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-outcome-propagations":
                return self._json_response(200, self._service().get_execution_outcome_propagation_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-outcome-propagations":
                return self._json_response(200, self._service().get_execution_outcome_propagation(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-timeout-cancellation-abort-failure-propagation-definition":
                return self._json_response(200, self._service().get_stage358_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "routing-delegation-lineage":
                return self._json_response(200, self._service().get_routing_delegation_event_lineage(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "routing-delegation-replay":
                return self._json_response(200, self._service().get_routing_delegation_event_replay(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "routing-delegation-recovery":
                return self._json_response(200, self._service().recover_routing_delegation_state(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "routing-delegation-recovery-checkpoints":
                return self._json_response(200, self._service().get_routing_delegation_recovery_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "routing-delegation-recovery-checkpoints":
                return self._json_response(200, self._service().get_routing_delegation_recovery_checkpoint(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "routing-delegation-lineage-definition":
                return self._json_response(200, self._service().get_routing_delegation_event_lineage_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-lineage":
                return self._json_response(200, self._service().get_execution_event_lineage(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-replay":
                return self._json_response(200, self._service().get_execution_event_replay(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-recovery":
                return self._json_response(200, self._service().recover_execution_state(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-recovery-checkpoints":
                return self._json_response(200, self._service().get_execution_recovery_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-recovery-checkpoints":
                return self._json_response(200, self._service().get_execution_recovery_checkpoint(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "adaptation-replans":
                return self._json_response(200, self._service().get_adaptation_replan_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "adaptation-replans":
                return self._json_response(200, self._service().get_adaptation_replan(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "adaptation-replan-definition":
                return self._json_response(200, self._service().get_adaptation_replan_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "adaptation-trigger-classifications":
                return self._json_response(200, self._service().get_adaptation_trigger_classification_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "adaptation-trigger-classifications":
                return self._json_response(200, self._service().get_adaptation_trigger_classification(parts[2], parts[4]))
            if len(parts) == 6 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "adaptation-replans" and parts[5] == "classification":
                return self._json_response(200, self._service().get_adaptation_trigger_classification_for_episode(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "adaptation-trigger-classification-definition":
                return self._json_response(200, self._service().get_adaptation_trigger_classification_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-eligibility-gates":
                return self._json_response(200, self._service().get_replan_eligibility_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-eligibility-gates":
                return self._json_response(200, self._service().get_replan_eligibility(parts[2], parts[4]))
            if len(parts) == 6 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "adaptation-replans" and parts[5] == "eligibility":
                return self._json_response(200, self._service().get_replan_eligibility_for_episode(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-eligibility-governance-definition":
                return self._json_response(200, self._service().get_replan_eligibility_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-snapshots":
                return self._json_response(200, self._service().get_replan_snapshot_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-snapshots":
                return self._json_response(200, self._service().get_replan_snapshot(parts[2], parts[4]))
            if len(parts) == 6 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "adaptation-replans" and parts[5] == "snapshot":
                return self._json_response(200, self._service().get_replan_snapshot_for_episode(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-snapshot-context-binding-definition":
                return self._json_response(200, self._service().get_replan_snapshot_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-candidates":
                return self._json_response(200, self._service().get_replan_candidate_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-candidates":
                return self._json_response(200, self._service().get_replan_candidate(parts[2], parts[4]))
            if len(parts) == 6 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-snapshots" and parts[5] == "candidate":
                return self._json_response(200, self._service().get_replan_candidate_for_snapshot(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "deterministic-replan-candidate-generation-definition":
                return self._json_response(200, self._service().get_replan_candidate_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-validations":
                return self._json_response(200, self._service().get_replan_validation_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-validations":
                return self._json_response(200, self._service().get_replan_validation(parts[2], parts[4]))
            if len(parts) == 6 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-candidates" and parts[5] == "validation":
                return self._json_response(200, self._service().get_replan_validation_for_candidate(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-candidate-validation-delta-feasibility-definition":
                return self._json_response(200, self._service().get_replan_validation_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-commits":
                return self._json_response(200, self._service().get_replan_commit_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-commits":
                return self._json_response(200, self._service().get_replan_commit(parts[2], parts[4]))
            if len(parts) == 6 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-validations" and parts[5] == "commit":
                return self._json_response(200, self._service().get_replan_commit_for_validation(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "authoritative-replan-commit-successor-plan-materialization-definition":
                return self._json_response(200, self._service().get_replan_commit_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-handoffs":
                return self._json_response(200, self._service().get_replan_handoff_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-handoffs":
                return self._json_response(200, self._service().get_replan_handoff(parts[2], parts[4]))
            if len(parts) == 6 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-commits" and parts[5] == "handoff":
                return self._json_response(200, self._service().get_replan_handoff_for_commit(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "atomic-replan-commit-supersession-handoff-definition":
                return self._json_response(200, self._service().get_replan_handoff_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-lineage":
                return self._json_response(200, self._service().get_replan_event_lineage(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-replay":
                return self._json_response(200, self._service().get_replan_event_replay(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-recovery":
                return self._json_response(200, self._service().get_replan_recovery(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-recovery-checkpoints":
                return self._json_response(200, self._service().get_replan_recovery_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-recovery-checkpoints":
                return self._json_response(200, self._service().get_replan_recovery_checkpoint(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-lineage-definition":
                return self._json_response(200, self._service().get_replan_event_lineage_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "outcome-lineage":
                return self._json_response(200, self._service().get_outcome_event_lineage(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "outcome-replay":
                return self._json_response(200, self._service().get_outcome_event_replay(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "outcome-recovery":
                return self._json_response(200, self._service().get_outcome_recovery(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "outcome-recovery-checkpoints":
                return self._json_response(200, self._service().get_outcome_recovery_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "outcome-recovery-checkpoints":
                return self._json_response(200, self._service().get_outcome_recovery_checkpoint(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "outcome-lineage-definition":
                return self._json_response(200, self._service().get_outcome_event_lineage_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-outcomes":
                return self._json_response(200, self._service().get_task_outcome_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-outcomes":
                return self._json_response(200, self._service().get_task_outcome(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-outcome-definition":
                return self._json_response(200, self._service().get_task_outcome_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-terminality-eligibility":
                return self._json_response(200, self._service().get_task_terminality_completion_eligibility_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-terminality-eligibility":
                return self._json_response(200, self._service().get_task_terminality_completion_eligibility(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-terminality-eligibility-definition":
                return self._json_response(200, self._service().get_task_terminality_completion_eligibility_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-evidence-binding-verifications":
                return self._json_response(200, self._service().get_task_evidence_binding_verification_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-evidence-binding-verifications":
                return self._json_response(200, self._service().get_task_evidence_binding_verification(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-evidence-binding-verification-definition":
                return self._json_response(200, self._service().get_task_evidence_binding_verification_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-completions":
                return self._json_response(200, self._service().get_task_completion_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-completions":
                return self._json_response(200, self._service().get_task_completion(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-completion-definition":
                return self._json_response(200, self._service().get_task_completion_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "mission-outcome-aggregations":
                return self._json_response(200, self._service().get_mission_outcome_aggregation_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "mission-outcome-aggregations":
                return self._json_response(200, self._service().get_mission_outcome_aggregation(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "mission-outcome-aggregation-definition":
                return self._json_response(200, self._service().get_mission_outcome_aggregation_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "mission-success-criteria-evaluations":
                return self._json_response(200, self._service().get_mission_success_evaluation_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "mission-success-criteria-evaluations":
                return self._json_response(200, self._service().get_mission_success_evaluation(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "mission-success-criteria-evaluation-definition":
                return self._json_response(200, self._service().get_mission_success_evaluation_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "completion-readiness-decisions":
                return self._json_response(200, self._service().get_completion_readiness_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "completion-readiness-decisions":
                return self._json_response(200, self._service().get_completion_readiness(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "completion-readiness-definition":
                return self._json_response(200, self._service().get_completion_readiness_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "verified-completion-declarations":
                return self._json_response(200, self._service().get_verified_completion_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "verified-completion-declarations":
                return self._json_response(200, self._service().get_verified_completion_declaration(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "verified-completion-definition":
                return self._json_response(200, self._service().get_verified_completion_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-lineage-definition":
                return self._json_response(200, self._service().get_execution_event_lineage_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "planning-lineage":
                return self._json_response(200, self._service().get_planning_event_lineage(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "planning-replay":
                return self._json_response(200, self._service().get_planning_event_replay(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "planning-recovery":
                return self._json_response(200, self._service().recover_planning_state(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "planning-recovery-checkpoint":
                return self._json_response(200, self._service().get_active_planning_recovery_checkpoint(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "planning-recovery-checkpoints":
                return self._json_response(200, self._service().get_planning_recovery_history(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "planning-lineage-definition":
                return self._json_response(200, self._service().get_planning_event_lineage_definition(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "planner-invocation":
                return self._json_response(200, self._service().get_planner_invocation(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "generated-plan":
                return self._json_response(200, self._service().get_generated_plan(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-dependency-edges":
                return self._json_response(200, self._service().list_task_dependency_edges(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "events":
                return self._json_response(200, self._service().get_mission_events(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "events":
                return self._json_response(200, self._service().get_mission_event(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "lineage":
                return self._json_response(200, self._service().get_mission_lineage(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "state":
                return self._json_response(200, self._service().get_mission_state(parts[2]))
            if (
                len(parts) == 5
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "state"
                and parts[4] == "transitions"
            ):
                return self._json_response(200, self._service().get_mission_state_history(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "scope-contract":
                return self._json_response(200, self._service().get_mission_scope_contract(parts[2]))
            if (
                len(parts) == 5
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "scope-contract"
                and parts[4] == "history"
            ):
                return self._json_response(200, self._service().get_mission_scope_contract_history(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "governance-visibility":
                return self._json_response(200, self._service().get_mission_governance_visibility(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "governance-binding":
                return self._json_response(200, self._service().get_mission_governance_binding(parts[2]))
            if (
                len(parts) == 5
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "governance-binding"
                and parts[4] == "history"
            ):
                return self._json_response(200, self._service().get_mission_governance_binding_history(parts[2]))
            if (
                len(parts) == 5
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "authorization-bindings"
                and parts[4] == "history"
            ):
                return self._json_response(200, self._service().get_mission_authorization_history(parts[2]))
            if (
                len(parts) == 5
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "authorization-bindings"
            ):
                return self._json_response(200, self._service().get_mission_authorization_binding(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "routing-tasks":
                return self._json_response(200, self._service().get_governed_routing_tasks(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "routing-tasks":
                return self._json_response(200, self._service().get_governed_routing_task(parts[2], parts[4]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "version-vector":
                return self._json_response(200, self._service().get_mission_version_vector(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "repository":
                return self._json_response(200, self._service().get_mission_repository(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "commands":
                return self._json_response(200, self._service().get_mission_command_history(parts[2]))
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "commands":
                return self._json_response(200, self._service().get_mission_command(parts[2], parts[4]))
            if (
                len(parts) == 4
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "lifecycle-command-contract"
            ):
                return self._json_response(200, self._service().get_mission_lifecycle_command_contract(parts[2]))
            if (
                len(parts) == 4
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "activation-contract"
            ):
                return self._json_response(200, self._service().get_mission_activation_contract(parts[2]))
            if (
                len(parts) == 4
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "planning-run-activation-contract"
            ):
                return self._json_response(200, self._service().get_mission_planning_run_activation_contract(parts[2]))
            if (
                len(parts) == 4
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "waiting-dependency-contract"
            ):
                return self._json_response(200, self._service().get_mission_waiting_dependency_contract(parts[2]))
            if (
                len(parts) == 4
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "pause-resume-replan-contract"
            ):
                return self._json_response(200, self._service().get_mission_pause_resume_replan_contract(parts[2]))
            if (
                len(parts) == 4
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "cleanup-completion-contract"
            ):
                return self._json_response(200, self._service().get_mission_cleanup_completion_contract(parts[2]))
            if (
                len(parts) == 4
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "lifecycle-automation-contract"
            ):
                return self._json_response(200, self._service().get_mission_lifecycle_automation_contract(parts[2]))
            if (
                len(parts) == 4
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "terminal-semantics-contract"
            ):
                return self._json_response(200, self._service().get_mission_terminal_semantics_contract(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "observability-trace":
                return self._json_response(200, self._service().get_observability_trace_identity(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "observability-events":
                return self._json_response(200, self._service().get_normalized_observability_events(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "observability-causal-graph":
                return self._json_response(200, self._service().get_global_causal_lineage_graph(parts[2]))
            if path == "/api/observability/causal-graph-contract":
                return self._json_response(200, self._service().get_global_causal_lineage_graph_contract_definition())
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "observability-live-state":
                return self._json_response(200, self._service().get_live_mission_state_execution_projection(parts[2]))
            if path == "/api/observability/live-state-contract":
                return self._json_response(200, self._service().get_live_mission_state_execution_projection_contract_definition())
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "decision-governance-evidence-trace":
                return self._json_response(200, self._service().get_decision_governance_evidence_trace(parts[2]))
            if path == "/api/observability/decision-governance-evidence-trace-contract":
                return self._json_response(200, self._service().get_decision_governance_evidence_trace_contract_definition())
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "observability-timeline":
                return self._json_response(200, self._service().get_deterministic_mission_timeline(parts[2]))
            if path == "/api/observability/timeline-contract":
                return self._json_response(200, self._service().get_deterministic_mission_timeline_contract_definition())
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "observability-diagnostics":
                return self._json_response(200, self._service().get_integrity_gap_consistency_diagnostics(parts[2]))
            if path == "/api/observability/diagnostics-contract":
                return self._json_response(200, self._service().get_integrity_gap_consistency_diagnostics_contract_definition())
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "observability-metrics-health":
                return self._json_response(200, self._service().get_observability_metrics_health(parts[2]))
            if path == "/api/observability/metrics-health-contract":
                return self._json_response(200, self._service().get_observability_metrics_health_contract_definition())
            if path == "/api/e2e/mission-scenario-acceptance-contract":
                return self._json_response(200, self._service().get_e2e_mission_acceptance_contract_definition())
            if path == "/api/e2e/intake-lifecycle-qualification-contract":
                return self._json_response(200, self._service().get_e2e_intake_lifecycle_qualification_contract_definition())
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "e2e-intake-lifecycle-qualification":
                return self._json_response(200, self._service().get_e2e_intake_lifecycle_qualification(parts[2]))
            if path == "/api/e2e/planning-task-graph-qualification-contract":
                return self._json_response(200, self._service().get_e2e_planning_task_graph_qualification_contract_definition())
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "e2e-planning-task-graph-qualification":
                return self._json_response(200, self._service().get_e2e_planning_task_graph_qualification(parts[2]))
            if path == "/api/e2e/routing-delegation-governance-qualification-contract":
                return self._json_response(200, self._service().get_e2e_routing_delegation_governance_qualification_contract_definition())
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "e2e-routing-delegation-governance-qualification":
                return self._json_response(200, self._service().get_e2e_routing_delegation_governance_qualification(parts[2]))
            if path == "/api/e2e/dispatch-execution-evidence-qualification-contract":
                return self._json_response(200, self._service().get_e2e_dispatch_execution_evidence_contract_definition())
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "e2e-dispatch-execution-evidence-qualification":
                return self._json_response(200, self._service().get_e2e_dispatch_execution_evidence_qualification(parts[2]))
            if path == "/api/e2e/completion-outcome-qualification-contract":
                return self._json_response(200, self._service().get_e2e_completion_outcome_contract_definition())
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "e2e-completion-outcome-qualification":
                return self._json_response(200, self._service().get_e2e_completion_outcome_qualification(parts[2]))
            if path == "/api/e2e/adaptation-replanning-qualification-contract":
                return self._json_response(200, self._service().get_e2e_adaptation_replanning_contract_definition())
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "e2e-adaptation-replanning-qualification":
                return self._json_response(200, self._service().get_e2e_adaptation_replanning_qualification(parts[2]))
            if path == "/api/e2e/restart-replay-recovery-qualification-contract":
                return self._json_response(200, self._service().get_e2e_restart_replay_recovery_contract_definition())
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "e2e-restart-replay-recovery-qualification":
                return self._json_response(200, self._service().get_e2e_restart_replay_recovery_qualification(parts[2]))
            if path == "/api/e2e/observation-reconstruction-forensic-equivalence-contract":
                return self._json_response(200, self._service().get_e2e_observation_reconstruction_forensic_contract_definition())
            if path == "/api/e2e/global-mission-orchestrator-acceptance-regression-gate-contract":
                return self._json_response(200, self._service().get_global_mission_acceptance_regression_gate_contract_definition())
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "e2e-observation-reconstruction-forensic-equivalence":
                return self._json_response(200, self._service().get_e2e_observation_reconstruction_forensic_equivalence(parts[2]))
            if path == "/api/observability/forensic-contract":
                return self._json_response(200, self._service().get_forensic_contract_definition())
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "forensic-evidence-bundle":
                return self._json_response(200, self._service().get_forensic_evidence_bundle(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "forensic-reconstruction":
                return self._json_response(200, self._service().get_forensic_reconstruction(parts[2]))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "forensic-query":
                try:
                    query = parse_qs(parsed_url.query, keep_blank_values=True, strict_parsing=True)
                except ValueError as exc:
                    raise MissionValidationError("malformed forensic query") from exc
                if set(query) - {"scope", "ref"} or len(query.get("scope", [])) != 1 or len(query.get("ref", [])) > 1:
                    raise MissionValidationError("forensic query requires one scope and at most one ref")
                return self._json_response(200, self._service().query_forensic_mission(
                    parts[2], scope=query["scope"][0], reference=query.get("ref", [None])[0]))

            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "routing-projection":
                return self._json_response(200, self._service().get_routing_projection(parts[2]))

            return self._json_response(404, {"status": "error", "code": "ROUTE_NOT_FOUND"})
        except Exception as exc:
            return self._handle_error(exc)

    def do_POST(self):
        try:
            parsed_url = urlparse(self.path)
            path = parsed_url.path.rstrip("/") or "/"
            wpt_parts = [part for part in path.split("/") if part]
            if path == "/api/wpt/intakes":
                if parsed_url.query:
                    return self._json_response(400, {"status": "invalid", "error": "WPT intake route forbids query parameters"})
                service = self._authorize_wpt_request()
                if service is None:
                    return
                result = service.submit(self._read_json(strict=True))
                return self._json_response(201 if result.get("created") else 200, result)
            if len(wpt_parts) == 5 and wpt_parts[:3] == ["api", "wpt", "intakes"] and wpt_parts[4] in {"stage6-results", "recon-handoff"}:
                if parsed_url.query:
                    return self._json_response(400, {"status": "invalid", "error": "WPT intake route forbids query parameters"})
                service = self._authorize_wpt_request()
                if service is None:
                    return
                body = self._read_json(strict=True)
                if wpt_parts[4] == "stage6-results":
                    result = service.submit_stage6_result(body)
                    return self._json_response(201 if result.get("created") else 200, result)
                result = service.handoff_to_recon(wpt_parts[3], body)
                status_code = 200 if result.get("delivery_status") == "DELIVERED" else 202
                return self._json_response(status_code, result)
            if path == "/api/missions/validate":
                payload = self._read_json()
                return self._json_response(200, self._service().validate_canonical_mission(payload))
            if path == "/api/missions":
                payload = self._read_json()
                result = self._service().create_mission(payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)

            parts = [p for p in path.split("/") if p]
            if len(parts) == 4 and parts[:2] == ["api", "missions"] and parts[3] == "cti-pentest-feedback":
                if parsed_url.query:
                    raise MissionValidationError("Mission CTI intake forbids query overrides")
                result = self._service().ingest_cti_pentest_feedback(parts[2], self._read_json(strict=True))
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "plan-contract":
                payload = self._read_json()
                result = self._service().create_mission_plan_contract(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "planner-input-snapshot":
                payload = self._read_json()
                result = self._service().create_planner_input_snapshot(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-decomposition":
                payload = self._read_json()
                result = self._service().create_task_decomposition(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-dependency-graph":
                payload = self._read_json()
                result = self._service().create_task_dependency_graph(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "planner-invocation":
                payload = self._read_json()
                result = self._service().invoke_planner_and_generate_plan(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "plan-validation":
                payload = self._read_json()
                result = self._service().validate_generated_plan_feasibility(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "plan-versions" and parts[4] == "activate":
                payload = self._read_json()
                result = self._service().activate_initial_plan_version(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "plan-versions" and parts[4] == "replan":
                payload = self._read_json()
                result = self._service().create_replan_successor_plan_version(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-readiness-projection":
                payload = self._read_json()
                result = self._service().create_task_readiness_projection(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-routing-intents":
                payload = self._read_json()
                result = self._service().create_task_routing_intent(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-routing-eligibility-gates":
                payload = self._read_json()
                result = self._service().create_task_routing_eligibility_gate(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-route-decisions":
                payload = self._read_json()
                result = self._service().create_task_route_selection_decision(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-delegation-authorizations":
                payload = self._read_json()
                result = self._service().authorize_task_delegation(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-delegations":
                payload = self._read_json()
                result = self._service().create_task_delegation(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "delegation-deliveries":
                payload = self._read_json()
                result = self._service().deliver_task_delegation(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "delegation-recovery-controls":
                payload = self._read_json()
                result = self._service().control_task_delegation_recovery(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-dispatch-contracts":
                payload = self._read_json()
                result = self._service().create_execution_dispatch_contract(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "dispatch-eligibility-gates":
                payload = self._read_json()
                result = self._service().create_dispatch_eligibility_gate(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "pre-dispatch-governance-revalidations":
                payload = self._read_json()
                result = self._service().authorize_pre_dispatch_execution(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-attempts":
                payload = self._read_json()
                result = self._service().commit_execution_attempt(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-deliveries":
                payload = self._read_json()
                result = self._service().deliver_execution_attempt(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-running-projections":
                payload = self._read_json()
                result = self._service().project_running_execution_state(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-result-captures":
                payload = self._read_json()
                result = self._service().capture_execution_result(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-termination-controls":
                payload = self._read_json()
                result = self._service().control_running_execution(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-outcome-propagations":
                payload = self._read_json()
                result = self._service().propagate_execution_outcome(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "execution-recovery-checkpoints":
                payload = self._read_json()
                result = self._service().create_execution_recovery_checkpoint(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-outcomes":
                payload = self._read_json()
                result = self._service().create_task_outcome(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-terminality-eligibility":
                payload = self._read_json()
                result = self._service().evaluate_task_terminality_completion_eligibility(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-evidence-binding-verifications":
                payload = self._read_json()
                result = self._service().verify_task_evidence_binding(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "task-completions":
                payload = self._read_json()
                result = self._service().commit_dependency_aware_task_completion(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "mission-outcome-aggregations":
                payload = self._read_json()
                result = self._service().aggregate_mission_outcome(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "mission-success-criteria-evaluations":
                payload = self._read_json()
                result = self._service().evaluate_mission_success_criteria(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "completion-readiness-decisions":
                payload = self._read_json()
                result = self._service().evaluate_completion_readiness(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "verified-completion-declarations":
                payload = self._read_json()
                result = self._service().declare_verified_completion(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "adaptation-replans":
                payload = self._read_json()
                result = self._service().create_adaptation_replan(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 6 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "adaptation-replans" and parts[5] == "classification":
                payload = self._read_json()
                result = self._service().classify_adaptation_trigger(parts[2], parts[4], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 6 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "adaptation-replans" and parts[5] == "eligibility":
                payload = self._read_json()
                result = self._service().evaluate_replan_eligibility(parts[2], parts[4], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 6 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "adaptation-replans" and parts[5] == "snapshot":
                payload = self._read_json()
                result = self._service().bind_replan_snapshot(parts[2], parts[4], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 6 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-snapshots" and parts[5] == "candidate":
                payload = self._read_json()
                result = self._service().generate_replan_candidate(parts[2], parts[4], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 6 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-candidates" and parts[5] == "validation":
                payload = self._read_json()
                result = self._service().validate_replan_candidate(parts[2], parts[4], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 6 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-validations" and parts[5] == "commit":
                payload = self._read_json()
                result = self._service().commit_authorized_replan(parts[2], parts[4], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 6 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-commits" and parts[5] == "handoff":
                payload = self._read_json()
                result = self._service().declare_replan_handoff(parts[2], parts[4], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "replan-recovery-checkpoints":
                payload = self._read_json()
                result = self._service().create_replan_recovery_checkpoint(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "outcome-recovery-checkpoints":
                payload = self._read_json()
                result = self._service().create_outcome_recovery_checkpoint(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "routing-delegation-recovery-checkpoints":
                payload = self._read_json()
                result = self._service().create_routing_delegation_recovery_checkpoint(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "planning-recovery-checkpoint":
                payload = self._read_json()
                result = self._service().create_planning_recovery_checkpoint(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if (
                len(parts) == 5
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "state"
                and parts[4] == "transitions"
            ):
                payload = self._read_json()
                return self._json_response(200, self._service().transition_mission_state(parts[2], payload))
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "scope-contract":
                payload = self._read_json()
                result = self._service().put_mission_scope_contract(parts[2], payload)
                status_code = 200 if result["idempotent_replay"] else 201
                return self._json_response(status_code, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "governance-binding":
                payload = self._read_json()
                result = self._service().put_mission_governance_binding(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "authorization-bindings":
                payload = self._read_json()
                result = self._service().authorize_mission_capability(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "commands":
                payload = self._read_json()
                result = self._service().execute_mission_command(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if (
                len(parts) == 5
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "lifecycle"
                and parts[4] == "commands"
            ):
                payload = self._read_json()
                result = self._service().execute_mission_lifecycle_command(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if (
                len(parts) == 5
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "lifecycle"
                and parts[4] == "events"
            ):
                payload = self._read_json()
                result = self._service().process_mission_lifecycle_event(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "missions" and parts[3] == "routing-tasks":
                payload = self._read_json()
                result = self._service().create_governed_routing_task(parts[2], payload)
                return self._json_response(200 if result["idempotent_replay"] else 201, result)
            if (
                len(parts) == 6
                and parts[0] == "api"
                and parts[1] == "missions"
                and parts[3] == "routing-tasks"
                and parts[5] == "dispatch"
            ):
                return self._json_response(200, self._service().dispatch_governed_routing_task(parts[2], parts[4]))

            return self._json_response(404, {"status": "error", "code": "ROUTE_NOT_FOUND"})
        except Exception as exc:
            return self._handle_error(exc)


def run_server(host="127.0.0.1", port=8780, service=None):
    MissionOrchestratorHandler.service = service or CanonicalMissionService()
    from .automatic_pip import start_worker
    automatic_pip_stop = start_worker(MissionOrchestratorHandler.service)
    httpd = ThreadingHTTPServer((host, int(port)), MissionOrchestratorHandler)
    print(f"APTS Global Mission Orchestrator running at http://{host}:{port}")
    print("Stage 3.4.7: Delegation Delivery, Acknowledgement & Ownership")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        automatic_pip_stop.set()
        httpd.server_close()
