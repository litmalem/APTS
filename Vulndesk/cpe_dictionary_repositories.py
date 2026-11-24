from __future__ import annotations

from typing import Any, Dict, Iterable, List

from sqlalchemy import and_, desc, func, or_, select

from orm_models import NvdCpeDictionaryORM


class CpeDictionaryRepository:
    def __init__(self, session):
        self.session = session

    def _apply_filters(self, stmt, keyword: str | None = None, include_deprecated: bool = False):
        if not include_deprecated:
            stmt = stmt.where(NvdCpeDictionaryORM.deprecated.is_(False))
        keyword = (keyword or "").strip()
        if keyword:
            kw = f"%{keyword.lower()}%"
            stmt = stmt.where(or_(
                func.lower(NvdCpeDictionaryORM.cpe_name_id).like(kw),
                func.lower(NvdCpeDictionaryORM.cpe23_uri).like(kw),
                func.lower(NvdCpeDictionaryORM.vendor).like(kw),
                func.lower(NvdCpeDictionaryORM.product).like(kw),
                func.lower(NvdCpeDictionaryORM.version).like(kw),
                func.lower(NvdCpeDictionaryORM.title).like(kw),
            ))
        return stmt

    def list_items(self, keyword: str | None = None, include_deprecated: bool = False, limit: int = 100, offset: int = 0) -> list[dict]:
        stmt = select(NvdCpeDictionaryORM)
        stmt = self._apply_filters(stmt, keyword, include_deprecated)
        stmt = stmt.order_by(desc(NvdCpeDictionaryORM.modified_at_source), NvdCpeDictionaryORM.vendor, NvdCpeDictionaryORM.product).limit(int(limit)).offset(int(offset))
        rows = self.session.execute(stmt).scalars().all()
        return [self.to_dict(r, compact=True) for r in rows]

    def count_items(self, keyword: str | None = None, include_deprecated: bool = False) -> int:
        stmt = select(func.count(NvdCpeDictionaryORM.id)).select_from(NvdCpeDictionaryORM)
        stmt = self._apply_filters(stmt, keyword, include_deprecated)
        return int(self.session.execute(stmt).scalar_one())

    def get_detail(self, cpe_id: int) -> dict | None:
        row = self.session.get(NvdCpeDictionaryORM, int(cpe_id))
        return self.to_dict(row) if row else None

    def get_by_uri(self, cpe23_uri: str) -> dict | None:
        if not cpe23_uri:
            return None
        row = self.session.execute(
            select(NvdCpeDictionaryORM).where(NvdCpeDictionaryORM.cpe23_uri == cpe23_uri).limit(1)
        ).scalar_one_or_none()
        return self.to_dict(row) if row else None

    def search_matching_products(self, products: Iterable[str], version: str = '', limit: int = 300, vendors=None) -> list[dict]:
        """Filter identity/version before LIMIT; avoid broad title/URI scans and raw JSON."""
        versions = [version, '*', ''] if version else ['*', '', '-']
        columns = ('id', 'cpe_name_id', 'cpe23_uri', 'part', 'vendor', 'product', 'version',
                   'update_value', 'title', 'deprecated', 'source_name')
        stmt = select(*(getattr(NvdCpeDictionaryORM, key) for key in columns)).where(
            NvdCpeDictionaryORM.product.in_(sorted(products)),
            NvdCpeDictionaryORM.deprecated.is_(False),
            NvdCpeDictionaryORM.version.in_(versions),
            or_(NvdCpeDictionaryORM.update_value.in_(['', '*', '-']), NvdCpeDictionaryORM.update_value.is_(None)),
        ).order_by(desc(NvdCpeDictionaryORM.version == version), NvdCpeDictionaryORM.cpe23_uri)
        if vendors:
            stmt = stmt.where(NvdCpeDictionaryORM.vendor.in_(sorted(vendors)))
        return [dict(row) for row in self.session.execute(stmt.limit(int(limit))).mappings().all()]

    def product_identities(self, products: Iterable[str], limit: int = 3, vendors=None) -> list[dict]:
        """Product evidence, without assigning a dictionary release to the target."""
        model = NvdCpeDictionaryORM
        stmt = select(model.part, model.vendor, model.product,
                      func.min(model.cpe23_uri).label('reference_cpe23_uri'),
                      func.count(model.id).label('dictionary_entry_count')).where(
            model.product.in_(sorted(products)), model.deprecated.is_(False)
        ).group_by(model.part, model.vendor, model.product).order_by(
            model.vendor, model.product, model.part).limit(limit)
        if vendors:
            stmt = stmt.where(model.vendor.in_(sorted(vendors)))
        return [dict(row) for row in self.session.execute(stmt).mappings().all()]

    def search_candidates(self, terms: Iterable[str], version: str | None = None, include_deprecated: bool = False, limit: int = 300) -> list[dict]:
        terms = [str(t).strip().lower() for t in terms if str(t or "").strip()]
        if not terms:
            return []
        conditions = []
        for term in terms:
            kw = f"%{term}%"
            conditions.extend([
                func.lower(NvdCpeDictionaryORM.vendor).like(kw),
                func.lower(NvdCpeDictionaryORM.product).like(kw),
                func.lower(NvdCpeDictionaryORM.title).like(kw),
                func.lower(NvdCpeDictionaryORM.cpe23_uri).like(kw),
            ])
        stmt = select(NvdCpeDictionaryORM).where(or_(*conditions))
        if not include_deprecated:
            stmt = stmt.where(NvdCpeDictionaryORM.deprecated.is_(False))
        if version:
            v = str(version).strip().lower()
            stmt = stmt.order_by(
                desc(NvdCpeDictionaryORM.version == v),
                desc(NvdCpeDictionaryORM.modified_at_source),
            )
        else:
            stmt = stmt.order_by(desc(NvdCpeDictionaryORM.modified_at_source))
        rows = self.session.execute(stmt.limit(int(limit))).scalars().all()
        return [self.to_dict(r, compact=False) for r in rows]

    def upsert_mapped_cpe(self, mapped: Dict[str, Any]) -> tuple[str, int]:
        cpe_name_id = (mapped.get("cpe_name_id") or "").strip()
        cpe23_uri = (mapped.get("cpe23_uri") or "").strip()
        if not cpe_name_id and not cpe23_uri:
            raise ValueError("mapped CPE has neither cpe_name_id nor cpe23_uri")

        row = None
        if cpe_name_id:
            row = self.session.execute(
                select(NvdCpeDictionaryORM).where(NvdCpeDictionaryORM.cpe_name_id == cpe_name_id)
            ).scalar_one_or_none()
        if row is None and cpe23_uri:
            row = self.session.execute(
                select(NvdCpeDictionaryORM).where(NvdCpeDictionaryORM.cpe23_uri == cpe23_uri)
            ).scalar_one_or_none()

        created = False
        if row is None:
            row = NvdCpeDictionaryORM()
            self.session.add(row)
            self.session.flush()
            created = True

        for key, value in mapped.items():
            if hasattr(row, key):
                setattr(row, key, value)
        self.session.flush()
        return ("inserted" if created else "updated", row.id)

    @staticmethod
    def to_dict(row: NvdCpeDictionaryORM, compact: bool = False) -> dict:
        base = {
            "id": row.id,
            "cpe_name_id": row.cpe_name_id,
            "cpe23_uri": row.cpe23_uri,
            "part": row.part,
            "vendor": row.vendor,
            "product": row.product,
            "version": row.version,
            "title": row.title,
            "deprecated": row.deprecated,
            "created_at_source": row.created_at_source,
            "modified_at_source": row.modified_at_source,
            "last_synced_at": row.last_synced_at,
            "source_name": row.source_name,
        }
        if compact:
            return base
        base.update({
            "update_value": row.update_value,
            "edition": row.edition,
            "language": row.language,
            "sw_edition": row.sw_edition,
            "target_sw": row.target_sw,
            "target_hw": row.target_hw,
            "other": row.other,
            "titles_json": row.titles_json,
            "references_json": row.references_json,
            "deprecated_by_json": row.deprecated_by_json,
            "raw_json": row.raw_json,
        })
        return base
