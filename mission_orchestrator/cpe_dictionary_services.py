from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, Iterable, List

from config import Config
from db import session_scope
from nvd_cpe_api import NvdCpeApiClient
from cpe_dictionary_mapper import map_nvd_cpe_product, normalize_cpe_value
from cpe_dictionary_repositories import CpeDictionaryRepository
from repositories import SyncAuditRepository


ALIASES: dict[str, list[str]] = {
    "apache": ["apache", "http_server", "apache http server"],
    "apache http server": ["apache", "http_server", "apache http server"],
    "php": ["php"],
    "nginx": ["nginx"],
    "wordpress": ["wordpress"],
    "jquery": ["jquery"],
    "bootstrap": ["bootstrap", "getbootstrap"],
    "microsoft iis": ["microsoft", "internet_information_services", "iis"],
    "iis": ["microsoft", "internet_information_services", "iis"],
    "joomla": ["joomla"],
    "drupal": ["drupal"],
    "laravel": ["laravel"],
    "django": ["django", "djangoproject"],
    "tomcat": ["tomcat", "apache tomcat"],
    "next.js": ["next.js", "nextjs", "next"],
    "react": ["react", "reactjs"],
}


class CpeDictionaryService:
    def list_cpes(self, keyword: str | None = None, include_deprecated: bool = False, limit: int = 100, offset: int = 0) -> list[dict]:
        with session_scope() as session:
            return CpeDictionaryRepository(session).list_items(keyword, include_deprecated, limit, offset)

    def count_cpes(self, keyword: str | None = None, include_deprecated: bool = False) -> int:
        with session_scope() as session:
            return CpeDictionaryRepository(session).count_items(keyword, include_deprecated)

    def get_cpe_detail(self, cpe_id: int) -> dict | None:
        with session_scope() as session:
            return CpeDictionaryRepository(session).get_detail(cpe_id)

    def match_technologies(self, technologies: list[dict[str, Any]], per_technology_limit: int = 3, auto_fetch: bool | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for tech in technologies or []:
            for row in self.match_technology(tech, limit=per_technology_limit, auto_fetch=auto_fetch):
                cpe_uri = row.get("cpe23_uri")
                if not cpe_uri or cpe_uri in seen:
                    continue
                seen.add(cpe_uri)
                out.append(row)
        return out

    def match_technology(self, technology: dict[str, Any], limit: int = 5, auto_fetch: bool | None = None) -> list[dict[str, Any]]:
        name = (technology.get("technology_name") or technology.get("name") or technology.get("product") or "").strip()
        version = (technology.get("technology_version") or technology.get("version") or "").strip()
        if not name:
            return []
        auto_fetch = Config.NVD_CPE_AUTO_FETCH_ON_MATCH if auto_fetch is None else bool(auto_fetch)
        terms = self._terms_for_name(name)

        with session_scope() as session:
            repo = CpeDictionaryRepository(session)
            rows = repo.search_candidates(terms, version=version, include_deprecated=False, limit=300)

        if auto_fetch and not self._has_reasonable_match(rows, name, version):
            # Fetch a bounded page from the official dictionary, then retry locally.
            keyword = f"{name} {version}".strip()
            try:
                CpeDictionarySyncService().sync_keyword(keyword, max_pages=1, page_size=min(100, Config.NVD_CPE_PAGE_SIZE))
            except Exception:
                # Matching should continue with local data even when NVD is temporarily unavailable.
                pass
            with session_scope() as session:
                repo = CpeDictionaryRepository(session)
                rows = repo.search_candidates(terms, version=version, include_deprecated=False, limit=300)

        ranked = sorted(
            (self._candidate_from_row(row, technology, name, version) for row in rows),
            key=lambda r: (-float(r.get("confidence") or 0), r.get("cpe23_uri") or ""),
        )
        deduped: list[dict[str, Any]] = []
        seen = set()
        for r in ranked:
            if r["cpe23_uri"] in seen:
                continue
            seen.add(r["cpe23_uri"])
            deduped.append(r)
            if len(deduped) >= int(limit):
                break
        return deduped

    def _candidate_from_row(self, row: dict[str, Any], technology: dict[str, Any], name: str, version: str) -> dict[str, Any]:
        score, method, reason_bits = self._score(row, name, version)
        return {
            "vulndesk_cpe_id": row.get("id"),
            "source_cpe_dictionary_id": row.get("id"),
            "cpe_name_id": row.get("cpe_name_id"),
            "cpe23_uri": row.get("cpe23_uri"),
            "criteria_uri": row.get("cpe23_uri"),
            "part": row.get("part"),
            "vendor": row.get("vendor"),
            "product": row.get("product"),
            "version": row.get("version"),
            "technology_name": name,
            "technology_version": version or technology.get("technology_version") or technology.get("version"),
            "detected_technology_id": technology.get("id") or technology.get("detected_technology_id") or technology.get("technology_id"),
            "confidence": score,
            "match_confidence": score,
            "match_method": method,
            "is_official": True,
            "deprecated": bool(row.get("deprecated")),
            "title": row.get("title"),
            "source_name": row.get("source_name") or "NVD Official CPE Dictionary",
            "reason": "Official CPE Dictionary match: " + "; ".join(reason_bits),
        }

    def _score(self, row: dict[str, Any], name: str, version: str) -> tuple[float, str, list[str]]:
        name_norm = self._norm(name)
        aliases = {self._norm(x) for x in self._terms_for_name(name)}
        vendor = self._norm(row.get("vendor"))
        product = self._norm(row.get("product"))
        title = self._norm(row.get("title"))
        row_version = self._norm(row.get("version"))
        version_norm = self._norm(version)
        score = 0.45
        bits: list[str] = []
        if product in aliases or product == name_norm:
            score += 0.25
            bits.append(f"product={row.get('product')}")
        elif any(a and a in product for a in aliases):
            score += 0.18
            bits.append(f"product contains alias ({row.get('product')})")
        if vendor in aliases or vendor == name_norm:
            score += 0.12
            bits.append(f"vendor={row.get('vendor')}")
        if any(a and a in title for a in aliases):
            score += 0.08
            bits.append("title contains technology name")
        if version_norm and row_version == version_norm:
            score += 0.25
            bits.append(f"exact version={row.get('version')}")
            method = "official_cpe_exact_version"
        elif version_norm and not row_version:
            score -= 0.03
            bits.append("dictionary version is wildcard/empty")
            method = "official_cpe_product_only"
        elif version_norm:
            score -= 0.08
            bits.append(f"version differs: dictionary={row.get('version') or '-'}, detected={version}")
            method = "official_cpe_product_only"
        else:
            method = "official_cpe_product_only"
        if row.get("deprecated"):
            score -= 0.20
            bits.append("deprecated CPE")
        score = max(0.05, min(0.99, round(score, 4)))
        if not bits:
            bits.append("keyword/title match")
        return score, method, bits

    def _has_reasonable_match(self, rows: list[dict[str, Any]], name: str, version: str) -> bool:
        if not rows:
            return False
        for row in rows:
            score, _, _ = self._score(row, name, version)
            if score >= (0.75 if version else 0.62):
                return True
        return False

    def _terms_for_name(self, name: str) -> list[str]:
        key = self._norm(name)
        terms = [name, key]
        terms.extend(ALIASES.get(key, []))
        # Tokenize names such as "Apache/2.4" or "Microsoft-IIS".
        terms.extend(t for t in re.split(r"[^a-zA-Z0-9_.+-]+", name.lower()) if len(t) >= 3)
        return sorted({t for t in terms if t})

    @staticmethod
    def _norm(value: Any) -> str:
        return normalize_cpe_value(value).replace(" ", "_").lower()


class CpeDictionarySyncService:
    def __init__(self):
        self.api_client = NvdCpeApiClient()

    def sync_keyword(self, keyword: str, max_pages: int = 1, page_size: int | None = None, progress_callback: Callable[[dict], None] | None = None) -> dict:
        keyword = (keyword or "").strip()
        if not keyword:
            raise ValueError("Keyword CPE tidak boleh kosong.")
        return self._sync_pages(
            mode="CPE_KEYWORD",
            page_fetcher=lambda start, size: self.api_client.search_keyword(keyword, start_index=start, results_per_page=size),
            max_pages=max_pages,
            page_size=page_size or Config.NVD_CPE_PAGE_SIZE,
            progress_callback=progress_callback,
            current_type=keyword,
        )

    def sync_match_string(self, cpe_match_string: str, max_pages: int = 1, page_size: int | None = None, progress_callback: Callable[[dict], None] | None = None) -> dict:
        cpe_match_string = (cpe_match_string or "").strip()
        if not cpe_match_string:
            raise ValueError("CPE match string tidak boleh kosong.")
        return self._sync_pages(
            mode="CPE_MATCH_STRING",
            page_fetcher=lambda start, size: self.api_client.search_match_string(cpe_match_string, start_index=start, results_per_page=size),
            max_pages=max_pages,
            page_size=page_size or Config.NVD_CPE_PAGE_SIZE,
            progress_callback=progress_callback,
            current_type=cpe_match_string,
        )

    def sync_modified_range(
        self,
        last_mod_start_date,
        last_mod_end_date,
        max_pages: int = 1,
        page_size: int | None = None,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> dict:
        result = self._sync_pages(
            mode="CPE_INCREMENTAL",
            page_fetcher=lambda start, size: self.api_client.fetch_modified_range(
                start_index=start, results_per_page=size,
                last_mod_start_date=last_mod_start_date, last_mod_end_date=last_mod_end_date,
            ),
            max_pages=max_pages,
            page_size=page_size or Config.NVD_CPE_PAGE_SIZE,
            progress_callback=progress_callback,
            current_type="last-modified-window",
        )
        if result.get("status") == "SUCCESS":
            result["last_successful_modified_at"] = last_mod_end_date
        return result

    def sync_first_pages(self, max_pages: int = 1, page_size: int | None = None, progress_callback: Callable[[dict], None] | None = None) -> dict:
        return self._sync_pages(
            mode="CPE_PAGE",
            page_fetcher=lambda start, size: self.api_client.fetch_page(start_index=start, results_per_page=size),
            max_pages=max_pages,
            page_size=page_size or Config.NVD_CPE_PAGE_SIZE,
            progress_callback=progress_callback,
            current_type="all-products-page",
        )

    def _sync_pages(self, mode: str, page_fetcher, max_pages: int, page_size: int, progress_callback=None, current_type: str | None = None) -> dict:
        total_fetched = total_inserted = total_updated = total_failed = 0
        max_pages = max(1, int(max_pages))
        page_size = max(1, min(int(page_size), 2000))
        with session_scope() as session:
            audit_repo = SyncAuditRepository(session)
            audit = audit_repo.create_running(mode, page_size=page_size)
            session.commit()
            repo = CpeDictionaryRepository(session)
            try:
                total_results = None
                for page_no in range(max_pages):
                    start_index = page_no * page_size
                    payload = page_fetcher(start_index, page_size)
                    products = payload.get("products") or []
                    total_results = payload.get("totalResults", total_results)
                    for item in products:
                        try:
                            mapped = map_nvd_cpe_product(item)
                            action, _ = repo.upsert_mapped_cpe(mapped)
                            total_fetched += 1
                            if action == "inserted":
                                total_inserted += 1
                            else:
                                total_updated += 1
                        except Exception as item_error:
                            total_failed += 1
                            print(f"[{mode}] failed CPE item: {item_error}")
                    session.commit()
                    self._emit(progress_callback, {
                        "mode": mode,
                        "current_page": page_no + 1,
                        "total_pages": max_pages,
                        "current_type": current_type,
                        "total_results": total_results,
                        "total_fetched": total_fetched,
                        "total_inserted": total_inserted,
                        "total_updated": total_updated,
                        "total_failed": total_failed,
                    })
                    if len(products) < page_size:
                        break
                    time.sleep(Config.NVD_CPE_REQUEST_DELAY_SECONDS)
                complete = total_results is None or total_fetched >= int(total_results or 0)
                status = "SUCCESS" if complete else "PARTIAL"
                if complete:
                    audit_repo.mark_success(audit, total_fetched, total_inserted, total_updated, total_failed)
                else:
                    audit_repo.mark_partial(audit, total_fetched, total_inserted, total_updated, total_failed)
                session.commit()
                return {
                    "status": status,
                    "mode": mode,
                    "total_results": total_results,
                    "total_fetched": total_fetched,
                    "total_inserted": total_inserted,
                    "total_updated": total_updated,
                    "total_failed": total_failed,
                }
            except Exception as exc:
                session.rollback()
                with session_scope() as session2:
                    audit2 = session2.get(type(audit), audit.id)
                    if audit2 is not None:
                        SyncAuditRepository(session2).mark_failed(audit2, str(exc), total_fetched, total_inserted, total_updated, total_failed)
                        session2.commit()
                raise

    @staticmethod
    def _emit(callback, payload: dict) -> None:
        if callback:
            callback(payload)
