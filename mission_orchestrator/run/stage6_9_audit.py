"""Verify CTI feedback or knowledge offline, including retained source artifact bytes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution_subsystem.cti_feedback_contract import (EXPORT_SCHEMA, KNOWLEDGE_EXPORT_SCHEMA,
    MAX_EXPORT_BYTES, verify_feedback_export, verify_knowledge_export)
from run.stage6_8_audit import unique


def audit_file(path):
    try:
        file = Path(path)
        if file.stat().st_size > MAX_EXPORT_BYTES:
            raise ValueError("CTI export byte quota exceeded")
        value = json.loads(file.read_text(encoding="utf-8-sig"), object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        if value.get("schema_version") == EXPORT_SCHEMA and verify_feedback_export(value):
            record = value["feedback"]
            return {"status":"VERIFIED_INTERNAL_LINEAGE", "feedback_id":record["feedback_id"],
                "hypothesis_outcome":record["assessment"]["hypothesis_outcome"],
                "review_required":record["mission_signal"]["review_required"], "execution_authorized":False}
        if value.get("schema_version") == KNOWLEDGE_EXPORT_SCHEMA and verify_knowledge_export(value):
            record = value["revisions"][-1]["record"]
            return {"status":"VERIFIED_INTERNAL_LINEAGE", "knowledge_id":record["knowledge_id"],
                "revision_id":record["revision_id"], "revision":record["revision"],
                "hypothesis_outcome":record["assessment"]["hypothesis_outcome"], "execution_authorized":False}
        raise ValueError("CTI export failed source, chain, or derived-state verification")
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
