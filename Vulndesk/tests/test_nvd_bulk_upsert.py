from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from db import Base
from orm_models import (
    CpeMatchORM,
    CweCatalogORM,
    CvssMetricORM,
    ReferenceLinkORM,
    VulnerabilityCweORM,
    VulnerabilityORM,
)
from repositories import UpsertRepository


def mapped(cve_id: str, modified_at: datetime, suffix: str = "a") -> dict:
    return {
        "vulnerability": {
            "cve_id": cve_id,
            "description_text": f"Description {suffix}",
            "source_name": "NVD",
            "vuln_status": "Analyzed",
            "published_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "modified_at": modified_at,
            "nvd_url": f"https://nvd.nist.gov/vuln/detail/{cve_id}",
            "has_cvss": True,
            "preferred_cvss_version": "3.1",
            "preferred_base_score": 7.5,
            "preferred_base_severity": "HIGH",
            "preferred_vector_string": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
            "raw_json": "{}",
        },
        "cvss_metrics": [
            {
                "cvss_version": "3.1",
                "source_name": "nvd@nist.gov",
                "metric_type": "Primary",
                "vector_string": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
                "base_score": 7.5,
                "base_severity": "HIGH",
                "attack_vector": "NETWORK",
                "attack_complexity": "LOW",
                "privileges_required": "NONE",
                "user_interaction": "NONE",
                "scope_value": "UNCHANGED",
                "confidentiality_impact": "HIGH",
                "integrity_impact": "NONE",
                "availability_impact": "NONE",
                "exploitability_score": 3.9,
                "impact_score": 3.6,
                "is_preferred": True,
            }
        ],
        "cwes": [
            {
                "cwe_id": "CWE-79",
                "cwe_name": None,
                "cwe_url": None,
                "source_name": "nvd@nist.gov",
            }
        ],
        "references": [
            {
                "url": f"https://example.test/{cve_id}/{suffix}",
                "source_name": "example",
                "tags_json": "[]",
            }
        ],
        "cpe_matches": [
            {
                "is_vulnerable": True,
                "criteria_uri": f"cpe:2.3:a:vendor:product:{suffix}:*:*:*:*:*:*:*",
                "match_criteria_id": f"match-{cve_id}-{suffix}",
                "version_start_including": None,
                "version_start_excluding": None,
                "version_end_including": None,
                "version_end_excluding": None,
            }
        ],
    }


def test_bulk_upsert_insert_skip_and_update():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    first_modified = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)

    with Session() as session:
        repo = UpsertRepository(session)
        stats = repo.bulk_upsert_mapped_vulnerabilities(
            [
                mapped("CVE-2026-0001", first_modified),
                mapped("CVE-2026-0002", first_modified),
            ]
        )
        session.commit()
        assert stats == {"inserted": 2, "updated": 0, "skipped": 0}
        assert session.scalar(select(func.count(VulnerabilityORM.id))) == 2
        assert session.scalar(select(func.count(CvssMetricORM.id))) == 2
        assert session.scalar(select(func.count(VulnerabilityCweORM.id))) == 2
        assert session.scalar(select(func.count(CweCatalogORM.id))) == 1
        assert session.scalar(select(func.count(ReferenceLinkORM.id))) == 2
        assert session.scalar(select(func.count(CpeMatchORM.id))) == 2

        stats = repo.bulk_upsert_mapped_vulnerabilities(
            [
                mapped("CVE-2026-0001", first_modified),
                mapped("CVE-2026-0002", first_modified),
            ]
        )
        session.commit()
        assert stats == {"inserted": 0, "updated": 0, "skipped": 2}
        assert session.scalar(select(func.count(ReferenceLinkORM.id))) == 2

        stats = repo.bulk_upsert_mapped_vulnerabilities(
            [
                mapped("CVE-2026-0001", first_modified + timedelta(days=1), "b"),
                mapped("CVE-2026-0002", first_modified, "b"),
            ]
        )
        session.commit()
        assert stats == {"inserted": 0, "updated": 1, "skipped": 1}
        row = session.scalar(
            select(VulnerabilityORM).where(VulnerabilityORM.cve_id == "CVE-2026-0001")
        )
        assert row.description_text == "Description b"
        urls = session.scalars(select(ReferenceLinkORM.url)).all()
        assert "https://example.test/CVE-2026-0001/b" in urls
        assert "https://example.test/CVE-2026-0001/a" not in urls

        stats = repo.bulk_upsert_mapped_vulnerabilities(
            [mapped("CVE-2026-0001", first_modified, "old")]
        )
        session.commit()
        assert stats == {"inserted": 0, "updated": 0, "skipped": 1}

        # MariaDB DATETIME in the supplied schema stores second precision.
        # A source timestamp in the same second must still be recognized as unchanged.
        same_second = (first_modified + timedelta(days=1)).replace(microsecond=987000)
        stats = repo.bulk_upsert_mapped_vulnerabilities(
            [mapped("CVE-2026-0001", same_second, "same-second")]
        )
        session.commit()
        assert stats == {"inserted": 0, "updated": 0, "skipped": 1}


