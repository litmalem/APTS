from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import requests

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from .console_auth import require
from .console_api import create_router
from fastapi.middleware.cors import CORSMiddleware

from .architecture import ARCHITECTURE_VERSION, COMPONENTS, INVARIANTS, SERVICE_ID, SERVICE_NAME
from .config import settings
from .approval_auth import AUTH_MODE, ApprovalAccessError, ApprovalPrincipal, require_human_approver
from .governance_service import GovernanceError, GovernanceService
from .interface_catalog import build_interface_catalog, cti_health_url
from .diagnostics import GovernanceHealthDiagnostics
from .human_layer import build_human_layer_contract
from .human_interaction import build_human_interaction_contract
from .models import (
    ApprovalDecisionInput,
    AuthorizationRequest,
    PolicyDecisionRevalidationRequest,
    EmergencyStopInput,
    RevokeDecisionInput,
    ScopeContractCreate,
)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

service = GovernanceService()
diagnostics = GovernanceHealthDiagnostics(service, settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    service.events.start()
    yield
    service.events.stop()


app = FastAPI(
    title=SERVICE_NAME,
    version="0.1.0",
    description=(
        "Independent, deterministic, non-agent Governance & Safety Plane for APTS. "
        "Reasoning components cannot self-authorize through this service."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1", "http://localhost"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, ApprovalAccessError):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
    if isinstance(exc, GovernanceError):
        return HTTPException(status_code=400, detail=str(exc))
    log.exception("Unhandled Governance error")
    return HTTPException(status_code=500, detail=str(exc) if settings.debug else "Internal Governance error")


@app.get("/health")
def health():
    snapshot = diagnostics.snapshot(deep=False)
    db_check = next((c for c in snapshot.get("checks", []) if c.get("name") == "DATABASE_CONNECTIVITY"), {})
    worker_check = next((c for c in snapshot.get("checks", []) if c.get("name") == "OUTBOX_WORKER"), {})
    return {
        "status": "ok" if snapshot.get("health_status") == "HEALTHY" else "degraded",
        "service": SERVICE_NAME,
        "component_id": SERVICE_ID,
        "architecture_version": ARCHITECTURE_VERSION,
        "database": "ok" if db_check.get("status") == "PASS" else "error",
        "database_backend": settings.db_driver,
        "database_error": db_check.get("detail") if db_check.get("status") == "FAIL" else None,
        "outbox_worker_running": worker_check.get("status") == "PASS",
        "authorization_revalidation_mode": "AUTHORITATIVE_PRE_DISPATCH_FAIL_CLOSED",
        "policy_revocation_mode": "GRANULAR_POLICY_DECISION_EVENT_OUTBOX",
        "cross_subsystem_lineage_mode": "AUTHORITATIVE_EVENT_ID_CORRELATED",
        "governance_correlation_probe_mode": "MISSION_SCOPED_AUTHORITATIVE_READ_ONLY",
        "execution_revalidation_schema_version": "apts-gss-execution-revalidation-v1",
        "execution_revalidation_checks": ["SCOPE", "ROE", "POLICY", "RISK", "EXPIRY", "REVOCATION", "TARGET", "TECHNIQUE"],
        "human_approval_authentication": AUTH_MODE,
        "human_approval_payload_identity_authoritative": False,
        "human_approval_single_use": True,
        "diagnostics_mode": "READ_ONLY_READINESS_WITH_OPTIONAL_DEEP_DEPENDENCY_PROBES",
        "readiness_status": snapshot.get("readiness_status"),
        "diagnostic_summary": snapshot.get("summary"),
    }


@app.get("/api/governance/diagnostics")
def governance_diagnostics(deep: bool = False):
    return {
        "status": "completed",
        "diagnostics": diagnostics.snapshot(deep=bool(deep)),
    }


@app.get("/api/governance/runtime/status")
def runtime_status():
    db_ok = False
    db_error = None
    emergency = None
    outbox = None
    try:
        db_ok = service.repo.db.ping()
        if db_ok:
            emergency = service.repo.get_emergency_state()
            outbox = service.repo.outbox_stats()
    except Exception as exc:
        db_error = str(exc)

    cti_ok = False
    cti_error = None
    cti_health = None
    try:
        response = requests.get(
            cti_health_url(settings),
            timeout=min(max(settings.cti_event_api_timeout_seconds, 0.5), 3.0),
        )
        cti_ok = 200 <= response.status_code < 300
        if cti_ok:
            try:
                cti_health = response.json()
            except Exception:
                cti_health = {"http_status": response.status_code}
        else:
            cti_error = f"HTTP {response.status_code}"
    except Exception as exc:
        cti_error = str(exc)

    return {
        "status": "completed",
        "service": {
            "name": SERVICE_NAME,
            "component_id": SERVICE_ID,
            "architecture_version": ARCHITECTURE_VERSION,
            "host": settings.host,
            "port": settings.port,
            "outbox_worker_running": bool(service.events._thread and service.events._thread.is_alive()),
        },
        "database": {
            "status": "ok" if db_ok else "error",
            "host": settings.db_host,
            "port": settings.db_port,
            "database": settings.db_name,
            "error": db_error,
        },
        "cti_event_api": {
            "status": "reachable" if cti_ok else "unreachable",
            "publish_url": settings.cti_event_api_url,
            "health_url": cti_health_url(settings),
            "health": cti_health,
            "error": cti_error,
        },
        "emergency_state": emergency,
        "outbox": outbox,
    }


@app.get("/api/governance/interfaces")
def interfaces():
    return {"status": "completed", **build_interface_catalog(settings)}


@app.get("/api/governance/outbox/status")
def outbox_status(limit: int = 25):
    try:
        return {
            "status": "completed",
            "worker_running": bool(service.events._thread and service.events._thread.is_alive()),
            "destination": settings.cti_event_api_url,
            "poll_seconds": settings.outbox_poll_seconds,
            "stats": service.repo.outbox_stats(),
            "recent": service.repo.recent_outbox(limit=limit),
        }
    except Exception as exc:
        raise _http_error(exc)


@app.get("/api/governance/human-layer")
def human_layer_contract(principal=Depends(require("read"))):
    return build_human_layer_contract(service)


@app.get("/api/governance/human-interaction")
def human_interaction_contract(principal=Depends(require("read"))):
    from .console_auth import capabilities
    return build_human_interaction_contract(
        principal_id=principal.principal_id,
        roles=principal.roles,
        capabilities=capabilities(principal),
    )


@app.get("/api/governance/architecture")
def architecture():
    return {
        "status": "completed",
        "service": SERVICE_NAME,
        "architecture_version": ARCHITECTURE_VERSION,
        "component_type": "Independent Non-Agent Governance Plane",
        "components": COMPONENTS,
        "invariants": INVARIANTS,
        "decision_values": ["ALLOW", "DENY", "REVIEW"],
        "authority_boundary": {
            "governance": "policy/scope/authorization/emergency authority",
            "cti_agents": "reasoning/proposal only",
            "pentest_agents": "reasoning/proposal only",
            "execution_gateway": "deterministic enforcement of valid governance decision",
        },
    }


@app.post("/api/governance/scope-contracts")
def create_scope_contract(payload: ScopeContractCreate):
    try:
        return {"status": "completed", "scope_contract": service.create_scope_contract(payload)}
    except Exception as exc:
        raise _http_error(exc)


@app.get("/api/governance/scope-contracts/{scope_contract_id}")
def get_scope_contract(scope_contract_id: str):
    try:
        row = service.repo.get_scope_contract(scope_contract_id)
        if not row:
            raise HTTPException(status_code=404, detail="Scope contract not found")
        return {"status": "completed", "scope_contract": row}
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc)


@app.get("/api/governance/compliance/obligations")
def compliance_obligations(policy_set_id: str = "default-policy", action_class: str = ""): 
    try:
        return {
            "status": "completed",
            "policy_set_id": policy_set_id,
            "action_class": action_class or None,
            "obligations": service.compliance.obligations(policy_set_id, action_class),
        }
    except Exception as exc:
        raise _http_error(exc)


@app.post("/api/governance/authorization/evaluate")
def evaluate_authorization(payload: AuthorizationRequest):
    try:
        return {"status": "completed", "policy_decision": service.evaluate_authorization(payload)}
    except Exception as exc:
        raise _http_error(exc)


@app.post("/api/governance/authorization/revalidate")
def revalidate_authorization(payload: PolicyDecisionRevalidationRequest):
    try:
        return {"status": "completed", "revalidation": service.revalidate_policy_decision(payload)}
    except Exception as exc:
        raise _http_error(exc)


@app.get("/api/governance/correlation/missions/{mission_id}")
def mission_correlation_snapshot(mission_id: str):
    try:
        key = str(mission_id or "").strip()
        if not key:
            raise HTTPException(status_code=400, detail="mission_id is required")
        return {
            "status": "completed",
            "correlation_snapshot": service.mission_correlation_snapshot(key),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc)


@app.get("/api/governance/decisions/{decision_id}")
def get_decision(decision_id: str):
    try:
        row = service.repo.get_policy_decision(decision_id)
        if not row:
            raise HTTPException(status_code=404, detail="Policy decision not found")
        return {"status": "completed", "policy_decision": row}
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc)


@app.post("/api/governance/decisions/{decision_id}/revoke")
def revoke_decision(decision_id: str, payload: RevokeDecisionInput, principal=Depends(require("revoke"))):
    payload = payload.model_copy(update={"actor_id": principal.principal_id})
    try:
        return {"status": "completed", "revocation": service.revoke_decision(decision_id, payload)}
    except Exception as exc:
        raise _http_error(exc)


@app.get("/api/governance/approvals/{approval_request_id}")
def get_approval(approval_request_id: str):
    try:
        row = service.repo.get_approval_request(approval_request_id)
        if not row:
            raise HTTPException(status_code=404, detail="Approval request not found")
        return {"status": "completed", "approval_request": row}
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc)


