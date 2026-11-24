from __future__ import annotations

import json
from sqlalchemy import select, func, desc, or_, case
from sqlalchemy.orm import selectinload

from orm_models import SyncAuditORM
from orm_models_mitre import (
    AttackPatternORM,
    MalwareORM,
    ThreatActorORM,
    AttackRelationshipORM,
    AttackExternalReferenceORM,
    AttackKillChainPhaseORM,
    AttackAliasORM,
)


class MitreAttackUpsertRepository:
    def __init__(self, session):
        self.session = session

    def _replace_attack_pattern_children(self, entity: AttackPatternORM, mapped: dict) -> None:
        entity.external_references.clear()
        entity.kill_chain_phases.clear()
        self.session.flush()

        for ref in mapped["external_references"]:
            entity.external_references.append(AttackExternalReferenceORM(**ref))

        for phase in mapped["kill_chain_phases"]:
            entity.kill_chain_phases.append(AttackKillChainPhaseORM(**phase))

    def _replace_malware_children(self, entity: MalwareORM, mapped: dict) -> None:
        entity.external_references.clear()
        entity.aliases.clear()
        self.session.flush()

        for ref in mapped["external_references"]:
            entity.external_references.append(AttackExternalReferenceORM(**ref))

        for alias in mapped["aliases"]:
            entity.aliases.append(AttackAliasORM(**alias))

    def _replace_threat_actor_children(self, entity: ThreatActorORM, mapped: dict) -> None:
        entity.external_references.clear()
        entity.aliases.clear()
        self.session.flush()

        for ref in mapped["external_references"]:
            entity.external_references.append(AttackExternalReferenceORM(**ref))

        for alias in mapped["aliases"]:
            entity.aliases.append(AttackAliasORM(**alias))

    def upsert_attack_pattern(self, mapped: dict) -> tuple[str, int]:
        payload = mapped["attack_pattern"]
        existing = self.session.execute(
            select(AttackPatternORM).where(AttackPatternORM.stix_id == payload["stix_id"])
        ).scalar_one_or_none()

        created = False
        if existing is None:
            existing = AttackPatternORM(**payload)
            self.session.add(existing)
            self.session.flush()
            created = True
        else:
            for key, value in payload.items():
                setattr(existing, key, value)

        self._replace_attack_pattern_children(existing, mapped)
        return ("inserted" if created else "updated", existing.id)

    def upsert_malware(self, mapped: dict) -> tuple[str, int]:
        payload = mapped["malware"]
        existing = self.session.execute(
            select(MalwareORM).where(MalwareORM.stix_id == payload["stix_id"])
        ).scalar_one_or_none()

        created = False
        if existing is None:
            existing = MalwareORM(**payload)
            self.session.add(existing)
            self.session.flush()
            created = True
        else:
            for key, value in payload.items():
                setattr(existing, key, value)

        self._replace_malware_children(existing, mapped)
        return ("inserted" if created else "updated", existing.id)

    def upsert_threat_actor(self, mapped: dict) -> tuple[str, int]:
        payload = mapped["threat_actor"]
        existing = self.session.execute(
            select(ThreatActorORM).where(ThreatActorORM.stix_id == payload["stix_id"])
        ).scalar_one_or_none()

        created = False
        if existing is None:
            existing = ThreatActorORM(**payload)
            self.session.add(existing)
            self.session.flush()
            created = True
        else:
            for key, value in payload.items():
                setattr(existing, key, value)

        self._replace_threat_actor_children(existing, mapped)
        return ("inserted" if created else "updated", existing.id)

    def upsert_relationship(self, mapped: dict) -> tuple[str, int]:
        existing = self.session.execute(
            select(AttackRelationshipORM).where(AttackRelationshipORM.stix_id == mapped["stix_id"])
        ).scalar_one_or_none()

        created = False
        if existing is None:
            existing = AttackRelationshipORM(**mapped)
            self.session.add(existing)
            self.session.flush()
            created = True
        else:
            for key, value in mapped.items():
                setattr(existing, key, value)

        return ("inserted" if created else "updated", existing.id)


class MitreAttackRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _json_list(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            data = json.loads(value)
            return [str(x) for x in data if x not in (None, "")]
        except Exception:
            return []

    @classmethod
    def _short_join(cls, value: str | None, limit: int = 3) -> str:
        items = cls._json_list(value)
        if not items:
            return ""
        if len(items) <= limit:
            return ", ".join(items)
        return ", ".join(items[:limit]) + f" (+{len(items) - limit})"

    def list_attack_patterns(self, keyword: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        malware_count_sq = (
            select(
                AttackRelationshipORM.target_ref.label("stix_id"),
                func.count(AttackRelationshipORM.id).label("malware_count"),
            )
            .where(
                AttackRelationshipORM.relationship_type == "uses",
                AttackRelationshipORM.source_type == "malware",
                AttackRelationshipORM.target_type == "attack-pattern",
            )
            .group_by(AttackRelationshipORM.target_ref)
            .subquery()
        )

        actor_count_sq = (
            select(
                AttackRelationshipORM.target_ref.label("stix_id"),
                func.count(AttackRelationshipORM.id).label("actor_count"),
            )
            .where(
                AttackRelationshipORM.relationship_type == "uses",
                AttackRelationshipORM.source_type == "intrusion-set",
                AttackRelationshipORM.target_type == "attack-pattern",
            )
            .group_by(AttackRelationshipORM.target_ref)
            .subquery()
        )

        malware_count_col = func.coalesce(malware_count_sq.c.malware_count, 0).label("malware_count")
        actor_count_col = func.coalesce(actor_count_sq.c.actor_count, 0).label("actor_count")

        stmt = (
            select(
                AttackPatternORM.id,
                AttackPatternORM.stix_id,
                AttackPatternORM.attack_id,
                AttackPatternORM.name,
                AttackPatternORM.is_subtechnique,
                AttackPatternORM.platforms_json,
                AttackPatternORM.domains_json,
                AttackPatternORM.modified_at_source,
                AttackPatternORM.revoked,
                AttackPatternORM.deprecated,
                malware_count_col,
                actor_count_col,
            )
            .select_from(AttackPatternORM)
            .outerjoin(malware_count_sq, malware_count_sq.c.stix_id == AttackPatternORM.stix_id)
            .outerjoin(actor_count_sq, actor_count_sq.c.stix_id == AttackPatternORM.stix_id)
            .where(AttackPatternORM.revoked.is_(False), AttackPatternORM.deprecated.is_(False))
        )

        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    AttackPatternORM.attack_id.ilike(like),
                    AttackPatternORM.name.ilike(like),
                    AttackPatternORM.description_text.ilike(like),
                )
            )

        stmt = stmt.order_by(desc(AttackPatternORM.modified_at_source), AttackPatternORM.attack_id, AttackPatternORM.name)
        stmt = stmt.limit(limit).offset(offset)
        rows = self.session.execute(stmt).all()
        return [
            {
                "id": row[0],
                "stix_id": row[1],
                "attack_id": row[2],
                "name": row[3],
                "is_subtechnique": bool(row[4]),
                "platforms_text": self._short_join(row[5]),
                "domains_text": self._short_join(row[6]),
                "modified_at_source": row[7],
                "revoked": bool(row[8]),
                "deprecated": bool(row[9]),
                "malware_count": int(row[10]),
                "actor_count": int(row[11]),
            }
            for row in rows
        ]

    def count_attack_patterns(self, keyword: str | None = None) -> int:
        stmt = select(func.count(AttackPatternORM.id)).where(
            AttackPatternORM.revoked.is_(False),
            AttackPatternORM.deprecated.is_(False),
        )
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    AttackPatternORM.attack_id.ilike(like),
                    AttackPatternORM.name.ilike(like),
                    AttackPatternORM.description_text.ilike(like),
                )
            )
        return int(self.session.execute(stmt).scalar_one())

    def list_malware(self, keyword: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        technique_count_sq = (
            select(
                AttackRelationshipORM.source_ref.label("stix_id"),
                func.count(AttackRelationshipORM.id).label("technique_count"),
            )
            .where(
                AttackRelationshipORM.relationship_type == "uses",
                AttackRelationshipORM.source_type == "malware",
                AttackRelationshipORM.target_type == "attack-pattern",
            )
            .group_by(AttackRelationshipORM.source_ref)
            .subquery()
        )

        actor_count_sq = (
            select(
                AttackRelationshipORM.target_ref.label("stix_id"),
                func.count(AttackRelationshipORM.id).label("actor_count"),
            )
            .where(
                AttackRelationshipORM.relationship_type == "uses",
                AttackRelationshipORM.source_type == "intrusion-set",
                AttackRelationshipORM.target_type == "malware",
            )
            .group_by(AttackRelationshipORM.target_ref)
            .subquery()
        )

        technique_count_col = func.coalesce(technique_count_sq.c.technique_count, 0).label("technique_count")
        actor_count_col = func.coalesce(actor_count_sq.c.actor_count, 0).label("actor_count")

        stmt = (
            select(
                MalwareORM.id,
                MalwareORM.stix_id,
                MalwareORM.software_id,
                MalwareORM.name,
                MalwareORM.is_family,
                MalwareORM.platforms_json,
                MalwareORM.domains_json,
                MalwareORM.modified_at_source,
                MalwareORM.revoked,
                MalwareORM.deprecated,
                technique_count_col,
                actor_count_col,
            )
            .select_from(MalwareORM)
            .outerjoin(technique_count_sq, technique_count_sq.c.stix_id == MalwareORM.stix_id)
            .outerjoin(actor_count_sq, actor_count_sq.c.stix_id == MalwareORM.stix_id)
            .where(MalwareORM.revoked.is_(False), MalwareORM.deprecated.is_(False))
        )

        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    MalwareORM.software_id.ilike(like),
                    MalwareORM.name.ilike(like),
                    MalwareORM.description_text.ilike(like),
                    MalwareORM.aliases_json.ilike(like),
                )
            )

        stmt = stmt.order_by(desc(MalwareORM.modified_at_source), MalwareORM.software_id, MalwareORM.name)
        stmt = stmt.limit(limit).offset(offset)
        rows = self.session.execute(stmt).all()
        return [
            {
                "id": row[0],
                "stix_id": row[1],
                "software_id": row[2],
                "name": row[3],
                "is_family": bool(row[4]),
                "platforms_text": self._short_join(row[5]),
                "domains_text": self._short_join(row[6]),
                "modified_at_source": row[7],
                "revoked": bool(row[8]),
                "deprecated": bool(row[9]),
                "technique_count": int(row[10]),
                "actor_count": int(row[11]),
            }
            for row in rows
        ]

    def count_malware(self, keyword: str | None = None) -> int:
        stmt = select(func.count(MalwareORM.id)).where(
            MalwareORM.revoked.is_(False),
            MalwareORM.deprecated.is_(False),
        )
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    MalwareORM.software_id.ilike(like),
                    MalwareORM.name.ilike(like),
                    MalwareORM.description_text.ilike(like),
                    MalwareORM.aliases_json.ilike(like),
                )
            )
        return int(self.session.execute(stmt).scalar_one())

    def list_threat_actors(self, keyword: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        technique_count_sq = (
            select(
                AttackRelationshipORM.source_ref.label("stix_id"),
                func.sum(case((AttackRelationshipORM.target_type == "attack-pattern", 1), else_=0)).label("technique_count"),
                func.sum(case((AttackRelationshipORM.target_type == "malware", 1), else_=0)).label("malware_count"),
            )
            .where(
                AttackRelationshipORM.relationship_type == "uses",
                AttackRelationshipORM.source_type == "intrusion-set",
                AttackRelationshipORM.target_type.in_(["attack-pattern", "malware"]),
            )
            .group_by(AttackRelationshipORM.source_ref)
            .subquery()
        )

        technique_count_col = func.coalesce(technique_count_sq.c.technique_count, 0).label("technique_count")
        malware_count_col = func.coalesce(technique_count_sq.c.malware_count, 0).label("malware_count")

        stmt = (
            select(
                ThreatActorORM.id,
                ThreatActorORM.stix_id,
                ThreatActorORM.group_id,
                ThreatActorORM.name,
                ThreatActorORM.aliases_json,
                ThreatActorORM.primary_motivation,
                ThreatActorORM.modified_at_source,
                ThreatActorORM.revoked,
                ThreatActorORM.deprecated,
                technique_count_col,
                malware_count_col,
            )
            .select_from(ThreatActorORM)
            .outerjoin(technique_count_sq, technique_count_sq.c.stix_id == ThreatActorORM.stix_id)
            .where(ThreatActorORM.revoked.is_(False), ThreatActorORM.deprecated.is_(False))
        )

        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    ThreatActorORM.group_id.ilike(like),
                    ThreatActorORM.name.ilike(like),
                    ThreatActorORM.description_text.ilike(like),
                    ThreatActorORM.aliases_json.ilike(like),
                    ThreatActorORM.primary_motivation.ilike(like),
                )
            )

        stmt = stmt.order_by(desc(ThreatActorORM.modified_at_source), ThreatActorORM.group_id, ThreatActorORM.name)
        stmt = stmt.limit(limit).offset(offset)
        rows = self.session.execute(stmt).all()
        return [
            {
                "id": row[0],
                "stix_id": row[1],
                "group_id": row[2],
                "name": row[3],
                "aliases_text": self._short_join(row[4]),
                "primary_motivation": row[5] or "",
                "modified_at_source": row[6],
                "revoked": bool(row[7]),
                "deprecated": bool(row[8]),
                "technique_count": int(row[9]),
                "malware_count": int(row[10]),
            }
            for row in rows
        ]

    def count_threat_actors(self, keyword: str | None = None) -> int:
        stmt = select(func.count(ThreatActorORM.id)).where(
            ThreatActorORM.revoked.is_(False),
            ThreatActorORM.deprecated.is_(False),
        )
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    ThreatActorORM.group_id.ilike(like),
                    ThreatActorORM.name.ilike(like),
                    ThreatActorORM.description_text.ilike(like),
                    ThreatActorORM.aliases_json.ilike(like),
                    ThreatActorORM.primary_motivation.ilike(like),
                )
            )
        return int(self.session.execute(stmt).scalar_one())

    def get_attack_pattern_detail(self, stix_id: str) -> dict | None:
        stmt = (
            select(AttackPatternORM)
            .options(
                selectinload(AttackPatternORM.external_references),
                selectinload(AttackPatternORM.kill_chain_phases),
            )
            .where(AttackPatternORM.stix_id == stix_id)
        )
        row = self.session.execute(stmt).scalar_one_or_none()
        if row is None:
            return None

        malware_uses_stmt = (
            select(AttackRelationshipORM, MalwareORM)
            .join(MalwareORM, MalwareORM.stix_id == AttackRelationshipORM.source_ref)
            .where(
                AttackRelationshipORM.relationship_type == "uses",
                AttackRelationshipORM.target_ref == stix_id,
                AttackRelationshipORM.source_type == "malware",
                AttackRelationshipORM.target_type == "attack-pattern",
            )
            .order_by(MalwareORM.software_id, MalwareORM.name)
        )
        malware_rows = self.session.execute(malware_uses_stmt).all()

        actor_uses_stmt = (
            select(AttackRelationshipORM, ThreatActorORM)
            .join(ThreatActorORM, ThreatActorORM.stix_id == AttackRelationshipORM.source_ref)
            .where(
                AttackRelationshipORM.relationship_type == "uses",
                AttackRelationshipORM.target_ref == stix_id,
                AttackRelationshipORM.source_type == "intrusion-set",
                AttackRelationshipORM.target_type == "attack-pattern",
            )
            .order_by(ThreatActorORM.group_id, ThreatActorORM.name)
        )
        actor_rows = self.session.execute(actor_uses_stmt).all()

        return {
            "entity_type": "attack-pattern",
            "stix_id": row.stix_id,
            "attack_id": row.attack_id,
            "name": row.name,
            "description_text": row.description_text,
            "created_at_source": row.created_at_source,
            "modified_at_source": row.modified_at_source,
            "is_subtechnique": row.is_subtechnique,
            "platforms": self._json_list(row.platforms_json),
            "domains": self._json_list(row.domains_json),
            "data_sources": self._json_list(row.data_sources_json),
            "version_value": row.version_value,
            "attack_spec_version": row.attack_spec_version,
            "stix_spec_version": row.stix_spec_version,
            "revoked": row.revoked,
            "deprecated": row.deprecated,
            "detection_text": row.detection_text,
            "kill_chain_phases": [
                {"kill_chain_name": x.kill_chain_name, "phase_name": x.phase_name}
                for x in row.kill_chain_phases
            ],
            "references": [
                {
                    "source_name": x.source_name,
                    "external_id": x.external_id,
                    "url": x.url,
                    "description_text": x.description_text,
                }
                for x in row.external_references
            ],
            "used_by_malware": [
                {
                    "software_id": mal.software_id,
                    "malware_name": mal.name,
                    "relationship_type": rel.relationship_type,
                    "malware_stix_id": mal.stix_id,
                }
                for rel, mal in malware_rows
            ],
            "used_by_threat_actors": [
                {
                    "group_id": actor.group_id,
                    "actor_name": actor.name,
                    "relationship_type": rel.relationship_type,
                    "actor_stix_id": actor.stix_id,
                }
                for rel, actor in actor_rows
            ],
            "raw_json": row.raw_json,
        }

    def get_malware_detail(self, stix_id: str) -> dict | None:
        stmt = (
            select(MalwareORM)
            .options(
                selectinload(MalwareORM.external_references),
                selectinload(MalwareORM.aliases),
            )
            .where(MalwareORM.stix_id == stix_id)
        )
        row = self.session.execute(stmt).scalar_one_or_none()
        if row is None:
            return None

        technique_stmt = (
            select(AttackRelationshipORM, AttackPatternORM)
            .join(AttackPatternORM, AttackPatternORM.stix_id == AttackRelationshipORM.target_ref)
            .where(
                AttackRelationshipORM.relationship_type == "uses",
                AttackRelationshipORM.source_ref == stix_id,
                AttackRelationshipORM.source_type == "malware",
                AttackRelationshipORM.target_type == "attack-pattern",
            )
            .order_by(AttackPatternORM.attack_id, AttackPatternORM.name)
        )
        technique_rows = self.session.execute(technique_stmt).all()

        actor_stmt = (
            select(AttackRelationshipORM, ThreatActorORM)
            .join(ThreatActorORM, ThreatActorORM.stix_id == AttackRelationshipORM.source_ref)
            .where(
                AttackRelationshipORM.relationship_type == "uses",
                AttackRelationshipORM.target_ref == stix_id,
                AttackRelationshipORM.source_type == "intrusion-set",
                AttackRelationshipORM.target_type == "malware",
            )
            .order_by(ThreatActorORM.group_id, ThreatActorORM.name)
        )
        actor_rows = self.session.execute(actor_stmt).all()

        return {
            "entity_type": "malware",
            "stix_id": row.stix_id,
            "software_id": row.software_id,
            "name": row.name,
            "description_text": row.description_text,
            "created_at_source": row.created_at_source,
            "modified_at_source": row.modified_at_source,
            "is_family": row.is_family,
            "platforms": self._json_list(row.platforms_json),
            "domains": self._json_list(row.domains_json),
            "aliases": [x.alias_value for x in row.aliases],
            "version_value": row.version_value,
            "attack_spec_version": row.attack_spec_version,
            "stix_spec_version": row.stix_spec_version,
            "revoked": row.revoked,
            "deprecated": row.deprecated,
            "references": [
                {
                    "source_name": x.source_name,
                    "external_id": x.external_id,
                    "url": x.url,
                    "description_text": x.description_text,
                }
                for x in row.external_references
            ],
            "uses_techniques": [
                {
                    "attack_id": tech.attack_id,
                    "technique_name": tech.name,
                    "relationship_type": rel.relationship_type,
                    "attack_pattern_stix_id": tech.stix_id,
                }
                for rel, tech in technique_rows
            ],
            "used_by_threat_actors": [
                {
                    "group_id": actor.group_id,
                    "actor_name": actor.name,
                    "relationship_type": rel.relationship_type,
                    "actor_stix_id": actor.stix_id,
                }
                for rel, actor in actor_rows
            ],
            "raw_json": row.raw_json,
        }

    def get_threat_actor_detail(self, stix_id: str) -> dict | None:
        stmt = (
            select(ThreatActorORM)
            .options(
                selectinload(ThreatActorORM.external_references),
                selectinload(ThreatActorORM.aliases),
            )
            .where(ThreatActorORM.stix_id == stix_id)
        )
        row = self.session.execute(stmt).scalar_one_or_none()
        if row is None:
            return None

        technique_stmt = (
            select(AttackRelationshipORM, AttackPatternORM)
            .join(AttackPatternORM, AttackPatternORM.stix_id == AttackRelationshipORM.target_ref)
            .where(
                AttackRelationshipORM.relationship_type == "uses",
                AttackRelationshipORM.source_ref == stix_id,
                AttackRelationshipORM.source_type == "intrusion-set",
                AttackRelationshipORM.target_type == "attack-pattern",
            )
            .order_by(AttackPatternORM.attack_id, AttackPatternORM.name)
        )
        technique_rows = self.session.execute(technique_stmt).all()

        malware_stmt = (
            select(AttackRelationshipORM, MalwareORM)
            .join(MalwareORM, MalwareORM.stix_id == AttackRelationshipORM.target_ref)
            .where(
                AttackRelationshipORM.relationship_type == "uses",
                AttackRelationshipORM.source_ref == stix_id,
                AttackRelationshipORM.source_type == "intrusion-set",
                AttackRelationshipORM.target_type == "malware",
            )
            .order_by(MalwareORM.software_id, MalwareORM.name)
        )
        malware_rows = self.session.execute(malware_stmt).all()

        return {
            "entity_type": "intrusion-set",
            "stix_id": row.stix_id,
            "group_id": row.group_id,
            "name": row.name,
            "description_text": row.description_text,
            "created_at_source": row.created_at_source,
            "modified_at_source": row.modified_at_source,
            "first_seen_source": row.first_seen_source,
            "last_seen_source": row.last_seen_source,
            "aliases": [x.alias_value for x in row.aliases],
            "goals": self._json_list(row.goals_json),
            "resource_level": row.resource_level,
            "primary_motivation": row.primary_motivation,
            "secondary_motivations": self._json_list(row.secondary_motivations_json),
            "domains": self._json_list(row.domains_json),
            "version_value": row.version_value,
            "attack_spec_version": row.attack_spec_version,
            "stix_spec_version": row.stix_spec_version,
            "revoked": row.revoked,
            "deprecated": row.deprecated,
            "references": [
                {
                    "source_name": x.source_name,
                    "external_id": x.external_id,
                    "url": x.url,
                    "description_text": x.description_text,
                }
                for x in row.external_references
            ],
            "uses_techniques": [
                {
                    "attack_id": tech.attack_id,
                    "technique_name": tech.name,
                    "relationship_type": rel.relationship_type,
                    "attack_pattern_stix_id": tech.stix_id,
                }
                for rel, tech in technique_rows
            ],
            "uses_malware": [
                {
                    "software_id": mal.software_id,
                    "malware_name": mal.name,
                    "relationship_type": rel.relationship_type,
                    "malware_stix_id": mal.stix_id,
                }
                for rel, mal in malware_rows
            ],
            "raw_json": row.raw_json,
        }


