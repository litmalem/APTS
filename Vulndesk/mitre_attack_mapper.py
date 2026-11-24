from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


class MitreAttackMapper:
    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            return None

    @staticmethod
    def _json_text(value: Any) -> str | None:
        if value in (None, [], {}, ""):
            return None
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _get_attack_external_id(external_references: list[dict] | None) -> str | None:
        for ref in external_references or []:
            if ref.get("source_name") == "mitre-attack" and ref.get("external_id"):
                return str(ref["external_id"])
        return None

    @classmethod
    def map_attack_pattern(cls, obj: dict) -> dict:
        external_refs = obj.get("external_references") or []
        return {
            "attack_pattern": {
                "stix_id": obj.get("id"),
                "attack_id": cls._get_attack_external_id(external_refs),
                "name": obj.get("name"),
                "description_text": obj.get("description"),
                "created_at_source": cls._parse_dt(obj.get("created")),
                "modified_at_source": cls._parse_dt(obj.get("modified")),
                "is_subtechnique": bool(obj.get("x_mitre_is_subtechnique", False)),
                "platforms_json": cls._json_text(obj.get("x_mitre_platforms") or []),
                "domains_json": cls._json_text(obj.get("x_mitre_domains") or []),
                "data_sources_json": cls._json_text(obj.get("x_mitre_data_sources") or []),
                "detection_text": obj.get("x_mitre_detection"),
                "version_value": obj.get("x_mitre_version"),
                "attack_spec_version": obj.get("x_mitre_attack_spec_version"),
                "stix_spec_version": obj.get("spec_version"),
                "revoked": bool(obj.get("revoked", False)),
                "deprecated": bool(obj.get("x_mitre_deprecated", False)),
                "raw_json": cls._json_text(obj),
            },
            "external_references": [
                {
                    "parent_stix_id": obj.get("id"),
                    "parent_type": "attack-pattern",
                    "source_name": ref.get("source_name"),
                    "external_id": ref.get("external_id"),
                    "url": ref.get("url"),
                    "description_text": ref.get("description"),
                }
                for ref in external_refs
                if ref.get("source_name")
            ],
            "kill_chain_phases": [
                {
                    "parent_stix_id": obj.get("id"),
                    "kill_chain_name": phase.get("kill_chain_name"),
                    "phase_name": phase.get("phase_name"),
                }
                for phase in (obj.get("kill_chain_phases") or [])
                if phase.get("kill_chain_name") and phase.get("phase_name")
            ],
            "aliases": [],
        }

    @classmethod
    def map_malware(cls, obj: dict) -> dict:
        external_refs = obj.get("external_references") or []
        aliases = obj.get("x_mitre_aliases") or []
        if not aliases and obj.get("aliases"):
            aliases = obj.get("aliases")

        return {
            "malware": {
                "stix_id": obj.get("id"),
                "software_id": cls._get_attack_external_id(external_refs),
                "name": obj.get("name"),
                "description_text": obj.get("description"),
                "created_at_source": cls._parse_dt(obj.get("created")),
                "modified_at_source": cls._parse_dt(obj.get("modified")),
                "platforms_json": cls._json_text(obj.get("x_mitre_platforms") or []),
                "domains_json": cls._json_text(obj.get("x_mitre_domains") or []),
                "aliases_json": cls._json_text(aliases),
                "version_value": obj.get("x_mitre_version"),
                "attack_spec_version": obj.get("x_mitre_attack_spec_version"),
                "stix_spec_version": obj.get("spec_version"),
                "is_family": bool(obj.get("is_family", False)),
                "revoked": bool(obj.get("revoked", False)),
                "deprecated": bool(obj.get("x_mitre_deprecated", False)),
                "raw_json": cls._json_text(obj),
            },
            "external_references": [
                {
                    "parent_stix_id": obj.get("id"),
                    "parent_type": "malware",
                    "source_name": ref.get("source_name"),
                    "external_id": ref.get("external_id"),
                    "url": ref.get("url"),
                    "description_text": ref.get("description"),
                }
                for ref in external_refs
                if ref.get("source_name")
            ],
            "kill_chain_phases": [],
            "aliases": [
                {
                    "parent_stix_id": obj.get("id"),
                    "parent_type": "malware",
                    "alias_value": alias,
                }
                for alias in aliases
                if alias
            ],
        }

    @classmethod
    def map_intrusion_set(cls, obj: dict) -> dict:
        external_refs = obj.get("external_references") or []
        aliases = obj.get("aliases") or []
        goals = obj.get("goals") or []
        secondary_motivations = obj.get("secondary_motivations") or []

        return {
            "threat_actor": {
                "stix_id": obj.get("id"),
                "group_id": cls._get_attack_external_id(external_refs),
                "name": obj.get("name"),
                "description_text": obj.get("description"),
                "created_at_source": cls._parse_dt(obj.get("created")),
                "modified_at_source": cls._parse_dt(obj.get("modified")),
                "first_seen_source": cls._parse_dt(obj.get("first_seen")),
                "last_seen_source": cls._parse_dt(obj.get("last_seen")),
                "aliases_json": cls._json_text(aliases),
                "goals_json": cls._json_text(goals),
                "resource_level": obj.get("resource_level"),
                "primary_motivation": obj.get("primary_motivation"),
                "secondary_motivations_json": cls._json_text(secondary_motivations),
                "domains_json": cls._json_text(obj.get("x_mitre_domains") or []),
                "version_value": obj.get("x_mitre_version"),
                "attack_spec_version": obj.get("x_mitre_attack_spec_version"),
                "stix_spec_version": obj.get("spec_version"),
                "revoked": bool(obj.get("revoked", False)),
                "deprecated": bool(obj.get("x_mitre_deprecated", False)),
                "raw_json": cls._json_text(obj),
            },
            "external_references": [
                {
                    "parent_stix_id": obj.get("id"),
                    "parent_type": "intrusion-set",
                    "source_name": ref.get("source_name"),
                    "external_id": ref.get("external_id"),
                    "url": ref.get("url"),
                    "description_text": ref.get("description"),
                }
                for ref in external_refs
                if ref.get("source_name")
            ],
            "kill_chain_phases": [],
            "aliases": [
                {
                    "parent_stix_id": obj.get("id"),
                    "parent_type": "intrusion-set",
                    "alias_value": alias,
                }
                for alias in aliases
                if alias
            ],
        }

    @classmethod
    def map_relationship(cls, obj: dict) -> dict:
        return {
            "stix_id": obj.get("id"),
            "relationship_type": obj.get("relationship_type"),
            "source_ref": obj.get("source_ref"),
            "target_ref": obj.get("target_ref"),
            "source_type": (obj.get("source_ref") or "").split("--", 1)[0] or None,
            "target_type": (obj.get("target_ref") or "").split("--", 1)[0] or None,
            "description_text": obj.get("description"),
            "created_at_source": cls._parse_dt(obj.get("created")),
            "modified_at_source": cls._parse_dt(obj.get("modified")),
            "stix_spec_version": obj.get("spec_version"),
            "revoked": bool(obj.get("revoked", False)),
            "deprecated": bool(obj.get("x_mitre_deprecated", False)),
            "raw_json": cls._json_text(obj),
        }
