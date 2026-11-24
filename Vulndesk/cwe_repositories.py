from __future__ import annotations

from sqlalchemy import select, func, or_, desc

from orm_models import CweCatalogORM, VulnerabilityCweORM
from cwe_mapper import normalize_cwe_id


class CweCatalogRepository:
    def __init__(self, session):
        self.session = session

    def _apply_keyword(self, stmt, keyword: str | None):
        keyword = (keyword or "").strip()
        if not keyword:
            return stmt
        normalized = normalize_cwe_id(keyword)
        kw = f"%{keyword}%"
        conditions = [
            CweCatalogORM.cwe_id.ilike(kw),
            CweCatalogORM.cwe_name.ilike(kw),
            CweCatalogORM.description_text.ilike(kw),
            CweCatalogORM.extended_description.ilike(kw),
        ]
        if normalized:
            conditions.append(CweCatalogORM.cwe_id == normalized)
        return stmt.where(or_(*conditions))

    def list_items(self, keyword: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        cve_count_sq = (
            select(
                VulnerabilityCweORM.cwe_catalog_id,
                func.count(VulnerabilityCweORM.id).label("cve_count"),
            )
            .group_by(VulnerabilityCweORM.cwe_catalog_id)
            .subquery()
        )
        cve_count_col = func.coalesce(cve_count_sq.c.cve_count, 0).label("cve_count")
        stmt = (
            select(
                CweCatalogORM.id,
                CweCatalogORM.cwe_id,
                CweCatalogORM.cwe_name,
                CweCatalogORM.abstraction,
                CweCatalogORM.status_value,
                CweCatalogORM.likelihood_of_exploit,
                CweCatalogORM.description_text,
                CweCatalogORM.api_synced_at,
                cve_count_col,
            )
            .select_from(CweCatalogORM)
            .outerjoin(cve_count_sq, cve_count_sq.c.cwe_catalog_id == CweCatalogORM.id)
        )
        stmt = self._apply_keyword(stmt, keyword)
        stmt = stmt.order_by(desc(CweCatalogORM.api_synced_at), CweCatalogORM.cwe_id).limit(int(limit)).offset(int(offset))
        rows = self.session.execute(stmt).all()
        return [
            {
                "id": row[0],
                "cwe_id": row[1],
                "cwe_name": row[2],
                "abstraction": row[3],
                "status_value": row[4],
                "likelihood_of_exploit": row[5],
                "description_text": row[6],
                "api_synced_at": row[7],
                "cve_count": int(row[8] or 0),
            }
            for row in rows
        ]

    def count_items(self, keyword: str | None = None) -> int:
        stmt = select(func.count(CweCatalogORM.id)).select_from(CweCatalogORM)
        stmt = self._apply_keyword(stmt, keyword)
        return int(self.session.execute(stmt).scalar_one())

    def get_detail_by_cwe_id(self, cwe_id: str) -> dict | None:
        normalized = normalize_cwe_id(cwe_id)
        if not normalized:
            return None
        row = self.session.execute(
            select(CweCatalogORM).where(CweCatalogORM.cwe_id == normalized)
        ).scalar_one_or_none()
        if row is None:
            return None
        return self.to_dict(row)

    def list_known_cwe_ids(self, only_missing_details: bool = False) -> list[str]:
        stmt = select(CweCatalogORM.cwe_id).order_by(CweCatalogORM.cwe_id)
        if only_missing_details:
            stmt = stmt.where(
                or_(
                    CweCatalogORM.cwe_name.is_(None),
                    CweCatalogORM.cwe_name == "",
                    CweCatalogORM.description_text.is_(None),
                    CweCatalogORM.description_text == "",
                )
            )
        rows = self.session.execute(stmt).scalars().all()
        result: list[str] = []
        for value in rows:
            normalized = normalize_cwe_id(value)
            if normalized and normalized.startswith("CWE-"):
                result.append(normalized)
        return sorted(set(result), key=lambda x: int(x.split("-")[1]) if x.split("-")[1].isdigit() else 0)

    def upsert_mapped_cwe(self, mapped: dict) -> tuple[str, int]:
        cwe_id = normalize_cwe_id(mapped.get("cwe_id"))
        if not cwe_id:
            raise ValueError("mapped CWE has no valid cwe_id")

        existing = self.session.execute(
            select(CweCatalogORM).where(CweCatalogORM.cwe_id == cwe_id)
        ).scalar_one_or_none()

        created = False
        if existing is None:
            existing = CweCatalogORM(cwe_id=cwe_id)
            self.session.add(existing)
            self.session.flush()
            created = True

        for key, value in mapped.items():
            if key == "cwe_id":
                continue
            if not hasattr(existing, key):
                continue
            # Do not erase useful local values with nulls from a partial API payload.
            if value is None and getattr(existing, key, None) not in (None, ""):
                continue
            setattr(existing, key, value)

        self.session.flush()
        return ("inserted" if created else "updated", existing.id)

    @staticmethod
    def to_dict(row: CweCatalogORM) -> dict:
        return {
            "id": row.id,
            "cwe_id": row.cwe_id,
            "cwe_name": row.cwe_name,
            "cwe_url": row.cwe_url,
            "description_text": row.description_text,
            "extended_description": row.extended_description,
            "abstraction": row.abstraction,
            "structure_value": row.structure_value,
            "status_value": row.status_value,
            "likelihood_of_exploit": row.likelihood_of_exploit,
            "source_name": row.source_name,
            "api_version": row.api_version,
            "api_synced_at": row.api_synced_at,
            "related_weaknesses_json": row.related_weaknesses_json,
            "alternate_terms_json": row.alternate_terms_json,
            "raw_json": row.raw_json,
        }
