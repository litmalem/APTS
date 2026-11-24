from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class CtiComponentDefinition:
    component_id: str
    service_key: str
    component_name: str
    component_type: str
    mechanism: str
    authority_boundary: str
    optional_component: bool = False
    enabled: bool = True
    sort_order: int = 0

    def as_registry_row(self) -> Dict[str, Any]:
        return {
            "component_id": self.component_id,
            "service_key": self.service_key,
            "service_name": self.component_name,
            "component_type": self.component_type,
            "mechanism": self.mechanism,
            "authority_boundary": self.authority_boundary,
            "optional_component": 1 if self.optional_component else 0,
            "enabled": 1 if self.enabled else 0,
            "sort_order": self.sort_order,
        }


# Canonical module registry from the harmonized dissertation design.
CTI_COMPONENTS: List[CtiComponentDefinition] = [
    CtiComponentDefinition(
        "CTI-A01", "cti_subsystem_orchestrator", "CTI Subsystem Orchestrator",
        "Agent", "Hybrid Reactive-Deliberative", "Task proposal/coordination only", sort_order=10,
    ),
    CtiComponentDefinition(
        "CTI-A02", "cti_acquisition_freshness_agent", "CTI Acquisition & Freshness",
        "Agent", "RAO", "Authorized source acquisition only", sort_order=20,
    ),
    CtiComponentDefinition(
        "CTI-S01", "normalization_provenance_service", "Normalization & Provenance",
        "Service", "Neuro-Symbolic / Statistical-Symbolic", "No mission agenda / no target actuation", sort_order=30,
    ),
    CtiComponentDefinition(
        "CTI-S02", "asset_profiling_cpe_resolution_service", "Asset Profiling & CPE Resolution",
        "Service", "Layered Neuro-Symbolic", "Enrichment requirement only", sort_order=40,
    ),
    CtiComponentDefinition(
        "CTI-S03", "vulnerability_correlation_service", "Vulnerability Correlation",
        "Service", "Graph + Layered Neuro-Symbolic", "Applicability only", sort_order=50,
    ),
    CtiComponentDefinition(
        "CTI-S04", "attack_mapping_service", "ATT&CK Mapping",
        "Service", "Neuro-Symbolic / Ontology", "Mapping only", sort_order=60,
    ),
    CtiComponentDefinition(
        "CTI-A03", "attack_path_reasoning_agent", "Attack-Path Reasoning",
        "Agent", "Layered Neuro-Symbolic + Graph Planning", "Proposed intelligence paths only",
        optional_component=True, sort_order=70,
    ),
    CtiComponentDefinition(
        "CTI-S05", "threat_context_service", "Threat Context",
        "Service", "Layered Neuro-Symbolic", "Context synthesis only", sort_order=80,
    ),
    CtiComponentDefinition(
        "CTI-A04", "risk_prioritization_agent", "Risk Prioritization",
        "Agent", "Belief-Desire-Intention (BDI)", "Priority recommendation only", sort_order=90,
    ),
    CtiComponentDefinition(
        "CTI-S06", "pip_assembly_validation_service", "PIP Assembly & Validation",
        "Service", "Deterministic Validation", "Packaging/validation only", sort_order=100,
    ),
    CtiComponentDefinition(
        "CTI-D01", "pentest_intelligence_package", "Pentest Intelligence Package",
        "Data Artifact", "Canonical immutable data", "No authority", sort_order=110,
    ),
    # Operational infrastructure, deliberately not counted as a CTI domain module.
    CtiComponentDefinition(
        "CTI-INF01", "pentest_enrichment_api_service", "Pentest Enrichment API Adapter",
        "Infrastructure Service", "Deterministic HTTP adapter", "Transport only; no CTI reasoning",
        sort_order=900,
    ),
    CtiComponentDefinition(
        "CTI-INF02", "cti_event_bus", "CTI Event Bus",
        "Infrastructure Service", "Typed event queue + durable event log", "Communication only; no domain reasoning",
        sort_order=910,
    ),
    CtiComponentDefinition(
        "CTI-INF03", "cti_event_dispatcher", "CTI Event Dispatcher",
        "Infrastructure Service", "Subscription routing / event delivery", "Dispatch only; no mission agenda",
        sort_order=920,
    ),
    CtiComponentDefinition(
        "CTI-INF04", "cti_source_sync_connector", "CTI Source Sync Connector",
        "Infrastructure Service", "Deterministic source adapter", "Authorized read-only CTI acquisition execution only",
        sort_order=930,
    ),
    CtiComponentDefinition(
        "CTI-INF05", "governance_client", "Governance Client",
        "Infrastructure Service", "Authoritative HTTP policy adapter",
        "Transport/contract validation only; aptsGSS remains policy authority",
        sort_order=940,
    ),
]


COMPONENT_BY_KEY = {c.service_key: c for c in CTI_COMPONENTS}
COMPONENT_BY_ID = {c.component_id: c for c in CTI_COMPONENTS}


DEPENDENCY_DAG = {
    "cti_acquisition_freshness_agent": [],
    "normalization_provenance_service": ["cti_acquisition_freshness_agent"],
    "asset_profiling_cpe_resolution_service": ["normalization_provenance_service"],
    "vulnerability_correlation_service": ["asset_profiling_cpe_resolution_service", "normalization_provenance_service"],
    "attack_mapping_service": ["vulnerability_correlation_service"],
    "attack_path_reasoning_agent": ["attack_mapping_service", "vulnerability_correlation_service", "asset_profiling_cpe_resolution_service"],
    "threat_context_service": ["attack_mapping_service", "vulnerability_correlation_service", "asset_profiling_cpe_resolution_service"],
    "risk_prioritization_agent": [
        "asset_profiling_cpe_resolution_service",
        "vulnerability_correlation_service",
        "attack_mapping_service",
        "attack_path_reasoning_agent",
        "threat_context_service",
    ],
    "pip_assembly_validation_service": [
        "asset_profiling_cpe_resolution_service",
        "vulnerability_correlation_service",
        "attack_mapping_service",
        "attack_path_reasoning_agent",
        "threat_context_service",
        "risk_prioritization_agent",
    ],
}
