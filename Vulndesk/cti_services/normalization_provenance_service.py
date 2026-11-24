from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from .audit_store import AuditStore
from .common import canonical_json, new_id, sha256_object, utcnow_iso
from .db_adapter import DbAdapter, to_json
from .service_registry import ServiceRegistry


class NormalizationProvenanceService:
    SERVICE_KEY = "normalization_provenance_service"
    COMPONENT_ID = "CTI-S01"
    SCHEMA_VERSION = "cti-normalized-1.0"
    PARSER_VERSION = "generic-json-parser-1.0"
    RULE_VERSION = "normalization-rules-1.0"

    def __init__(self, db: Optional[DbAdapter] = None, registry: Optional[ServiceRegistry] = None, audit: Optional[AuditStore] = None):
        self.db = db or DbAdapter()
        self.registry = registry or ServiceRegistry(self.db)
        self.audit = audit or AuditStore(self.db)

    def normalize_envelope(self, envelope: Dict[str, Any], task_id: Optional[str] = None) -> Dict[str, Any]:
        if not self.registry.is_enabled(self.SERVICE_KEY):
            return {"status": "skipped", "reason": "component_disabled"}
        self.registry.update_status(self.SERVICE_KEY, "running")
        try:
            errors = self._validate_envelope(envelope)
            artifact_id = str(envelope.get("artifact_id") or new_id("artifact"))
            raw_hash = envelope.get("content_hash") or envelope.get("raw_hash")
            payload = envelope.get("raw_payload")
            if payload is None:
                payload = envelope.get("payload")
            if raw_hash is None and payload is not None:
                raw_hash = sha256_object(payload)

            provenance = self._build_provenance(envelope, artifact_id, raw_hash, task_id)
            pcs, missing_provenance = self._provenance_completeness(provenance)
            errors.extend(missing_provenance)

            if payload is None:
                status = "quarantined"
                canonical = None
                schema_validity = 0.0
                errors.append("PAYLOAD_NOT_AVAILABLE_INLINE_OR_RESOLVED")
            else:
                canonical = self._canonicalize(payload)
                schema_validity = 1.0 if isinstance(canonical, (dict, list)) else 0.7
                hard_failure = raw_hash in (None, "") or not provenance.get("source", {}).get("source_id")
                status = "quarantined" if hard_failure else ("verified" if not errors and pcs >= 0.85 else "provisional")

            normalized_id = new_id("ncti")
            object_hash = sha256_object(canonical) if canonical is not None else None
            quality = {
                "schema_validity": schema_validity,
                "provenance_completeness": round(pcs, 4),
                "identity_confidence": 1.0 if isinstance(canonical, dict) and any(k in canonical for k in ("id", "cve_id", "stix_id", "name")) else 0.6,
                "consistency": 1.0,
                "information_preservation": 1.0 if payload is not None else 0.0,
            }
            trace = {
                "task_id": task_id,
                "artifact_id": artifact_id,
                "stages": [
                    "EVIDENCE_INTAKE_INTEGRITY_GATE",
                    "SCHEMA_FORMAT_DETECTION",
                    "CANONICALIZATION",
                    "PROVENANCE_BUILD",
                    "QUALITY_GATE",
                ],
                "reason_codes": errors or ["NORMALIZATION_VERIFIED"],
                "parser_version": self.PARSER_VERSION,
                "rule_version": self.RULE_VERSION,
                "evaluated_at": utcnow_iso(),
            }
            out = {
                "normalized_object": canonical,
                "normalized_object_id": normalized_id,
                "version": 1,
                "canonical_schema_version": self.SCHEMA_VERSION,
                "object_hash": object_hash,
                "provenance_record": provenance,
                "quality_metrics": quality,
                "status": status,
                "decision_trace": trace,
                "exception_list": errors,
                "downstream_hints": self._downstream_hints(canonical),
            }
            self._persist(out, envelope, artifact_id, raw_hash)
            self.audit.append(
                mission_id=envelope.get("mission_id"), component_id=self.COMPONENT_ID,
                event_type="normalization.completed", reason_code=(errors[0] if errors else "NORMALIZATION_VERIFIED"),
                input_snapshot={"artifact_id": artifact_id, "source_id": envelope.get("source_id")},
                selected_output={"normalized_object_id": normalized_id, "status": status, "quality_metrics": quality},
                evidence_refs=[artifact_id],
                versions={"schema": self.SCHEMA_VERSION, "parser": self.PARSER_VERSION, "rules": self.RULE_VERSION},
                trace_id=normalized_id,
            )
            self.registry.update_status(self.SERVICE_KEY, "idle")
            return out
        except Exception as exc:
            self.registry.update_status(self.SERVICE_KEY, "error", str(exc))
            raise

    def normalize_many(self, envelopes: List[Dict[str, Any]], task_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return [self.normalize_envelope(e, task_id=task_id) for e in envelopes or []]

    @staticmethod
    def _validate_envelope(envelope: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        for field in ("source_id", "retrieved_at_utc"):
            if not envelope.get(field):
                errors.append(f"MISSING_{field.upper()}")
        if not (envelope.get("content_hash") or envelope.get("raw_hash") or envelope.get("raw_payload") is not None or envelope.get("payload") is not None):
            errors.append("MISSING_RAW_HASH_AND_PAYLOAD")
        return errors

    def _build_provenance(self, envelope: Dict[str, Any], artifact_id: str, raw_hash: Optional[str], task_id: Optional[str]) -> Dict[str, Any]:
        activity_id = new_id("provact")
        return {
            "source": {
                "source_id": envelope.get("source_id"),
                "source_type": envelope.get("protocol") or "unknown",
                "source_uri_or_name": envelope.get("endpoint_ref"),
                "trust_profile": envelope.get("trust_tier"),
            },
            "raw_artifact": {
                "artifact_id": artifact_id,
                "raw_hash": raw_hash,
                "retrieval_time": envelope.get("retrieved_at_utc"),
                "publication_time": envelope.get("source_published_at"),
                "mime_or_schema_hint": envelope.get("content_type"),
                "immutable_storage_reference": envelope.get("raw_payload_ref"),
            },
            "transformation_activity": {
                "activity_id": activity_id,
                "task_id": task_id,
                "parser_version": self.PARSER_VERSION,
                "mapping_rule_set": self.RULE_VERSION,
                "performed_at": utcnow_iso(),
            },
            "attribution": {
                "component_id": self.COMPONENT_ID,
                "service_key": self.SERVICE_KEY,
                "software_version": "harmonized-baseline-1.0",
            },
            "relations": ["wasDerivedFrom", "wasGeneratedBy", "used", "wasAttributedTo"],
        }

    @staticmethod
    def _provenance_completeness(provenance: Dict[str, Any]) -> Tuple[float, List[str]]:
        checks = [
            ("SOURCE_ID", provenance.get("source", {}).get("source_id"), 2.0),
            ("RAW_ARTIFACT_ID", provenance.get("raw_artifact", {}).get("artifact_id"), 1.0),
            ("RAW_HASH", provenance.get("raw_artifact", {}).get("raw_hash"), 2.0),
            ("RETRIEVAL_TIME", provenance.get("raw_artifact", {}).get("retrieval_time"), 1.0),
            ("TRANSFORMATION_ACTIVITY", provenance.get("transformation_activity", {}).get("activity_id"), 1.5),
            ("PARSER_VERSION", provenance.get("transformation_activity", {}).get("parser_version"), 1.0),
            ("RULE_VERSION", provenance.get("transformation_activity", {}).get("mapping_rule_set"), 1.0),
            ("COMPONENT_ATTRIBUTION", provenance.get("attribution", {}).get("component_id"), 0.5),
        ]
        total = sum(w for _, _, w in checks)
        present = sum(w for _, v, w in checks if v not in (None, ""))
        missing = [f"PROVENANCE_{name}_MISSING" for name, v, _ in checks if v in (None, "")]
        return (present / total if total else 0.0), missing

    def _canonicalize(self, value: Any) -> Any:
        if isinstance(value, dict):
            out: Dict[str, Any] = {}
            for key in sorted(value.keys(), key=lambda k: str(k).lower()):
                canonical_key = str(key).strip().lower().replace("-", "_").replace(" ", "_")
                out[canonical_key] = self._canonicalize(value[key])
            return out
        if isinstance(value, list):
            return [self._canonicalize(v) for v in value]
        if isinstance(value, str):
            return value.strip()
        return value

    @staticmethod
    def _downstream_hints(canonical: Any) -> Dict[str, Any]:
        if not isinstance(canonical, dict):
            return {"entity_type": "generic"}
        keys = set(canonical)
        if "cve_id" in keys or "cve" in keys:
            entity_type = "vulnerability"
        elif "stix_id" in keys or "attack_id" in keys:
            entity_type = "attack_object"
        elif "vendor" in keys or "product" in keys or "cpe23_uri" in keys:
            entity_type = "asset_technology"
        else:
            entity_type = "generic"
        return {"entity_type": entity_type, "candidate_domains": [entity_type]}

    def _persist(self, out: Dict[str, Any], envelope: Dict[str, Any], artifact_id: str, raw_hash: Optional[str]) -> None:
        if not self.db.table_exists("cti_normalized_objects"):
            return
        self.db.execute(
            """
            INSERT INTO cti_normalized_objects
                (normalized_object_id, mission_id, artifact_id, object_type, canonical_id,
                 schema_version, object_version, canonical_json, object_hash, confidence,
                 provenance_completeness, quality_status, quality_metrics_json,
                 decision_trace_json, exception_list_json, valid_from, valid_until, created_at)
            VALUES
                (%(id)s, %(mission_id)s, %(artifact_id)s, %(object_type)s, %(canonical_id)s,
                 %(schema_version)s, 1, %(canonical_json)s, %(object_hash)s, %(confidence)s,
                 %(pcs)s, %(status)s, %(quality)s, %(trace)s, %(exceptions)s,
                 CURRENT_TIMESTAMP, NULL, CURRENT_TIMESTAMP)
            """,
            {
                "id": out["normalized_object_id"],
                "mission_id": envelope.get("mission_id"),
                "artifact_id": artifact_id,
                "object_type": out.get("downstream_hints", {}).get("entity_type"),
                "canonical_id": self._canonical_id(out.get("normalized_object")),
                "schema_version": out["canonical_schema_version"],
                "canonical_json": to_json(out.get("normalized_object")),
                "object_hash": out.get("object_hash"),
                "confidence": out.get("quality_metrics", {}).get("identity_confidence"),
                "pcs": out.get("quality_metrics", {}).get("provenance_completeness"),
                "status": out.get("status"),
                "quality": to_json(out.get("quality_metrics")),
                "trace": to_json(out.get("decision_trace")),
                "exceptions": to_json(out.get("exception_list")),
            },
        )
        if self.db.table_exists("cti_provenance_records"):
            prov_id = new_id("prov")
            self.db.execute(
                """
                INSERT INTO cti_provenance_records
                    (provenance_id, mission_id, normalized_object_id, source_id, artifact_id,
                     raw_hash, activity_id, parser_version, rule_version, provenance_json,
                     completeness_score, created_at)
                VALUES
                    (%(provenance_id)s, %(mission_id)s, %(normalized_object_id)s, %(source_id)s,
                     %(artifact_id)s, %(raw_hash)s, %(activity_id)s, %(parser_version)s,
                     %(rule_version)s, %(provenance_json)s, %(completeness_score)s, CURRENT_TIMESTAMP)
                """,
                {
                    "provenance_id": prov_id,
                    "mission_id": envelope.get("mission_id"),
                    "normalized_object_id": out["normalized_object_id"],
                    "source_id": envelope.get("source_id"),
                    "artifact_id": artifact_id,
                    "raw_hash": raw_hash,
                    "activity_id": out["provenance_record"]["transformation_activity"]["activity_id"],
                    "parser_version": self.PARSER_VERSION,
                    "rule_version": self.RULE_VERSION,
                    "provenance_json": to_json(out["provenance_record"]),
                    "completeness_score": out["quality_metrics"]["provenance_completeness"],
                },
            )

    @staticmethod
    def _canonical_id(value: Any) -> Optional[str]:
        if not isinstance(value, dict):
            return None
        for key in ("id", "cve_id", "stix_id", "attack_id", "name"):
            if value.get(key):
                return str(value[key])
        return None
