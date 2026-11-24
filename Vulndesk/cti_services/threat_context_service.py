from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .audit_store import AuditStore
from .common import clamp, evidence_ref, new_id, safe_json_loads, utcnow_iso, to_db_datetime
from .db_adapter import DbAdapter, to_json
from .service_registry import ServiceRegistry


class ThreatContextService:
    """CTI-S05 layered neuro-symbolic threat-context service baseline.

    The implementation keeps relational ATT&CK context separate from target
    evidence.  A group/malware that *uses* a technique is represented as an
    inference candidate, never as proof that the actor or malware is present on
    the target.
    """

    SERVICE_KEY = "threat_context_service"
    COMPONENT_ID = "CTI-S05"
    MODEL_VERSION = "threat-context-baseline-1.0"
    RULE_VERSION = "threat-context-rules-1.0"

    def __init__(
        self,
        db: Optional[DbAdapter] = None,
        registry: Optional[ServiceRegistry] = None,
        audit: Optional[AuditStore] = None,
    ):
        self.db = db or DbAdapter()
        self.registry = registry or ServiceRegistry(self.db)
        self.audit = audit or AuditStore(self.db)

    def synthesize(
        self,
        mission_id: str,
        asset_profiles: List[Dict[str, Any]],
        correlations: List[Dict[str, Any]],
        attack_mappings: List[Dict[str, Any]],
        attack_paths: Optional[List[Dict[str, Any]]] = None,
        mission_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.registry.is_enabled(self.SERVICE_KEY):
            return {"status": "skipped", "contexts": []}

        self.registry.update_status(self.SERVICE_KEY, "running")
        try:
            mission_context = mission_context or {}
            assets = {str(a.get("asset_id")): a for a in asset_profiles or [] if a.get("asset_id")}
            corr_by_id = {str(c.get("correlation_id")): c for c in correlations or [] if c.get("correlation_id")}
            paths_by_mapping: Dict[str, List[Dict[str, Any]]] = {}
            for path in attack_paths or []:
                if path.get("mapping_id"):
                    paths_by_mapping.setdefault(str(path["mapping_id"]), []).append(path)

            contexts: List[Dict[str, Any]] = []
            for mapping in attack_mappings or []:
                if str(mapping.get("verification_state") or "").upper() == "REJECTED":
                    continue
                corr = corr_by_id.get(str(mapping.get("correlation_id") or "")) or {}
                asset_id = str(mapping.get("asset_id") or corr.get("asset_id") or "")
                attack_stix = mapping.get("attack_pattern_stix_id")
                if not attack_stix and mapping.get("technique_id"):
                    attack_stix = self._resolve_attack_stix(mapping.get("technique_id"))
                relations = self._relationship_context(attack_stix) if attack_stix else []
                context = self._build_context(
                    mission_id=mission_id,
                    asset=assets.get(asset_id) or {},
                    corr=corr,
                    mapping=mapping,
                    relations=relations,
                    paths=paths_by_mapping.get(str(mapping.get("mapping_id") or ""), []),
                    mission_context=mission_context,
                )
                contexts.append(context)
                self._persist(context)

            contexts = self._dedupe(contexts)
            self.audit.append(
                mission_id=mission_id,
                component_id=self.COMPONENT_ID,
                event_type="threat_context.completed",
                reason_code="CONTEXT_SYNTHESIS_COMPLETE",
                input_snapshot={
                    "asset_count": len(asset_profiles or []),
                    "correlation_count": len(correlations or []),
                    "mapping_count": len(attack_mappings or []),
                    "path_count": len(attack_paths or []),
                },
                candidate_alternatives=[
                    {
                        "context_id": c["context_id"],
                        "asset_id": c.get("asset_id"),
                        "technique_id": c.get("technique_id"),
                        "confidence": c.get("confidence"),
                        "verification_status": c.get("verification_status"),
                    }
                    for c in contexts
                ],
                selected_output={"context_count": len(contexts)},
                evidence_refs=[e for c in contexts for e in c.get("evidence_refs", [])],
                versions={"model": self.MODEL_VERSION, "rules": self.RULE_VERSION},
            )
            self.registry.update_status(self.SERVICE_KEY, "idle")
            return {
                "status": "completed",
                "contexts": contexts,
                "model_version": self.MODEL_VERSION,
                "rule_version": self.RULE_VERSION,
            }
        except Exception as exc:
            self.registry.update_status(self.SERVICE_KEY, "error", str(exc))
            raise

    def enrich_attack_context(self, attack_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Backward-compatible low-level relationship lookup."""
        if not self.registry.is_enabled(self.SERVICE_KEY):
            return []
        stix = attack_context.get("attack_pattern_stix_id")
        if not stix and attack_context.get("attack_id"):
            stix = self._resolve_attack_stix(attack_context.get("attack_id"))
        return self._relationship_context(stix) if stix else []

    def _build_context(
        self,
        *,
        mission_id: str,
        asset: Dict[str, Any],
        corr: Dict[str, Any],
        mapping: Dict[str, Any],
        relations: List[Dict[str, Any]],
        paths: List[Dict[str, Any]],
        mission_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        asset_id = mapping.get("asset_id") or corr.get("asset_id")
        severity_score = self._severity_score(corr)
        exploit_activity = self._exploit_activity(corr)
        relation_conf = max([clamp(r.get("confidence"), default=0.0) for r in relations] or [0.0])
        target_relevance = self._target_relevance(asset, mission_context)
        recency = self._recency_score(corr)
        source_credibility = self._source_credibility(corr, mapping)
        path_support = max([clamp(p.get("path_confidence"), default=0.0) for p in paths] or [0.0])

        dimensions = {
            "exploit_activity": exploit_activity,
            "campaign_relevance": relation_conf,
            "actor_attribution": {
                "score": relation_conf,
                "epistemic_state": "INFERENCE_ONLY",
                "target_presence_asserted": False,
            },
            "target_relevance": target_relevance,
            "recency": recency,
            "source_credibility": source_credibility,
            "vulnerability_severity": severity_score,
            "attack_path_support": path_support,
        }
        numeric = [
            exploit_activity,
            relation_conf,
            target_relevance,
            recency,
            source_credibility,
            severity_score,
            path_support,
        ]
        confidence = round(sum(numeric) / max(1, len(numeric)), 6)
        evidence = list(dict.fromkeys(
            list(corr.get("matched_evidence") or corr.get("evidence_refs") or [])
            + list(mapping.get("evidence_refs") or [])
            + [e for r in relations for e in r.get("evidence_refs", [])]
            + [e for p in paths for e in p.get("evidence_refs", [])]
        ))
        missing: List[str] = []
        if not relations:
            missing.append("no_attack_actor_or_malware_relationship_context")
        if exploit_activity <= 0.35:
            missing.append("no_direct_exploitation_activity_evidence")
        if not paths:
            missing.append("no_attack_path_support")

        verification = "VERIFIED_CONTEXT" if evidence and source_credibility >= 0.65 else "PROVISIONAL_CONTEXT"
        return {
            "context_id": new_id("threatctx"),
            "mission_id": mission_id,
            "asset_id": asset_id,
            "correlation_id": corr.get("correlation_id"),
            "mapping_id": mapping.get("mapping_id"),
            "technique_id": mapping.get("technique_id") or mapping.get("attack_id"),
            "target_asset_ids": [asset_id] if asset_id else [],
            "dimensions": dimensions,
            "relations": relations,
            "evidence_refs": evidence,
            "contradictions": [],
            "missing_evidence": missing,
            "valid_from": utcnow_iso(),
            "valid_until": None,
            "confidence": confidence,
            "verification_status": verification,
            "belief_components": {
                "threat_activity": exploit_activity,
                "campaign_relevance": relation_conf,
                "target_relevance": target_relevance,
                "evidence_confidence": source_credibility,
                "path_support": path_support,
            },
            "rule_trace": [
                "R_RELATIONSHIP_CONTEXT_IS_NOT_ATTRIBUTION",
                "R_TARGET_RELEVANCE_FROM_MISSION_AND_ASSET",
                "R_CONTEXT_CONFIDENCE_EVIDENCE_BOUND",
            ],
            "model_version": self.MODEL_VERSION,
            "rule_version": self.RULE_VERSION,
            "authority_state": "CONTEXT_SYNTHESIS_ONLY",
            "execution_authorized": False,
        }

    @staticmethod
    def _severity_score(corr: Dict[str, Any]) -> float:
        score = corr.get("cvss_score") or corr.get("base_score")
        try:
            if score is not None:
                return clamp(float(score) / 10.0)
        except Exception:
            pass
        severity = str(corr.get("severity") or "").upper()
        return {"CRITICAL": 0.95, "HIGH": 0.8, "MEDIUM": 0.55, "LOW": 0.3}.get(severity, 0.5)

    @staticmethod
    def _exploit_activity(corr: Dict[str, Any]) -> float:
        # Only explicit evidence fields may raise this dimension substantially.
        if bool(corr.get("known_exploited")) or bool(corr.get("kev")):
            return 0.95
        if str(corr.get("status") or "").upper() == "EMPIRICALLY_VALIDATED":
            return 0.90
        if corr.get("exploit_evidence_refs"):
            return 0.80
        return 0.25

    @staticmethod
    def _target_relevance(asset: Dict[str, Any], mission: Dict[str, Any]) -> float:
        base = clamp(asset.get("criticality"), default=0.5)
        asset_id = str(asset.get("asset_id") or "")
        high = {str(x) for x in (mission.get("high_priority_assets") or [])}
        if asset_id and asset_id in high:
            base = max(base, 0.9)
        return base

    @staticmethod
    def _recency_score(corr: Dict[str, Any]) -> float:
        value = corr.get("evaluated_at") or corr.get("valid_from") or corr.get("last_modified_date") or corr.get("published_date")
        if not value:
            return 0.45
        if isinstance(value, datetime):
            dt = value
        else:
            try:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except Exception:
                return 0.45
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days = max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 86400.0)
        if days <= 7:
            return 0.95
        if days <= 30:
            return 0.80
        if days <= 90:
            return 0.65
        if days <= 365:
            return 0.50
        return 0.35

    @staticmethod
    def _source_credibility(corr: Dict[str, Any], mapping: Dict[str, Any]) -> float:
        mapping_state = str(mapping.get("verification_state") or "PROVISIONAL").upper()
        corr_state = str(corr.get("status") or "NEEDS_VERIFICATION").upper()
        score = 0.55
        if mapping_state == "VERIFIED":
            score += 0.15
        if corr_state in {"CORRELATED_APPLICABLE", "EMPIRICALLY_VALIDATED"}:
            score += 0.15
        if corr.get("provenance") or corr.get("provenance_refs"):
            score += 0.10
        return clamp(score)

    def _resolve_attack_stix(self, attack_id: str) -> Optional[str]:
        if not self.db.table_exists("attack_patterns"):
            return None
        cols = self.db.columns("attack_patterns")
        for col in ("attack_id", "external_id"):
            if col in cols:
                row = self.db.fetch_one(
                    f"SELECT stix_id FROM attack_patterns WHERE {col}=%(attack_id)s LIMIT 1",
                    {"attack_id": attack_id},
                )
                if row:
                    return row.get("stix_id")
        return None

    def _relationship_context(self, attack_pattern_stix_id: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not attack_pattern_stix_id or not self.db.table_exists("attack_relationships"):
            return out

        if self.db.table_exists("attack_malware"):
            rows = self.db.fetch_all(
                """
                SELECT DISTINCT m.*, r.relationship_type, r.stix_id AS relationship_stix_id,
                                r.description_text AS relationship_description
                FROM attack_relationships r
                JOIN attack_malware m ON m.stix_id = r.source_ref
                WHERE r.relationship_type='uses' AND r.target_ref=%(stix)s
                  AND COALESCE(r.revoked,0)=0 AND COALESCE(r.deprecated,0)=0
                  AND COALESCE(m.revoked,0)=0 AND COALESCE(m.deprecated,0)=0
                LIMIT 200
                """,
                {"stix": attack_pattern_stix_id},
            )
            out.extend(self._format_relation(r, "malware", 0.60) for r in rows)

        actor_table = None
        if self.db.table_exists("attack_threat_actors"):
            actor_table = "attack_threat_actors"
        elif self.db.table_exists("attack_intrusion_sets"):
            actor_table = "attack_intrusion_sets"
        if actor_table:
            rows = self.db.fetch_all(
                f"""
                SELECT DISTINCT a.*, r.relationship_type, r.stix_id AS relationship_stix_id,
                                r.description_text AS relationship_description
                FROM attack_relationships r
                JOIN {actor_table} a ON a.stix_id = r.source_ref
                WHERE r.relationship_type='uses' AND r.target_ref=%(stix)s
                  AND COALESCE(r.revoked,0)=0 AND COALESCE(r.deprecated,0)=0
                  AND COALESCE(a.revoked,0)=0 AND COALESCE(a.deprecated,0)=0
                LIMIT 200
                """,
                {"stix": attack_pattern_stix_id},
            )
            ctype = "threat_actor" if actor_table == "attack_threat_actors" else "intrusion_set"
            out.extend(self._format_relation(r, ctype, 0.55) for r in rows)
        return self._dedupe_relations(out)

    def _format_relation(self, row: Dict[str, Any], context_type: str, confidence: float) -> Dict[str, Any]:
        aliases = safe_json_loads(row.get("aliases_json"), default=row.get("aliases"))
        if aliases is None:
            aliases = []
        if not isinstance(aliases, list):
            aliases = [aliases]
        relation_ref = row.get("relationship_stix_id") or evidence_ref("attack-rel", row.get("stix_id"), row.get("name"))
        return {
            "context_type": context_type,
            "stix_id": row.get("stix_id"),
            "external_id": row.get("group_id") or row.get("software_id") or row.get("external_id") or row.get("attack_id"),
            "name": row.get("name") or "Unknown",
            "aliases": aliases,
            "description": row.get("description_text") or row.get("description"),
            "relationship_type": row.get("relationship_type") or "uses",
            "relationship_ref": relation_ref,
            "relationship_description": row.get("relationship_description"),
            "confidence": confidence,
            "epistemic_state": "RELATIONAL_CONTEXT_INFERENCE",
            "target_presence_asserted": False,
            "evidence_refs": [evidence_ref("mitre-attack-relationship", relation_ref)],
            "note": "MITRE ATT&CK relationship context only; not evidence that this entity is present on the tested target.",
        }

    @staticmethod
    def _dedupe_relations(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen = set()
        for row in rows:
            key = (row.get("context_type"), row.get("stix_id"), row.get("name"))
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        return out

    @staticmethod
    def _dedupe(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        best: Dict[tuple, Dict[str, Any]] = {}
        for row in rows:
            key = (row.get("asset_id"), row.get("correlation_id"), row.get("technique_id"))
            prev = best.get(key)
            if prev is None or float(row.get("confidence") or 0) > float(prev.get("confidence") or 0):
                best[key] = row
        return list(best.values())

    def _persist(self, context: Dict[str, Any]) -> None:
        if not self.db.table_exists("cti_threat_contexts"):
            return
        self.db.execute(
            """
            INSERT INTO cti_threat_contexts
                (context_id, mission_id, asset_id, correlation_id, mapping_id, technique_id,
                 target_asset_ids_json, dimensions_json, relations_json, evidence_refs_json,
                 contradictions_json, missing_evidence_json, valid_from, valid_until,
                 confidence, verification_status, belief_components_json, rule_trace_json,
                 model_version, rule_version, authority_state, execution_authorized, created_at)
            VALUES
                (%(context_id)s, %(mission_id)s, %(asset_id)s, %(correlation_id)s, %(mapping_id)s,
                 %(technique_id)s, %(target_asset_ids_json)s, %(dimensions_json)s,
                 %(relations_json)s, %(evidence_refs_json)s, %(contradictions_json)s,
                 %(missing_evidence_json)s, %(valid_from)s, %(valid_until)s, %(confidence)s,
                 %(verification_status)s, %(belief_components_json)s, %(rule_trace_json)s,
                 %(model_version)s, %(rule_version)s, %(authority_state)s,
                 %(execution_authorized)s, CURRENT_TIMESTAMP)
            """,
            {
                **context,
                "valid_from": to_db_datetime(context.get("valid_from")),
                "valid_until": to_db_datetime(context.get("valid_until")),
                "target_asset_ids_json": to_json(context.get("target_asset_ids") or []),
                "dimensions_json": to_json(context.get("dimensions") or {}),
                "relations_json": to_json(context.get("relations") or []),
                "evidence_refs_json": to_json(context.get("evidence_refs") or []),
                "contradictions_json": to_json(context.get("contradictions") or []),
                "missing_evidence_json": to_json(context.get("missing_evidence") or []),
                "belief_components_json": to_json(context.get("belief_components") or {}),
                "rule_trace_json": to_json(context.get("rule_trace") or []),
                "execution_authorized": 1 if context.get("execution_authorized") else 0,
            },
        )