@app.post("/api/governance/approvals/{approval_request_id}/decision")
def decide_approval(approval_request_id: str, payload: ApprovalDecisionInput,
                    principal: ApprovalPrincipal = Depends(require_human_approver)):
    try:
        return {"status": "completed", **service.decide_approval(approval_request_id, payload, principal=principal)}
    except Exception as exc:
        raise _http_error(exc)


@app.get("/api/governance/emergency-stop")
def emergency_state():
    try:
        return {"status": "completed", "emergency_state": service.repo.get_emergency_state()}
    except Exception as exc:
        raise _http_error(exc)


@app.post("/api/governance/emergency-stop/activate")
def activate_emergency_stop(payload: EmergencyStopInput, principal=Depends(require("emergency_activate"))):
    payload = payload.model_copy(update={"actor_id": principal.principal_id})
    try:
        with service.repo.db.connect():
            row = service.repo.db.fetch_one("SELECT * FROM gov_emergency_state WHERE singleton_id=1 FOR UPDATE")
            expected = payload.metadata.get("expected_version")
            if expected is not None and (not row or row["version"] != expected):
                raise HTTPException(409, "Emergency state changed; refresh")
            return {"status": "completed", "emergency_state": service.activate_emergency_stop(payload)}
    except Exception as exc:
        raise _http_error(exc)


