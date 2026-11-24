from __future__ import annotations

from typing import Any, Dict, List, Optional

from .audit_store import AuditStore
from .common import clamp, evidence_ref, new_id, to_db_datetime, utcnow_iso
from .db_adapter import DbAdapter, to_json
from .service_registry import ServiceRegistry


class AssetProfilingCpeResolutionService:
    SERVICE_KEY = "asset_profiling_cpe_resolution_service"
    COMPONENT_ID = "CTI-S02"
    MODEL_VERSION = "cpe-ranker-baseline-1.0"
    RULE_VERSION = "cpe-resolution-rules-1.0"

    def __init__(
        self,
        db: Optional[DbAdapter] = None,
        registry: Optional[ServiceRegistry] = None,
        audit: Optional[AuditStore] = None,
        dictionary_service: Optional[Any] = None,
    ):
        self.db = db or DbAdapter()
        self.registry = registry or ServiceRegistry(self.db)
        self.audit = audit or AuditStore(self.db)
        if dictionary_service is None:
            from cpe_dictionary_services import CpeDictionaryService
            dictionary_service = CpeDictionaryService()
        self.dictionary = dictionary_service

    def profile_scan(self, scan_payload: Dict[str, Any], mission_id: str) -> Dict[str, Any]:
        if not self.registry.is_enabled(self.SERVICE_KEY):
            return {"status": "skipped", "asset_profiles": [], "cpe_claims": [], "enrichment_requirements": []}
        self.registry.update_status(self.SERVICE_KEY, "running")
        try:
            assets = scan_payload.get("assets") or [self._synthetic_asset(scan_payload)]
            asset_profiles: List[Dict[str, Any]] = []
            all_claims: List[Dict[str, Any]] = []
            enrichment: List[Dict[str, Any]] = []

            for asset in assets:
                profile = self._build_asset_profile(asset, scan_payload, mission_id)
                asset_profiles.append(profile)
                technologies = asset.get("technologies") or scan_payload.get("technologies") or []
                official_candidates = [] if scan_payload.get("wpt_context_only") is True else self.dictionary.match_technologies(
                    technologies,
                    per_technology_limit=int(scan_payload.get("cpe_limit") or 3),
                    auto_fetch=bool(scan_payload.get("cpe_auto_fetch", True)),
                )
                submitted_candidates = [
                    dict(c) for c in (scan_payload.get("cpe_candidates") or [])
                    if not c.get("asset_id") or str(c.get("asset_id")) == str(profile["asset_id"])
                ]
                candidates = self._merge_candidate_inputs(official_candidates, submitted_candidates)
                claims = self._claims_for_candidates(profile, technologies, candidates)
                all_claims.extend(claims)
                profile["cpe_resolution_refs"] = [c["resolution_id"] for c in claims if c["asset_id"] == profile["asset_id"]]
                for tech in technologies:
                    tech_key = self._tech_key(tech)
                    tech_claims = [c for c in claims if c.get("technology_key") == tech_key]
                    if not tech_claims or all(c["status"] in {"UNRESOLVED", "AMBIGUOUS", "REJECTED"} for c in tech_claims):
                        enrichment.append({
                            "requirement_id": new_id("enrichreq"),
                            "asset_id": profile["asset_id"],
                            "technology_key": tech_key,
                            "required_evidence": ["vendor", "product", "exact_version_or_build"],
                            "reason_code": "INSUFFICIENT_CPE_EVIDENCE",
                            "authority_state": "REQUEST_ONLY_NO_ACTIVE_PROBE",
                        })
                self._persist_profile(profile)
            for claim in all_claims:
                self._persist_claim(claim)
            for requirement in enrichment:
                self._persist_enrichment_requirement(mission_id, requirement)

            result = {
                "status": "completed",
                "asset_profiles": asset_profiles,
                "cpe_claims": all_claims,
                "enrichment_requirements": enrichment,
                "model_version": self.MODEL_VERSION,
                "rule_version": self.RULE_VERSION,
            }
            self.audit.append(
                mission_id=mission_id,
                component_id=self.COMPONENT_ID,
                event_type="asset_cpe.completed",
                reason_code="ASSET_CPE_RESOLUTION_COMPLETE",
                input_snapshot={"asset_count": len(assets), "technology_count": len(scan_payload.get("technologies") or [])},
                candidate_alternatives=[{"resolution_id": c["resolution_id"], "status": c["status"], "confidence": c["confidence"]} for c in all_claims],
                selected_output={"asset_profiles": [p["asset_id"] for p in asset_profiles], "claim_count": len(all_claims)},
                evidence_refs=[e for c in all_claims for e in c.get("evidence_refs", [])],
                versions={"model": self.MODEL_VERSION, "rules": self.RULE_VERSION},
            )
            self.registry.update_status(self.SERVICE_KEY, "idle")
            return result
        except Exception as exc:
            self.registry.update_status(self.SERVICE_KEY, "error", str(exc))
            raise


    @staticmethod
    def _merge_candidate_inputs(official: List[Dict[str, Any]], submitted: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen = set()
        for row in (official or []) + (submitted or []):
            item = dict(row or {})
            uri = str(item.get("cpe23_uri") or item.get("criteria_uri") or "").strip()
            key = (uri, str(item.get("technology_name") or item.get("product") or ""), str(item.get("technology_version") or item.get("version") or ""))
            if key in seen:
                continue
            seen.add(key)
            if uri:
                item.setdefault("cpe23_uri", uri)
                item.setdefault("criteria_uri", uri)
            # Submitted candidates are evidence candidates, never silently treated
            # as dictionary-verified facts.
            item.setdefault("match_method", "submitted_candidate" if row in (submitted or []) else "candidate")
            item.setdefault("confidence", item.get("match_confidence", 0.55))
            out.append(item)
        return out

    @staticmethod
    def _synthetic_asset(scan_payload: Dict[str, Any]) -> Dict[str, Any]:
        scan_id = scan_payload.get("scan_job_id") or scan_payload.get("id") or "adhoc"
        return {
            "asset_id": scan_payload.get("asset_id") or f"asset-scan-{scan_id}",
            "asset_type": scan_payload.get("asset_type") or "web_application",
            "target_url": scan_payload.get("target_url"),
            "hostname": scan_payload.get("hostname"),
            "ip": scan_payload.get("ip"),
            "exposure": scan_payload.get("exposure") or "internet-facing",
            "criticality": scan_payload.get("asset_criticality", 0.5),
            "sector": scan_payload.get("sector"),
            "technologies": scan_payload.get("technologies") or [],
            "endpoints": scan_payload.get("endpoints") or [],
        }

    def _build_asset_profile(self, asset: Dict[str, Any], scan_payload: Dict[str, Any], mission_id: str) -> Dict[str, Any]:
        asset_id = str(asset.get("asset_id") or new_id("asset"))
        observed = {
            "target_url": asset.get("target_url") or scan_payload.get("target_url"),
            "hostname": asset.get("hostname"),
            "ip": asset.get("ip"),
            "asset_type": asset.get("asset_type") or "unknown",
            "exposure": asset.get("exposure") or "unknown",
            "technologies": asset.get("technologies") or [],
            "endpoints": asset.get("endpoints") or [],
            "sector": asset.get("sector") or scan_payload.get("sector"),
        }
        evidence_refs = [
            evidence_ref("asset-observation", mission_id, asset_id, "profile"),
        ]
        evidence_refs.extend(scan_payload.get("evidence_refs") or [])
        for tech in observed["technologies"]:
            evidence_refs.append(evidence_ref("technology-observation", mission_id, asset_id, self._tech_key(tech)))
        return {
            "asset_profile_id": new_id("assetprof"),
            "mission_id": mission_id,
            "asset_id": asset_id,
            "asset_type": observed["asset_type"],
            "exposure": observed["exposure"],
            "criticality": clamp(asset.get("criticality"), default=0.5),
            "observed_attributes": observed,
            "inferred_attributes": {},
            "evidence_refs": evidence_refs,
            "confidence": 0.95 if observed.get("target_url") or observed.get("hostname") or observed.get("ip") else 0.65,
            "verification_status": "OBSERVED",
            "profile_version": 1,
            "observed_at": scan_payload.get("observed_at") or utcnow_iso(),
        }

    def _claims_for_candidates(self, profile: Dict[str, Any], technologies: List[Dict[str, Any]], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        tech_by_key = {self._tech_key(t): t for t in technologies or []}
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for candidate in candidates or []:
            key = self._candidate_tech_key(candidate)
            grouped.setdefault(key, []).append(candidate)

        claims: List[Dict[str, Any]] = []
        for key, rows in grouped.items():
            rows = sorted(rows, key=lambda r: -float(r.get("confidence") or r.get("match_confidence") or 0))
            top = float(rows[0].get("confidence") or rows[0].get("match_confidence") or 0) if rows else 0.0
            second = float(rows[1].get("confidence") or rows[1].get("match_confidence") or 0) if len(rows) > 1 else 0.0
            margin = top - second
            for rank, candidate in enumerate(rows, start=1):
                score = clamp(candidate.get("confidence") or candidate.get("match_confidence"), default=0.0)
                method = str(candidate.get("match_method") or "candidate")
                if candidate.get("deprecated"):
                    status = "REJECTED"
                elif rank == 1 and method == "official_cpe_exact_version" and score >= 0.88:
                    status = "VERIFIED"
                elif rank == 1 and score >= 0.75 and margin >= 0.08:
                    status = "PROBABLE"
                elif rank <= 2 and score >= 0.65 and margin < 0.08:
                    status = "AMBIGUOUS"
                else:
                    status = "UNRESOLVED"
                if candidate.get("wpt_context_only") and status != "REJECTED":
                    status = "AMBIGUOUS"
                tech = tech_by_key.get(key) or {
                    "technology_name": candidate.get("technology_name"),
                    "technology_version": candidate.get("technology_version"),
                }
                evidence_refs = [
                    evidence_ref("technology-observation", profile["mission_id"], profile["asset_id"], key),
                    evidence_ref("cpe-dictionary", candidate.get("cpe_name_id") or candidate.get("vulndesk_cpe_id") or candidate.get("cpe23_uri")),
                ]
                evidence_refs.extend(profile.get("evidence_refs") or [])
                claims.append({
                    "resolution_id": new_id("cperes"),
                    "mission_id": profile["mission_id"],
                    "asset_profile_id": profile["asset_profile_id"],
                    "asset_id": profile["asset_id"],
                    "technology_key": key,
                    "candidate_rank": rank,
                    "cpe_wfn": candidate.get("cpe23_uri"),
                    "cpe23_formatted": candidate.get("cpe23_uri"),
                    "dictionary_ref": candidate.get("cpe_name_id") or candidate.get("vulndesk_cpe_id"),
                    "status": status,
                    "confidence": score,
                    "observed_attributes": {
                        "technology_name": tech.get("technology_name") or tech.get("name") or tech.get("product"),
                        "technology_version": tech.get("technology_version") or tech.get("version"),
                    },
                    "inferred_attributes": {
                        "vendor": candidate.get("vendor"),
                        "product": candidate.get("product"),
                        "version": candidate.get("version"),
                        "part": candidate.get("part"),
                    },
                    "evidence_refs": evidence_refs,
                    "contradiction_refs": (["DEPRECATED_CPE"] if candidate.get("deprecated") else []),
                    "rule_trace": (["R_WPT_OBSERVATION_REQUIRES_CONFIGURATION_EVIDENCE"] if candidate.get("wpt_context_only") else []) + [
                        "R_DICTIONARY_MATCH",
                        "R_DEPRECATION_REJECT" if candidate.get("deprecated") else "R_DEPRECATION_OK",
                        "R_EXACT_VERSION" if method == "official_cpe_exact_version" else "R_PRODUCT_OR_ALIAS_MATCH",
                    ],
                    "model_version": self.MODEL_VERSION,
                    "dictionary_version": "local-nvd-cpe-dictionary",
                    "decision_time": utcnow_iso(),
                    "source_candidate": candidate,
                })
        return claims

    @staticmethod
    def _tech_key(tech: Dict[str, Any]) -> str:
        name = str(tech.get("technology_name") or tech.get("name") or tech.get("product") or "unknown").strip().lower()
        version = str(tech.get("technology_version") or tech.get("version") or "").strip().lower()
        return f"{name}|{version}"

    @staticmethod
    def _candidate_tech_key(candidate: Dict[str, Any]) -> str:
        name = str(candidate.get("technology_name") or candidate.get("product") or "unknown").strip().lower()
        version = str(candidate.get("technology_version") or candidate.get("version") or "").strip().lower()
        return f"{name}|{version}"

    def _persist_profile(self, profile: Dict[str, Any]) -> None:
        if not self.db.table_exists("cti_asset_profiles"):
            return
        self.db.execute(
            """
            INSERT INTO cti_asset_profiles
                (asset_profile_id, mission_id, asset_id, asset_type, target_url, hostname, ip_address,
                 exposure, criticality, observed_json, inferred_json, evidence_refs_json, confidence,
                 verification_status, profile_version, observed_at, created_at)
            VALUES
                (%(asset_profile_id)s, %(mission_id)s, %(asset_id)s, %(asset_type)s, %(target_url)s,
                 %(hostname)s, %(ip_address)s, %(exposure)s, %(criticality)s, %(observed_json)s,
                 %(inferred_json)s, %(evidence_refs_json)s, %(confidence)s, %(verification_status)s,
                 %(profile_version)s, %(observed_at)s, CURRENT_TIMESTAMP)
            """,
            {
                **profile,
                "target_url": profile["observed_attributes"].get("target_url"),
                "hostname": profile["observed_attributes"].get("hostname"),
                "ip_address": profile["observed_attributes"].get("ip"),
                "observed_json": to_json(profile["observed_attributes"]),
                "inferred_json": to_json(profile["inferred_attributes"]),
                "evidence_refs_json": to_json(profile["evidence_refs"]),
                # Keep ISO-8601 in runtime/event objects, but persist a
                # timezone-naive UTC datetime because MariaDB DATETIME does
                # not accept the trailing-Z representation used by utcnow_iso.
                "observed_at": to_db_datetime(profile.get("observed_at")),
            },
        )

    def _persist_claim(self, claim: Dict[str, Any]) -> None:
        if not self.db.table_exists("cti_cpe_resolution_claims"):
            return
        self.db.execute(
            """
            INSERT INTO cti_cpe_resolution_claims
                (resolution_id, mission_id, asset_profile_id, asset_id, technology_key, candidate_rank,
                 cpe_wfn, cpe23_formatted, dictionary_ref, status, confidence, observed_attributes_json,
                 inferred_attributes_json, evidence_refs_json, contradiction_refs_json, rule_trace_json,
                 model_version, dictionary_version, decision_time, supersedes, created_at)
            VALUES
                (%(resolution_id)s, %(mission_id)s, %(asset_profile_id)s, %(asset_id)s, %(technology_key)s,
                 %(candidate_rank)s, %(cpe_wfn)s, %(cpe23_formatted)s, %(dictionary_ref)s, %(status)s,
                 %(confidence)s, %(observed_attributes_json)s, %(inferred_attributes_json)s,
                 %(evidence_refs_json)s, %(contradiction_refs_json)s, %(rule_trace_json)s,
                 %(model_version)s, %(dictionary_version)s, %(decision_time)s, NULL, CURRENT_TIMESTAMP)
            """,
            {
                **claim,
                "observed_attributes_json": to_json(claim["observed_attributes"]),
                "inferred_attributes_json": to_json(claim["inferred_attributes"]),
                "evidence_refs_json": to_json(claim["evidence_refs"]),
                "contradiction_refs_json": to_json(claim["contradiction_refs"]),
                "rule_trace_json": to_json(claim["rule_trace"]),
                # decision_time is the next DATETIME persistence boundary in
                # this service; normalize it for the same reason as observed_at.
                "decision_time": to_db_datetime(claim.get("decision_time")),
            },
        )

    def _persist_enrichment_requirement(self, mission_id: str, requirement: Dict[str, Any]) -> None:
        if not self.db.table_exists("cti_enrichment_requirements"):
            return
        self.db.execute(
            """
            INSERT INTO cti_enrichment_requirements
                (requirement_id, mission_id, asset_id, technology_key, required_evidence_json,
                 reason_code, authority_state, status, created_at)
            VALUES
                (%(requirement_id)s, %(mission_id)s, %(asset_id)s, %(technology_key)s,
                 %(required_evidence_json)s, %(reason_code)s, %(authority_state)s, 'OPEN', CURRENT_TIMESTAMP)
            """,
            {
                **requirement,
                "mission_id": mission_id,
                "required_evidence_json": to_json(requirement.get("required_evidence") or []),
            },
        )
