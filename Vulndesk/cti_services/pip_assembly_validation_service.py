from __future__ import annotations

import copy
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .audit_store import AuditStore
from .common import canonical_json, new_id, safe_json_loads, sha256_object, utcnow_iso
from .db_adapter import DbAdapter, make_json_safe, to_json
from .service_registry import ServiceRegistry


class PipAssemblyValidationService:
    """CTI-S06 deterministic PIP assembly and validation service.

    The service packages only upstream facts/inferences.  It is forbidden to
    invent CVEs/CPEs/paths/confidence/priority, and validation objectives are
    explicitly non-executable decision-support records.
    """

    SERVICE_KEY = "pip_assembly_validation_service"
    ARTIFACT_SERVICE_KEY = "pentest_intelligence_package"
    COMPONENT_ID = "CTI-S06"
    ARTIFACT_COMPONENT_ID = "CTI-D01"
    SCHEMA_VERSION = "1.0-harmonized-2026-08"
    VALIDATOR_VERSION = "pip-validator-1.0"

    SECRET_KEY_RE = re.compile(
        r"(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|bearer|authorization|credential|private[_-]?key|session[_-]?cookie|cookie)$",
        re.IGNORECASE,
    )

    def __init__(
        self,
        db: Optional[DbAdapter] = None,
        registry: Optional[ServiceRegistry] = None,
        audit: Optional[AuditStore] = None,
    ):
        self.db = db or DbAdapter()
        self.registry = registry or ServiceRegistry(self.db)
        self.audit = audit or AuditStore(self.db)

    def build(
        self,
        *,
        mission_id: str,
        mission_binding: Dict[str, Any],
        asset_profiles: List[Dict[str, Any]],
        cpe_claims: List[Dict[str, Any]],
        vulnerability_correlations: List[Dict[str, Any]],
        attack_mappings: List[Dict[str, Any]],
        attack_paths: Optional[List[Dict[str, Any]]] = None,
        threat_contexts: Optional[List[Dict[str, Any]]] = None,
        risk_priorities: Optional[List[Dict[str, Any]]] = None,
        normalized_objects: Optional[List[Dict[str, Any]]] = None,
        provenance_records: Optional[List[Dict[str, Any]]] = None,
        assumptions_and_gaps: Optional[List[Dict[str, Any]]] = None,
        policy_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.registry.is_enabled(self.SERVICE_KEY):
            return {"status": "skipped", "pip": None, "validation_results": []}

        self.registry.update_status(self.SERVICE_KEY, "running")
        try:
            pip_id = new_id("pip")
            revision = self._next_revision(mission_id)
            validation_objectives = self._validation_objectives(
                vulnerability_correlations or [],
                attack_mappings or [],
                attack_paths or [],
                risk_priorities or [],
            )
            generated_gaps = self._derive_gaps(
                cpe_claims or [], vulnerability_correlations or [], attack_mappings or [], attack_paths or [], threat_contexts or []
            )
            gaps = list(assumptions_and_gaps or []) + generated_gaps

            raw_pip = {
                "schema_version": self.SCHEMA_VERSION,
                "pip_id": pip_id,
                "revision": revision,
                "created_at": utcnow_iso(),
                "mission_binding": {
                    **(mission_binding or {}),
                    "mission_id": mission_id,
                },
                "intelligence": {
                    "normalized_objects": normalized_objects or [],
                    "provenance_records": provenance_records or [],
                    "asset_profiles": asset_profiles or [],
                    "cpe_resolution_claims": cpe_claims or [],
                    "vulnerability_correlations": vulnerability_correlations or [],
                    "attack_mappings": attack_mappings or [],
                    "attack_paths": attack_paths or [],
                    "threat_contexts": threat_contexts or [],
                    "risk_priorities": risk_priorities or [],
                },
                "validation_objectives": validation_objectives,
                "assumptions_and_gaps": gaps,
                "policy_context": policy_context or {},
                "semantics": {
                    "data_artifact": True,
                    "immutable_after_publication": True,
                    "execution_command": False,
                    "execution_authorized": False,
                    "validation_objectives_are_commands": False,
                    "reasoning_implies_authority": False,
                    "applicability_implies_exploitability": False,
                    "feasible_path_implies_executable_path": False,
                },
            }
            sanitized, redacted_paths = self._sanitize_secrets(raw_pip)
            validation_results = self.validate(sanitized, redacted_paths=redacted_paths)
            readiness = self._readiness(sanitized, validation_results)
            sanitized["quality"] = {
                "readiness": readiness,
                "hard_gate_passed": all(v["passed"] for v in validation_results),
                "validation_results": validation_results,
                "redacted_secret_paths": redacted_paths,
                "validator_version": self.VALIDATOR_VERSION,
            }
            # Hash the canonical artifact without the integrity block itself.
            integrity_hash = sha256_object(self._hash_material(sanitized))
            sanitized["integrity"] = {
                "algorithm": "SHA-256",
                "canonicalization": "JSON_SORT_KEYS_COMPACT_UTF8",
                "sha256": integrity_hash,
                "signature": None,
            }
            # Re-evaluate H4 now that integrity exists; other gates are unchanged.
            validation_results = self.validate(sanitized, redacted_paths=redacted_paths)
            readiness = self._readiness(sanitized, validation_results)
            sanitized["quality"]["readiness"] = readiness
            sanitized["quality"]["hard_gate_passed"] = all(v["passed"] for v in validation_results)
            sanitized["quality"]["validation_results"] = validation_results

            artifact = {
                "pip_id": pip_id,
                "mission_id": mission_id,
                "revision": revision,
                "schema_version": self.SCHEMA_VERSION,
                "readiness": readiness,
                "canonical_sha256": sanitized["integrity"]["sha256"],
                "artifact": sanitized,
                "validation_results": validation_results,
                "immutable": True,
                "execution_authorized": False,
            }
            self._persist(artifact)
            self.audit.append(
                mission_id=mission_id,
                component_id=self.COMPONENT_ID,
                event_type="pip.published" if readiness != "REJECTED" else "pip.rejected",
                reason_code="PIP_HARD_GATES_PASSED" if readiness != "REJECTED" else "PIP_HARD_GATE_FAILED",
                input_snapshot={
                    "asset_count": len(asset_profiles or []),
                    "correlation_count": len(vulnerability_correlations or []),
                    "mapping_count": len(attack_mappings or []),
                    "path_count": len(attack_paths or []),
                    "priority_count": len(risk_priorities or []),
                },
                candidate_alternatives=None,
                selected_output={
                    "pip_id": pip_id,
                    "revision": revision,
                    "readiness": readiness,
                    "canonical_sha256": artifact["canonical_sha256"],
                    "hard_gate_failures": [v["gate_id"] for v in validation_results if not v["passed"]],
                },
                evidence_refs=self._collect_evidence_refs(sanitized),
                versions={"schema": self.SCHEMA_VERSION, "validator": self.VALIDATOR_VERSION},
            )
            self.registry.update_status(self.SERVICE_KEY, "idle")
            return {"status": "completed", "pip": artifact, "validation_results": validation_results}
        except Exception as exc:
            self.registry.update_status(self.SERVICE_KEY, "error", str(exc))
            raise

    def validate(self, pip: Dict[str, Any], redacted_paths: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        redacted_paths = redacted_paths or []
        checks = [
            ("QG-H1", "Schema validity", self._gate_schema(pip)),
            ("QG-H2", "Referential integrity", self._gate_referential_integrity(pip)),
            ("QG-H3", "Mission/scope binding", self._gate_mission_scope(pip)),
            ("QG-H4", "Integrity/hash", self._gate_integrity(pip)),
            ("QG-H5", "Minimum provenance", self._gate_provenance(pip)),
            ("QG-H6", "Validity/freshness", self._gate_freshness(pip)),
            ("QG-H7", "No secret leakage", self._gate_secret_leakage(pip, redacted_paths)),
            ("QG-H8", "Contradiction policy", self._gate_contradictions(pip)),
            ("QG-H9", "Authorization semantics", self._gate_authorization_semantics(pip)),
            ("QG-H10", "Revocation/deprecation check", self._gate_revocation(pip)),
        ]
        return [
            {
                "gate_id": gate_id,
                "name": name,
                "passed": bool(result[0]),
                "reason": result[1],
                "details": result[2],
            }
            for gate_id, name, result in checks
        ]

    def get_pip(self, pip_id: str) -> Optional[Dict[str, Any]]:
        if not self.db.table_exists("cti_pip_artifacts"):
            return None
        row = self.db.fetch_one(
            "SELECT * FROM cti_pip_artifacts WHERE pip_id=%(pip_id)s LIMIT 1",
            {"pip_id": pip_id},
        )
        if not row:
            return None
        artifact = safe_json_loads(row.get("artifact_json"), default={})
        validation_results = self.validate(artifact, redacted_paths=(artifact.get("quality") or {}).get("redacted_secret_paths") or [])
        return {
            "pip_id": row.get("pip_id"),
            "mission_id": row.get("mission_id"),
            "revision": row.get("revision_no"),
            "schema_version": row.get("schema_version"),
            "readiness": self._readiness(artifact, validation_results),
            "published_readiness": row.get("readiness"),
            "validation_results": validation_results,
            "canonical_sha256": row.get("canonical_sha256"),
            "immutable": bool(row.get("immutable")),
            "artifact": artifact,
        }

    def _next_revision(self, mission_id: str) -> int:
        if not self.db.table_exists("cti_pip_artifacts"):
            return 1
        row = self.db.fetch_one(
            "SELECT MAX(revision_no) AS n FROM cti_pip_artifacts WHERE mission_id=%(mission_id)s",
            {"mission_id": mission_id},
        )
        return int((row or {}).get("n") or 0) + 1

    @staticmethod
    def _validation_objectives(
        correlations: List[Dict[str, Any]],
        mappings: List[Dict[str, Any]],
        paths: List[Dict[str, Any]],
        priorities: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        objectives: List[Dict[str, Any]] = []
        prioritized_corr = {str(p.get("correlation_id")): p for p in priorities if p.get("correlation_id")}
        for corr in correlations:
            status = str(corr.get("status") or "").upper()
            if status in {"NEEDS_VERIFICATION", "SEMANTIC_CANDIDATE", "PLATFORM_MATCH", "VERSION_APPLICABLE"}:
                objectives.append({
                    "objective_id": new_id("valobj"),
                    "objective_type": "VERIFY_VULNERABILITY_APPLICABILITY",
                    "target_ref": corr.get("correlation_id"),
                    "asset_id": corr.get("asset_id"),
                    "cve_id": corr.get("cve_id"),
                    "required_evidence": list(corr.get("missing_prerequisites") or ["target-side validation evidence"]),
                    "priority_band": (prioritized_corr.get(str(corr.get("correlation_id"))) or {}).get("priority_band"),
                    "execution_command": False,
                    "authorization_granted": False,
                })
        for mapping in mappings:
            if str(mapping.get("verification_state") or "").upper() == "NEEDS_EVIDENCE":
                objectives.append({
                    "objective_id": new_id("valobj"),
                    "objective_type": "VERIFY_ATTACK_MAPPING_EVIDENCE",
                    "target_ref": mapping.get("mapping_id"),
                    "required_evidence": ["additional ATT&CK mapping evidence"],
                    "execution_command": False,
                    "authorization_granted": False,
                })
        for path in paths:
            if str(path.get("feasibility_state") or "").upper() == "NEEDS_EVIDENCE":
                objectives.append({
                    "objective_id": new_id("valobj"),
                    "objective_type": "VERIFY_ATTACK_PATH_PREREQUISITES",
                    "target_ref": path.get("path_id"),
                    "required_evidence": list(path.get("preconditions") or ["path prerequisite evidence"]),
                    "execution_command": False,
                    "authorization_granted": False,
                })
        return objectives

    @staticmethod
    def _derive_gaps(
        cpe_claims: List[Dict[str, Any]],
        correlations: List[Dict[str, Any]],
        mappings: List[Dict[str, Any]],
        paths: List[Dict[str, Any]],
        contexts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        gaps: List[Dict[str, Any]] = []
        if any(str(c.get("status") or "").upper() in {"AMBIGUOUS", "UNRESOLVED"} for c in cpe_claims):
            gaps.append({"gap_code": "CPE_IDENTITY_UNCERTAINTY", "severity": "MEDIUM"})
        if any(str(c.get("status") or "").upper() == "NEEDS_VERIFICATION" for c in correlations):
            gaps.append({"gap_code": "VULNERABILITY_APPLICABILITY_NEEDS_VERIFICATION", "severity": "MEDIUM"})
        if any(str(m.get("verification_state") or "").upper() in {"PROVISIONAL", "NEEDS_EVIDENCE"} for m in mappings):
            gaps.append({"gap_code": "ATTACK_MAPPING_PROVISIONAL", "severity": "LOW"})
        if any(str(p.get("feasibility_state") or "").upper() == "NEEDS_EVIDENCE" for p in paths):
            gaps.append({"gap_code": "ATTACK_PATH_PREREQUISITES_MISSING", "severity": "MEDIUM"})
        if any(c.get("missing_evidence") for c in contexts):
            gaps.append({"gap_code": "THREAT_CONTEXT_EVIDENCE_GAPS", "severity": "LOW"})
        # deterministic de-duplication
        seen = set()
        out = []
        for gap in gaps:
            if gap["gap_code"] not in seen:
                seen.add(gap["gap_code"])
                out.append(gap)
        return out

    def _sanitize_secrets(self, value: Any, path: str = "$") -> Tuple[Any, List[str]]:
        redacted: List[str] = []
        if isinstance(value, dict):
            out: Dict[str, Any] = {}
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if self.SECRET_KEY_RE.search(str(key)) and child not in (None, "", [], {}):
                    out[key] = "[REDACTED]"
                    redacted.append(child_path)
                    continue
                clean_child, child_redacted = self._sanitize_secrets(child, child_path)
                out[key] = clean_child
                redacted.extend(child_redacted)
            return out, redacted
        if isinstance(value, list):
            out_list = []
            for idx, child in enumerate(value):
                clean_child, child_redacted = self._sanitize_secrets(child, f"{path}[{idx}]")
                out_list.append(clean_child)
                redacted.extend(child_redacted)
            return out_list, redacted
        return make_json_safe(value), redacted

    @staticmethod
    def _gate_schema(pip: Dict[str, Any]) -> Tuple[bool, str, Any]:
        required = {"schema_version", "pip_id", "revision", "created_at", "mission_binding", "intelligence", "validation_objectives", "semantics"}
        missing = sorted(required - set(pip.keys()))
        intelligence = pip.get("intelligence")
        valid = not missing and isinstance(intelligence, dict) and isinstance(pip.get("validation_objectives"), list)
        return valid, "required structure present" if valid else "missing or invalid required structure", {"missing": missing}

    @staticmethod
    def _gate_referential_integrity(pip: Dict[str, Any]) -> Tuple[bool, str, Any]:
        intel = pip.get("intelligence") or {}
        assets = {str(x.get("asset_id")) for x in intel.get("asset_profiles") or [] if x.get("asset_id")}
        correlations = {str(x.get("correlation_id")): x for x in intel.get("vulnerability_correlations") or [] if x.get("correlation_id")}
        mappings = {str(x.get("mapping_id")): x for x in intel.get("attack_mappings") or [] if x.get("mapping_id")}
        broken: List[str] = []
        for cid, corr in correlations.items():
            if corr.get("asset_id") and str(corr.get("asset_id")) not in assets:
                broken.append(f"correlation:{cid}->asset:{corr.get('asset_id')}")
        for mid, mapping in mappings.items():
            if mapping.get("correlation_id") and str(mapping.get("correlation_id")) not in correlations:
                broken.append(f"mapping:{mid}->correlation:{mapping.get('correlation_id')}")
        for path in intel.get("attack_paths") or []:
            if path.get("correlation_id") and str(path.get("correlation_id")) not in correlations:
                broken.append(f"path:{path.get('path_id')}->correlation:{path.get('correlation_id')}")
            if path.get("mapping_id") and str(path.get("mapping_id")) not in mappings:
                broken.append(f"path:{path.get('path_id')}->mapping:{path.get('mapping_id')}")
        return not broken, "all cross-object references resolve" if not broken else "broken cross-object references", {"broken": broken[:50]}

    @staticmethod
    def _gate_mission_scope(pip: Dict[str, Any]) -> Tuple[bool, str, Any]:
        binding = pip.get("mission_binding") or {}
        mission_id = binding.get("mission_id")
        has_scope = bool(binding.get("asset_scope") or binding.get("target_url") or binding.get("target_urls") or binding.get("scope"))
        valid = bool(mission_id) and has_scope and binding.get("scope_allowed", True) is not False
        return valid, "mission and scope are bound" if valid else "mission/scope binding missing or disallowed", {"mission_id": mission_id, "has_scope": has_scope, "scope_allowed": binding.get("scope_allowed", True)}

    def _gate_integrity(self, pip: Dict[str, Any]) -> Tuple[bool, str, Any]:
        integ = pip.get("integrity") or {}
        current = integ.get("sha256")
        if not current:
            # During the pre-hash validation pass this is expected.
            return True, "integrity hash pending canonical publication", {"pending": True}
        format_ok = isinstance(current, str) and len(current) == 64 and all(c in "0123456789abcdefABCDEF" for c in current)
        expected = sha256_object(self._hash_material(pip)) if format_ok else None
        valid = bool(format_ok and expected == current)
        return valid, "canonical SHA-256 verified" if valid else "canonical SHA-256 mismatch", {"sha256": current, "expected": expected}

    @staticmethod
    def _hash_material(pip: Dict[str, Any]) -> Dict[str, Any]:
        clone = copy.deepcopy(pip)
        clone.pop("integrity", None)
        # Gate results and readiness are derived from the artifact and therefore
        # excluded from the hash material to avoid a self-referential digest.
        if isinstance(clone.get("quality"), dict):
            quality = dict(clone["quality"])
            quality.pop("validation_results", None)
            quality.pop("readiness", None)
            quality.pop("hard_gate_passed", None)
            clone["quality"] = quality
        return clone

    def _gate_provenance(self, pip: Dict[str, Any]) -> Tuple[bool, str, Any]:
        intel = pip.get("intelligence") or {}
        missing: List[str] = []
        for collection, id_key in (
            ("vulnerability_correlations", "correlation_id"),
            ("attack_mappings", "mapping_id"),
            ("risk_priorities", "intention_id"),
        ):
            for item in intel.get(collection) or []:
                refs = item.get("evidence_refs") or item.get("matched_evidence") or item.get("provenance_refs") or []
                if not refs:
                    missing.append(f"{collection}:{item.get(id_key) or '?'}")
        return not missing, "critical claims have evidence/provenance references" if not missing else "critical claims missing evidence/provenance", {"missing": missing[:50]}

    @staticmethod
    def _gate_freshness(pip: Dict[str, Any]) -> Tuple[bool, str, Any]:
        intel = pip.get("intelligence") or {}
        stale: List[str] = []
        for collection in ("normalized_objects", "vulnerability_correlations", "threat_contexts"):
            for item in intel.get(collection) or []:
                state = str(item.get("freshness_status") or item.get("validity_status") or "").upper()
                if state in {"STALE", "EXPIRED", "INVALID"}:
                    stale.append(f"{collection}:{item.get('normalized_object_id') or item.get('correlation_id') or item.get('context_id') or '?'}")
        return not stale, "no explicitly stale/expired critical intelligence" if not stale else "stale or expired intelligence exists", {"stale": stale[:50]}

    def _gate_secret_leakage(self, pip: Dict[str, Any], redacted_paths: List[str]) -> Tuple[bool, str, Any]:
        leaked: List[str] = []

        def walk(value: Any, path: str = "$") -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    child_path = f"{path}.{key}"
                    if self.SECRET_KEY_RE.search(str(key)) and child not in (None, "", "[REDACTED]", [], {}):
                        leaked.append(child_path)
                    walk(child, child_path)
            elif isinstance(value, list):
                for idx, child in enumerate(value):
                    walk(child, f"{path}[{idx}]")
        walk(pip)
        passed = not leaked
        reason = "no secret values in published artifact" if passed else "secret-like values remain in artifact"
        return passed, reason, {"redacted_paths": redacted_paths, "remaining_leaks": leaked[:50]}

    @staticmethod
    def _gate_contradictions(pip: Dict[str, Any]) -> Tuple[bool, str, Any]:
        intel = pip.get("intelligence") or {}
        critical: List[str] = []
        for collection in ("cpe_resolution_claims", "vulnerability_correlations", "attack_mappings", "threat_contexts"):
            for item in intel.get(collection) or []:
                contradictions = item.get("contradictions") or item.get("contradiction_refs") or []
                for contradiction in contradictions:
                    text = str(contradiction)
                    if "CRITICAL" in text.upper() or "POLICY" in text.upper():
                        critical.append(f"{collection}:{text}")
        return not critical, "no unresolved critical contradiction" if not critical else "critical contradictions remain", {"critical": critical[:50]}

    @staticmethod
    def _gate_authorization_semantics(pip: Dict[str, Any]) -> Tuple[bool, str, Any]:
        failures: List[str] = []
        semantics = pip.get("semantics") or {}
        if semantics.get("execution_command") is not False or semantics.get("execution_authorized") is not False:
            failures.append("PIP_SEMANTICS_EXECUTION_NOT_FALSE")
        intel = pip.get("intelligence") or {}
        for collection in ("attack_paths", "risk_priorities"):
            for item in intel.get(collection) or []:
                if item.get("execution_authorized") is True:
                    failures.append(f"{collection}:{item.get('path_id') or item.get('intention_id')}:AUTHORIZED")
        for obj in pip.get("validation_objectives") or []:
            if obj.get("execution_command") is True or obj.get("authorization_granted") is True:
                failures.append(f"validation_objective:{obj.get('objective_id')}:COMMAND_OR_AUTH")
        return not failures, "recommendation/validation remains separate from authorization" if not failures else "authorization semantics violated", {"failures": failures[:50]}

    @staticmethod
    def _gate_revocation(pip: Dict[str, Any]) -> Tuple[bool, str, Any]:
        intel = pip.get("intelligence") or {}
        revoked: List[str] = []
        for collection in ("cpe_resolution_claims", "attack_mappings", "threat_contexts"):
            for item in intel.get(collection) or []:
                if item.get("revoked") is True or item.get("deprecated") is True:
                    revoked.append(f"{collection}:{item.get('resolution_id') or item.get('mapping_id') or item.get('context_id')}")
                if (
                    str(item.get("verification_state") or item.get("status") or "").upper() == "REJECTED"
                    and item.get("selected") is True
                ):
                    # Rejected alternatives may remain in the evidence history. They
                    # fail the gate only if an upstream component explicitly marked
                    # them as selected/published intelligence.
                    revoked.append(f"{collection}:rejected-selected:{item.get('resolution_id') or item.get('mapping_id') or item.get('context_id')}")
        return not revoked, "no revoked/deprecated selected intelligence" if not revoked else "revoked/deprecated/rejected selected intelligence present", {"items": revoked[:50]}

    @staticmethod
    def _readiness(pip: Dict[str, Any], validation_results: List[Dict[str, Any]]) -> str:
        if any(not r["passed"] for r in validation_results):
            return "REJECTED"
        intel = pip.get("intelligence") or {}
        priorities = intel.get("risk_priorities") or []
        correlations = intel.get("vulnerability_correlations") or []
        gaps = pip.get("assumptions_and_gaps") or []
        if priorities and not gaps:
            return "VALIDATION_READY"
        if priorities or correlations:
            return "ACTIONABLE"
        return "PARTIAL"

    @staticmethod
    def _collect_evidence_refs(pip: Dict[str, Any]) -> List[str]:
        refs: List[str] = []

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in {"evidence_refs", "matched_evidence", "provenance_refs"} and isinstance(child, list):
                        refs.extend(str(x) for x in child if x)
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(pip)
        return list(dict.fromkeys(refs))

    def _persist(self, artifact: Dict[str, Any]) -> None:
        """Persist the immutable PIP using an explicit SQL-boundary contract.

        PyMySQL eagerly escapes every value supplied in a named-parameter
        mapping, including values whose keys are not referenced by the SQL
        statement.  A broad mapping such as ``{**artifact, ...}`` therefore
        leaks nested ``dict`` / ``list[dict]`` objects (for example the PIP
        document and quality-gate results) into the driver and can raise
        ``TypeError: dict can not be used as parameter``.

        Keep the persistence boundary deliberately narrow: every structured
        field is serialized explicitly and only SQL-referenced scalar values
        are passed to the driver.  This also makes the PIP's non-executable
        authority semantics obvious at publication time.
        """
        if not self.db.table_exists("cti_pip_artifacts"):
            return

        pip_params: Dict[str, Any] = {
            "pip_id": str(artifact["pip_id"]),
            "mission_id": str(artifact["mission_id"]),
            "revision": int(artifact["revision"]),
            "schema_version": str(artifact["schema_version"]),
            "readiness": str(artifact["readiness"]),
            "canonical_sha256": str(artifact["canonical_sha256"]),
            "artifact_json": canonical_json(artifact["artifact"]),
            "validation_summary_json": to_json(artifact.get("validation_results") or []),
        }

        statements: List[tuple[str, Dict[str, Any]]] = [
            (
                """
                INSERT INTO cti_pip_artifacts
                    (pip_id, mission_id, revision_no, schema_version, readiness, canonical_sha256,
                     artifact_json, validation_summary_json, immutable, execution_authorized, created_at)
                VALUES
                    (%(pip_id)s, %(mission_id)s, %(revision)s, %(schema_version)s, %(readiness)s,
                     %(canonical_sha256)s, %(artifact_json)s, %(validation_summary_json)s, 1, 0,
                     CURRENT_TIMESTAMP)
                """,
                pip_params,
            )
        ]

        if self.db.table_exists("cti_pip_validation_results"):
            for result in artifact.get("validation_results") or []:
                validation_params: Dict[str, Any] = {
                    "validation_id": new_id("pipgate"),
                    "pip_id": str(artifact["pip_id"]),
                    "gate_id": str(result["gate_id"]),
                    "gate_name": str(result["name"]),
                    "passed": 1 if bool(result["passed"]) else 0,
                    "reason": None if result.get("reason") is None else str(result.get("reason")),
                    "details_json": to_json(result.get("details") or {}),
                    "validator_version": self.VALIDATOR_VERSION,
                }
                statements.append(
                    (
                        """
                        INSERT INTO cti_pip_validation_results
                            (validation_id, pip_id, gate_id, gate_name, passed, reason, details_json, validator_version, created_at)
                        VALUES
                            (%(validation_id)s, %(pip_id)s, %(gate_id)s, %(gate_name)s,
                             %(passed)s, %(reason)s, %(details_json)s, %(validator_version)s,
                             CURRENT_TIMESTAMP)
                        """,
                        validation_params,
                    )
                )

        self.db.execute_transaction(statements)
