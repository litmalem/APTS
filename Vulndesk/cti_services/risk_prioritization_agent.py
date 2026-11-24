from __future__ import annotations

from typing import Any, Dict, List, Optional

from .audit_store import AuditStore
from .common import clamp, new_id, severity_to_score, utcnow_iso
from .db_adapter import DbAdapter, to_json
from .service_registry import ServiceRegistry


class RiskPrioritizationAgent:
    """CTI-A04 Belief-Desire-Intention risk prioritization baseline.

    The agent commits to *prioritization intentions* only.  It does not grant
    authorization and it never turns a ranked item into an execution command.
    Hard feasibility/policy constraints are evaluated separately from utility.
    """

    SERVICE_KEY = "risk_prioritization_agent"
    COMPONENT_ID = "CTI-A04"
    MODEL_VERSION = "bdi-risk-baseline-1.0"
    RULE_VERSION = "bdi-risk-rules-1.0"

    DEFAULT_WEIGHTS = {
        "severity": 0.22,
        "exposure": 0.12,
        "asset_criticality": 0.16,
        "threat_activity": 0.14,
        "path_contribution": 0.10,
        "mission_relevance": 0.12,
        "evidence_confidence": 0.14,
    }
    DEFAULT_PENALTIES = {
        "uncertainty": 0.12,
        "operational_cost": 0.04,
        "disruption_risk": 0.04,
    }

    def __init__(
        self,
        db: Optional[DbAdapter] = None,
        registry: Optional[ServiceRegistry] = None,
        audit: Optional[AuditStore] = None,
    ):
        self.db = db or DbAdapter()
        self.registry = registry or ServiceRegistry(self.db)
        self.audit = audit or AuditStore(self.db)

    def prioritize(
        self,
        mission_id: str,
        asset_profiles: List[Dict[str, Any]],
        correlations: List[Dict[str, Any]],
        attack_mappings: Optional[List[Dict[str, Any]]] = None,
        attack_paths: Optional[List[Dict[str, Any]]] = None,
        threat_contexts: Optional[List[Dict[str, Any]]] = None,
        mission_context: Optional[Dict[str, Any]] = None,
        policy_context: Optional[Dict[str, Any]] = None,
        feedback_context: Optional[Dict[str, Any]] = None,
        quality_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.registry.is_enabled(self.SERVICE_KEY):
            return {"status": "skipped", "belief_snapshot": None, "portfolio": None, "intentions": []}

        self.registry.update_status(self.SERVICE_KEY, "running")
        try:
            mission_context = mission_context or {}
            policy_context = policy_context or {}
            feedback_context = feedback_context or {}
            quality_context = quality_context or {}
            belief_snapshot = self._build_beliefs(
                mission_id,
                asset_profiles,
                correlations,
                attack_mappings or [],
                attack_paths or [],
                threat_contexts or [],
                mission_context,
                policy_context,
                feedback_context,
                quality_context,
            )
            self._persist_beliefs(belief_snapshot)

            asset_by_id = {str(a.get("asset_id")): a for a in asset_profiles or [] if a.get("asset_id")}
            mappings_by_corr: Dict[str, List[Dict[str, Any]]] = {}
            for row in attack_mappings or []:
                if row.get("correlation_id"):
                    mappings_by_corr.setdefault(str(row["correlation_id"]), []).append(row)
            paths_by_corr: Dict[str, List[Dict[str, Any]]] = {}
            for row in attack_paths or []:
                if row.get("correlation_id"):
                    paths_by_corr.setdefault(str(row["correlation_id"]), []).append(row)
            threat_by_corr: Dict[str, List[Dict[str, Any]]] = {}
            for row in threat_contexts or []:
                if row.get("correlation_id"):
                    threat_by_corr.setdefault(str(row["correlation_id"]), []).append(row)

            candidates: List[Dict[str, Any]] = []
            for corr in correlations or []:
                corr_id = str(corr.get("correlation_id") or "")
                asset = asset_by_id.get(str(corr.get("asset_id") or "")) or {}
                candidate = self._desire_candidate(
                    corr=corr,
                    asset=asset,
                    mappings=mappings_by_corr.get(corr_id, []),
                    paths=paths_by_corr.get(corr_id, []),
                    threats=threat_by_corr.get(corr_id, []),
                    mission=mission_context,
                    policy=policy_context,
                )
                candidates.append(candidate)

            admissible = [c for c in candidates if c["feasibility"]["admissible"]]
            inadmissible = [c for c in candidates if not c["feasibility"]["admissible"]]
            admissible.sort(key=lambda x: (-float(x["utility_total"]), -float(x["confidence"]), str(x.get("target_ref"))))

            portfolio_id = new_id("portfolio")
            intentions: List[Dict[str, Any]] = []
            for rank, cand in enumerate(admissible, start=1):
                band = self._priority_band(cand["utility_total"])
                intention = {
                    "portfolio_id": portfolio_id,
                    "belief_snapshot_id": belief_snapshot["belief_snapshot_id"],
                    "intention_id": new_id("intention"),
                    "mission_id": mission_id,
                    "target_ref": cand["target_ref"],
                    "asset_id": cand.get("asset_id"),
                    "cve_id": cand.get("cve_id"),
                    "correlation_id": cand.get("correlation_id"),
                    "priority_band": band,
                    "priority_rank": rank,
                    "utility_total": round(float(cand["utility_total"]), 6),
                    "utility_components": cand["utility_components"],
                    "penalty_components": cand["penalty_components"],
                    "confidence": round(float(cand["confidence"]), 6),
                    "reason_codes": cand["reason_codes"],
                    "evidence_refs": cand["evidence_refs"],
                    "dependencies": cand["dependencies"],
                    "approval_requirement": "GOVERNANCE_APPROVAL_REQUIRED_FOR_ANY_TARGET_ACTION",
                    "commitment_state": "COMMITTED_PRIORITY_RECOMMENDATION",
                    "reconsider_after": None,
                    "policy_version": policy_context.get("policy_version") or policy_context.get("version"),
                    "feasibility": cand["feasibility"],
                    "execution_authorized": False,
                    "authority_state": "PRIORITY_RECOMMENDATION_ONLY",
                    "created_at": utcnow_iso(),
                }
                intentions.append(intention)
                self._persist_intention(intention)

            portfolio = {
                "portfolio_id": portfolio_id,
                "mission_id": mission_id,
                "belief_snapshot_id": belief_snapshot["belief_snapshot_id"],
                "created_at": utcnow_iso(),
                "intention_ids": [i["intention_id"] for i in intentions],
                "ranked_intentions": intentions,
                "inadmissible_candidates": inadmissible,
                "selection_rule": "HARD_FEASIBILITY_THEN_WEIGHTED_UTILITY",
                "weights": self.DEFAULT_WEIGHTS,
                "penalties": self.DEFAULT_PENALTIES,
                "model_version": self.MODEL_VERSION,
                "rule_version": self.RULE_VERSION,
                "execution_authorized": False,
            }
            self._persist_portfolio(portfolio)

            self.audit.append(
                mission_id=mission_id,
                component_id=self.COMPONENT_ID,
                event_type="risk_prioritization.completed",
                reason_code="BDI_INTENTIONS_COMMITTED",
                input_snapshot={
                    "belief_snapshot_id": belief_snapshot["belief_snapshot_id"],
                    "candidate_count": len(candidates),
                },
                candidate_alternatives=[
                    {
                        "target_ref": c["target_ref"],
                        "utility": c["utility_total"],
                        "admissible": c["feasibility"]["admissible"],
                        "reason_codes": c["reason_codes"],
                    }
                    for c in candidates
                ],
                selected_output={
                    "portfolio_id": portfolio_id,
                    "intention_ids": [i["intention_id"] for i in intentions],
                },
                evidence_refs=[e for i in intentions for e in i.get("evidence_refs", [])],
                versions={
                    "model": self.MODEL_VERSION,
                    "rules": self.RULE_VERSION,
                    "policy_version": policy_context.get("policy_version") or policy_context.get("version"),
                },
            )
            self.registry.update_status(self.SERVICE_KEY, "idle")
            return {
                "status": "completed",
                "belief_snapshot": belief_snapshot,
                "portfolio": portfolio,
                "intentions": intentions,
                "model_version": self.MODEL_VERSION,
                "rule_version": self.RULE_VERSION,
            }
        except Exception as exc:
            self.registry.update_status(self.SERVICE_KEY, "error", str(exc))
            raise

    def _build_beliefs(
        self,
        mission_id: str,
        assets: List[Dict[str, Any]],
        correlations: List[Dict[str, Any]],
        mappings: List[Dict[str, Any]],
        paths: List[Dict[str, Any]],
        threats: List[Dict[str, Any]],
        mission: Dict[str, Any],
        policy: Dict[str, Any],
        feedback: Dict[str, Any],
        quality: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "belief_snapshot_id": new_id("beliefsnap"),
            "mission_id": mission_id,
            "created_at": utcnow_iso(),
            "beliefs": {
                "asset": assets,
                "vulnerability": correlations,
                "attack_mapping": mappings,
                "path": paths,
                "threat": threats,
                "mission": mission,
                "policy": policy,
                "feedback": feedback,
                "quality": quality,
            },
            "categories": ["asset", "cpe", "vulnerability", "threat", "path", "mission", "policy", "feedback", "quality"],
            "model_version": self.MODEL_VERSION,
        }

    def _desire_candidate(
        self,
        *,
        corr: Dict[str, Any],
        asset: Dict[str, Any],
        mappings: List[Dict[str, Any]],
        paths: List[Dict[str, Any]],
        threats: List[Dict[str, Any]],
        mission: Dict[str, Any],
        policy: Dict[str, Any],
    ) -> Dict[str, Any]:
        severity = severity_to_score(corr.get("severity"), corr.get("cvss_score"))
        exposure = self._exposure_score(asset)
        criticality = clamp(asset.get("criticality"), default=0.5)
        threat_activity = max([
            clamp((t.get("belief_components") or {}).get("threat_activity"), default=0.0)
            for t in threats
        ] or [0.25])
        path_contribution = max([clamp(p.get("path_confidence"), default=0.0) for p in paths] or [0.0])
        mission_relevance = self._mission_relevance(asset, corr, mission)
        corr_conf = clamp(corr.get("confidence"), default=0.5)
        mapping_conf = max([clamp(m.get("confidence") or m.get("probability_score"), default=0.0) for m in mappings] or [0.4])
        threat_conf = max([clamp(t.get("confidence"), default=0.0) for t in threats] or [0.4])
        evidence_conf = clamp((corr_conf + mapping_conf + threat_conf) / 3.0)

        uncertainty = clamp(1.0 - evidence_conf)
        operational_cost = clamp(corr.get("operational_cost"), default=0.2)
        disruption_risk = clamp(corr.get("disruption_risk"), default=0.2)

        utility_components = {
            "severity": severity,
            "exposure": exposure,
            "asset_criticality": criticality,
            "threat_activity": threat_activity,
            "path_contribution": path_contribution,
            "mission_relevance": mission_relevance,
            "evidence_confidence": evidence_conf,
        }
        penalties = {
            "uncertainty": uncertainty,
            "operational_cost": operational_cost,
            "disruption_risk": disruption_risk,
        }
        positive = sum(self.DEFAULT_WEIGHTS[k] * utility_components[k] for k in self.DEFAULT_WEIGHTS)
        negative = sum(self.DEFAULT_PENALTIES[k] * penalties[k] for k in self.DEFAULT_PENALTIES)
        utility = clamp(positive - negative)

        feasibility = self._hard_feasibility(corr, asset, policy, evidence_conf)
        reason_codes = self._reason_codes(utility_components, feasibility)
        dependencies = [
            x
            for x in [
                corr.get("correlation_id"),
                *[m.get("mapping_id") for m in mappings],
                *[p.get("path_id") for p in paths],
                *[t.get("context_id") for t in threats],
            ]
            if x
        ]
        evidence = list(dict.fromkeys(
            list(corr.get("matched_evidence") or corr.get("evidence_refs") or [])
            + [e for m in mappings for e in m.get("evidence_refs", [])]
            + [e for p in paths for e in p.get("evidence_refs", [])]
            + [e for t in threats for e in t.get("evidence_refs", [])]
        ))
        target_ref = corr.get("correlation_id") or f"{corr.get('asset_id')}:{corr.get('cve_id')}"
        return {
            "target_ref": target_ref,
            "asset_id": corr.get("asset_id"),
            "cve_id": corr.get("cve_id"),
            "correlation_id": corr.get("correlation_id"),
            "utility_total": utility,
            "utility_components": utility_components,
            "penalty_components": penalties,
            "confidence": evidence_conf,
            "feasibility": feasibility,
            "reason_codes": reason_codes,
            "dependencies": dependencies,
            "evidence_refs": evidence,
        }

    @staticmethod
    def _exposure_score(asset: Dict[str, Any]) -> float:
        exposure = str(asset.get("exposure") or (asset.get("observed_attributes") or {}).get("exposure") or "unknown").lower()
        if any(x in exposure for x in ("internet", "public", "external")):
            return 0.95
        if any(x in exposure for x in ("dmz", "partner")):
            return 0.75
        if any(x in exposure for x in ("internal", "private")):
            return 0.50
        return 0.45

    @staticmethod
    def _mission_relevance(asset: Dict[str, Any], corr: Dict[str, Any], mission: Dict[str, Any]) -> float:
        score = clamp(mission.get("default_relevance"), default=0.6)
        asset_id = str(asset.get("asset_id") or corr.get("asset_id") or "")
        high_assets = {str(x) for x in mission.get("high_priority_assets") or []}
        if asset_id and asset_id in high_assets:
            score = max(score, 0.95)
        cve_id = str(corr.get("cve_id") or "")
        high_vulns = {str(x) for x in mission.get("high_priority_vulnerabilities") or []}
        if cve_id and cve_id in high_vulns:
            score = max(score, 0.95)
        return score

    @staticmethod
    def _hard_feasibility(corr: Dict[str, Any], asset: Dict[str, Any], policy: Dict[str, Any], evidence_conf: float) -> Dict[str, Any]:
        reasons: List[str] = []
        status = str(corr.get("status") or "").upper()
        symbolic = str(corr.get("symbolic_result") or "UNKNOWN").upper()
        if status in {"NOT_APPLICABLE", "REJECTED"} or symbolic == "FALSE":
            reasons.append("VULNERABILITY_NOT_APPLICABLE")
        if policy.get("scope_allowed") is False:
            reasons.append("OUTSIDE_POLICY_SCOPE")
        denied_assets = {str(x) for x in policy.get("denied_assets") or []}
        if str(asset.get("asset_id") or corr.get("asset_id") or "") in denied_assets:
            reasons.append("ASSET_DENIED_BY_POLICY")
        minimum = clamp(policy.get("minimum_evidence_confidence"), default=0.25)
        if evidence_conf < minimum:
            reasons.append("EVIDENCE_BELOW_HARD_MINIMUM")
        return {
            "admissible": not reasons,
            "hard_constraint_failures": reasons,
            "policy_can_be_overridden_by_utility": False,
        }

    @staticmethod
    def _reason_codes(components: Dict[str, float], feasibility: Dict[str, Any]) -> List[str]:
        reasons: List[str] = []
        if not feasibility["admissible"]:
            return ["INADMISSIBLE_HARD_CONSTRAINT"] + list(feasibility["hard_constraint_failures"])
        ranked = sorted(components.items(), key=lambda kv: -kv[1])
        for name, value in ranked[:3]:
            if value >= 0.65:
                reasons.append(f"HIGH_{name.upper()}")
        return reasons or ["BALANCED_RISK_EVIDENCE"]

    @staticmethod
    def _priority_band(score: float) -> str:
        if score >= 0.78:
            return "P1_CRITICAL"
        if score >= 0.62:
            return "P2_HIGH"
        if score >= 0.45:
            return "P3_MEDIUM"
        return "P4_LOW"

    def _persist_beliefs(self, snapshot: Dict[str, Any]) -> None:
        if not self.db.table_exists("cti_beliefs"):
            return
        for category, payload in (snapshot.get("beliefs") or {}).items():
            self.db.execute(
                """
                INSERT INTO cti_beliefs
                    (belief_id, belief_snapshot_id, mission_id, belief_category, subject_ref,
                     belief_json, confidence, source_refs_json, valid_from, valid_until,
                     model_version, created_at)
                VALUES
                    (%(belief_id)s, %(belief_snapshot_id)s, %(mission_id)s, %(belief_category)s,
                     NULL, %(belief_json)s, NULL, '[]', CURRENT_TIMESTAMP, NULL,
                     %(model_version)s, CURRENT_TIMESTAMP)
                """,
                {
                    "belief_id": new_id("belief"),
                    "belief_snapshot_id": snapshot["belief_snapshot_id"],
                    "mission_id": snapshot["mission_id"],
                    "belief_category": category,
                    "belief_json": to_json(payload),
                    "model_version": self.MODEL_VERSION,
                },
            )

    def _persist_intention(self, intention: Dict[str, Any]) -> None:
        if not self.db.table_exists("cti_intentions"):
            return
        self.db.execute(
            """
            INSERT INTO cti_intentions
                (intention_id, portfolio_id, belief_snapshot_id, mission_id, target_ref, asset_id,
                 cve_id, correlation_id, priority_band, priority_rank, utility_total,
                 utility_components_json, penalty_components_json, confidence, reason_codes_json,
                 evidence_refs_json, dependencies_json, approval_requirement, commitment_state,
                 reconsider_after, policy_version, feasibility_json, execution_authorized,
                 authority_state, created_at)
            VALUES
                (%(intention_id)s, %(portfolio_id)s, %(belief_snapshot_id)s, %(mission_id)s,
                 %(target_ref)s, %(asset_id)s, %(cve_id)s, %(correlation_id)s,
                 %(priority_band)s, %(priority_rank)s, %(utility_total)s,
                 %(utility_components_json)s, %(penalty_components_json)s, %(confidence)s,
                 %(reason_codes_json)s, %(evidence_refs_json)s, %(dependencies_json)s,
                 %(approval_requirement)s, %(commitment_state)s, %(reconsider_after)s,
                 %(policy_version)s, %(feasibility_json)s, %(execution_authorized)s,
                 %(authority_state)s, CURRENT_TIMESTAMP)
            """,
            {
                **intention,
                "utility_components_json": to_json(intention.get("utility_components") or {}),
                "penalty_components_json": to_json(intention.get("penalty_components") or {}),
                "reason_codes_json": to_json(intention.get("reason_codes") or []),
                "evidence_refs_json": to_json(intention.get("evidence_refs") or []),
                "dependencies_json": to_json(intention.get("dependencies") or []),
                "feasibility_json": to_json(intention.get("feasibility") or {}),
                "execution_authorized": 1 if intention.get("execution_authorized") else 0,
            },
        )

    def _persist_portfolio(self, portfolio: Dict[str, Any]) -> None:
        if not self.db.table_exists("cti_priority_portfolios"):
            return
        self.db.execute(
            """
            INSERT INTO cti_priority_portfolios
                (portfolio_id, mission_id, belief_snapshot_id, selection_rule, weights_json,
                 penalties_json, ranked_intentions_json, inadmissible_candidates_json,
                 model_version, rule_version, execution_authorized, created_at)
            VALUES
                (%(portfolio_id)s, %(mission_id)s, %(belief_snapshot_id)s, %(selection_rule)s,
                 %(weights_json)s, %(penalties_json)s, %(ranked_intentions_json)s,
                 %(inadmissible_candidates_json)s, %(model_version)s, %(rule_version)s,
                 %(execution_authorized)s, CURRENT_TIMESTAMP)
            """,
            {
                **portfolio,
                "weights_json": to_json(portfolio.get("weights") or {}),
                "penalties_json": to_json(portfolio.get("penalties") or {}),
                "ranked_intentions_json": to_json(portfolio.get("ranked_intentions") or []),
                "inadmissible_candidates_json": to_json(portfolio.get("inadmissible_candidates") or []),
                "execution_authorized": 1 if portfolio.get("execution_authorized") else 0,
            },
        )
