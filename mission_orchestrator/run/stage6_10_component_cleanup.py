"""Quarantine only exact GSS test copies misplaced in the Mission test directory."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run.stage6_10_component_baselines import checked_path, file_digest, read_json, verify_gss_baseline


def quarantine_copies(mission, gss, lock, *, apply=False):
    mission, gss = Path(mission).resolve(), Path(gss).resolve()
    if mission == gss:
        raise ValueError("Mission and GSS must have distinct source roots")
    manifest, _ = verify_gss_baseline(gss, lock)
    mission_files = {node.split("::", 1)[0] for node in lock["components"]["mission"]}
    foreign_files = sorted(set(manifest["gss_test_files"] + [manifest["database_test_file"]]) - mission_files)
    planned = []
    for relative in foreign_files:
        path = checked_path(mission, relative)
        if not path.exists():
            continue
        expected = manifest["source_sha256"][relative]
        if not path.is_file() or file_digest(path) != expected:
            raise ValueError("Refusing to move a modified or unrecognized Mission test: " + relative)
        planned.append({"file": relative, "sha256": expected})
    report = {"schema_version": "apts-stage6.10-misplaced-gss-test-quarantine-v1",
        "status": "DRY_RUN" if planned and not apply else "CLEAN", "moved_count": 0,
        "planned_files": planned, "mission_tests_deleted": False, "execution_authorized": False}
    if not apply or not planned:
        return report
    # All content is verified before the first move. The destination is outside
    # canonical tests and retains every byte, along with a receipt for recovery.
    destination = mission / "evidence" / "stage6_10" / ("gss_test_copies-" + uuid.uuid4().hex)
    destination.mkdir(parents=True, exist_ok=False)
    report.update(status="QUARANTINED", quarantine_directory=str(destination),
                  created_at=datetime.now(timezone.utc).isoformat())
    moved = []
    try:
        for item in planned:
            source = checked_path(mission, item["file"])
            target = destination / item["file"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or file_digest(source) != item["sha256"]:
                raise ValueError("Source changed while planning quarantine: " + item["file"])
            os.replace(source, target)
            moved.append((source, target))
        report["moved_count"] = len(moved)
        (destination / "quarantine_receipt.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except BaseException:
        for source, target in reversed(moved):
            if source.exists():
                raise RuntimeError("Cannot safely restore quarantined source because its original path now exists: " + str(source))
            os.replace(target, source)
        raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gss-root", required=True)
    parser.add_argument("--apply", action="store_true", help="Move verified GSS copies to evidence; otherwise report only")
    args = parser.parse_args(argv)
    try:
        lock = read_json(ROOT / "acceptance/stage6_10_inventory.json")
        report = quarantine_copies(ROOT, args.gss_root, lock, apply=args.apply)
        print(json.dumps(report, indent=2), flush=True)
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print("COMPONENT CLEANUP: FAIL; " + str(exc), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
