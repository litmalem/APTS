from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any


def normalize_cwe_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if text.startswith("NVD-CWE"):
        return text
    match = re.search(r"(\d+)", text)
    if match:
        return f"CWE-{int(match.group(1))}"
    if text.startswith("CWE-"):
        return text
    return text


def cwe_number(cwe_id: str) -> str | None:
    cwe_id = normalize_cwe_id(cwe_id) or ""
    match = re.search(r"(\d+)", cwe_id)
    return match.group(1) if match else None


def cwe_url(cwe_id: str) -> str | None:
    number = cwe_number(cwe_id)
    if not number:
        return None
    return f"https://cwe.mitre.org/data/definitions/{number}.html"


def _pick(obj: dict, keys: list[str]) -> Any:
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
        # tolerate case-only differences from future API versions
        for existing_key, value in obj.items():
            if existing_key.lower() == key.lower() and value not in (None, ""):
                return value
    return None


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip() or None


def _as_json(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


def extract_cwe_objects(payload: Any) -> list[dict]:
    """Extract CWE weakness/category/view objects from a CWE API payload.

    MITRE CWE API responses usually contain top-level arrays such as
    Weaknesses, Categories, and Views. This function also recursively scans
    nested dictionaries/lists so the app is resilient to minor schema changes.
    """
    if not isinstance(payload, (dict, list)):
        return []

    found: list[dict] = []
    seen: set[int] = set()

    def looks_like_cwe_object(obj: dict) -> bool:
        return any(k in obj for k in ("ID", "Id", "id", "CWE_ID", "CWE-ID")) and any(
            k in obj for k in ("Name", "name", "Description", "description")
        )

    def add_obj(obj: dict) -> None:
        marker = id(obj)
        if marker not in seen and looks_like_cwe_object(obj):
            found.append(obj)
            seen.add(marker)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            add_obj(node)
            for key in ("Weaknesses", "weaknesses", "Categories", "categories", "Views", "views"):
                value = node.get(key)
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            add_obj(item)
                        walk(item)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


def api_version_from_payload(version_payload: dict | None) -> str | None:
    if not isinstance(version_payload, dict):
        return None
    value = _pick(version_payload, ["Version", "version", "CWEVersion", "CWE_Version"])
    if value is None:
        return _as_text(version_payload)
    return _as_text(value)


def map_cwe_object(obj: dict, api_version: str | None = None) -> dict | None:
    raw_id = _pick(obj, ["ID", "Id", "id", "CWE_ID", "CWE-ID", "cwe_id"])
    cwe_id = normalize_cwe_id(raw_id)
    if not cwe_id:
        return None

    name = _as_text(_pick(obj, ["Name", "name", "Title", "title"]))
    description = _as_text(_pick(obj, ["Description", "description", "Summary", "summary"]))
    extended = _as_text(
        _pick(obj, ["ExtendedDescription", "Extended_Description", "Extended Description", "extended_description"])
    )
    abstraction = _as_text(_pick(obj, ["Abstraction", "abstraction", "WeaknessAbstraction"]))
    structure = _as_text(_pick(obj, ["Structure", "structure", "WeaknessStructure"]))
    status = _as_text(_pick(obj, ["Status", "status", "WeaknessStatus"]))
    likelihood = _as_text(
        _pick(obj, ["LikelihoodOfExploit", "Likelihood_Of_Exploit", "Likelihood of Exploit", "likelihood_of_exploit"])
    )

    return {
        "cwe_id": cwe_id,
        "cwe_name": name,
        "cwe_url": cwe_url(cwe_id),
        "description_text": description,
        "extended_description": extended,
        "abstraction": abstraction,
        "structure_value": structure,
        "status_value": status,
        "likelihood_of_exploit": likelihood,
        "source_name": "MITRE CWE",
        "api_version": api_version,
        "api_synced_at": datetime.utcnow(),
        "related_weaknesses_json": _as_json(_pick(obj, ["RelatedWeaknesses", "Related_Weaknesses", "related_weaknesses"])),
        "alternate_terms_json": _as_json(_pick(obj, ["AlternateTerms", "Alternate_Terms", "alternate_terms"])),
        "raw_json": _as_json(obj),
    }
