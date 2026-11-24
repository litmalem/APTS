# patch_vulndesk_cwe_lookup_v2.py
# Robust patch for VulnDesk cti_services/cpe_cve_matching_service.py
# Fixes: pymysql.err.OperationalError: (1054, "Unknown column 'vc.cwe_id' in 'field list'")
#
# Usage:
#   cd /d D:\vulndesk
#   .venv\Scripts\python patch_vulndesk_cwe_lookup_v2.py
#
# Or:
#   .venv\Scripts\python patch_vulndesk_cwe_lookup_v2.py D:\vulndesk\cti_services\cpe_cve_matching_service.py

from pathlib import Path
from datetime import datetime
import py_compile
import re
import shutil
import sys

METHOD_NAME = "_get_cwes"


def find_method_bounds(lines, method_name):
    """
    Find a Python class method by line scanning instead of a strict regex.
    This works even when the method has type hints, comments, or different spacing.
    """
    method_re = re.compile(r"^([ \t]*)(?:async[ \t]+)?def[ \t]+" + re.escape(method_name) + r"[ \t]*\(")

    for start, line in enumerate(lines):
        m = method_re.match(line)
        if not m:
            continue

        indent = m.group(1)
        base_indent_len = len(indent)

        end = len(lines)
        for j in range(start + 1, len(lines)):
            raw = lines[j]
            stripped = raw.strip()
            if not stripped:
                continue
            current_indent_len = len(raw) - len(raw.lstrip(" \t"))
            if current_indent_len <= base_indent_len and re.match(r"(?:async[ \t]+def|def|class)[ \t]+", raw.lstrip(" \t")):
                end = j
                break

        return start, end, indent

    return None


