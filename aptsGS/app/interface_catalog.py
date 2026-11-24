from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import urlsplit

from .architecture import SERVICE_ID, SERVICE_NAME
from .config import Settings, settings


def _endpoint_parts(url: str) -> tuple[str, str, int, str]:
    parsed = urlsplit(url)
    scheme = (parsed.scheme or "http").lower()
    host = parsed.hostname or ""
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"
    return scheme.upper(), host, int(port), path


def build_interface_catalog(cfg: Settings = settings) -> Dict[str, List[Dict[str, Any]]]:
    provided = [
        {
            "provider": SERVICE_ID,
            "entity": SERVICE_NAME,
            "consumer": "VulnDesk / APTS subsystems / Operator",
            "protocol": "HTTP",
            "host": cfg.host,
            "port": cfg.port,
            "endpoint": "/health",
            "function": "Runtime health, database and outbox-worker status",
        },
        {
            "provider": SERVICE_ID,
            "entity": SERVICE_NAME,
            "consumer": "Operator / Diagnostics / Integration clients",
            "protocol": "HTTP",
            "host": cfg.host,
            "port": cfg.port,
            "endpoint": "/api/governance/diagnostics?deep={true|false}",
            "function": "Stage 2.9.6 read-only Governance readiness, outbox, emergency-stop, and optional CTI dependency diagnostics",
        },
        {
            "provider": "HUMAN-LAYER/HUMAN-INTERACTION",
            "entity": "Human Authority & Interaction Contracts",
            "consumer": "Governance Operations Console / authorized operator",
            "protocol": "HTTP",
            "host": cfg.host,
            "port": cfg.port,
            "endpoint": "/api/governance/human-layer ; /api/governance/human-interaction",
            "function": "Read-only explicit human authority, workflow, identity, and safety-boundary contracts",
        },
        {
            "provider": "GOV-S01",
            "entity": "Scope & Rules of Engagement Service",
            "consumer": "Global Mission Orchestrator / Operator",
            "protocol": "HTTP",
            "host": cfg.host,
            "port": cfg.port,
            "endpoint": "/api/governance/scope-contracts",
            "function": "Create/read versioned ScopeContract and RoE boundaries",
        },
        {
            "provider": "GOV-S02/GOV-S04",
            "entity": "Policy & Authorization / Deterministic Action Gate",
            "consumer": "VulnDesk GovernanceClient / Pentest components",
            "protocol": "HTTP",
            "host": cfg.host,
            "port": cfg.port,
            "endpoint": "/api/governance/authorization/evaluate ; /api/governance/authorization/revalidate",
            "function": "Authoritative ALLOW/DENY/REVIEW decision and pre-dispatch PolicyDecision revalidation",
        },
        {
            "provider": "GOV-PLANE",
            "entity": "Governance Correlation Read Model",
            "consumer": "VulnDesk Canonical Lineage Projector",
            "protocol": "HTTP",
            "host": cfg.host,
            "port": cfg.port,
            "endpoint": "/api/governance/correlation/missions/{mission_id}",
            "function": "Read-only authoritative mission provenance for Stage 2.9.4 cross-subsystem correlation",
        },
        {
            "provider": "GOV-S06",
            "entity": "Kill Switch & Emergency Stop Service",
            "consumer": "Governance Operations Console / authorized operator",
            "protocol": "HTTP",
            "host": cfg.host,
            "port": cfg.port,
            "endpoint": "/api/governance/emergency-stop/*",
            "function": "Read, activate, and release emergency-stop state",
        },
        {
            "provider": "GOV-PLANE",
            "entity": "Transactional Outbox Operations",
            "consumer": "Governance Operations Console",
            "protocol": "HTTP",
            "host": cfg.host,
            "port": cfg.port,
            "endpoint": "/api/governance/outbox/status ; /api/governance/events/retry",
            "function": "Monitor and retry governance-event delivery",
        },
    ]

    cti_protocol, cti_host, cti_port, cti_path = _endpoint_parts(cfg.cti_event_api_url)
    consumed = [
        {
            "consumer": "GovernanceRepository / all GOV-Sxx services",
            "provider": "MariaDB",
            "protocol": "MYSQL/TCP",
            "host": cfg.db_host,
            "port": cfg.db_port,
            "endpoint": cfg.db_name,
            "function": "Authoritative governance persistence",
        },
        {
            "consumer": "GovernanceEventPublisher",
            "provider": "VulnDesk CTI Event API",
            "protocol": cti_protocol,
            "host": cti_host,
            "port": cti_port,
            "endpoint": cti_path,
            "function": "Publish governance events through transactional outbox",
        },
    ]
    return {"provided": provided, "consumed": consumed}


def cti_health_url(cfg: Settings = settings) -> str:
    parsed = urlsplit(cfg.cti_event_api_url)
    scheme = parsed.scheme or "http"
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if scheme == "https" else 80)
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    authority = host if default_port else f"{host}:{port}"
    return f"{scheme}://{authority}/health"
