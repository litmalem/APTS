"""Protect component ownership and exact source copies during baseline repair."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import shutil

import pytest

from run.stage6_10_component_baselines import (
    checked_path, file_digest, ignored_test_files, verify_gss_baseline,
)
from run.stage6_10_component_cleanup import quarantine_copies

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def component_roots(tmp_path):
    mission, gss = tmp_path / "mission", tmp_path / "gss"
    (mission / "tests").mkdir(parents=True)
    (gss / "tests").mkdir(parents=True)
    (gss / "scripts").mkdir()
    (gss / "app").mkdir()
    configured = Path(os.environ.get("APTS_ACCEPTANCE_GSS_ROOT", ROOT.parent / "aptsGS"))
    verifier = gss / "scripts/gss_source_manifest.py"
    shutil.copyfile(configured / "scripts/gss_source_manifest.py", verifier)
    spec = importlib.util.spec_from_file_location("_fixture_gss_source_manifest", verifier)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    native_file = "tests/test_foreign_gss.py"
    database_file = module.DATABASE_TEST
    bridge_file = "tests/" + module.FOREIGN_TEST
    for relative in (native_file, database_file, bridge_file):
        (gss / relative).write_text("def test_fixture():\n    assert True\n")
    (gss / "app/__init__.py").write_text("")
    (mission / "tests/test_native_mission.py").write_text("def test_native():\n    assert True\n")
    snapshot = module.source_snapshot(gss)
    manifest = {"schema_version": "apts-gss-approval-source-manifest-v1",
        "source_sha256": snapshot, "source_digest": module.digest(snapshot),
        "gss_test_files": [native_file], "gss_test_nodes": [native_file + "::test_fixture"],
        "expected_gss_tests": 1, "database_test_file": database_file,
        "database_test_nodes": [database_file + "::test_fixture"], "expected_database_tests": 1}
    manifest_path = gss / "GSS_SOURCE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest))
    lock = {"components": {"mission": ["tests/test_native_mission.py::test_native"],
                           "gss": [native_file + "::test_fixture", bridge_file + "::test_fixture"]},
        "component_baselines": {"gss": {"manifest_file": manifest_path.name,
            "manifest_sha256": file_digest(manifest_path), "source_digest": manifest["source_digest"],
            "bridge": {"file": bridge_file, "sha256": file_digest(gss / bridge_file),
                       "nodes": [bridge_file + "::test_fixture"]},
            "optional_database_suite": {"file": database_file, "nodes": manifest["database_test_nodes"],
                                        "required_for_canonical_regression": False}}}}
    for relative in (native_file, database_file):
        shutil.copyfile(gss / relative, mission / relative)
    return mission, gss, lock, native_file, database_file, bridge_file


def test_exact_gss_copies_are_quarantined_and_native_mission_is_preserved(component_roots):
    mission, gss, lock, native_file, db_file, _ = component_roots
    dry = quarantine_copies(mission, gss, lock)
    assert dry["status"] == "DRY_RUN" and dry["moved_count"] == 0
    assert (mission / native_file).is_file() and (mission / db_file).is_file()
    result = quarantine_copies(mission, gss, lock, apply=True)
    assert result["status"] == "QUARANTINED" and result["moved_count"] == 2
    assert (mission / "tests/test_native_mission.py").is_file()
    destination = Path(result["quarantine_directory"])
    for relative in (native_file, db_file):
        assert not (mission / relative).exists()
        assert (destination / relative).read_bytes() == (gss / relative).read_bytes()
    receipt = json.loads((destination / "quarantine_receipt.json").read_text())
    assert receipt == result
    repeated = quarantine_copies(mission, gss, lock, apply=True)
    assert repeated["status"] == "CLEAN" and repeated["moved_count"] == 0


@pytest.mark.parametrize("which", ["native", "database"])
def test_modified_copy_blocks_every_move_before_mutation(component_roots, which):
    mission, gss, lock, native_file, db_file, _ = component_roots
    modified = native_file if which == "native" else db_file
    (mission / modified).write_text("# local modification must be preserved\n")
    with pytest.raises(ValueError, match="Refusing to move"):
        quarantine_copies(mission, gss, lock, apply=True)
    assert (mission / native_file).exists() and (mission / db_file).exists()
    assert not (mission / "evidence").exists()


def test_mission_owned_filename_is_never_quarantined(component_roots):
    mission, gss, lock, native_file, db_file, _ = component_roots
    lock["components"]["mission"].append(native_file + "::test_owned")
    (mission / db_file).unlink()
    result = quarantine_copies(mission, gss, lock, apply=True)
    assert result["status"] == "CLEAN" and (mission / native_file).exists()


def test_unknown_additional_mission_test_is_preserved(component_roots):
    mission, gss, lock, _, _, _ = component_roots
    extra = mission / "tests/test_unknown.py"
    extra.write_text("def test_unknown():\n    assert True\n")
    quarantine_copies(mission, gss, lock, apply=True)
    assert extra.is_file()


def test_failure_during_move_restores_all_completed_moves(component_roots, monkeypatch):
    import run.stage6_10_component_cleanup as cleanup
    mission, gss, lock, native_file, db_file, _ = component_roots
    replace = cleanup.os.replace
    calls = []
    def interrupted(source, target):
        calls.append((source, target))
        if len(calls) == 2:
            raise OSError("synthetic move failure")
        return replace(source, target)
    monkeypatch.setattr(cleanup.os, "replace", interrupted)
    with pytest.raises(OSError, match="synthetic move failure"):
        quarantine_copies(mission, gss, lock, apply=True)
    assert (mission / native_file).read_bytes() == (gss / native_file).read_bytes()
    assert (mission / db_file).read_bytes() == (gss / db_file).read_bytes()


@pytest.mark.parametrize("mutation", ["manifest", "native_test", "verifier", "bridge", "new_runtime", "new_test"])
def test_changed_gss_source_or_scope_cannot_rebaseline_itself(component_roots, mutation):
    mission, gss, lock, native_file, _, bridge_file = component_roots
    if mutation == "manifest":
        (gss / "GSS_SOURCE_MANIFEST.json").write_text("{}")
    elif mutation == "native_test":
        (gss / native_file).write_text("def test_changed():\n    assert True\n")
    elif mutation == "verifier":
        with (gss / "scripts/gss_source_manifest.py").open("a") as handle: handle.write("\n# changed verifier\n")
    elif mutation == "bridge":
        (gss / bridge_file).write_text("# changed historical bridge\n")
    elif mutation == "new_runtime":
        (gss / "app/new_runtime.py").write_text("EXTRA = True\n")
    else:
        (gss / "tests/test_new.py").write_text("def test_new():\n    assert True\n")
    with pytest.raises(ValueError):
        quarantine_copies(mission, gss, lock, apply=True)
    assert (mission / native_file).exists()


def test_only_reviewed_optional_database_suite_is_outside_canonical_regression(component_roots):
    _, gss, lock, _, db_file, _ = component_roots
    _, result = verify_gss_baseline(gss, lock)
    assert result["gss_native_tests"] == result["gss_historical_bridge_tests"] == 1
    assert result["optional_database_suite"]["status"] == "NOT_EXERCISED_IN_CANONICAL_REGRESSION"
    assert ignored_test_files("gss", lock) == [db_file]
    assert ignored_test_files("mission", lock) == ignored_test_files("vulndesk", lock) == []
    bad = deepcopy(lock)
    bad["component_baselines"]["gss"]["optional_database_suite"]["required_for_canonical_regression"] = True
    with pytest.raises(ValueError, match="suite scopes"):
        verify_gss_baseline(gss, bad)


def test_identical_component_root_cannot_be_cleaned(component_roots):
    _, gss, lock, _, _, _ = component_roots
    with pytest.raises(ValueError, match="distinct source roots"):
        quarantine_copies(gss, gss, lock, apply=True)


@pytest.mark.parametrize("relative", ["../outside.py", "/outside.py", "tests\\outside.py"])
def test_cleanup_paths_cannot_escape_component(tmp_path, relative):
    with pytest.raises(ValueError): checked_path(tmp_path, relative)