def build_replacement(indent):
    i = indent
    return f'''{i}def _get_cwes(self, vuln_id):
{i}    """
{i}    Resolve CWE entries linked to a vulnerability.
{i}
{i}    This implementation is schema-tolerant because different VulnDesk
{i}    database imports may name the CWE relation column differently:
{i}    cwe_id, cwe, cwe_code, weakness_id, cwe_name, etc.
{i}
{i}    If no CWE mapping is found, it returns [] instead of crashing the
{i}    enrichment API.
{i}    """
{i}    def _safe_fetch(sql, params=None):
{i}        try:
{i}            return self.db.fetch_all(sql, params or {{}}) or []
{i}        except Exception:
{i}            return []
{i}
{i}    def _get_value(row, *names):
{i}        if row is None or not isinstance(row, dict):
{i}            return None
{i}        lower_map = {{str(k).lower(): k for k in row.keys()}}
{i}        for name in names:
{i}            key = lower_map.get(str(name).lower())
{i}            if key is not None:
{i}                return row.get(key)
{i}        return None
{i}
{i}    def _normalize(rows):
{i}        out = []
{i}        seen = set()
{i}        for r in rows or []:
{i}            cwe = _get_value(r, "cwe_id", "cwe", "cwe_code", "weakness_id", "weakness", "cwe_name", "name")
{i}            if cwe is None:
{i}                continue
{i}            cwe = str(cwe).strip()
{i}            if not cwe:
{i}                continue
{i}            if cwe.upper().startswith("CWE-"):
{i}                cwe_id = cwe.upper()
{i}            elif cwe.isdigit():
{i}                cwe_id = "CWE-" + cwe
{i}            else:
{i}                cwe_id = cwe
{i}            if cwe_id in seen:
{i}                continue
{i}            seen.add(cwe_id)
{i}            out.append({{
{i}                "cwe_id": cwe_id,
{i}                "name": _get_value(r, "name", "cwe_name", "title") or "",
{i}                "description": _get_value(r, "description", "summary") or "",
{i}            }})
{i}        return out
{i}
{i}    # 1) Try common relation-table/column combinations.
{i}    direct_queries = [
{i}        "SELECT vc.cwe_id AS cwe_id FROM vulnerability_cwes vc WHERE vc.vulnerability_id = %(vuln_id)s",
{i}        "SELECT vc.cwe AS cwe_id FROM vulnerability_cwes vc WHERE vc.vulnerability_id = %(vuln_id)s",
{i}        "SELECT vc.cwe_code AS cwe_id FROM vulnerability_cwes vc WHERE vc.vulnerability_id = %(vuln_id)s",
{i}        "SELECT vc.weakness_id AS cwe_id FROM vulnerability_cwes vc WHERE vc.vulnerability_id = %(vuln_id)s",
{i}        "SELECT vc.cwe_id AS cwe_id FROM vulnerability_cwe vc WHERE vc.vulnerability_id = %(vuln_id)s",
{i}        "SELECT vc.cwe AS cwe_id FROM vulnerability_cwe vc WHERE vc.vulnerability_id = %(vuln_id)s",
{i}        "SELECT vc.cwe_code AS cwe_id FROM vulnerability_cwe vc WHERE vc.vulnerability_id = %(vuln_id)s",
{i}        "SELECT vc.weakness_id AS cwe_id FROM vulnerability_cwe vc WHERE vc.vulnerability_id = %(vuln_id)s",
{i}        "SELECT vc.cwe_id AS cwe_id FROM cve_cwes vc WHERE vc.vulnerability_id = %(vuln_id)s",
{i}        "SELECT vc.cwe AS cwe_id FROM cve_cwes vc WHERE vc.vulnerability_id = %(vuln_id)s",
{i}        "SELECT vc.cwe_code AS cwe_id FROM cve_cwes vc WHERE vc.vulnerability_id = %(vuln_id)s",
{i}        "SELECT vc.weakness_id AS cwe_id FROM cve_cwes vc WHERE vc.vulnerability_id = %(vuln_id)s",
{i}        "SELECT vc.cwe_id AS cwe_id FROM cve_cwe vc WHERE vc.vulnerability_id = %(vuln_id)s",
{i}        "SELECT vc.cwe AS cwe_id FROM cve_cwe vc WHERE vc.vulnerability_id = %(vuln_id)s",
{i}        "SELECT vc.cwe_code AS cwe_id FROM cve_cwe vc WHERE vc.vulnerability_id = %(vuln_id)s",
{i}        "SELECT vc.weakness_id AS cwe_id FROM cve_cwe vc WHERE vc.vulnerability_id = %(vuln_id)s",
{i}        "SELECT vc.cwe_id AS cwe_id FROM vulnerability_cwes vc WHERE vc.vuln_id = %(vuln_id)s",
{i}        "SELECT vc.cwe AS cwe_id FROM vulnerability_cwes vc WHERE vc.vuln_id = %(vuln_id)s",
{i}        "SELECT vc.cwe_code AS cwe_id FROM vulnerability_cwes vc WHERE vc.vuln_id = %(vuln_id)s",
{i}        "SELECT vc.weakness_id AS cwe_id FROM vulnerability_cwes vc WHERE vc.vuln_id = %(vuln_id)s",
{i}    ]
{i}
{i}    for sql in direct_queries:
{i}        normalized = _normalize(_safe_fetch(sql, {{"vuln_id": vuln_id}}))
{i}        if normalized:
{i}            return normalized
{i}
{i}    # 2) Schema discovery fallback.
{i}    table_rows = _safe_fetch(
{i}        "SELECT TABLE_NAME AS table_name "
{i}        "FROM INFORMATION_SCHEMA.TABLES "
{i}        "WHERE TABLE_SCHEMA = DATABASE() "
{i}        "AND (LOWER(TABLE_NAME) LIKE '%%cwe%%' OR LOWER(TABLE_NAME) LIKE '%%weakness%%')"
{i}    )
{i}
{i}    vuln_col_candidates = [
{i}        "vulnerability_id", "vuln_id", "id_vulnerability", "id_vuln",
{i}        "cve_id", "id_cve", "cve", "vulnerability"
{i}    ]
{i}    cwe_col_candidates = [
{i}        "cwe_id", "cwe", "cwe_code", "weakness_id", "weakness",
{i}        "cwe_name", "name"
{i}    ]
{i}
{i}    for trow in table_rows:
{i}        table_name = _get_value(trow, "table_name", "TABLE_NAME")
{i}        if not table_name:
{i}            continue
{i}
{i}        col_rows = _safe_fetch(
{i}            "SELECT COLUMN_NAME AS column_name "
{i}            "FROM INFORMATION_SCHEMA.COLUMNS "
{i}            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %(table_name)s",
{i}            {{"table_name": table_name}}
{i}        )
{i}
{i}        col_map = {{}}
{i}        for crow in col_rows:
{i}            col_name = _get_value(crow, "column_name", "COLUMN_NAME")
{i}            if col_name:
{i}                col_map[str(col_name).lower()] = str(col_name)
{i}
{i}        vuln_col = next((col_map[c] for c in vuln_col_candidates if c in col_map), None)
{i}        cwe_col = next((col_map[c] for c in cwe_col_candidates if c in col_map), None)
{i}
{i}        if not vuln_col or not cwe_col:
{i}            continue
{i}
{i}        sql = (
{i}            f"SELECT `{{cwe_col}}` AS cwe_id "
{i}            f"FROM `{{table_name}}` "
{i}            f"WHERE `{{vuln_col}}` = %(vuln_id)s"
{i}        )
{i}        normalized = _normalize(_safe_fetch(sql, {{"vuln_id": vuln_id}}))
{i}        if normalized:
{i}            return normalized
{i}
{i}    # 3) Never break enrichment only because CWE mapping is unavailable.
{i}    return []
'''


def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "cti_services" / "cpe_cve_matching_service.py"
    target = target.resolve()

    if not target.exists():
        print(f"ERROR: target file not found: {target}")
        print("Run this from D:\\vulndesk or pass the full file path.")
        sys.exit(1)

    text = target.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)

    found = find_method_bounds(lines, METHOD_NAME)
    if not found:
        print(f"ERROR: method def {METHOD_NAME}(...) was not found in {target}")
        print("Check the exact method name in cpe_cve_matching_service.py.")
        sys.exit(2)

    start, end, indent = found
    replacement = build_replacement(indent)
    if not replacement.endswith("\n"):
        replacement += "\n"

    new_lines = lines[:start] + [replacement] + lines[end:]
    new_text = "".join(new_lines)

    backup = target.with_suffix(target.suffix + ".bak_cwe_lookup_v2_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(target, backup)
    target.write_text(new_text, encoding="utf-8")

    try:
        py_compile.compile(str(target), doraise=True)
    except Exception as exc:
        shutil.copy2(backup, target)
        print("ERROR: patched file failed to compile. Original restored.")
        print(f"Backup: {backup}")
        print(exc)
        sys.exit(3)

    print("OK: patched successfully.")
    print(f"Target : {target}")
    print(f"Backup : {backup}")
    print("Next   : restart VulnDesk API, then run enrichment again from Pentest.")


if __name__ == "__main__":
    main()
