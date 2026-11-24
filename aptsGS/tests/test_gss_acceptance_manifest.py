from __future__ import annotations

import json

import pytest

from scripts.gss_source_manifest import ROOT, canonical_tests, digest, source_snapshot, verify_source_manifest


@pytest.fixture
def pinned(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    # Build a minimal reviewed component with the real manifest verification.
    for name, content in {"app/main.py": "value = 1\n", "requirements.txt": "requests>=2.32,<3\n",
                          "tests/test_example.py": "def test_example(): pass\n"}.items():
        path = root / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(content)
    snapshot = source_snapshot(root)
    manifest = {"schema_version": "apts-gss-approval-source-manifest-v1", "source_sha256": snapshot,
                "source_digest": digest(snapshot), "gss_test_files": canonical_tests(root),
                "database_test_file": "tests/test_human_approval_mariadb.py"}
    (root / "GSS_SOURCE_MANIFEST.json").write_text(json.dumps(manifest))
    return root


def test_reviewed_source_manifest_passes(pinned):
    manifest, actual = verify_source_manifest(pinned)
    assert manifest["source_digest"] == digest(actual)


@pytest.mark.parametrize("path", ["app/main.py", "requirements.txt"])
def test_source_or_dependency_drift_is_rejected(pinned, path):
    (pinned / path).write_text("changed\n")
    with pytest.raises(ValueError, match="source hash mismatch"):
        verify_source_manifest(pinned)


@pytest.mark.parametrize("change", ["add_runtime", "delete_runtime", "add_test"])
def test_source_topology_drift_is_rejected(pinned, change):
    if change == "add_runtime": (pinned / "app/new_runtime.py").write_text("x = 1\n")
    elif change == "delete_runtime": (pinned / "app/main.py").unlink()
    else: (pinned / "tests/test_new.py").write_text("def test_new(): pass\n")
    with pytest.raises(ValueError, match="source hash mismatch"):
        verify_source_manifest(pinned)


def test_manifest_digest_tamper_is_rejected(pinned):
    path = pinned / "GSS_SOURCE_MANIFEST.json"
    manifest = json.loads(path.read_text())
    manifest["source_digest"] = "a" * 64
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="source hash mismatch"):
        verify_source_manifest(pinned)


def test_dependency_manifest_covers_runtime_and_preserves_gui_separation():
    dependency = json.loads((ROOT / "GSS_DEPENDENCIES.json").read_text())
    runtime = (ROOT / dependency["runtime"]["requirements"]).read_text()
    for distribution in dependency["runtime"]["imports"].values():
        assert any(line.lower().startswith(distribution.lower() + ">=") for line in runtime.splitlines())
    assert "pytest" not in runtime and "PySide6" not in runtime
    assert (ROOT / "requirements-dev.txt").read_text().startswith("-r requirements.txt\n")
    assert (ROOT / "requirements-gui.txt").read_text().startswith("-r requirements.txt\n")
    assert dependency["mission_execution_overlay_may_replace_gss_requirements"] is False
