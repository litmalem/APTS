from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib

from sqlalchemy import select, func, and_, or_, desc, asc, insert, update, delete
from sqlalchemy.orm import selectinload

from cwe_mapper import cwe_url as _cwe_url
from config import Config

from orm_models import (
    VulnerabilityORM,
    CvssMetricORM,
    CweCatalogORM,
    VulnerabilityCweORM,
    ReferenceLinkORM,
    CpeMatchORM,
    VulnerabilityRawJsonChunkORM,
    SyncAuditORM,
    AppSettingORM,
)


class VulnerabilityRepository:
    def __init__(self, session):
        self.session = session

    def _apply_common_filters(self, stmt, filters: dict):
        conditions = []

        keyword = (filters.get("keyword") or "").strip()
        if keyword:
            kw = f"%{keyword}%"
            conditions.append(
                or_(
                    VulnerabilityORM.cve_id.ilike(kw),
                    VulnerabilityORM.description_text.ilike(kw),
                )
            )

        severity = filters.get("severity")
        if severity:
            conditions.append(VulnerabilityORM.preferred_base_severity == severity)

        min_score = filters.get("min_score")
        if min_score is not None:
            conditions.append(VulnerabilityORM.preferred_base_score >= min_score)

        max_score = filters.get("max_score")
        if max_score is not None:
            conditions.append(VulnerabilityORM.preferred_base_score <= max_score)

        year = filters.get("year")
        if year is not None:
            conditions.append(func.year(VulnerabilityORM.published_at) == year)

        modified_from = filters.get("modified_from")
        if modified_from is not None:
            conditions.append(VulnerabilityORM.modified_at >= modified_from)

        modified_to = filters.get("modified_to")
        if modified_to is not None:
            conditions.append(VulnerabilityORM.modified_at <= modified_to)

        if filters.get("has_cpe") is True:
            stmt = stmt.join(CpeMatchORM, CpeMatchORM.vulnerability_id == VulnerabilityORM.id)

        cwe_id = (filters.get("cwe_id") or "").strip().upper()
        if cwe_id:
            stmt = (
                stmt.join(VulnerabilityCweORM, VulnerabilityCweORM.vulnerability_id == VulnerabilityORM.id)
                .join(CweCatalogORM, CweCatalogORM.id == VulnerabilityCweORM.cwe_catalog_id)
            )
            conditions.append(CweCatalogORM.cwe_id == cwe_id)

        if conditions:
            stmt = stmt.where(and_(*conditions))
        return stmt

    def list_items(self, filters: dict) -> list[dict]:
        cwe_count_sq = (
            select(
                VulnerabilityCweORM.vulnerability_id,
                func.count(VulnerabilityCweORM.id).label("cwe_count"),
            )
            .group_by(VulnerabilityCweORM.vulnerability_id)
            .subquery()
        )

        ref_count_sq = (
            select(
                ReferenceLinkORM.vulnerability_id,
                func.count(ReferenceLinkORM.id).label("reference_count"),
            )
            .group_by(ReferenceLinkORM.vulnerability_id)
            .subquery()
        )

        cpe_count_sq = (
            select(
                CpeMatchORM.vulnerability_id,
                func.count(CpeMatchORM.id).label("affected_product_count"),
            )
            .group_by(CpeMatchORM.vulnerability_id)
            .subquery()
        )

        cwe_count_col = func.coalesce(cwe_count_sq.c.cwe_count, 0).label("cwe_count")
        cpe_count_col = func.coalesce(cpe_count_sq.c.affected_product_count, 0).label("affected_product_count")
        ref_count_col = func.coalesce(ref_count_sq.c.reference_count, 0).label("reference_count")

        stmt = (
            select(
                VulnerabilityORM.id,
                VulnerabilityORM.cve_id,
                VulnerabilityORM.description_text,
                VulnerabilityORM.vuln_status,
                VulnerabilityORM.published_at,
                VulnerabilityORM.modified_at,
                VulnerabilityORM.preferred_cvss_version,
                VulnerabilityORM.preferred_base_score,
                VulnerabilityORM.preferred_base_severity,
                cwe_count_col,
                cpe_count_col,
                ref_count_col,
            )
            .select_from(VulnerabilityORM)
            .outerjoin(cwe_count_sq, cwe_count_sq.c.vulnerability_id == VulnerabilityORM.id)
            .outerjoin(cpe_count_sq, cpe_count_sq.c.vulnerability_id == VulnerabilityORM.id)
            .outerjoin(ref_count_sq, ref_count_sq.c.vulnerability_id == VulnerabilityORM.id)
        )

        stmt = self._apply_common_filters(stmt, filters)

        sort_by = filters.get("sort_by") or "modified_at"
        sort_desc = bool(filters.get("sort_desc", True))
        sort_map = {
            "cve_id": VulnerabilityORM.cve_id,
            "description_text": VulnerabilityORM.description_text,
            "preferred_base_severity": VulnerabilityORM.preferred_base_severity,
            "preferred_base_score": VulnerabilityORM.preferred_base_score,
            "preferred_cvss_version": VulnerabilityORM.preferred_cvss_version,
            "published_at": VulnerabilityORM.published_at,
            "modified_at": VulnerabilityORM.modified_at,
            "cwe_count": cwe_count_col,
            "reference_count": ref_count_col,
            "affected_product_count": cpe_count_col,
        }
        sort_expr = sort_map.get(sort_by, VulnerabilityORM.modified_at)
        order_expr = desc(sort_expr) if sort_desc else asc(sort_expr)

        limit = int(filters.get("limit", 100))
        offset = int(filters.get("offset", 0))

        stmt = stmt.order_by(order_expr, desc(VulnerabilityORM.id)).limit(limit).offset(offset)

        rows = self.session.execute(stmt).all()
        return [
            {
                "id": row[0],
                "cve_id": row[1],
                "description_text": row[2],
                "vuln_status": row[3],
                "published_at": row[4],
                "modified_at": row[5],
                "preferred_cvss_version": row[6],
                "preferred_base_score": float(row[7]) if row[7] is not None else None,
                "preferred_base_severity": row[8],
                "cwe_count": int(row[9]),
                "affected_product_count": int(row[10]),
                "reference_count": int(row[11]),
            }
            for row in rows
        ]

    def count_items(self, filters: dict) -> int:
        stmt = select(func.count(func.distinct(VulnerabilityORM.id))).select_from(VulnerabilityORM)
        stmt = self._apply_common_filters(stmt, filters)
        return int(self.session.execute(stmt).scalar_one())

    def _load_raw_json(self, vulnerability_id: int, legacy_raw_json: str | None) -> str:
        rows = self.session.execute(
            select(VulnerabilityRawJsonChunkORM.compressed_data)
            .where(VulnerabilityRawJsonChunkORM.vulnerability_id == vulnerability_id)
            .order_by(VulnerabilityRawJsonChunkORM.chunk_index.asc())
        ).scalars().all()
        if not rows:
            return legacy_raw_json or ""
        try:
            compressed = b"".join(bytes(row) for row in rows)
            return gzip.decompress(compressed).decode("utf-8")
        except Exception as error:
            # Keep the detail screen usable even if a chunk was damaged.
            return legacy_raw_json or f"Raw JSON compressed payload could not be read: {error}"

    def get_detail_by_id(self, vulnerability_id: int) -> dict | None:
        stmt = (
            select(VulnerabilityORM)
            .options(
                selectinload(VulnerabilityORM.cvss_metrics),
                selectinload(VulnerabilityORM.vulnerability_cwes).selectinload(VulnerabilityCweORM.cwe_catalog),
                selectinload(VulnerabilityORM.reference_links),
                selectinload(VulnerabilityORM.cpe_matches),
            )
            .where(VulnerabilityORM.id == vulnerability_id)
        )

        vuln = self.session.execute(stmt).scalar_one_or_none()
        if vuln is None:
            return None

        cvss_metrics = []
        for m in sorted(
            vuln.cvss_metrics,
            key=lambda x: (not x.is_preferred, -(float(x.base_score) if x.base_score is not None else -1)),
        ):
            cvss_metrics.append({
                "cvss_version": m.cvss_version,
                "source_name": m.source_name,
                "metric_type": m.metric_type,
                "vector_string": m.vector_string,
                "base_score": float(m.base_score) if m.base_score is not None else None,
                "base_severity": m.base_severity,
                "attack_vector": m.attack_vector,
                "attack_complexity": m.attack_complexity,
                "privileges_required": m.privileges_required,
                "user_interaction": m.user_interaction,
                "scope_value": m.scope_value,
                "confidentiality_impact": m.confidentiality_impact,
                "integrity_impact": m.integrity_impact,
                "availability_impact": m.availability_impact,
                "exploitability_score": float(m.exploitability_score) if m.exploitability_score is not None else None,
                "impact_score": float(m.impact_score) if m.impact_score is not None else None,
                "is_preferred": m.is_preferred,
            })

        cwes = [
            {
                "cwe_id": link.cwe_catalog.cwe_id,
                "cwe_name": link.cwe_catalog.cwe_name,
                "cwe_url": link.cwe_catalog.cwe_url,
                "description_text": link.cwe_catalog.description_text,
                "extended_description": link.cwe_catalog.extended_description,
                "abstraction": link.cwe_catalog.abstraction,
                "structure_value": link.cwe_catalog.structure_value,
                "status_value": link.cwe_catalog.status_value,
                "likelihood_of_exploit": link.cwe_catalog.likelihood_of_exploit,
                "api_synced_at": link.cwe_catalog.api_synced_at,
            }
            for link in vuln.vulnerability_cwes
            if link.cwe_catalog
        ]

        refs = [
            {
                "url": r.url,
                "source_name": r.source_name,
                "tags_json": r.tags_json,
            }
            for r in vuln.reference_links
        ]

        cpe_matches = [
            {
                "is_vulnerable": cp.is_vulnerable,
                "criteria_uri": cp.criteria_uri,
                "match_criteria_id": cp.match_criteria_id,
                "version_start_including": cp.version_start_including,
                "version_start_excluding": cp.version_start_excluding,
                "version_end_including": cp.version_end_including,
                "version_end_excluding": cp.version_end_excluding,
            }
            for cp in vuln.cpe_matches
        ]

        return {
            "id": vuln.id,
            "cve_id": vuln.cve_id,
            "description_text": vuln.description_text,
            "source_name": vuln.source_name,
            "vuln_status": vuln.vuln_status,
            "published_at": vuln.published_at,
            "modified_at": vuln.modified_at,
            "nvd_url": vuln.nvd_url,
            "preferred_cvss_version": vuln.preferred_cvss_version,
            "preferred_base_score": float(vuln.preferred_base_score) if vuln.preferred_base_score is not None else None,
            "preferred_base_severity": vuln.preferred_base_severity,
            "preferred_vector_string": vuln.preferred_vector_string,
            "cvss_metrics": cvss_metrics,
            "cwes": cwes,
            "references": refs,
            "cpe_matches": cpe_matches,
            "raw_json": self._load_raw_json(vuln.id, vuln.raw_json),
        }


