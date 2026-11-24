from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from config import Config


@dataclass(frozen=True)
class ServiceInterface:
    """Declarative network/interface metadata shown by the CTI Component Manager.

    This catalog is intentionally descriptive only. It does not grant authority,
    open sockets, or perform connectivity checks. Runtime status is supplied by
    the UI/service manager where appropriate.
    """

    entity: str
    peer: str
    protocol: str
    host: str
    port: Optional[int]
    interface: str
    purpose: str
    direction: str
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "entity": self.entity,
            "peer": self.peer,
            "protocol": self.protocol,
            "host": self.host,
            "port": self.port,
            "interface": self.interface,
            "purpose": self.purpose,
            "direction": self.direction,
            "notes": self.notes,
        }


def _endpoint_parts(url: str, *, default_host: str = "", default_port: Optional[int] = None) -> tuple[str, Optional[int], str, str]:
    parsed = urlparse(str(url or "").strip())
    scheme = (parsed.scheme or "").upper()
    host = parsed.hostname or default_host
    if parsed.port is not None:
        port = parsed.port
    elif parsed.scheme == "https":
        port = 443
    elif parsed.scheme == "http":
        port = 80
    else:
        port = default_port
    path = parsed.path or "/"
    return scheme, port, host, path


def provided_interfaces(host: str = "127.0.0.1", port: int = 8765) -> List[ServiceInterface]:
    """Interfaces exposed by VulnDesk itself.

    The Pentest Enrichment API is the current socket/listener exposed by the CTI
    subsystem. Multiple logical consumers share that listener but use different
    endpoint groups.
    """

    bind_host = str(host or "127.0.0.1")
    bind_port = int(port)
    return [
        ServiceInterface(
            entity="CTI-INF01 · Pentest Enrichment API Adapter",
            peer="Pentest Subsystem / Global Mission Orchestrator",
            protocol="HTTP",
            host=bind_host,
            port=bind_port,
            interface=(
                "POST /api/pentest/enrich-scan; POST /api/cti/enrich-scan; "
                "POST /api/cti/missions/start; GET /api/cti/missions/{mission_id}; "
                "GET /api/cti/pip/{pip_id}"
            ),
            purpose="Pentest enrichment, CTI mission control, and PIP retrieval",
            direction="PROVIDED",
            notes="Transport adapter only; no CTI reasoning authority.",
        ),
        ServiceInterface(
            entity="CTI-INF01 · Pentest Enrichment API Adapter",
            peer="aptsGSS · Governance & Safety Plane outbox/event publisher",
            protocol="HTTP",
            host=bind_host,
            port=bind_port,
            interface="POST /api/cti/events/publish",
            purpose="Ingress for governance/safety events into the VulnDesk CTI event runtime",
            direction="PROVIDED",
            notes="Used for cross-subsystem governance event delivery.",
        ),
        ServiceInterface(
            entity="CTI-INF01 · Pentest Enrichment API Adapter",
            peer="Operator / Diagnostics / Integration clients",
            protocol="HTTP",
            host=bind_host,
            port=bind_port,
            interface=(
                "GET /health; GET /api/cti/diagnostics; GET /api/cti/components; GET /api/cti/architecture; "
                "GET /api/cti/events/{mission_id}; "
                "GET /api/cti/tasks/{task_id}/lineage; GET /api/cti/tasks/{task_id}/integrity; "
                "GET /api/cti/missions/{mission_id}/lineage; GET /api/cti/missions/{mission_id}/integrity; GET /api/cti/missions/{mission_id}/diagnostics"
            ),
            purpose="Health/readiness diagnostics, architecture discovery, event trace, canonical Task/mission lineage, Stage 2.9.4 Governance correlation, Stage 2.9.5 integrity probes, and Stage 2.9.6 mission diagnostics",
            direction="PROVIDED",
            notes="Read/diagnostic interfaces except event ingestion endpoints listed separately.",
        ),
    ]