@app.post("/api/governance/emergency-stop/release")
def release_emergency_stop(payload: EmergencyStopInput, principal=Depends(require("emergency_release"))):
    payload = payload.model_copy(update={"actor_id": principal.principal_id})
    try:
        with service.repo.db.connect():
            row = service.repo.db.fetch_one("SELECT * FROM gov_emergency_state WHERE singleton_id=1 FOR UPDATE")
            expected = payload.metadata.get("expected_version")
            if expected is not None and (not row or row["version"] != expected):
                raise HTTPException(409, "Emergency state changed; refresh")
            return {"status": "completed", "emergency_state": service.release_emergency_stop(payload)}
    except Exception as exc:
        raise _http_error(exc)


@app.post("/api/governance/events/retry")
def retry_outbox(principal=Depends(require("retry"))):
    try:
        service.audit.record("OUTBOX_RETRY_REQUESTED", actor_id=principal.principal_id, subject_type="EVENT_OUTBOX", payload={"limit": 1})
        delivered = service.events.deliver_pending(limit=1)
        return {"status": "completed", "delivered": delivered}
    except Exception as exc:
        raise _http_error(exc)


app.include_router(create_router(lambda: service))


@app.middleware("http")
async def machine_boundary(request: Request, call_next):
    # Existing local Mission/CTI callers retain their machine contracts.
    # Browsers must use the authenticated console scope endpoint.
    paths = {"/api/governance/scope-contracts", "/api/governance/authorization/evaluate", "/api/governance/authorization/revalidate"}
    if request.method == "POST" and request.url.path in paths:
        host = request.client.host if request.client else ""
        if host not in {"127.0.0.1", "::1", "testclient"} or request.headers.get("origin") or request.headers.get("sec-fetch-site"):
            return JSONResponse({"detail": "LOCAL_MACHINE_ENDPOINT_ONLY"}, status_code=403)
    return await call_next(request)