class UpsertRepository:
    """Packet-safe high-throughput NVD persistence.

    Parent rows never carry oversized source JSON in the default mode. Exact
    NVD JSON is gzip-compressed and split into small child rows, so one unusual
    CVE cannot exceed MariaDB ``max_allowed_packet``.
    """

    def __init__(self, session):
        self.session = session

    @staticmethod
    def _db_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(microsecond=0)
        return value.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)

    @classmethod
    def _parent_values(cls, values: dict) -> dict:
        row = dict(values)
        row["published_at"] = cls._db_datetime(row.get("published_at"))
        row["modified_at"] = cls._db_datetime(row.get("modified_at"))
        storage = Config.NVD_RAW_JSON_STORAGE
        if storage == "none":
            row["raw_json"] = None
        elif storage == "compressed_chunks":
            # Stored separately after the parent ID has been resolved.
            row["raw_json"] = None
        return row

    @classmethod
    def _is_unchanged_or_older(
        cls,
        existing_modified_at: datetime | None,
        incoming_modified_at: datetime | None,
    ) -> bool:
        existing = cls._db_datetime(existing_modified_at)
        incoming = cls._db_datetime(incoming_modified_at)
        return existing is not None and incoming is not None and existing >= incoming

    @staticmethod
    def _estimate_value_bytes(value) -> int:
        if value is None:
            return 4
        if isinstance(value, (bytes, bytearray, memoryview)):
            # PyMySQL escapes binary parameters before sending them. Use a 2x
            # upper-bound so a 128 KiB chunk remains packet-safe even when the
            # server max_allowed_packet is only 1 MiB.
            return len(value) * 2 + 32
        if isinstance(value, str):
            return int(len(value.encode("utf-8", errors="replace")) * 1.15) + 16
        return 32

    @classmethod
    def _estimate_row_bytes(cls, row: dict) -> int:
        # Include conservative SQL/protocol overhead for names, escaping and
        # delimiters. The byte cap is intentionally below max_allowed_packet.
        return 256 + sum(cls._estimate_value_bytes(value) for value in row.values())

    def _execute_insert_chunks(
        self,
        model,
        rows: list[dict],
        *,
        max_rows: int,
        max_bytes: int | None = None,
    ) -> None:
        if not rows:
            return
        max_bytes = int(max_bytes or Config.NVD_DB_MAX_STATEMENT_BYTES)
        chunk: list[dict] = []
        chunk_bytes = 0
        for row in rows:
            row_bytes = self._estimate_row_bytes(row)
            if chunk and (
                len(chunk) >= max_rows or chunk_bytes + row_bytes > max_bytes
            ):
                self.session.execute(insert(model), chunk)
                chunk = []
                chunk_bytes = 0
            chunk.append(row)
            chunk_bytes += row_bytes
            if len(chunk) >= max_rows:
                self.session.execute(insert(model), chunk)
                chunk = []
                chunk_bytes = 0
        if chunk:
            self.session.execute(insert(model), chunk)

    def _execute_update_chunks(
        self,
        model,
        rows: list[dict],
        *,
        max_rows: int,
        max_bytes: int | None = None,
    ) -> None:
        if not rows:
            return
        max_bytes = int(max_bytes or Config.NVD_DB_MAX_STATEMENT_BYTES)
        chunk: list[dict] = []
        chunk_bytes = 0
        for row in rows:
            row_bytes = self._estimate_row_bytes(row)
            if chunk and (
                len(chunk) >= max_rows or chunk_bytes + row_bytes > max_bytes
            ):
                self.session.execute(update(model), chunk)
                chunk = []
                chunk_bytes = 0
            chunk.append(row)
            chunk_bytes += row_bytes
        if chunk:
            self.session.execute(update(model), chunk)

    @staticmethod
    def _deduplicate_by_prefix(rows: list[dict], fields: tuple[str, ...]) -> list[dict]:
        """Deduplicate rows using the effective MariaDB unique-key semantics.

        The supplied schema uses ``utf8mb4_unicode_ci`` and several 255-character
        prefix indexes. Consequently, string comparisons are case-insensitive and
        only the indexed prefix participates in uniqueness. NVD can publish the
        same reference with different capitalization (for example ``NTAP`` and
        ``ntap``), so Python-side deduplication must apply the same rule before a
        bulk insert is sent to MariaDB.
        """
        seen: set[tuple] = set()
        result: list[dict] = []
        for row in rows:
            key_parts = []
            for field in fields:
                value = row.get(field)
                if isinstance(value, str):
                    # VARCHAR comparisons under *_unicode_ci ignore case and
                    # trailing spaces. Prefix indexes use only the first 255 chars.
                    value = value[:255].rstrip().casefold()
                key_parts.append(value)
            key = tuple(key_parts)
            if key in seen:
                continue
            seen.add(key)
            result.append(row)
        return result

    def _ensure_cwe_catalog(self, mapped_items: list[dict]) -> dict[str, int]:
        cwe_ids = {
            cwe.get("cwe_id")
            for mapped in mapped_items
            for cwe in mapped.get("cwes", [])
            if cwe.get("cwe_id")
        }
        if not cwe_ids:
            return {}
        rows = self.session.execute(
            select(CweCatalogORM.id, CweCatalogORM.cwe_id).where(
                CweCatalogORM.cwe_id.in_(cwe_ids)
            )
        ).all()
        catalog_by_cwe = {cwe_id: row_id for row_id, cwe_id in rows}
        missing_ids = sorted(cwe_ids.difference(catalog_by_cwe))
        if missing_ids:
            metadata: dict[str, dict] = {}
            for mapped in mapped_items:
                for cwe in mapped.get("cwes", []):
                    cwe_id = cwe.get("cwe_id")
                    if cwe_id and cwe_id not in metadata:
                        metadata[cwe_id] = cwe
            self._execute_insert_chunks(
                CweCatalogORM,
                [
                    {
                        "cwe_id": cwe_id,
                        "cwe_name": metadata.get(cwe_id, {}).get("cwe_name"),
                        "cwe_url": metadata.get(cwe_id, {}).get("cwe_url") or _cwe_url(cwe_id),
                    }
                    for cwe_id in missing_ids
                ],
                max_rows=200,
            )
            rows = self.session.execute(
                select(CweCatalogORM.id, CweCatalogORM.cwe_id).where(
                    CweCatalogORM.cwe_id.in_(cwe_ids)
                )
            ).all()
            catalog_by_cwe = {cwe_id: row_id for row_id, cwe_id in rows}
        return catalog_by_cwe

    def _build_raw_json_chunk_rows(
        self,
        changed_items: list[dict],
        vulnerability_id_by_cve: dict[str, int],
    ) -> list[dict]:
        if Config.NVD_RAW_JSON_STORAGE != "compressed_chunks":
            return []
        rows: list[dict] = []
        chunk_size = Config.NVD_RAW_JSON_CHUNK_BYTES
        for mapped in changed_items:
            parent = mapped.get("vulnerability", {})
            raw_json = parent.get("raw_json")
            if not raw_json:
                continue
            raw_bytes = raw_json.encode("utf-8")
            compressed = gzip.compress(raw_bytes, compresslevel=6, mtime=0)
            digest = hashlib.sha256(raw_bytes).hexdigest()
            vulnerability_id = vulnerability_id_by_cve[parent["cve_id"]]
            for index, offset in enumerate(range(0, len(compressed), chunk_size)):
                part = compressed[offset : offset + chunk_size]
                rows.append(
                    {
                        "vulnerability_id": vulnerability_id,
                        "chunk_index": index,
                        "compressed_data": part,
                        "original_size": len(raw_bytes),
                        "compressed_size": len(compressed),
                        "sha256_hex": digest,
                    }
                )
        return rows

    def bulk_upsert_mapped_vulnerabilities(
        self,
        mapped_items: list[dict],
        skip_unchanged: bool = True,
    ) -> dict:
        if not mapped_items:
            return {"inserted": 0, "updated": 0, "skipped": 0}

        by_cve: dict[str, dict] = {}
        for mapped in mapped_items:
            cve_id = (mapped.get("vulnerability", {}).get("cve_id") or "").strip()
            if not cve_id:
                raise ValueError("Mapped vulnerability is missing cve_id")
            previous = by_cve.get(cve_id)
            if previous is None:
                by_cve[cve_id] = mapped
                continue
            previous_modified = previous["vulnerability"].get("modified_at")
            incoming_modified = mapped["vulnerability"].get("modified_at")
            if previous_modified is None or (
                incoming_modified is not None and incoming_modified > previous_modified
            ):
                by_cve[cve_id] = mapped

        unique_items = list(by_cve.values())
        cve_ids = list(by_cve)
        existing_rows = self.session.execute(
            select(
                VulnerabilityORM.id,
                VulnerabilityORM.cve_id,
                VulnerabilityORM.modified_at,
            ).where(VulnerabilityORM.cve_id.in_(cve_ids))
        ).all()
        existing_by_cve = {
            cve_id: {"id": row_id, "modified_at": modified_at}
            for row_id, cve_id, modified_at in existing_rows
        }

        insert_items: list[dict] = []
        update_items: list[dict] = []
        skipped = 0
        for mapped in unique_items:
            parent = mapped["vulnerability"]
            existing = existing_by_cve.get(parent["cve_id"])
            if existing is None:
                insert_items.append(mapped)
            elif skip_unchanged and self._is_unchanged_or_older(
                existing.get("modified_at"), parent.get("modified_at")
            ):
                skipped += 1
            else:
                update_items.append(mapped)

        if not insert_items and not update_items:
            return {"inserted": 0, "updated": 0, "skipped": skipped}

        if insert_items:
            self._execute_insert_chunks(
                VulnerabilityORM,
                [self._parent_values(item["vulnerability"]) for item in insert_items],
                max_rows=Config.NVD_DB_PARENT_WRITE_BATCH_SIZE,
            )

        if update_items:
            update_rows: list[dict] = []
            for mapped in update_items:
                values = self._parent_values(mapped["vulnerability"])
                values["id"] = existing_by_cve[values["cve_id"]]["id"]
                update_rows.append(values)
            self._execute_update_chunks(
                VulnerabilityORM,
                update_rows,
                max_rows=Config.NVD_DB_PARENT_WRITE_BATCH_SIZE,
            )

        changed_items = insert_items + update_items
        changed_cve_ids = [item["vulnerability"]["cve_id"] for item in changed_items]
        id_rows = self.session.execute(
            select(VulnerabilityORM.id, VulnerabilityORM.cve_id).where(
                VulnerabilityORM.cve_id.in_(changed_cve_ids)
            )
        ).all()
        vulnerability_id_by_cve = {cve_id: row_id for row_id, cve_id in id_rows}
        if len(vulnerability_id_by_cve) != len(changed_cve_ids):
            missing = sorted(set(changed_cve_ids).difference(vulnerability_id_by_cve))
            raise RuntimeError(f"Failed to resolve vulnerability IDs after upsert: {missing}")
        changed_ids = list(vulnerability_id_by_cve.values())

        for model in (
            CvssMetricORM,
            VulnerabilityCweORM,
            ReferenceLinkORM,
            CpeMatchORM,
            VulnerabilityRawJsonChunkORM,
        ):
            self.session.execute(delete(model).where(model.vulnerability_id.in_(changed_ids)))

        catalog_by_cwe = self._ensure_cwe_catalog(changed_items)
        cvss_rows: list[dict] = []
        cwe_rows: list[dict] = []
        reference_rows: list[dict] = []
        cpe_rows: list[dict] = []

        for mapped in changed_items:
            cve_id = mapped["vulnerability"]["cve_id"]
            vulnerability_id = vulnerability_id_by_cve[cve_id]
            for metric in mapped.get("cvss_metrics", []):
                cvss_rows.append({"vulnerability_id": vulnerability_id, **metric})
            for cwe in mapped.get("cwes", []):
                catalog_id = catalog_by_cwe.get(cwe.get("cwe_id"))
                if catalog_id is not None:
                    cwe_rows.append(
                        {
                            "vulnerability_id": vulnerability_id,
                            "cwe_catalog_id": catalog_id,
                            "source_name": cwe.get("source_name"),
                        }
                    )
            for ref in mapped.get("references", []):
                if ref.get("url"):
                    reference_rows.append({"vulnerability_id": vulnerability_id, **ref})
            for cpe in mapped.get("cpe_matches", []):
                if cpe.get("criteria_uri"):
                    cpe_rows.append({"vulnerability_id": vulnerability_id, **cpe})

        cvss_rows = self._deduplicate_by_prefix(
            cvss_rows,
            ("vulnerability_id", "cvss_version", "source_name", "metric_type"),
        )
        cwe_rows = self._deduplicate_by_prefix(
            cwe_rows, ("vulnerability_id", "cwe_catalog_id")
        )
        reference_rows = self._deduplicate_by_prefix(
            reference_rows, ("vulnerability_id", "url")
        )
        cpe_rows = self._deduplicate_by_prefix(
            cpe_rows, ("vulnerability_id", "criteria_uri", "match_criteria_id")
        )

        child_max = Config.NVD_DB_CHILD_WRITE_BATCH_SIZE
        self._execute_insert_chunks(CvssMetricORM, cvss_rows, max_rows=child_max)
        self._execute_insert_chunks(VulnerabilityCweORM, cwe_rows, max_rows=child_max)
        self._execute_insert_chunks(ReferenceLinkORM, reference_rows, max_rows=child_max)
        self._execute_insert_chunks(CpeMatchORM, cpe_rows, max_rows=child_max)

        raw_chunk_rows = self._build_raw_json_chunk_rows(
            changed_items, vulnerability_id_by_cve
        )
        self._execute_insert_chunks(
            VulnerabilityRawJsonChunkORM,
            raw_chunk_rows,
            max_rows=max(1, Config.NVD_DB_MAX_STATEMENT_BYTES // Config.NVD_RAW_JSON_CHUNK_BYTES),
            max_bytes=Config.NVD_DB_MAX_STATEMENT_BYTES,
        )

        return {
            "inserted": len(insert_items),
            "updated": len(update_items),
            "skipped": skipped,
        }

    def upsert_mapped_vulnerability(self, mapped: dict) -> tuple[str, int]:
        stats = self.bulk_upsert_mapped_vulnerabilities([mapped])
        cve_id = mapped["vulnerability"]["cve_id"]
        row_id = self.session.execute(
            select(VulnerabilityORM.id).where(VulnerabilityORM.cve_id == cve_id)
        ).scalar_one()
        if stats["inserted"]:
            action = "inserted"
        elif stats["updated"]:
            action = "updated"
        else:
            action = "skipped"
        return action, row_id


class SyncAuditRepository:
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

    def mark_success(self, audit: SyncAuditORM, total_fetched: int, total_inserted: int, total_updated: int, total_failed: int, last_successful_modified_at=None):
        audit.finished_at = func.now()
        audit.status_value = "SUCCESS"
        audit.total_fetched = total_fetched
        audit.total_inserted = total_inserted
        audit.total_updated = total_updated
        audit.total_failed = total_failed
        audit.last_successful_modified_at = last_successful_modified_at

    def mark_failed(self, audit: SyncAuditORM, error_message: str, total_fetched: int, total_inserted: int, total_updated: int, total_failed: int):
        audit.finished_at = func.now()
        audit.status_value = "FAILED"
        audit.total_fetched = total_fetched
        audit.total_inserted = total_inserted
        audit.total_updated = total_updated
        audit.total_failed = total_failed
        audit.error_message = error_message

    def mark_partial(self, audit: SyncAuditORM, total_fetched: int, total_inserted: int, total_updated: int, total_failed: int, last_successful_modified_at=None):
        audit.finished_at = func.now()
        audit.status_value = "PARTIAL"
        audit.total_fetched = total_fetched
        audit.total_inserted = total_inserted
        audit.total_updated = total_updated
        audit.total_failed = total_failed
        audit.last_successful_modified_at = last_successful_modified_at

    def get_latest_successful_incremental_time(self):
        stmt = (
            select(SyncAuditORM)
            .where(
                SyncAuditORM.status_value == "SUCCESS",
                SyncAuditORM.sync_type == "INCREMENTAL",
                SyncAuditORM.last_successful_modified_at.is_not(None),
            )
            .order_by(desc(SyncAuditORM.last_successful_modified_at), desc(SyncAuditORM.id))
            .limit(1)
        )
        row = self.session.execute(stmt).scalar_one_or_none()
        return row.last_successful_modified_at if row else None


class SyncStateRepository:
    """Persistent checkpoints stored in the existing app_settings table."""

    def __init__(self, session):
        self.session = session

    def get(self, key: str) -> str | None:
        stmt = select(AppSettingORM).where(AppSettingORM.setting_key == key).limit(1)
        row = self.session.execute(stmt).scalar_one_or_none()
        return row.setting_value if row else None

    def set(self, key: str, value: str) -> None:
        stmt = select(AppSettingORM).where(AppSettingORM.setting_key == key).limit(1)
        row = self.session.execute(stmt).scalar_one_or_none()
        if row is None:
            row = AppSettingORM(setting_key=key, setting_value=value)
            self.session.add(row)
        else:
            row.setting_value = value
        self.session.flush()

    def delete(self, key: str) -> None:
        stmt = select(AppSettingORM).where(AppSettingORM.setting_key == key).limit(1)
        row = self.session.execute(stmt).scalar_one_or_none()
        if row is not None:
            self.session.delete(row)
            self.session.flush()

    def get_int(self, key: str, default: int = 0) -> int:
        value = self.get(key)
        try:
            return int(value) if value is not None else default
        except (TypeError, ValueError):
            return default