def consumed_interfaces() -> List[ServiceInterface]:
    """External service interfaces actively consumed by VulnDesk.

    Values come from the effective Config class so the UI reflects the local
    .env configuration without exposing credentials or API keys.
    """

    gov_scheme, gov_port, gov_host, _ = _endpoint_parts(
        Config.GOVERNANCE_BASE_URL,
        default_host="127.0.0.1",
        default_port=8770,
    )
    nvd_scheme, nvd_port, nvd_host, nvd_path = _endpoint_parts(Config.NVD_API_URL)
    cpe_scheme, cpe_port, cpe_host, cpe_path = _endpoint_parts(Config.NVD_CPE_API_URL)
    mitre_scheme, mitre_port, mitre_host, mitre_path = _endpoint_parts(Config.MITRE_ATTACK_API_ROOT)
    cwe_scheme, cwe_port, cwe_host, cwe_path = _endpoint_parts(Config.CWE_API_ROOT)

    governance_state = "enabled" if Config.GOVERNANCE_ENABLED else "disabled"

    return [
        ServiceInterface(
            entity="CTI-INF05 · GovernanceClient (used by CTI-A02)",
            peer="aptsGSS · GOV-PLANE",
            protocol=gov_scheme or "HTTP",
            host=gov_host,
            port=gov_port,
            interface=(
                "GET /health; POST /api/governance/authorization/evaluate; "
                "POST /api/governance/authorization/revalidate; "
                "GET /api/governance/decisions/{decision_id}; "
                "GET /api/governance/correlation/missions/{mission_id}"
            ),
            purpose="Authoritative CTI source authorization, fail-closed pre-dispatch PolicyDecision revalidation, and read-only mission Governance correlation",
            direction="CONSUMED",
            notes=f"{governance_state}; fail-closed; timeout={Config.GOVERNANCE_TIMEOUT_SECONDS:g}s",
        ),
        ServiceInterface(
            entity="DbAdapter / ORM · all persistent CTI components",
            peer=f"MariaDB · {Config.DB_NAME}",
            protocol="MYSQL/TCP",
            host=Config.DB_HOST,
            port=int(Config.DB_PORT),
            interface=f"database={Config.DB_NAME}",
            purpose="Persistent CTI, runtime state, registry, event log, and derived artifacts",
            direction="CONSUMED",
            notes="Credentials intentionally not displayed.",
        ),
        ServiceInterface(
            entity="CTI-INF04 · Source Sync Connector / NVD CVE Sync",
            peer="NIST NVD CVE API 2.0",
            protocol=nvd_scheme or "HTTPS",
            host=nvd_host,
            port=nvd_port,
            interface=nvd_path,
            purpose="CVE/vulnerability acquisition for source_id=nvd-cve",
            direction="CONSUMED",
            notes=f"timeout={Config.NVD_TIMEOUT_SECONDS}s; page_size={Config.NVD_PAGE_SIZE}",
        ),
        ServiceInterface(
            entity="CTI-INF04 · Source Sync Connector / NVD CPE Sync",
            peer="NIST NVD CPE API 2.0",
            protocol=cpe_scheme or "HTTPS",
            host=cpe_host,
            port=cpe_port,
            interface=cpe_path,
            purpose="CPE dictionary acquisition for source_id=nvd-cpe",
            direction="CONSUMED",
            notes=f"timeout={Config.NVD_CPE_TIMEOUT_SECONDS}s; page_size={Config.NVD_CPE_PAGE_SIZE}",
        ),
        ServiceInterface(
            entity="CTI-INF04 · Source Sync Connector / ATT&CK Sync",
            peer="MITRE ATT&CK TAXII 2.1",
            protocol=mitre_scheme or "HTTPS",
            host=mitre_host,
            port=mitre_port,
            interface=f"{mitre_path}/collections/{{collection_id}}/objects",
            purpose="ATT&CK techniques, malware, intrusion sets, and relationships",
            direction="CONSUMED",
            notes=f"timeout={Config.MITRE_TIMEOUT_SECONDS}s",
        ),
        ServiceInterface(
            entity="CWE Catalog Service / CWE API client",
            peer="MITRE CWE REST API",
            protocol=cwe_scheme or "HTTPS",
            host=cwe_host,
            port=cwe_port,
            interface=f"{cwe_path}/cwe/...",
            purpose="CWE catalog lookup and synchronization",
            direction="CONSUMED",
            notes=f"timeout={Config.CWE_TIMEOUT_SECONDS}s",
        ),
    ]