def test_large_raw_json_is_compressed_chunked_and_reconstructed():
    import random
    import string

    from config import Config
    from orm_models import VulnerabilityRawJsonChunkORM
    from repositories import VulnerabilityRepository

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    rng = random.Random(20260722)
    payload = "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(1_450_000))
    raw_json = '{"payload":"' + payload + '"}'
    item = mapped(
        "CVE-2021-3942",
        datetime(2026, 6, 17, 4, 6, 1, tzinfo=timezone.utc),
        "large",
    )
    item["vulnerability"]["raw_json"] = raw_json

    with Session() as session:
        stats = UpsertRepository(session).bulk_upsert_mapped_vulnerabilities([item])
        session.commit()
        assert stats == {"inserted": 1, "updated": 0, "skipped": 0}

        vuln = session.scalar(
            select(VulnerabilityORM).where(VulnerabilityORM.cve_id == "CVE-2021-3942")
        )
        assert vuln.raw_json is None

        chunks = session.scalars(
            select(VulnerabilityRawJsonChunkORM)
            .where(VulnerabilityRawJsonChunkORM.vulnerability_id == vuln.id)
            .order_by(VulnerabilityRawJsonChunkORM.chunk_index)
        ).all()
        assert len(chunks) > 1
        assert all(len(chunk.compressed_data) <= Config.NVD_RAW_JSON_CHUNK_BYTES for chunk in chunks)
        assert chunks[0].original_size == len(raw_json.encode("utf-8"))

        detail = VulnerabilityRepository(session).get_detail_by_id(vuln.id)
        assert detail is not None
        assert detail["raw_json"] == raw_json


def test_reference_urls_are_deduplicated_case_insensitively():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    item = mapped(
        "CVE-2023-48795",
        datetime(2026, 7, 22, 1, 0, tzinfo=timezone.utc),
        "netapp",
    )
    item["references"] = [
        {
            "url": "https://security.netapp.com/advisory/NTAP-20231215-0001/",
            "source_name": "security-alert@netapp.com",
            "tags_json": '["Vendor Advisory"]',
        },
        {
            "url": "https://security.netapp.com/advisory/ntap-20231215-0001/",
            "source_name": "nvd@nist.gov",
            "tags_json": '["Vendor Advisory"]',
        },
    ]

    with Session() as session:
        stats = UpsertRepository(session).bulk_upsert_mapped_vulnerabilities([item])
        session.commit()
        assert stats == {"inserted": 1, "updated": 0, "skipped": 0}
        refs = session.scalars(select(ReferenceLinkORM.url)).all()
        assert refs == ["https://security.netapp.com/advisory/NTAP-20231215-0001/"]


def test_reference_prefix_deduplication_matches_255_character_index():
    common_prefix = "https://example.test/" + ("a" * 300)
    rows = [
        {"vulnerability_id": 1, "url": common_prefix + "ONE"},
        {"vulnerability_id": 1, "url": common_prefix.upper() + "two"},
    ]
    deduplicated = UpsertRepository._deduplicate_by_prefix(
        rows, ("vulnerability_id", "url")
    )
    assert deduplicated == [rows[0]]
