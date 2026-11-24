"""Regression tests for CpeCveMatchingService version-range correlation.

Guards the bug where `_query_vendor_product` applied a flat `LIMIT 500` over an
unordered `pattern1 OR pattern2` query, so for any product with more than 500
CPE-match rows (nginx has 700+, linux_kernel 160k+) the version-range row that
actually covered the detected version could be truncated away before
`version_in_range` ever saw it -- resolving a real correlation to zero.
"""
import re

from cti_services.cpe_cve_matching_service import CpeCveMatchingService
from cti_services.cpe_utils import version_in_range


class _FakeDb:
    """Minimal db adapter that honours LIKE + ORDER BY id + LIMIT/OFFSET so the
    service's pagination is exercised exactly as against MySQL."""

    def __init__(self, cpe_rows):
        self._rows = cpe_rows

    def table_exists(self, name):
        return name == "cpe_matches"

    def has_column(self, table, column):
        return False

    @staticmethod
    def _like(pattern, value):
        # Translate a SQL LIKE pattern (% -> any run, _ -> any char) to a regex;
        # every other char, '*' included, is matched literally.
        out = ["^"]
        for ch in pattern:
            if ch == "%":
                out.append(".*")
            elif ch == "_":
                out.append(".")
            else:
                out.append(re.escape(ch))
        out.append("$")
        return re.match("".join(out), value) is not None

    def fetch_all(self, sql, params=None):
        params = params or {}
        if "cpe_matches" not in sql:
            return []
        pattern = params.get("pattern") or params.get("pattern1") or ""
        matched = [r for r in self._rows if self._like(pattern, r["criteria_uri"])]
        matched.sort(key=lambda r: r["id"])
        if "OFFSET" in sql:
            offset = params.get("offset", 0)
            limit = params.get("limit", len(matched))
            return matched[offset:offset + limit]
        if "LIMIT" in sql:  # legacy flat-limit shape, should no longer be used
            return matched[:500]
        return matched

    def fetch_one(self, sql, params=None):
        return None


def _nginx_rows():
    rows = []
    # 700 non-covering exact-version rows (old pattern2 noise that filled the cap).
    for i in range(700):
        rows.append({
            "id": i + 1,
            "criteria_uri": f"cpe:2.3:a:f5:nginx:0.{i}.0:*:*:*:*:*:*:*",
            "version_start_including": None, "version_start_excluding": None,
            "version_end_including": None, "version_end_excluding": None,
            "vulnerability_id": None, "cve_id": None,
        })
    # The single wildcard-version range row that covers 1.24.0, placed last so
    # an arbitrary LIMIT 500 over unordered rows would drop it.
    rows.append({
        "id": 10_000,
        "criteria_uri": "cpe:2.3:a:f5:nginx:*:*:*:*:*:*:*:*",
        "version_start_including": "1.9.5", "version_start_excluding": None,
        "version_end_including": "1.25.2", "version_end_excluding": None,
        "vulnerability_id": "V-RAPID-RESET", "cve_id": "CVE-2023-44487",
    })
    return rows


def test_version_range_row_survives_beyond_legacy_500_cap():
    svc = CpeCveMatchingService(db=_FakeDb(_nginx_rows()))
    rows = svc._query_vendor_product("f5", "nginx", "1.24.0")
    covering = [r for r in rows if version_in_range("1.24.0", r)]
    assert any(r["cve_id"] == "CVE-2023-44487" for r in covering), (
        "version-range row covering nginx 1.24.0 must be returned, not truncated"
    )


def test_wildcard_version_rows_are_fetched_first():
    # Range rows (wildcard version) must be scanned ahead of exact-version noise
    # so the scan cap can never drop a row that carries a range.
    svc = CpeCveMatchingService(db=_FakeDb(_nginx_rows()))
    rows = svc._query_vendor_product("f5", "nginx", "1.24.0")
    first = rows[0]["criteria_uri"]
    assert first == "cpe:2.3:a:f5:nginx:*:*:*:*:*:*:*:*"


def test_product_only_fallback_when_vendor_absent():
    rows = [{
        "id": 1, "criteria_uri": "cpe:2.3:a:f5:nginx:*:*:*:*:*:*:*:*",
        "version_start_including": "1.9.5", "version_start_excluding": None,
        "version_end_including": "1.25.2", "version_end_excluding": None,
        "vulnerability_id": "V", "cve_id": "CVE-2023-44487",
    }]
    svc = CpeCveMatchingService(db=_FakeDb(rows))
    # Vendor unknown (empty) -> product-only fallback still finds the row.
    out = svc._query_vendor_product("", "nginx", "1.24.0")
    assert out and out[0]["cve_id"] == "CVE-2023-44487"
