"""Verify saved read-only API responses, including the exact downloaded blob bytes."""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution_subsystem.evidence_contract import verify_artifact, verify_evidence


def audit(capture, artifacts):
    assert capture["read_only"] is True and capture["target_network_io_performed"] is False
    assert capture["execution_authorized"] is False and capture["replay_performs_io"] is False
    if capture["status"] == "LEGACY_NOT_CAPTURED":
        assert capture["sealed"] is False and capture["manifest"] is None and capture["artifacts"] == artifacts == []
        return "LEGACY_NOT_CAPTURED"
    manifest = capture["manifest"]
    assert capture["sealed"] is True and verify_evidence(manifest)
    assert capture["attempt_id"] == manifest["attempt_id"]
    assert capture["evidence_id"] == manifest["evidence_id"] and capture["status"] == manifest["capture_status"]
    assert capture["manifest_sha256"] == manifest["integrity"]["canonical_sha256"]
    assert capture["artifacts"] == manifest["artifacts"] and capture["artifact_count"] == len(artifacts)
    downloaded = {v["artifact"]["artifact_id"]:v for v in artifacts}
    assert len(downloaded) == len(artifacts) == len(manifest["artifacts"])
    for ref in manifest["artifacts"]:
        value = downloaded[ref["artifact_id"]]
        assert value["artifact"] == ref and value["read_only"] is True
        assert value["execution_authorized"] is False and value["target_network_io_performed"] is False
        assert verify_artifact(ref, base64.b64decode(value["content_base64"], validate=True))
    return "VERIFIED"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-file", required=True)
    parser.add_argument("--artifacts-file", required=True)
    args = parser.parse_args()
    try:
        capture = json.loads(Path(args.capture_file).read_text(encoding="utf-8-sig"))
        artifacts = json.loads(Path(args.artifacts_file).read_text(encoding="utf-8-sig"))
        print(json.dumps({"status": audit(capture, artifacts), "artifact_count": len(artifacts)}))
        return 0
    except (AssertionError, KeyError, TypeError, ValueError, OSError) as exc:
        print(json.dumps({"status": "FAIL", "reason": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
