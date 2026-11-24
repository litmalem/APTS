from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, Text, DateTime, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


class AttackPatternORM(Base):
    __tablename__ = "attack_patterns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stix_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    attack_id: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at_source: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    modified_at_source: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    is_subtechnique: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    platforms_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    domains_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_sources_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    detection_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    version_value: Mapped[str | None] = mapped_column(String(20), nullable=True)
    attack_spec_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stix_spec_version: Mapped[str | None] = mapped_column(String(10), nullable=True)

    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    external_references: Mapped[list["AttackExternalReferenceORM"]] = relationship(
        back_populates="attack_pattern",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    kill_chain_phases: Mapped[list["AttackKillChainPhaseORM"]] = relationship(
        back_populates="attack_pattern",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class MalwareORM(Base):
    __tablename__ = "attack_malware"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stix_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    software_id: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at_source: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    modified_at_source: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    platforms_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    domains_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    version_value: Mapped[str | None] = mapped_column(String(20), nullable=True)
    attack_spec_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stix_spec_version: Mapped[str | None] = mapped_column(String(10), nullable=True)

    is_family: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    external_references: Mapped[list["AttackExternalReferenceORM"]] = relationship(
        back_populates="malware",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    aliases: Mapped[list["AttackAliasORM"]] = relationship(
        back_populates="malware",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ThreatActorORM(Base):
    __tablename__ = "attack_threat_actors"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stix_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    group_id: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at_source: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    modified_at_source: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    first_seen_source: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_source: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    aliases_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    goals_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    primary_motivation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    secondary_motivations_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    domains_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    version_value: Mapped[str | None] = mapped_column(String(20), nullable=True)
    attack_spec_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stix_spec_version: Mapped[str | None] = mapped_column(String(10), nullable=True)

    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    external_references: Mapped[list["AttackExternalReferenceORM"]] = relationship(
        back_populates="threat_actor",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    aliases: Mapped[list["AttackAliasORM"]] = relationship(
        back_populates="threat_actor",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class AttackRelationshipORM(Base):
    __tablename__ = "attack_relationships"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stix_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    relationship_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    source_ref: Mapped[str] = mapped_column(String(80), index=True)
    target_ref: Mapped[str] = mapped_column(String(80), index=True)
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at_source: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    modified_at_source: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    stix_spec_version: Mapped[str | None] = mapped_column(String(10), nullable=True)

    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AttackExternalReferenceORM(Base):
    __tablename__ = "attack_external_references"
    __table_args__ = (
        UniqueConstraint("parent_stix_id", "parent_type", "source_name", "external_id", name="uq_attack_ext_ref"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    parent_stix_id: Mapped[str] = mapped_column(String(80), index=True)
    parent_type: Mapped[str] = mapped_column(String(30), index=True)
    source_name: Mapped[str] = mapped_column(String(150), index=True)
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    attack_pattern_id: Mapped[int | None] = mapped_column(ForeignKey("attack_patterns.id", ondelete="CASCADE"), nullable=True, index=True)
    malware_id: Mapped[int | None] = mapped_column(ForeignKey("attack_malware.id", ondelete="CASCADE"), nullable=True, index=True)
    threat_actor_id: Mapped[int | None] = mapped_column(ForeignKey("attack_threat_actors.id", ondelete="CASCADE"), nullable=True, index=True)

    attack_pattern: Mapped["AttackPatternORM | None"] = relationship(back_populates="external_references")
    malware: Mapped["MalwareORM | None"] = relationship(back_populates="external_references")
    threat_actor: Mapped["ThreatActorORM | None"] = relationship(back_populates="external_references")


class AttackKillChainPhaseORM(Base):
    __tablename__ = "attack_kill_chain_phases"
    __table_args__ = (
        UniqueConstraint("parent_stix_id", "kill_chain_name", "phase_name", name="uq_attack_kill_chain_phase"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    parent_stix_id: Mapped[str] = mapped_column(String(80), index=True)
    kill_chain_name: Mapped[str] = mapped_column(String(100), index=True)
    phase_name: Mapped[str] = mapped_column(String(100), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    attack_pattern_id: Mapped[int | None] = mapped_column(ForeignKey("attack_patterns.id", ondelete="CASCADE"), nullable=True, index=True)
    attack_pattern: Mapped["AttackPatternORM | None"] = relationship(back_populates="kill_chain_phases")


class AttackAliasORM(Base):
    __tablename__ = "attack_aliases"
    __table_args__ = (
        UniqueConstraint("parent_stix_id", "parent_type", "alias_value", name="uq_attack_alias"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    parent_stix_id: Mapped[str] = mapped_column(String(80), index=True)
    parent_type: Mapped[str] = mapped_column(String(30), index=True)
    alias_value: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    malware_id: Mapped[int | None] = mapped_column(ForeignKey("attack_malware.id", ondelete="CASCADE"), nullable=True, index=True)
    threat_actor_id: Mapped[int | None] = mapped_column(ForeignKey("attack_threat_actors.id", ondelete="CASCADE"), nullable=True, index=True)

    malware: Mapped["MalwareORM | None"] = relationship(back_populates="aliases")
    threat_actor: Mapped["ThreatActorORM | None"] = relationship(back_populates="aliases")
