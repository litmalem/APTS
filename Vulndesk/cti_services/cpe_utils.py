from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering
from typing import Dict, Optional


@dataclass
class Cpe23:
    part: str = ""
    vendor: str = ""
    product: str = ""
    version: str = ""
    update: str = ""
    edition: str = ""
    language: str = ""
    sw_edition: str = ""
    target_sw: str = ""
    target_hw: str = ""
    other: str = ""

    @classmethod
    def parse(cls, uri: str) -> "Cpe23":
        # cpe:2.3:a:vendor:product:version:update:edition:language:sw_edition:target_sw:target_hw:other
        if not uri:
            return cls()
        parts = uri.split(":")
        if len(parts) >= 13 and parts[0] == "cpe" and parts[1] == "2.3":
            return cls(*parts[2:13])
        return cls()

    def normalized_vendor_product(self) -> tuple[str, str]:
        return normalize_cpe_token(self.vendor), normalize_cpe_token(self.product)


def normalize_cpe_token(value: Optional[str]) -> str:
    if value is None:
        return ""
    value = str(value).strip().lower()
    value = value.replace("\\:", ":").replace("\\_", "_").replace("\\-", "-")
    return value


def clean_version(v: Optional[str]) -> str:
    if v is None:
        return ""
    v = str(v).strip().lower()
    if v in {"", "*", "-", "any", "na", "n/a"}:
        return ""
    return v


def version_tokens(v: str):
    v = clean_version(v)
    # 2.4.49-alpha -> [2,4,49,'alpha']
    out = []
    for p in re.split(r"[.\-_+~ ]+", v):
        if not p:
            continue
        if p.isdigit():
            out.append(int(p))
        else:
            m = re.match(r"^(\d+)([a-z].*)$", p)
            if m:
                out.append(int(m.group(1)))
                out.append(m.group(2))
            else:
                out.append(p)
    return out


def compare_versions(a: Optional[str], b: Optional[str]) -> int:
    a = clean_version(a)
    b = clean_version(b)
    if not a and not b:
        return 0
    if not a:
        return -1
    if not b:
        return 1
    try:
        from packaging.version import parse as vparse
        va, vb = vparse(a), vparse(b)
        return (va > vb) - (va < vb)
    except Exception:
        pass
    ta, tb = version_tokens(a), version_tokens(b)
    n = max(len(ta), len(tb))
    for i in range(n):
        x = ta[i] if i < len(ta) else 0
        y = tb[i] if i < len(tb) else 0
        if type(x) != type(y):
            x, y = str(x), str(y)
        if x < y:
            return -1
        if x > y:
            return 1
    return 0


def version_in_range(version: Optional[str], row: Dict) -> bool:
    v = clean_version(version)
    if not v:
        return True
    start_inc = clean_version(row.get("version_start_including"))
    start_exc = clean_version(row.get("version_start_excluding"))
    end_inc = clean_version(row.get("version_end_including"))
    end_exc = clean_version(row.get("version_end_excluding"))
    if start_inc and compare_versions(v, start_inc) < 0:
        return False
    if start_exc and compare_versions(v, start_exc) <= 0:
        return False
    if end_inc and compare_versions(v, end_inc) > 0:
        return False
    if end_exc and compare_versions(v, end_exc) >= 0:
        return False
    criteria = Cpe23.parse(row.get("criteria_uri") or row.get("cpe23_uri") or "")
    criteria_version = clean_version(criteria.version)
    if criteria_version and criteria_version != "*":
        return compare_versions(v, criteria_version) == 0
    return True
