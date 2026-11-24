from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    String,
    Text,
    DateTime,
    Boolean,
    DECIMAL,
    ForeignKey,
    UniqueConstraint,
    BigInteger,
    Integer,
    LargeBinary,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.mysql import LONGTEXT, LONGBLOB, BIGINT as MYSQL_BIGINT

from db import Base


# MariaDB requires foreign-key columns to match the referenced column type
# exactly, including BIGINT width and UNSIGNED. SQLite still needs INTEGER for
# reliable autoincrement behavior in tests/development.
MYSQL_COMPAT_ID = Integer().with_variant(MYSQL_BIGINT(unsigned=True), "mysql")


class VulnerabilityORM(Base):
    __tablename__ = "vulnerabilities"

    id: Mapped[int] = mapped_column(MYSQL_COMPAT_ID, primary_key=True, autoincrement=True)
    cve_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    description_text: Mapped[str | None] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql"), nullable=True
    )
    source_name: Mapped[str | None] = mapped_column(String(100), nullable=True, default="NVD")
    vuln_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    nvd_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    has_cvss: Mapped[bool] = mapped_column(Boolean, default=False)
    preferred_cvss_version: Mapped[str | None] = mapped_column(String(10), nullable=True)
    preferred_base_score: Mapped[float | None] = mapped_column(DECIMAL(4, 1), nullable=True, index=True)
    preferred_base_severity: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    preferred_vector_string: Mapped[str | None] = mapped_column(String(255), nullable=True)

    raw_json: Mapped[str | None] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    cvss_metrics: Mapped[list["CvssMetricORM"]] = relationship(
        back_populates="vulnerability",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    vulnerability_cwes: Mapped[list["VulnerabilityCweORM"]] = relationship(
        back_populates="vulnerability",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    reference_links: Mapped[list["ReferenceLinkORM"]] = relationship(
        back_populates="vulnerability",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    cpe_matches: Mapped[list["CpeMatchORM"]] = relationship(
        back_populates="vulnerability",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    raw_json_chunks: Mapped[list["VulnerabilityRawJsonChunkORM"]] = relationship(
        back_populates="vulnerability",
        cascade="all, delete-orphan",
        lazy="noload",
    )


class VulnerabilityRawJsonChunkORM(Base):
    """Gzip-compressed NVD JSON split into packet-safe database chunks.

    Raw NVD documents can exceed MariaDB's max_allowed_packet even when a
    single CVE is written alone. Storing compressed chunks keeps exact source
    JSON available to the UI without requiring a server-wide packet increase.
    """

    __tablename__ = "vulnerability_raw_json_chunks"
    __table_args__ = (
        UniqueConstraint(
            "vulnerability_id", "chunk_index",
            name="uq_vulnerability_raw_json_chunk",
        ),
    )

    id: Mapped[int] = mapped_column(MYSQL_COMPAT_ID, primary_key=True, autoincrement=True)
    vulnerability_id: Mapped[int] = mapped_column(
        MYSQL_COMPAT_ID,
        ForeignKey("vulnerabilities.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    compressed_data: Mapped[bytes] = mapped_column(
        LargeBinary().with_variant(LONGBLOB(), "mysql"), nullable=False
    )
    original_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    compressed_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    vulnerability: Mapped["VulnerabilityORM"] = relationship(
        back_populates="raw_json_chunks"
    )


class CvssMetricORM(Base):
    __tablename__ = "cvss_metrics"
    __table_args__ = (
        UniqueConstraint(
            "vulnerability_id", "cvss_version", "source_name", "metric_type",
            name="uq_cvss_unique_metric"
        ),
    )

    id: Mapped[int] = mapped_column(MYSQL_COMPAT_ID, primary_key=True, autoincrement=True)
    vulnerability_id: Mapped[int] = mapped_column(MYSQL_COMPAT_ID, ForeignKey("vulnerabilities.id", ondelete="CASCADE"), index=True)

    cvss_version: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    metric_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vector_string: Mapped[str | None] = mapped_column(String(255), nullable=True)
    base_score: Mapped[float | None] = mapped_column(DECIMAL(4, 1), nullable=True, index=True)
    base_severity: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    attack_vector: Mapped[str | None] = mapped_column(String(50), nullable=True)
    attack_complexity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    privileges_required: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_interaction: Mapped[str | None] = mapped_column(String(50), nullable=True)
    scope_value: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidentiality_impact: Mapped[str | None] = mapped_column(String(50), nullable=True)
    integrity_impact: Mapped[str | None] = mapped_column(String(50), nullable=True)
    availability_impact: Mapped[str | None] = mapped_column(String(50), nullable=True)

    exploitability_score: Mapped[float | None] = mapped_column(DECIMAL(6, 2), nullable=True)
    impact_score: Mapped[float | None] = mapped_column(DECIMAL(6, 2), nullable=True)

    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vulnerability: Mapped["VulnerabilityORM"] = relationship(back_populates="cvss_metrics")


class CweCatalogORM(Base):
    __tablename__ = "cwe_catalog"

    id: Mapped[int] = mapped_column(MYSQL_COMPAT_ID, primary_key=True, autoincrement=True)
    cwe_id: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    cwe_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    cwe_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extended_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstraction: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    structure_value: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status_value: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    likelihood_of_exploit: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    source_name: Mapped[str | None] = mapped_column(String(100), nullable=True, default="MITRE CWE")
    api_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    api_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    related_weaknesses_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    alternate_terms_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vulnerability_links: Mapped[list["VulnerabilityCweORM"]] = relationship(
        back_populates="cwe_catalog",
        lazy="selectin",
    )


class VulnerabilityCweORM(Base):
    __tablename__ = "vulnerability_cwes"
    __table_args__ = (
        UniqueConstraint("vulnerability_id", "cwe_catalog_id", name="uq_vulnerability_cwe"),
    )

    id: Mapped[int] = mapped_column(MYSQL_COMPAT_ID, primary_key=True, autoincrement=True)
    vulnerability_id: Mapped[int] = mapped_column(MYSQL_COMPAT_ID, ForeignKey("vulnerabilities.id", ondelete="CASCADE"), index=True)
    cwe_catalog_id: Mapped[int] = mapped_column(MYSQL_COMPAT_ID, ForeignKey("cwe_catalog.id", ondelete="RESTRICT"), index=True)
    source_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    vulnerability: Mapped["VulnerabilityORM"] = relationship(back_populates="vulnerability_cwes")
    cwe_catalog: Mapped["CweCatalogORM"] = relationship(back_populates="vulnerability_links")


class ReferenceLinkORM(Base):
    __tablename__ = "reference_links"
    __table_args__ = (
        UniqueConstraint("vulnerability_id", "url", name="uq_reference_link"),
    )

    id: Mapped[int] = mapped_column(MYSQL_COMPAT_ID, primary_key=True, autoincrement=True)
    vulnerability_id: Mapped[int] = mapped_column(MYSQL_COMPAT_ID, ForeignKey("vulnerabilities.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    source_name: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    vulnerability: Mapped["VulnerabilityORM"] = relationship(back_populates="reference_links")


class CpeMatchORM(Base):
    __tablename__ = "cpe_matches"

    id: Mapped[int] = mapped_column(MYSQL_COMPAT_ID, primary_key=True, autoincrement=True)
    vulnerability_id: Mapped[int] = mapped_column(MYSQL_COMPAT_ID, ForeignKey("vulnerabilities.id", ondelete="CASCADE"), index=True)
    is_vulnerable: Mapped[bool] = mapped_column(Boolean, default=True)
    criteria_uri: Mapped[str] = mapped_column(String(1024))
    match_criteria_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    version_start_including: Mapped[str | None] = mapped_column(String(100), nullable=True)
    version_start_excluding: Mapped[str | None] = mapped_column(String(100), nullable=True)
    version_end_including: Mapped[str | None] = mapped_column(String(100), nullable=True)
    version_end_excluding: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vulnerability: Mapped["VulnerabilityORM"] = relationship(back_populates="cpe_matches")


class NvdCpeDictionaryORM(Base):
    """Local mirror of the NVD Official CPE Dictionary.

    This table is intentionally separate from cpe_matches. cpe_matches stores
    CPE criteria embedded in CVE applicability configurations, while this table
    stores canonical product names from the official CPE dictionary used to
    validate and normalize technology fingerprints from the Pentest app.
    """

    __tablename__ = "nvd_cpe_dictionary"

    id: Mapped[int] = mapped_column(MYSQL_COMPAT_ID, primary_key=True, autoincrement=True)
    cpe_name_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True, index=True)
    cpe23_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    part: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    vendor: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    product: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    version: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    update_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    edition: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sw_edition: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_sw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_hw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    other: Mapped[str | None] = mapped_column(String(255), nullable=True)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    titles_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    references_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deprecated_by_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at_source: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    modified_at_source: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    source_name: Mapped[str | None] = mapped_column(String(100), nullable=True, default="NVD Official CPE Dictionary")
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SyncAuditORM(Base):
    __tablename__ = "sync_audit"

    id: Mapped[int] = mapped_column(MYSQL_COMPAT_ID, primary_key=True, autoincrement=True)
    sync_type: Mapped[str] = mapped_column(String(30))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status_value: Mapped[str] = mapped_column(String(30), index=True)

    last_successful_modified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    page_size: Mapped[int | None] = mapped_column(nullable=True)

    total_fetched: Mapped[int] = mapped_column(default=0)
    total_inserted: Mapped[int] = mapped_column(default=0)
    total_updated: Mapped[int] = mapped_column(default=0)
    total_failed: Mapped[int] = mapped_column(default=0)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AppSettingORM(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(MYSQL_COMPAT_ID, primary_key=True, autoincrement=True)
    setting_key: Mapped[str] = mapped_column(String(100), unique=True)
    setting_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
