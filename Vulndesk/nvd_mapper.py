from __future__ import annotations

import json
from datetime import datetime


def parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def pick_preferred_metric(metrics: list[dict]) -> dict | None:
    priority = {"4.0": 4, "3.1": 3, "3.0": 2, "2.0": 1}
    if not metrics:
        return None

    return sorted(
        metrics,
        key=lambda m: (
            -priority.get(str(m.get("cvss_version")), 0),
            -(m.get("base_score") or -1),
        ),
    )[0]


class NvdMapper:
    @staticmethod
    def map_full(item: dict) -> dict:
        cve = item.get("cve", {})
        descriptions = cve.get("descriptions", [])
        english_desc = next(
            (d.get("value") for d in descriptions if d.get("lang") == "en"),
            None,
        )

        metrics_out = []
        metrics = cve.get("metrics", {})

        for metric_key in ["cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"]:
            for metric in metrics.get(metric_key, []):
                cvss = metric.get("cvssData", {})
                metrics_out.append(
                    {
                        "cvss_version": cvss.get("version"),
                        "source_name": metric.get("source"),
                        "metric_type": metric.get("type"),
                        "vector_string": cvss.get("vectorString"),
                        "base_score": cvss.get("baseScore"),
                        "base_severity": metric.get("baseSeverity") or cvss.get("baseSeverity"),
                        "attack_vector": cvss.get("attackVector"),
                        "attack_complexity": cvss.get("attackComplexity"),
                        "privileges_required": cvss.get("privilegesRequired"),
                        "user_interaction": cvss.get("userInteraction"),
                        "scope_value": cvss.get("scope"),
                        "confidentiality_impact": cvss.get("confidentialityImpact"),
                        "integrity_impact": cvss.get("integrityImpact"),
                        "availability_impact": cvss.get("availabilityImpact"),
                        "exploitability_score": metric.get("exploitabilityScore"),
                        "impact_score": metric.get("impactScore"),
                        "is_preferred": False,
                    }
                )

        preferred = pick_preferred_metric(metrics_out)
        if preferred:
            preferred["is_preferred"] = True

        cwes_out = []
        seen_cwe_ids = set()

        for weakness in cve.get("weaknesses", []):
            source_name = weakness.get("source")
            for desc in weakness.get("description", []):
                value = (desc.get("value") or "").strip()
                if value.startswith("CWE-") and value not in seen_cwe_ids:
                    seen_cwe_ids.add(value)
                    cwes_out.append(
                        {
                            "cwe_id": value,
                            "cwe_name": None,
                            "cwe_url": None,
                            "source_name": source_name,
                        }
                    )

        # PATCH: deduplicate references by URL and merge tags/source
        refs_map: dict[str, dict] = {}

        for ref in cve.get("references", []):
            url = (ref.get("url") or "").strip()
            if not url:
                continue

            source_name = (ref.get("source") or "").strip() or None
            tags = set(ref.get("tags") or [])

            if url not in refs_map:
                refs_map[url] = {
                    "url": url,
                    "source_name": source_name,
                    "tags": tags,
                }
            else:
                if not refs_map[url]["source_name"] and source_name:
                    refs_map[url]["source_name"] = source_name
                refs_map[url]["tags"].update(tags)

        refs_out = []
        for ref_item in refs_map.values():
            refs_out.append(
                {
                    "url": ref_item["url"],
                    "source_name": ref_item["source_name"],
                    "tags_json": json.dumps(sorted(ref_item["tags"]), ensure_ascii=False),
                }
            )

        # PATCH: deduplicate CPE rows
        cpe_out = []
        seen_cpe_keys = set()

        for config in cve.get("configurations", []):
            for node in config.get("nodes", []):
                for match in node.get("cpeMatch", []):
                    criteria_uri = match.get("criteria")
                    row = {
                        "is_vulnerable": bool(match.get("vulnerable", True)),
                        "criteria_uri": criteria_uri,
                        "match_criteria_id": match.get("matchCriteriaId"),
                        "version_start_including": match.get("versionStartIncluding"),
                        "version_start_excluding": match.get("versionStartExcluding"),
                        "version_end_including": match.get("versionEndIncluding"),
                        "version_end_excluding": match.get("versionEndExcluding"),
                    }

                    dedupe_key = (
                        row["criteria_uri"],
                        row["version_start_including"],
                        row["version_start_excluding"],
                        row["version_end_including"],
                        row["version_end_excluding"],
                        row["is_vulnerable"],
                    )

                    if criteria_uri and dedupe_key not in seen_cpe_keys:
                        seen_cpe_keys.add(dedupe_key)
                        cpe_out.append(row)

        preferred_metric = preferred or {}

        return {
            "vulnerability": {
                "cve_id": cve.get("id"),
                "description_text": english_desc,
                "source_name": "NVD",
                "vuln_status": cve.get("vulnStatus"),
                "published_at": parse_dt(cve.get("published")),
                "modified_at": parse_dt(cve.get("lastModified")),
                "nvd_url": f"https://nvd.nist.gov/vuln/detail/{cve.get('id')}" if cve.get("id") else None,
                "has_cvss": bool(metrics_out),
                "preferred_cvss_version": preferred_metric.get("cvss_version"),
                "preferred_base_score": preferred_metric.get("base_score"),
                "preferred_base_severity": preferred_metric.get("base_severity"),
                "preferred_vector_string": preferred_metric.get("vector_string"),
                "raw_json": json.dumps(item, ensure_ascii=False),
            },
            "cvss_metrics": metrics_out,
            "cwes": cwes_out,
            "references": refs_out,
            "cpe_matches": cpe_out,
        }