from __future__ import annotations

import csv
from pathlib import Path


CSV_HEADERS = [
    "id",
    "cve_id",
    "description_text",
    "vuln_status",
    "published_at",
    "modified_at",
    "preferred_cvss_version",
    "preferred_base_score",
    "preferred_base_severity",
    "cwe_count",
    "reference_count",
    "affected_product_count",
]


def export_rows_to_csv(rows: list[dict], filepath: str | Path) -> None:
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for row in rows:
            out = {key: row.get(key) for key in CSV_HEADERS}
            for dt_key in ("published_at", "modified_at"):
                value = out.get(dt_key)
                if value is not None:
                    out[dt_key] = value.isoformat(sep=" ")
            writer.writerow(out)
