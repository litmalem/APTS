from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .audit_store import AuditStore
from .common import clamp, evidence_ref, new_id, utcnow_iso
from .db_adapter import DbAdapter, to_json
from .service_registry import ServiceRegistry


class AttackMappingService:
    SERVICE_KEY = "attack_mapping_service"
    COMPONENT_ID = "CTI-S04"
    MODEL_VERSION = "attack-mapping-baseline-1.0"
    RULE_VERSION = "attack-ontology-rules-1.1"

    def __init__(self, db: Optional[DbAdapter] = None, registry: Optional[ServiceRegistry] = None, audit: Optional[AuditStore] = None):
        self.db = db or DbAdapter()
        self.registry = registry or ServiceRegistry(self.db)
        self.audit = audit or AuditStore(self.db)

    def map_vulnerability(self, candidate: Dict[str, Any], endpoint_context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        if not self.registry.is_enabled(self.SERVICE_KEY):
            return []
        self.registry.update_status(self.SERVICE_KEY, "running")
        try:
            mappings: List[Dict[str, Any]] = []
            mappings.extend(self._map_by_cve(candidate))
            # The caller may only know the CVE. Resolve every catalog CWE here
            # so all clients use the same CVE -> CWE -> CAPEC/ATT&CK paths.
            for weakness in self._weakness_candidates(candidate):
                mappings.extend(self._map_by_capec(weakness))
                mappings.extend(self._map_by_cwe(weakness))
            mappings.extend(self._map_by_vuln_type(candidate))
            mappings.extend(self._map_by_keywords(candidate))
            mappings.extend(self._map_by_endpoint_heuristic(candidate, endpoint_context or {}))
            out = self._rank_and_dedupe([self._verify_mapping(candidate, self._complete_attack_metadata(m)) for m in mappings])
            self.registry.update_status(self.SERVICE_KEY, "idle")
            return out
        except Exception as e:
            self.registry.update_status(self.SERVICE_KEY, "error", str(e))
            raise


    def map_correlations(self, mission_id: str, correlations: List[Dict[str, Any]], endpoints: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Map vulnerability correlations to ATT&CK without performing path planning."""
        endpoint_by_id = {e.get("id"): e for e in (endpoints or [])}
        results: List[Dict[str, Any]] = []
        for correlation in correlations or []:
            if correlation.get("status") == "NOT_APPLICABLE":
                continue
            endpoint_context = endpoint_by_id.get(correlation.get("endpoint_id")) or {}
            for mapping in self.map_vulnerability(correlation, endpoint_context):
                item = dict(mapping)
                item["mapping_id"] = new_id("attmap")
                item["mission_id"] = mission_id
                item["correlation_id"] = correlation.get("correlation_id")
                item["asset_id"] = correlation.get("asset_id")
                item["cve_id"] = correlation.get("cve_id")
                item["evidence_ref"] = (correlation.get("matched_evidence") or [None])[0]
                item["evidence_refs"] = list(correlation.get("matched_evidence") or [])
                item["probability_score"] = clamp(item.get("mapping_confidence"), default=0.5)
                item["confidence"] = min(
                    clamp(item.get("mapping_confidence"), default=0.5),
                    clamp(correlation.get("confidence"), default=0.5),
                )
                item["provenance"] = {
                    "mapping_source": item.get("mapping_source"),
                    "mapping_level": item.get("mapping_level"),
                    "model_version": self.MODEL_VERSION,
                    "rule_version": self.RULE_VERSION,
                    "correlation_id": correlation.get("correlation_id"),
                    "source_dataset": item.get("source_dataset"),
                    "source_version": item.get("source_version"),
                    "source_url": item.get("source_url"),
                    "source_sha256": item.get("source_sha256"),
                    "relationship_type": item.get("relationship_type"),
                    "supporting_mappings": item.get("supporting_mappings") or [],
                }
                self._persist_mapping(item)
                results.append(item)
        self.audit.append(
            mission_id=mission_id, component_id=self.COMPONENT_ID,
            event_type="attack_mapping.completed", reason_code="ATTACK_MAPPING_COMPLETE",
            input_snapshot={"correlation_count": len(correlations or [])},
            candidate_alternatives=[{"correlation_id": m.get("correlation_id"), "technique_id": m.get("attack_id"), "score": m.get("probability_score")} for m in results],
            selected_output={"mapping_count": len(results), "verified": sum(1 for m in results if m.get("verification_state") == "VERIFIED")},
            evidence_refs=[e for m in results for e in m.get("evidence_refs", [])],
            versions={"model": self.MODEL_VERSION, "rules": self.RULE_VERSION},
        )
        return {"status": "completed", "mappings": results, "model_version": self.MODEL_VERSION, "rule_version": self.RULE_VERSION}

    def _verify_mapping(self, candidate: Dict[str, Any], mapping: Dict[str, Any]) -> Dict[str, Any]:
        """Symbolic/ontology verification baseline for a candidate mapping."""
        score = clamp(mapping.get("mapping_confidence") or mapping.get("confidence"), default=0.5)
        rules = ["R_TYPED_ATTACK_TECHNIQUE"]
        contradictions: List[str] = []
        state = "PROVISIONAL"
        if not mapping.get("attack_id") and not mapping.get("attack_pattern_stix_id"):
            state = "REJECTED"
            contradictions.append("MISSING_ATTACK_IDENTITY")
            rules.append("R_ATTACK_ID_REQUIRED")
        elif candidate.get('status') == 'NEEDS_VERIFICATION':
            rules.append('R_UNVERIFIED_VULNERABILITY_CONTEXT_ONLY')
        elif mapping.get('source_dataset'):
            # Imported associations describe catalog context, not target verification.
            rules.append('R_IMPORTED_CONTEXT_REQUIRES_TARGET_EVIDENCE')
        elif score >= 0.60 and mapping.get("mapping_source") in {"manual", "capec", "seed"}:
            state = "VERIFIED"
            rules.append("R_CURATED_MAPPING_SOURCE")
        elif score >= 0.75:
            state = "VERIFIED"
            rules.append("R_HIGH_CONFIDENCE_MAPPING")
        elif score < 0.30:
            state = "NEEDS_EVIDENCE"
            rules.append("R_LOW_CONFIDENCE_NEEDS_EVIDENCE")
        else:
            rules.append("R_PROVISIONAL_MAPPING")
        mapping["probability_score"] = score
        mapping["verification_state"] = state
        mapping["symbolic_rules"] = rules
        mapping["contradictions"] = contradictions
        mapping["confidence"] = score
        mapping["model_version"] = self.MODEL_VERSION
        mapping["rule_version"] = self.RULE_VERSION
        return mapping

    def _persist_mapping(self, item: Dict[str, Any]) -> None:
        if not self.db.table_exists("cti_attack_mappings"):
            return
        self.db.execute(
            """
            INSERT INTO cti_attack_mappings
                (mapping_id, mission_id, correlation_id, asset_id, cve_id, evidence_ref,
                 attack_pattern_stix_id, technique_id, technique_name, tactic_name,
                 probability_score, verification_state, symbolic_rules_json, confidence,
                 provenance_json, contradictions_json, evidence_refs_json, model_version,
                 rule_version, created_at)
            VALUES
                (%(mapping_id)s, %(mission_id)s, %(correlation_id)s, %(asset_id)s, %(cve_id)s,
                 %(evidence_ref)s, %(attack_pattern_stix_id)s, %(technique_id)s, %(technique_name)s,
                 %(tactic_name)s, %(probability_score)s, %(verification_state)s, %(symbolic_rules_json)s,
                 %(confidence)s, %(provenance_json)s, %(contradictions_json)s, %(evidence_refs_json)s,
                 %(model_version)s, %(rule_version)s, CURRENT_TIMESTAMP)
            """,
            {
                **item,
                "technique_id": item.get("attack_id"),
                "symbolic_rules_json": to_json(item.get("symbolic_rules") or []),
                "provenance_json": to_json(item.get("provenance") or {}),
                "contradictions_json": to_json(item.get("contradictions") or []),
                "evidence_refs_json": to_json(item.get("evidence_refs") or []),
            },
        )

    def _weakness_candidates(self, candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
        weaknesses = {}
        if candidate.get("cwe_id"):
            weaknesses[candidate["cwe_id"]] = candidate
        if candidate.get("cve_id") and all(self.db.table_exists(t) for t in (
            "vulnerabilities", "vulnerability_cwes", "cwe_catalog"
        )):
            rows = self.db.fetch_all(
                "SELECT DISTINCT cw.cwe_id,cw.cwe_name "
                "FROM vulnerabilities v JOIN vulnerability_cwes vc ON vc.vulnerability_id=v.id "
                "JOIN cwe_catalog cw ON cw.id=vc.cwe_catalog_id "
                "WHERE v.cve_id=%(cve_id)s ORDER BY cw.cwe_id",
                {"cve_id": candidate["cve_id"]},
            )
            for row in rows:
                if row.get("cwe_id"):
                    weaknesses.setdefault(row["cwe_id"], {**candidate, **row})
        return list(weaknesses.values())

    def _map_by_cve(self, candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
        cve_id = candidate.get("cve_id")
        if not cve_id:
            return []
        return self._query_vuln_attack_mappings("cve_id = %(cve_id)s AND mapping_level = 'cve_to_attack'", {"cve_id": cve_id})

    def _map_by_cwe(self, candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
        cwe_id = candidate.get("cwe_id")
        if not cwe_id:
            return []
        return self._query_vuln_attack_mappings("cwe_id = %(cwe_id)s AND mapping_level = 'cwe_to_attack'", {"cwe_id": cwe_id})

    def _map_by_capec(self, candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
        cwe_id = candidate.get("cwe_id")
        if not cwe_id or not self.db.table_exists("capec_cwe_mappings") or not self.db.table_exists("capec_attack_mappings"):
            return []
        rows = self.db.fetch_all(
            """
            SELECT
                ccm.cwe_id,
                ccm.capec_id,
                cam.attack_pattern_stix_id,
                cam.attack_id,
                cam.attack_name,
                cam.tactic_name,
                'capec_to_attack' AS mapping_level,
                'capec' AS mapping_source,
                cam.confidence,
                cam.rationale,cam.source_dataset,cam.source_version,cam.source_url,
                cam.source_sha256,cam.relationship_type,cam.references_json,cam.publisher_status
            FROM capec_cwe_mappings ccm
            JOIN capec_attack_mappings cam ON cam.capec_id = ccm.capec_id
            WHERE ccm.cwe_id = %(cwe_id)s AND ccm.is_active=1 AND cam.is_active=1
            ORDER BY cam.confidence DESC
            """,
            {"cwe_id": cwe_id},
        )
        return rows

    def _map_by_vuln_type(self, candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
        vt = candidate.get("vulnerability_type") or candidate.get("cwe_name")
        if not vt:
            return []
        return self._query_vuln_attack_mappings(
            "LOWER(vuln_type) = LOWER(%(vuln_type)s) AND mapping_level = 'vuln_type_to_attack'",
            {"vuln_type": vt},
        )

    def _map_by_keywords(self, candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
        text = " ".join(str(candidate.get(k) or "") for k in ["description", "evidence_text", "vulnerability_type", "cwe_name"]).lower()
        if not text:
            return []
        # First use DB-configurable keyword rules.
        rows = self._query_vuln_attack_mappings("mapping_level = 'keyword_to_attack' AND keyword_pattern IS NOT NULL", {})
        matched = []
        for r in rows:
            pattern = r.get("keyword_pattern")
            try:
                if pattern and re.search(pattern, text, flags=re.IGNORECASE):
                    matched.append(r)
            except re.error:
                if pattern and pattern.lower() in text:
                    matched.append(r)
        # Built-in fallback rules.
        fallback = []
        if "remote code execution" in text or re.search(r"\brce\b", text):
            fallback.append(self._rule("T1190", "Exploit Public-Facing Application", "Initial Access", "keyword_to_attack", "rule", 0.55, "Description indicates remote code execution in an exposed application."))
        if "web shell" in text:
            fallback.append(self._rule("T1505.003", "Server Software Component: Web Shell", "Persistence", "keyword_to_attack", "rule", 0.75, "Description mentions web shell."))
        if "credential" in text or "password" in text:
            fallback.append(self._rule("T1552", "Unsecured Credentials", "Credential Access", "keyword_to_attack", "rule", 0.55, "Description mentions credential exposure."))
        return matched + fallback

    def _map_by_endpoint_heuristic(self, candidate: Dict[str, Any], endpoint_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        endpoint = str(candidate.get("affected_endpoint") or endpoint_context.get("url") or endpoint_context.get("normalized_url") or "").lower()
        cwe_id = candidate.get("cwe_id")
        out = []
        if cwe_id == "CWE-434" or "upload" in endpoint:
            out.append(self._rule("T1505.003", "Server Software Component: Web Shell", "Persistence", "endpoint_heuristic", "rule", 0.60, "Upload context can lead to web shell placement if server-side execution is possible."))
        if "/admin" in endpoint or "/wp-admin" in endpoint or "/administrator" in endpoint:
            out.append(self._rule("T1190", "Exploit Public-Facing Application", "Initial Access", "endpoint_heuristic", "rule", 0.30, "Administrative endpoint exposure is a low-confidence public-facing application exploitation context."))
        return out

    def _query_vuln_attack_mappings(self, where_sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self.db.table_exists("vuln_attack_mappings"):
            return []
        sql = f"""
            SELECT id, cve_id, cwe_id, capec_id, vuln_type, keyword_pattern,
                   attack_pattern_stix_id, attack_id, attack_name, tactic_name,
                   mapping_level, mapping_source, confidence, rationale,
                   source_dataset,source_version,source_url,source_sha256,relationship_type,references_json,publisher_status
            FROM vuln_attack_mappings
            WHERE is_active = 1 AND {where_sql}
            ORDER BY confidence DESC
        """
        return self.db.fetch_all(sql, params)

    @staticmethod
    def _rule(attack_id: str, attack_name: str, tactic_name: str, mapping_level: str, mapping_source: str, confidence: float, rationale: str) -> Dict[str, Any]:
        return {
            "attack_id": attack_id,
            "attack_name": attack_name,
            "technique_name": attack_name,
            "tactic_name": tactic_name,
            "mapping_level": mapping_level,
            "mapping_source": mapping_source,
            "confidence": confidence,
            "mapping_confidence": confidence,
            "rationale": rationale,
        }

    def _complete_attack_metadata(self, mapping: Dict[str, Any]) -> Dict[str, Any]:
        attack_id = mapping.get("attack_id")
        stix = mapping.get("attack_pattern_stix_id")
        ap = None
        if self.db.table_exists("attack_patterns"):
            if stix:
                ap = self.db.fetch_one("SELECT * FROM attack_patterns WHERE stix_id = %(stix)s LIMIT 1", {"stix": stix})
            if not ap and attack_id:
                if mapping.get('source_dataset'):
                    ap = self.db.fetch_one("SELECT * FROM attack_patterns WHERE attack_id = %(attack_id)s LIMIT 1", {'attack_id': attack_id})
                else:
                    ap = self._find_attack_pattern_by_attack_id(attack_id)
        if ap:
            mapping["attack_pattern_stix_id"] = mapping.get("attack_pattern_stix_id") or ap.get("stix_id")
            mapping["attack_id"] = mapping.get("attack_id") or ap.get("attack_id") or ap.get("external_id")
            mapping["attack_name"] = mapping.get("attack_name") or ap.get("name")
            mapping["technique_name"] = mapping.get("technique_name") or mapping.get("attack_name") or ap.get("name")
            mapping["description"] = ap.get("description_text") or ap.get("description")
            mapping["platforms"] = ap.get("platforms") if "platforms" in ap else None
        else:
            mapping["technique_name"] = mapping.get("technique_name") or mapping.get("attack_name")
        mapping["mapping_confidence"] = float(mapping.get("mapping_confidence") or mapping.get("confidence") or 0.5)
        return mapping

    def _find_attack_pattern_by_attack_id(self, attack_id: str) -> Optional[Dict[str, Any]]:
        cols = self.db.columns("attack_patterns")
        if "attack_id" in cols:
            row = self.db.fetch_one("SELECT * FROM attack_patterns WHERE attack_id = %(attack_id)s LIMIT 1", {"attack_id": attack_id})
            if row:
                return row
        if "external_id" in cols:
            row = self.db.fetch_one("SELECT * FROM attack_patterns WHERE external_id = %(attack_id)s LIMIT 1", {"attack_id": attack_id})
            if row:
                return row
        # Fallback via external references.
        if self.db.table_exists("attack_external_references"):
            ref_cols = self.db.columns("attack_external_references")
            src_col = "source_ref" if "source_ref" in ref_cols else ("stix_id" if "stix_id" in ref_cols else None)
            ext_col = "external_id" if "external_id" in ref_cols else None
            if src_col and ext_col:
                ref = self.db.fetch_one(
                    f"SELECT * FROM attack_external_references WHERE {ext_col}=%(attack_id)s LIMIT 1",
                    {"attack_id": attack_id},
                )
                if ref:
                    return self.db.fetch_one("SELECT * FROM attack_patterns WHERE stix_id=%(stix)s LIMIT 1", {"stix": ref[src_col]})
        return None

    def _rank_and_dedupe(self, mappings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        best: Dict[str, Dict[str, Any]] = {}
        support: Dict[str, List[Dict[str, Any]]] = {}
        for m in mappings:
            key = str(m.get("attack_pattern_stix_id") or m.get("attack_id") or m.get("attack_name"))
            if not key or key == "None":
                continue
            context = {k: m.get(k) for k in ('mapping_level','mapping_source','confidence',
                       'source_dataset','source_version','source_url','source_sha256','relationship_type',
                       'capec_id','cwe_id','rationale','references_json','publisher_status')}
            if context not in support.setdefault(key, []):
                support[key].append(context)
            if key not in best or float(m.get("mapping_confidence") or 0) > float(best[key].get("mapping_confidence") or 0):
                best[key] = m
        for key, mapping in best.items():
            mapping["supporting_mappings"] = support[key]
        return sorted(best.values(), key=lambda x: float(x.get("mapping_confidence") or 0), reverse=True)
