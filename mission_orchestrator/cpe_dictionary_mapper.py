from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List


def parse_dt(value: str | None):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        return None


def split_cpe23(uri: str | None) -> list[str]:
    """Split CPE 2.3 URI while respecting backslash-escaped colons."""
    if not uri:
        return []
    out: list[str] = []
    buf: list[str] = []
    escaped = False
    for ch in str(uri):
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            buf.append(ch)
            continue
        if ch == ":":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return out


def unescape_cpe(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return (
        text.replace("\\:", ":")
        .replace("\\_", "_")
        .replace("\\-", "-")
        .replace("\\.", ".")
        .replace("\\/", "/")
    )


def normalize_cpe_value(value: Any) -> str:
    value = unescape_cpe(value).strip().lower()
    if value in {"*", "-", "any", "na", "n/a"}:
        return ""
    return value


def parse_cpe23_fields(cpe23_uri: str | None) -> dict[str, str]:
    fields = {
        "part": "", "vendor": "", "product": "", "version": "", "update_value": "",
        "edition": "", "language": "", "sw_edition": "", "target_sw": "",
        "target_hw": "", "other": "",
    }
    parts = split_cpe23(cpe23_uri)
    # cpe:2.3:part:vendor:product:version:update:edition:language:sw_edition:target_sw:target_hw:other
    if len(parts) >= 13 and parts[0] == "cpe" and parts[1] == "2.3":
        keys = list(fields.keys())
        for idx, key in enumerate(keys, start=2):
            fields[key] = normalize_cpe_value(parts[idx])
    return fields


def _english_title(titles: list[dict[str, Any]]) -> str | None:
    if not titles:
        return None
    for row in titles:
        if str(row.get("lang") or "").lower() == "en":
            return row.get("title") or row.get("value")
    return titles[0].get("title") or titles[0].get("value")


def map_nvd_cpe_product(product_item: Dict[str, Any]) -> Dict[str, Any]:
    cpe = product_item.get("cpe") if isinstance(product_item.get("cpe"), dict) else product_item
    cpe_name = cpe.get("cpeName") or cpe.get("cpe23Uri") or cpe.get("name")
    fields = parse_cpe23_fields(cpe_name)
    titles: List[Dict[str, Any]] = cpe.get("titles") or []
    refs: List[Dict[str, Any]] = cpe.get("refs") or cpe.get("references") or []
    deprecated_by = cpe.get("deprecatedBy") or []

    return {
        "cpe_name_id": cpe.get("cpeNameId") or cpe.get("cpe_name_id"),
        "cpe23_uri": cpe_name,
        "part": fields["part"],
        "vendor": fields["vendor"],
        "product": fields["product"],
        "version": fields["version"],
        "update_value": fields["update_value"],
        "edition": fields["edition"],
        "language": fields["language"],
        "sw_edition": fields["sw_edition"],
        "target_sw": fields["target_sw"],
        "target_hw": fields["target_hw"],
        "other": fields["other"],
        "title": _english_title(titles),
        "titles_json": json.dumps(titles, ensure_ascii=False),
        "references_json": json.dumps(refs, ensure_ascii=False),
        "deprecated": bool(cpe.get("deprecated", False)),
        "deprecated_by_json": json.dumps(deprecated_by, ensure_ascii=False),
        "created_at_source": parse_dt(cpe.get("created")),
        "modified_at_source": parse_dt(cpe.get("lastModified")),
        "last_synced_at": datetime.utcnow(),
        "source_name": "NVD Official CPE Dictionary",
        "raw_json": json.dumps(product_item, ensure_ascii=False),
    }
