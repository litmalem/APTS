"""Verify a self-contained VEP export offline without opening databases or network clients."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution_subsystem.api_service import _unique_pairs, _reject_constant
from execution_subsystem.vep_contract import MAX_EXPORT_BYTES, verify_vep_export


def audit_file(path):
    with Path(path).open("rb") as handle:
        raw = handle.read(MAX_EXPORT_BYTES + 1)
    if len(raw) > MAX_EXPORT_BYTES:
        raise ValueError("VEP export byte quota exceeded")
    value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    if not verify_vep_export(value):
        raise ValueError("VEP integrity, semantics, lineage, or artifact byte verification failed")
    return {"status":"VERIFIED", "vep_id":value["vep"]["vep_id"],
        "vep_sha256":value["vep"]["integrity"]["canonical_sha256"],
        "artifact_count":len(value["artifacts"]), "read_only":True, "offline":True,
        "target_network_io_performed":False, "execution_authorized":False,
        "vulnerability_confirmed":False, "independent_authenticity_verified":False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-file", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(audit_file(args.export_file)))
        return 0
    except (KeyError, TypeError, ValueError, RuntimeError, OSError, RecursionError) as exc:
        print(json.dumps({"status":"FAIL", "reason":type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
