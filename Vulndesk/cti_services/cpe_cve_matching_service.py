from __future__ import annotations

from typing import Any, Dict, List, Optional

from .cpe_utils import Cpe23, clean_version, normalize_cpe_token, version_in_range
from .db_adapter import DbAdapter
from .service_registry import ServiceRegistry


# A single vendor:product can own far more CPE-match rows than any flat row
# cap (nginx has 700+, linux_kernel 160k+). The only rows that can match a
# detected version are (a) wildcard-version rows that carry a version range,
# and (b) rows pinned to the exact detected version; every other exact-version
# row is for a different version and can never match. Scanning just those two
# bounded sets -- range rows first, paged so the cap can never drop a range
# row -- keeps matching correct for popular products while staying bounded.
# The previous `... LIMIT 500` over an unordered `pattern1 OR pattern2`
# silently truncated the range rows away, so a correlation that existed
# (e.g. nginx 1.24.0 -> real CVEs) resolved to zero.
_CPE_MATCH_PAGE = 2000
_CPE_MATCH_SCAN_CAP = 200000


class CpeCveMatchingService:
    SERVICE_KEY = "vulnerability_correlation_service"

    def __init__(self, db: Optional[DbAdapter] = None, registry: Optional[ServiceRegistry] = None):
        self.db = db or DbAdapter()
        self.registry = registry or ServiceRegistry(self.db)

    def resolve_cpe_candidates(self, cpe_candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self.registry.is_enabled(self.SERVICE_KEY):
            return []
        self.registry.update_status(self.SERVICE_KEY, "running")
        try:
            out: List[Dict[str, Any]] = []
            for c in cpe_candidates:
                out.extend(self.resolve_one(c))
            self.registry.update_status(self.SERVICE_KEY, "idle")
            return self._dedupe(out)
        except Exception as e:
            self.registry.update_status(self.SERVICE_KEY, "error", str(e))
            raise

    def resolve_one(self, cpe_candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
        cpe_uri = cpe_candidate.get("cpe23_uri") or cpe_candidate.get("criteria_uri") or ""
        parsed = Cpe23.parse(cpe_uri)
        vendor = normalize_cpe_token(cpe_candidate.get("vendor") or parsed.vendor)
        product = normalize_cpe_token(cpe_candidate.get("product") or parsed.product)
        version = clean_version(cpe_candidate.get("version") or parsed.version)
        exact_rows = self._query_exact_cpe(cpe_uri)
        rows = exact_rows or self._query_vendor_product(vendor, product, version)
        matched = []
        for row in rows:
            if not version_in_range(version, row):
                continue
            detail = self._build_vulnerability_result(row, cpe_candidate, version)
            if detail:
                detail["match_method"] = "cpe_exact" if exact_rows else ("cpe_version_range" if version else "cpe_product_only")
                detail["match_confidence"] = self._confidence(cpe_candidate, exact=bool(exact_rows), version=bool(version))
                matched.append(detail)
        return matched

    def _query_exact_cpe(self, cpe_uri: str) -> List[Dict[str, Any]]:
        if not cpe_uri or not self.db.table_exists("cpe_matches"):
            return []
        return self.db.fetch_all(
            """
            SELECT * FROM cpe_matches
            WHERE criteria_uri = %(cpe_uri)s OR cpe23_uri = %(cpe_uri)s
            """ if self.db.has_column("cpe_matches", "cpe23_uri") else
            "SELECT * FROM cpe_matches WHERE criteria_uri = %(cpe_uri)s",
            {"cpe_uri": cpe_uri},
        )

    def _query_vendor_product(self, vendor: str, product: str, version: str = "") -> List[Dict[str, Any]]:
        if not product or not self.db.table_exists("cpe_matches"):
            return []
        if vendor:
            # Range rows (wildcard version) carry version_start/end bounds; fetch
            # them first and unbounded-by-arbitrary-cap so version_in_range always
            # sees the row whose range covers the detected version.
            rows = self._scan_cpe_matches(f"cpe:2.3:%:{vendor}:{product}:*:%")
            if version:
                seen = {r.get("id") for r in rows if r.get("id") is not None}
                exact = self._scan_cpe_matches(
                    f"cpe:2.3:%:{vendor}:{product}:{self._like_literal(version)}:%", escape=True)
                for row in exact:
                    rid = row.get("id")
                    if rid is None or rid not in seen:
                        rows.append(row)
            if rows:
                return rows
        # Vendor unknown or no vendor-scoped rows: bounded product-only fallback.
        return self._scan_cpe_matches(f"%:{product}:%")

    @staticmethod
    def _like_literal(value: str) -> str:
        return str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _scan_cpe_matches(self, pattern: str, *, escape: bool = False) -> List[Dict[str, Any]]:
        """Page through cpe_matches for a LIKE pattern, deterministically ordered,
        so no candidate row is lost to an arbitrary LIMIT. Bounded by a scan cap
        that only the largest products (linux_kernel) can approach."""
        if not self.db.table_exists("cpe_matches"):
            return []
        like = "criteria_uri LIKE %(pattern)s ESCAPE '\\\\'" if escape else "criteria_uri LIKE %(pattern)s"
        out: List[Dict[str, Any]] = []
        offset = 0
        while len(out) < _CPE_MATCH_SCAN_CAP:
            page = self.db.fetch_all(
                f"SELECT * FROM cpe_matches WHERE {like} ORDER BY id LIMIT %(limit)s OFFSET %(offset)s",
                {"pattern": pattern, "limit": _CPE_MATCH_PAGE, "offset": offset},
            )
            if not page:
                break
            out.extend(page)
            if len(page) < _CPE_MATCH_PAGE:
                break
            offset += _CPE_MATCH_PAGE
        return out

    def _build_vulnerability_result(self, cpe_row: Dict[str, Any], cpe_candidate: Dict[str, Any], detected_version: str) -> Optional[Dict[str, Any]]:
        vulnerability_id = cpe_row.get("vulnerability_id") or cpe_row.get("vuln_id") or cpe_row.get("cve_db_id")
        if not vulnerability_id:
            # Fallback: some dumps use cve_id directly on cpe_matches.
            cve_id = cpe_row.get("cve_id")
            vuln = self._get_vuln_by_cve(cve_id) if cve_id else None
        else:
            vuln = self._get_vuln_by_id(vulnerability_id)
        if not vuln:
            return None
        vuln_id = vuln.get("id") or vulnerability_id
        cvss = self._get_best_cvss(vuln_id)
        cwes = self._get_cwes(vuln_id)
        if not cwes:
            cwes = [{"cwe_id": None, "cwe_name": None}]
        out = []
        for cwe in cwes:
            out.append({
                "vulndesk_vulnerability_id": vuln_id,
                "cve_id": vuln.get("cve_id") or cpe_row.get("cve_id"),
                "description": vuln.get("description_text") or vuln.get("description"),
                "published_date": vuln.get("published_at") or vuln.get("published_date") or vuln.get("published"),
                "last_modified_date": vuln.get("modified_at") or vuln.get("last_modified_date") or vuln.get("last_modified"),
                "cwe_id": cwe.get("cwe_id"),
                "cwe_name": cwe.get("cwe_name") or cwe.get("name"),
                "severity": (cvss or {}).get("base_severity") or (cvss or {}).get("severity"),
                "cvss_score": (cvss or {}).get("base_score") or (cvss or {}).get("score"),
                "exploitability_score": (cvss or {}).get("exploitability_score"),
                "impact_score": (cvss or {}).get("impact_score"),
                "cpe23_uri": cpe_candidate.get("cpe23_uri") or cpe_row.get("criteria_uri"),
                "criteria_uri": cpe_row.get("criteria_uri"),
                "official_cpe23_uri": cpe_candidate.get("cpe23_uri"),
                "source_cpe_candidate_id": cpe_candidate.get("id"),
                "cpe_candidate_id": cpe_candidate.get("id"),
                "vulndesk_cpe_id": cpe_candidate.get("vulndesk_cpe_id") or cpe_candidate.get("source_cpe_dictionary_id"),
                "source_cpe_dictionary_id": cpe_candidate.get("source_cpe_dictionary_id") or cpe_candidate.get("vulndesk_cpe_id"),
                "cpe_name_id": cpe_candidate.get("cpe_name_id"),
                "cpe_title": cpe_candidate.get("title"),
                "technology_name": (
                    cpe_candidate.get("technology_name")
                    or cpe_candidate.get("product")
                    or cpe_candidate.get("technology")
                    or cpe_candidate.get("name")
                ),
                "technology_version": detected_version or cpe_candidate.get("technology_version") or cpe_candidate.get("version"),
                "cpe_match_row": cpe_row,
            })
        # This method returns one row in caller's loop. If multiple CWE, caller can handle list? Simpler: return first; caller calls _explode.
        return out[0] if out else None

    def _get_vuln_by_id(self, vulnerability_id: Any) -> Optional[Dict[str, Any]]:
        if not self.db.table_exists("vulnerabilities"):
            return None
        return self.db.fetch_one("SELECT * FROM vulnerabilities WHERE id = %(id)s", {"id": vulnerability_id})

    def _get_vuln_by_cve(self, cve_id: str) -> Optional[Dict[str, Any]]:
        if not cve_id or not self.db.table_exists("vulnerabilities"):
            return None
        return self.db.fetch_one("SELECT * FROM vulnerabilities WHERE cve_id = %(cve_id)s", {"cve_id": cve_id})

    def _get_best_cvss(self, vulnerability_id: Any) -> Optional[Dict[str, Any]]:
        if not vulnerability_id or not self.db.table_exists("cvss_metrics"):
            return None
        order_col = "base_score" if self.db.has_column("cvss_metrics", "base_score") else "score"
        return self.db.fetch_one(
            f"SELECT * FROM cvss_metrics WHERE vulnerability_id = %(id)s ORDER BY {order_col} DESC LIMIT 1",
            {"id": vulnerability_id},
        )

    def _get_cwes(self, vuln_id):
        """
        Resolve CWE entries linked to a vulnerability.
    
        This implementation is schema-tolerant because different VulnDesk
        database imports may name the CWE relation column differently:
        cwe_id, cwe, cwe_code, weakness_id, cwe_name, etc.
    
        If no CWE mapping is found, it returns [] instead of crashing the
        enrichment API.
        """
        def _safe_fetch(sql, params=None):
            try:
                return self.db.fetch_all(sql, params or {}) or []
            except Exception:
                return []
    
        def _get_value(row, *names):
            if row is None or not isinstance(row, dict):
                return None
            lower_map = {str(k).lower(): k for k in row.keys()}
            for name in names:
                key = lower_map.get(str(name).lower())
                if key is not None:
                    return row.get(key)
            return None
    
        def _normalize(rows):
            out = []
            seen = set()
            for r in rows or []:
                cwe = _get_value(r, "cwe_id", "cwe", "cwe_code", "weakness_id", "weakness", "cwe_name", "name")
                if cwe is None:
                    continue
                cwe = str(cwe).strip()
                if not cwe:
                    continue
                if cwe.upper().startswith("CWE-"):
                    cwe_id = cwe.upper()
                elif cwe.isdigit():
                    cwe_id = "CWE-" + cwe
                else:
                    cwe_id = cwe
                if cwe_id in seen:
                    continue
                seen.add(cwe_id)
                out.append({
                    "cwe_id": cwe_id,
                    "name": _get_value(r, "name", "cwe_name", "title") or "",
                    "description": _get_value(r, "description", "summary") or "",
                })
            return out
        
                # Fast path for current VulnDesk schema:
        # vulnerability_cwes(vulnerability_id, cwe_catalog_id)
        # cwe_catalog(id, cwe_id, cwe_name)
        if self.db.table_exists("vulnerability_cwes") and self.db.table_exists("cwe_catalog"):
            rows = _safe_fetch(
                """
                SELECT
                    cc.cwe_id AS cwe_id,
                    cc.cwe_name AS cwe_name,
                    cc.cwe_name AS name
                FROM vulnerability_cwes vc
                JOIN cwe_catalog cc ON cc.id = vc.cwe_catalog_id
                WHERE vc.vulnerability_id = %(vuln_id)s
                """,
                {"vuln_id": vuln_id}
            )
            normalized = _normalize(rows)
            if normalized:
                return normalized
    
        # 1) Try common relation-table/column combinations.
        direct_queries = [
            "SELECT vc.cwe_id AS cwe_id FROM vulnerability_cwes vc WHERE vc.vulnerability_id = %(vuln_id)s",
            "SELECT vc.cwe AS cwe_id FROM vulnerability_cwes vc WHERE vc.vulnerability_id = %(vuln_id)s",
            "SELECT vc.cwe_code AS cwe_id FROM vulnerability_cwes vc WHERE vc.vulnerability_id = %(vuln_id)s",
            "SELECT vc.weakness_id AS cwe_id FROM vulnerability_cwes vc WHERE vc.vulnerability_id = %(vuln_id)s",
            "SELECT vc.cwe_id AS cwe_id FROM vulnerability_cwe vc WHERE vc.vulnerability_id = %(vuln_id)s",
            "SELECT vc.cwe AS cwe_id FROM vulnerability_cwe vc WHERE vc.vulnerability_id = %(vuln_id)s",
            "SELECT vc.cwe_code AS cwe_id FROM vulnerability_cwe vc WHERE vc.vulnerability_id = %(vuln_id)s",
            "SELECT vc.weakness_id AS cwe_id FROM vulnerability_cwe vc WHERE vc.vulnerability_id = %(vuln_id)s",
            "SELECT vc.cwe_id AS cwe_id FROM cve_cwes vc WHERE vc.vulnerability_id = %(vuln_id)s",
            "SELECT vc.cwe AS cwe_id FROM cve_cwes vc WHERE vc.vulnerability_id = %(vuln_id)s",
            "SELECT vc.cwe_code AS cwe_id FROM cve_cwes vc WHERE vc.vulnerability_id = %(vuln_id)s",
            "SELECT vc.weakness_id AS cwe_id FROM cve_cwes vc WHERE vc.vulnerability_id = %(vuln_id)s",
            "SELECT vc.cwe_id AS cwe_id FROM cve_cwe vc WHERE vc.vulnerability_id = %(vuln_id)s",
            "SELECT vc.cwe AS cwe_id FROM cve_cwe vc WHERE vc.vulnerability_id = %(vuln_id)s",
            "SELECT vc.cwe_code AS cwe_id FROM cve_cwe vc WHERE vc.vulnerability_id = %(vuln_id)s",
            "SELECT vc.weakness_id AS cwe_id FROM cve_cwe vc WHERE vc.vulnerability_id = %(vuln_id)s",
            "SELECT vc.cwe_id AS cwe_id FROM vulnerability_cwes vc WHERE vc.vuln_id = %(vuln_id)s",
            "SELECT vc.cwe AS cwe_id FROM vulnerability_cwes vc WHERE vc.vuln_id = %(vuln_id)s",
            "SELECT vc.cwe_code AS cwe_id FROM vulnerability_cwes vc WHERE vc.vuln_id = %(vuln_id)s",
            "SELECT vc.weakness_id AS cwe_id FROM vulnerability_cwes vc WHERE vc.vuln_id = %(vuln_id)s",
        ]
    
        for sql in direct_queries:
            normalized = _normalize(_safe_fetch(sql, {"vuln_id": vuln_id}))
            if normalized:
                return normalized
    
        # 2) Schema discovery fallback.
        table_rows = _safe_fetch(
            "SELECT TABLE_NAME AS table_name "
            "FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND (LOWER(TABLE_NAME) LIKE '%%cwe%%' OR LOWER(TABLE_NAME) LIKE '%%weakness%%')"
        )
    
        vuln_col_candidates = [
            "vulnerability_id", "vuln_id", "id_vulnerability", "id_vuln",
            "cve_id", "id_cve", "cve", "vulnerability"
        ]
        cwe_col_candidates = [
            "cwe_id", "cwe", "cwe_code", "weakness_id", "weakness",
            "cwe_name", "name"
        ]
    
        for trow in table_rows:
            table_name = _get_value(trow, "table_name", "TABLE_NAME")
            if not table_name:
                continue
    
            col_rows = _safe_fetch(
                "SELECT COLUMN_NAME AS column_name "
                "FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %(table_name)s",
                {"table_name": table_name}
            )
    
            col_map = {}
            for crow in col_rows:
                col_name = _get_value(crow, "column_name", "COLUMN_NAME")
                if col_name:
                    col_map[str(col_name).lower()] = str(col_name)
    
            vuln_col = next((col_map[c] for c in vuln_col_candidates if c in col_map), None)
            cwe_col = next((col_map[c] for c in cwe_col_candidates if c in col_map), None)
    
            if not vuln_col or not cwe_col:
                continue
    
            sql = (
                f"SELECT `{cwe_col}` AS cwe_id "
                f"FROM `{table_name}` "
                f"WHERE `{vuln_col}` = %(vuln_id)s"
            )
            normalized = _normalize(_safe_fetch(sql, {"vuln_id": vuln_id}))
            if normalized:
                return normalized
    
        # 3) Never break enrichment only because CWE mapping is unavailable.
        return []
    def _confidence(self, cpe_candidate: Dict[str, Any], exact: bool, version: bool) -> float:
        base = float(cpe_candidate.get("confidence") or 0.5)
        if exact and version:
            return min(0.98, max(base, 0.90))
        if exact:
            return min(0.90, max(base, 0.80))
        if version:
            return min(0.85, max(base, 0.65))
        return min(0.65, max(base, 0.45))

    def _dedupe(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        best: Dict[tuple, Dict[str, Any]] = {}
        for r in rows:
            key = (r.get("cve_id"), r.get("cwe_id"), r.get("source_cpe_candidate_id"))
            if key not in best or float(r.get("match_confidence") or 0) > float(best[key].get("match_confidence") or 0):
                best[key] = r
        return list(best.values())