class MitreSyncAuditRepository:
    def __init__(self, session):
        self.session = session

    def create_running(self, sync_type: str, page_size: int | None = None) -> SyncAuditORM:
        row = SyncAuditORM(
            sync_type=sync_type,
            started_at=func.now(),
            status_value="RUNNING",
            page_size=page_size,
            total_fetched=0,
            total_inserted=0,
            total_updated=0,
            total_failed=0,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def mark_success(
        self,
        audit: SyncAuditORM,
        total_fetched: int,
        total_inserted: int,
        total_updated: int,
        total_failed: int,
        last_successful_modified_at=None,
    ) -> None:
        audit.finished_at = func.now()
        audit.status_value = "SUCCESS"
        audit.total_fetched = total_fetched
        audit.total_inserted = total_inserted
        audit.total_updated = total_updated
        audit.total_failed = total_failed
        audit.last_successful_modified_at = last_successful_modified_at

    def mark_failed(
        self,
        audit: SyncAuditORM,
        error_message: str,
        total_fetched: int,
        total_inserted: int,
        total_updated: int,
        total_failed: int,
    ) -> None:
        audit.finished_at = func.now()
        audit.status_value = "FAILED"
        audit.total_fetched = total_fetched
        audit.total_inserted = total_inserted
        audit.total_updated = total_updated
        audit.total_failed = total_failed
        audit.error_message = error_message

    def get_latest_successful_mitre_time(self):
        stmt = (
            select(SyncAuditORM)
            .where(
                SyncAuditORM.status_value == "SUCCESS",
                SyncAuditORM.sync_type.in_(["MITRE_FULL", "MITRE_INCREMENTAL"]),
            )
            .order_by(desc(SyncAuditORM.last_successful_modified_at), desc(SyncAuditORM.id))
            .limit(1)
        )
        row = self.session.execute(stmt).scalar_one_or_none()
        return row.last_successful_modified_at if row else None
