from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .audit_store import AuditStore
from .common import clamp, evidence_ref, new_id, utcnow_iso
from .db_adapter import DbAdapter, to_json
from .service_registry import ServiceRegistry


class AttackPathReasoningAgent:
    """CTI-A03 optional intelligence-only attack-path reasoning agent.

    This baseline deliberately reasons only over evidence already produced by
    Vulnerability Correlation and ATT&CK Mapping.  It does not create exploit
    commands, does not authorize execution, and does not convert an applicable
    vulnerability into an executable action.
    """

    SERVICE_KEY = "attack_path_reasoning_agent"
    COMPONENT_ID = "CTI-A03"
    MODEL_VERSION = "attack-path-graph-baseline-1.0"
    RULE_VERSION = "attack-path-rules-1.0"

    def __init__(
        self,
        db: Optional[DbAdapter] = None,
        registry: Optional[ServiceRegistry] = None,
        audit: Optional[AuditStore] = None,
    ):
        self.db = db or DbAdapter()
        self.registry = registry or ServiceRegistry(self.db)
        self.audit = audit or AuditStore(self.db)

    def reason(
        self,
        mission_id: str,
        asset_profiles: List[Dict[str, Any]],
        correlations: List[Dict[str, Any]],
        attack_mappings: List[Dict[str, Any]],
        policy_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.registry.is_enabled(self.SERVICE_KEY):
            return {
                "status": "skipped",
                "optional_component": True,
                "graph_snapshot": None,
                "paths": [],
            }

        self.registry.update_status(self.SERVICE_KEY, "running")
        try:
            graph = self._build_graph(mission_id, asset_profiles, correlations, attack_mappings, policy_context or {})
            paths = self._rank_paths(mission_id, graph, correlations, attack_mappings, policy_context or {})
            self._persist_graph(graph)
            for path in paths:
                self._persist_path(path)

            self.audit.append(
                mission_id=mission_id,
                component_id=self.COMPONENT_ID,
                event_type="attack_path.completed",
                reason_code="INTELLIGENCE_PATHS_PROPOSED",
                input_snapshot={
                    "asset_count": len(asset_profiles or []),
                    "correlation_count": len(correlations or []),
                    "mapping_count": len(attack_mappings or []),
                    "policy_context": policy_context or {},
                },
                candidate_alternatives=[
                    {
                        "path_id": p["path_id"],
                        "feasibility_state": p["feasibility_state"],
                        "path_confidence": p["path_confidence"],
                    }
                    for p in paths
                ],
                selected_output={
                    "graph_snapshot_id": graph["graph_snapshot_id"],
                    "ranked_path_ids": [p["path_id"] for p in paths],
                },
                evidence_refs=[e for p in paths for e in p.get("evidence_refs", [])],
                versions={"model": self.MODEL_VERSION, "rules": self.RULE_VERSION},
            )
            self.registry.update_status(self.SERVICE_KEY, "idle")
            return {
                "status": "completed",
                "optional_component": True,
                "graph_snapshot": graph,
                "paths": paths,
                "model_version": self.MODEL_VERSION,
                "rule_version": self.RULE_VERSION,
            }
        except Exception as exc:
            self.registry.update_status(self.SERVICE_KEY, "error", str(exc))
            raise

    def _build_graph(
        self,
        mission_id: str,
        asset_profiles: List[Dict[str, Any]],
        correlations: List[Dict[str, Any]],
        mappings: List[Dict[str, Any]],
        policy_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        nodes: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []

        for asset in asset_profiles or []:
            asset_id = str(asset.get("asset_id") or "")
            if not asset_id:
                continue
            node_id = f"asset:{asset_id}"
            nodes[node_id] = {
                "node_id": node_id,
                "node_type": "ASSET",
                "ref_id": asset_id,
                "label": asset.get("observed_attributes", {}).get("hostname")
                or asset.get("observed_attributes", {}).get("target_url")
                or asset_id,
                "confidence": clamp(asset.get("confidence"), default=0.7),
                "evidence_refs": list(asset.get("evidence_refs") or []),
            }

        for corr in correlations or []:
            asset_id = str(corr.get("asset_id") or "")
            cve_id = str(corr.get("cve_id") or corr.get("vulnerability_id") or "")
            if not asset_id or not cve_id:
                continue
            asset_node = f"asset:{asset_id}"
            vuln_node = f"vuln:{asset_id}:{cve_id}"
            nodes.setdefault(
                vuln_node,
                {
                    "node_id": vuln_node,
                    "node_type": "VULNERABILITY",
                    "ref_id": corr.get("correlation_id") or cve_id,
                    "label": cve_id,
                    "confidence": clamp(corr.get("confidence"), default=0.5),
                    "evidence_refs": list(corr.get("matched_evidence") or corr.get("evidence_refs") or []),
                },
            )
            edge_state = self._correlation_edge_state(corr)
            edges.append(
                {
                    "edge_id": new_id("edge"),
                    "source": asset_node,
                    "target": vuln_node,
                    "edge_type": "AFFECTED_BY",
                    "verification_state": edge_state,
                    "confidence": clamp(corr.get("confidence"), default=0.5),
                    "preconditions": list(corr.get("missing_prerequisites") or []),
                    "postconditions": [],
                    "evidence_refs": list(corr.get("matched_evidence") or corr.get("evidence_refs") or []),
                    "policy_state": "INTELLIGENCE_ONLY",
                    "execution_authorized": False,
                }
            )

        corr_by_id = {str(c.get("correlation_id")): c for c in correlations or [] if c.get("correlation_id")}
        for mapping in mappings or []:
            corr = corr_by_id.get(str(mapping.get("correlation_id") or ""))
            asset_id = str(mapping.get("asset_id") or (corr or {}).get("asset_id") or "")
            cve_id = str(mapping.get("cve_id") or (corr or {}).get("cve_id") or "")
            technique_id = str(mapping.get("technique_id") or mapping.get("attack_id") or "")
            if not asset_id or not cve_id or not technique_id:
                continue
            vuln_node = f"vuln:{asset_id}:{cve_id}"
            technique_node = f"technique:{technique_id}"
            nodes.setdefault(
                technique_node,
                {
                    "node_id": technique_node,
                    "node_type": "ATTACK_TECHNIQUE",
                    "ref_id": mapping.get("mapping_id") or technique_id,
                    "label": mapping.get("technique_name") or mapping.get("attack_name") or technique_id,
                    "confidence": clamp(mapping.get("confidence") or mapping.get("probability_score"), default=0.5),
                    "evidence_refs": list(mapping.get("evidence_refs") or []),
                },
            )
            verification = str(mapping.get("verification_state") or "PROVISIONAL").upper()
            edges.append(
                {
                    "edge_id": new_id("edge"),
                    "source": vuln_node,
                    "target": technique_node,
                    "edge_type": "MAPPED_TO_TECHNIQUE",
                    "verification_state": verification,
                    "confidence": clamp(mapping.get("confidence") or mapping.get("probability_score"), default=0.5),
                    "preconditions": [],
                    "postconditions": [],
                    "evidence_refs": list(mapping.get("evidence_refs") or []),
                    "policy_state": "INTELLIGENCE_ONLY",
                    "execution_authorized": False,
                }
            )

        graph_snapshot_id = new_id("attackgraph")
        return {
            "graph_snapshot_id": graph_snapshot_id,
            "mission_id": mission_id,
            "graph_version": 1,
            "generated_at": utcnow_iso(),
            "nodes": list(nodes.values()),
            "edges": edges,
            "policy_context": policy_context,
            "model_version": self.MODEL_VERSION,
            "rule_version": self.RULE_VERSION,
            "semantics": {
                "feasible_path_is_execution_command": False,
                "execution_authorized": False,
                "reasoning_authority": "INTELLIGENCE_PROPOSAL_ONLY",
            },
        }

    @staticmethod
    def _correlation_edge_state(corr: Dict[str, Any]) -> str:
        status = str(corr.get("status") or "").upper()
        symbolic = str(corr.get("symbolic_result") or "UNKNOWN").upper()
        if status in {"NOT_APPLICABLE", "REJECTED"} or symbolic == "FALSE":
            return "BLOCKED"
        if status in {"CORRELATED_APPLICABLE", "EMPIRICALLY_VALIDATED", "CONFIGURATION_APPLICABLE", "PREREQUISITE_SATISFIED"} and symbolic == "TRUE":
            return "VERIFIED"
        return "NEEDS_EVIDENCE"

    def _rank_paths(
        self,
        mission_id: str,
        graph: Dict[str, Any],
        correlations: List[Dict[str, Any]],
        mappings: List[Dict[str, Any]],
        policy_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        corr_by_id = {str(c.get("correlation_id")): c for c in correlations or [] if c.get("correlation_id")}
        rows: List[Dict[str, Any]] = []

        for mapping in mappings or []:
            corr = corr_by_id.get(str(mapping.get("correlation_id") or ""))
            if not corr:
                continue
            if str(mapping.get("verification_state") or "").upper() == "REJECTED":
                continue
            corr_state = self._correlation_edge_state(corr)
            if corr_state == "BLOCKED":
                continue

            corr_conf = clamp(corr.get("confidence"), default=0.5)
            map_conf = clamp(mapping.get("confidence") or mapping.get("probability_score"), default=0.5)
            path_conf = math.sqrt(max(0.0, corr_conf * map_conf))
            missing = list(corr.get("missing_prerequisites") or [])
            verification = str(mapping.get("verification_state") or "PROVISIONAL").upper()

            if corr_state == "VERIFIED" and verification == "VERIFIED" and not missing:
                feasibility = "FEASIBLE_INTELLIGENCE_PATH"
                reason = "EVIDENCE_BOUND_PATH"
            else:
                feasibility = "NEEDS_EVIDENCE"
                reason = "MISSING_OR_PROVISIONAL_EVIDENCE"

            asset_id = corr.get("asset_id")
            cve_id = corr.get("cve_id")
            technique_id = mapping.get("technique_id") or mapping.get("attack_id")
            evidence = list(dict.fromkeys(
                list(corr.get("matched_evidence") or corr.get("evidence_refs") or [])
                + list(mapping.get("evidence_refs") or [])
            ))
            path_id = new_id("attackpath")
            rows.append(
                {
                    "path_id": path_id,
                    "mission_id": mission_id,
                    "graph_snapshot_id": graph["graph_snapshot_id"],
                    "asset_id": asset_id,
                    "correlation_id": corr.get("correlation_id"),
                    "cve_id": cve_id,
                    "mapping_id": mapping.get("mapping_id"),
                    "technique_id": technique_id,
                    "technique_name": mapping.get("technique_name") or mapping.get("attack_name"),
                    "path_nodes": [
                        f"asset:{asset_id}",
                        f"vuln:{asset_id}:{cve_id}",
                        f"technique:{technique_id}",
                    ],
                    "path_confidence": round(path_conf, 6),
                    "feasibility_state": feasibility,
                    "reason_code": reason,
                    "preconditions": missing,
                    "postconditions": [],
                    "evidence_refs": evidence,
                    "policy_state": {
                        "scope_allowed": policy_context.get("scope_allowed", True),
                        "authorization_required_for_execution": True,
                    },
                    "rule_trace": [
                        "R_CORRELATION_EDGE_NOT_BLOCKED",
                        "R_MAPPING_NOT_REJECTED",
                        "R_FEASIBLE_ONLY_IF_VERIFIED" if feasibility == "FEASIBLE_INTELLIGENCE_PATH" else "R_REQUIRE_MORE_EVIDENCE",
                    ],
                    "model_version": self.MODEL_VERSION,
                    "rule_version": self.RULE_VERSION,
                    "execution_authorized": False,
                    "authority_state": "PROPOSED_INTELLIGENCE_PATH_ONLY",
                    "created_at": utcnow_iso(),
                }
            )

        rows.sort(key=lambda p: (p["feasibility_state"] != "FEASIBLE_INTELLIGENCE_PATH", -float(p["path_confidence"]), str(p["path_id"])))
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        return rows

    def _persist_graph(self, graph: Dict[str, Any]) -> None:
        if not self.db.table_exists("cti_attack_graph_snapshots"):
            return
        self.db.execute(
            """
            INSERT INTO cti_attack_graph_snapshots
                (graph_snapshot_id, mission_id, graph_version, nodes_json, edges_json,
                 policy_context_json, model_version, rule_version, created_at)
            VALUES
                (%(graph_snapshot_id)s, %(mission_id)s, %(graph_version)s, %(nodes_json)s,
                 %(edges_json)s, %(policy_context_json)s, %(model_version)s, %(rule_version)s,
                 CURRENT_TIMESTAMP)
            """,
            {
                "graph_snapshot_id": graph.get("graph_snapshot_id"),
                "mission_id": graph.get("mission_id"),
                "graph_version": graph.get("graph_version"),
                "nodes_json": to_json(graph.get("nodes") or []),
                "edges_json": to_json(graph.get("edges") or []),
                "policy_context_json": to_json(graph.get("policy_context") or {}),
                "model_version": graph.get("model_version"),
                "rule_version": graph.get("rule_version"),
            },
        )

    def _persist_path(self, path: Dict[str, Any]) -> None:
        if not self.db.table_exists("cti_attack_paths"):
            return
        self.db.execute(
            """
            INSERT INTO cti_attack_paths
                (path_id, mission_id, graph_snapshot_id, rank_no, asset_id, correlation_id,
                 cve_id, mapping_id, technique_id, technique_name, path_nodes_json,
                 path_confidence, feasibility_state, reason_code, preconditions_json,
                 postconditions_json, evidence_refs_json, policy_state_json, rule_trace_json,
                 model_version, rule_version, execution_authorized, authority_state, created_at)
            VALUES
                (%(path_id)s, %(mission_id)s, %(graph_snapshot_id)s, %(rank)s, %(asset_id)s,
                 %(correlation_id)s, %(cve_id)s, %(mapping_id)s, %(technique_id)s,
                 %(technique_name)s, %(path_nodes_json)s, %(path_confidence)s,
                 %(feasibility_state)s, %(reason_code)s, %(preconditions_json)s,
                 %(postconditions_json)s, %(evidence_refs_json)s, %(policy_state_json)s,
                 %(rule_trace_json)s, %(model_version)s, %(rule_version)s,
                 %(execution_authorized)s, %(authority_state)s, CURRENT_TIMESTAMP)
            """,
            {
                "path_id": path.get("path_id"),
                "mission_id": path.get("mission_id"),
                "graph_snapshot_id": path.get("graph_snapshot_id"),
                "rank": path.get("rank"),
                "asset_id": path.get("asset_id"),
                "correlation_id": path.get("correlation_id"),
                "cve_id": path.get("cve_id"),
                "mapping_id": path.get("mapping_id"),
                "technique_id": path.get("technique_id"),
                "technique_name": path.get("technique_name"),
                "path_nodes_json": to_json(path.get("path_nodes") or []),
                "path_confidence": path.get("path_confidence"),
                "feasibility_state": path.get("feasibility_state"),
                "reason_code": path.get("reason_code"),
                "preconditions_json": to_json(path.get("preconditions") or []),
                "postconditions_json": to_json(path.get("postconditions") or []),
                "evidence_refs_json": to_json(path.get("evidence_refs") or []),
                "policy_state_json": to_json(path.get("policy_state") or {}),
                "rule_trace_json": to_json(path.get("rule_trace") or []),
                "model_version": path.get("model_version"),
                "rule_version": path.get("rule_version"),
                "execution_authorized": 1 if path.get("execution_authorized") else 0,
                "authority_state": path.get("authority_state"),
            },
        )
