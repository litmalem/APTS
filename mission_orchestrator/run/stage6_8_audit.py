"""Offline internal-lineage verification of post-action reports and retained VEP bytes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution_subsystem.cleanup_contract import MAX_REPORT_BYTES, MAX_RECEIPT_BYTES, verify_post_action_export
from execution_subsystem.vep_contract import MAX_EXPORT_BYTES


def unique(pairs):
    out = {}
    for key,value in pairs:
        if key in out:
            raise ValueError("duplicate JSON key")
        out[key] = value
    return out


def audit_file(path):
    try:
        file = Path(path)
        if file.stat().st_size > MAX_EXPORT_BYTES + MAX_REPORT_BYTES + MAX_RECEIPT_BYTES + 8192:
            raise ValueError("post-action export quota exceeded")
        value = json.loads(file.read_text(encoding="utf-8-sig"), object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        if not verify_post_action_export(value):
            raise ValueError("post-action export failed integrity or derived-state verification")
        report = value["report"]
        return {"status":"VERIFIED_INTERNAL_LINEAGE", "post_action_id":report["post_action_id"],
            "attempt_id":report["attempt_id"], "closure_state":report["state"],
            "execution_closed":report["execution_closed"], "cleanup_verified":report["cleanup_verified"],
            "blocking_reasons":report["blocking_reasons"], "target_state_verified":False,
            "issuer_credential_revocation_proven":False, "execution_authorized":False,
            "artifact_count":len(value["vep_export"]["artifacts"])}
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        return {"status":"INVALID", "error":type(exc).__name__}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-file", required=True)
    args = parser.parse_args()
    result = audit_file(args.export_file)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "VERIFIED_INTERNAL_LINEAGE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
