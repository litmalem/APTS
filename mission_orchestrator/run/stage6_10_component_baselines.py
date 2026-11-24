"""Verify the reviewed GSS baseline before collection, cleanup or evidence checks."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


def read_json(path):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate JSON key")
            out[key] = value
        return out
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked_path(root, relative):
    root = Path(root).resolve()
    if not isinstance(relative, str) or "\\" in relative:
        raise ValueError("invalid component source path")
    rel = Path(relative)
    if rel.is_absolute() or not rel.parts or any(part in {"..", "."} for part in rel.parts):
        raise ValueError("component source path traversal")
    path = root / rel
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("component source path is not canonical")
    return path


def verify_gss_baseline(root, lock):
    baseline = lock["component_baselines"]["gss"]
    root = Path(root).resolve()
    manifest_path = checked_path(root, baseline["manifest_file"])
    if file_digest(manifest_path) != baseline["manifest_sha256"]:
        raise ValueError("GSS source manifest differs from the reviewed Stage 6.10 baseline")
    manifest = read_json(manifest_path)
    if manifest.get("source_digest") != baseline["source_digest"]:
        raise ValueError("GSS source digest differs from the reviewed Stage 6.10 baseline")
    script = checked_path(root, "scripts/gss_source_manifest.py")
    if file_digest(script) != manifest["source_sha256"]["scripts/gss_source_manifest.py"]:
        raise ValueError("GSS source manifest verifier changed")
    # Only execute the exact verifier pinned by the already-verified manifest.
    spec = importlib.util.spec_from_file_location("_apts_stage610_verified_gss_manifest", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    verified, _ = module.verify_source_manifest(root)
    if verified != manifest:
        raise ValueError("GSS verified manifest mismatch")
    bridge = baseline["bridge"]
    if file_digest(checked_path(root, bridge["file"])) != bridge["sha256"]:
        raise ValueError("GSS historical Stage 6.9 bridge test source changed")
    native_nodes = [node for node in lock["components"]["gss"]
                    if node.split("::", 1)[0] != bridge["file"]]
    bridge_nodes = [node for node in lock["components"]["gss"]
                    if node.split("::", 1)[0] == bridge["file"]]
    optional = baseline["optional_database_suite"]
    if (native_nodes != manifest["gss_test_nodes"] or bridge_nodes != bridge["nodes"]
            or manifest["expected_gss_tests"] != len(native_nodes)
            or optional["file"] != manifest["database_test_file"]
            or optional["nodes"] != manifest["database_test_nodes"]
            or manifest["expected_database_tests"] != len(optional["nodes"])
            or optional["required_for_canonical_regression"] is not False):
        raise ValueError("GSS suite scopes do not match the reviewed manifest")
    return manifest, {
        "status": "PASS", "gss_manifest_sha256": baseline["manifest_sha256"],
        "gss_source_digest": manifest["source_digest"], "gss_native_tests": len(native_nodes),
        "gss_historical_bridge_tests": len(bridge_nodes),
        "optional_database_suite": {"file": optional["file"], "test_count": len(optional["nodes"]),
                                    "status": "NOT_EXERCISED_IN_CANONICAL_REGRESSION"},
    }


def verify_component_baselines(roots, lock):
    if "component_baselines" not in lock:
        return {"status": "LEGACY_UNPINNED_COMPONENT_BASELINES"}
    _, result = verify_gss_baseline(roots["gss"], lock)
    return result


def ignored_test_files(component, lock):
    if component == "gss" and "component_baselines" in lock:
        return [lock["component_baselines"]["gss"]["optional_database_suite"]["file"]]
    return []
