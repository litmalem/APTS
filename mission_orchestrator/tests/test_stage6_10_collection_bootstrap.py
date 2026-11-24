"""Exercise collection as a subprocess, including Windows path and error cases."""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from run.stage6_10_regression import collect, collection_nodes, pytest_command, strict_json


@pytest.fixture
def source_roots(tmp_path):
    mission, component = tmp_path / "mission", tmp_path / "aptsGS"
    for root in (mission, component): (root / "tests").mkdir(parents=True)
    for package in ("run", "execution_subsystem"):
        (mission / package).mkdir()
        (mission / package / "__init__.py").write_text("TOKEN = 'complete-mission'\n")
    (mission / "tests" / "_mission_helper.py").write_text("TOKEN = 'mission-test-helper'\n")
    (component / "execution_subsystem").mkdir()
    (component / "execution_subsystem" / "__init__.py").write_text("raise RuntimeError('incomplete GSS copy was imported')\n")
    (component / "run.py").write_text("raise RuntimeError('GSS run.py shadowed the Mission package')\n")
    (component / "app").mkdir()
    (component / "app" / "__init__.py").write_text("TOKEN = 'native-gss'\n")
    (component / "tests" / "test_gss.py").write_text(
        "from run import TOKEN as RUN\nfrom execution_subsystem import TOKEN as EXECUTION\n"
        "from tests._mission_helper import TOKEN as HELPER\nfrom app import TOKEN as GSS\n"
        "assert RUN == EXECUTION == 'complete-mission'\nassert HELPER == 'mission-test-helper'\n"
        "assert GSS == 'native-gss'\ndef test_gss():\n    assert True\n")
    return mission, component


def test_collection_resolves_native_gss_and_complete_mission_sources(source_roots, tmp_path):
    mission, component = source_roots
    log = tmp_path / "gss_inventory.log"
    assert collect(component, mission, log, os.environ) == ["tests/test_gss.py::test_gss"]
    context = strict_json(tmp_path / "gss_inventory_context.json")
    assert context["status"] == "COLLECTED" and context["exit_code"] == 0 and not context["acceptance_proven"]
    assert context["python_executable"] == sys.executable and context["component_root"] == str(component.resolve())


def test_mission_app_copy_does_not_shadow_selected_gss(source_roots, tmp_path):
    mission, component = source_roots
    (mission / "app").mkdir()
    (mission / "app" / "__init__.py").write_text("raise RuntimeError('misplaced Mission app copy was imported')\n")
    assert collect(component, mission, tmp_path / "owned_app.log", os.environ) == ["tests/test_gss.py::test_gss"]


def test_explicit_suite_exclusion_still_collects_unknown_tests(source_roots, tmp_path):
    mission, component = source_roots
    (component / "tests" / "test_optional.py").write_text("raise RuntimeError('opt-in suite needs its own database config')\n")
    (component / "tests" / "test_extra.py").write_text("def test_extra():\n    assert True\n")
    nodes = collect(component, mission, tmp_path / "scoped.log", os.environ, ["tests/test_optional.py"])
    assert nodes == ["tests/test_extra.py::test_extra", "tests/test_gss.py::test_gss"]


def test_collection_ignores_ancestor_config_conftest_and_environment_plugins(source_roots, tmp_path):
    mission, component = source_roots
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = --unrelated-legacy-option\n")
    (tmp_path / "conftest.py").write_text("raise RuntimeError('unrelated ancestor conftest was imported')\n")
    env = dict(os.environ, PYTEST_ADDOPTS="--invalid-env-option", PYTEST_PLUGINS="missing_unrelated_plugin")
    assert collect(component, mission, tmp_path / "isolated.log", env) == ["tests/test_gss.py::test_gss"]


def test_standalone_bootstrap_uses_requested_component_even_from_mission_cwd(source_roots):
    mission, component = source_roots
    result = subprocess.run(pytest_command(component, mission, "--collect-only", "-q", "tests"), cwd=mission,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
    assert result.returncode == 0, result.stdout.decode()
    assert collection_nodes(result.stdout.decode()) == ["tests/test_gss.py::test_gss"]


def test_missing_dependency_traceback_is_visible_and_preserved(source_roots, tmp_path):
    mission, component = source_roots
    (component / "tests" / "test_gss.py").write_text("import missing_stage610_backend_dependency\n")
    log = tmp_path / "missing.log"
    with pytest.raises(ValueError, match="missing_stage610_backend_dependency") as error:
        collect(component, mission, log, os.environ)
    assert "Python: " + sys.executable in str(error.value) and "pip install -r" in str(error.value)
    assert "ModuleNotFoundError" in log.read_text(encoding="utf-8")
    context = strict_json(tmp_path / "missing_context.json")
    assert context["status"] == "FAIL" and context["exit_code"] != 0 and not context["acceptance_proven"]


def test_collection_normalizes_windows_filenames_without_changing_parameters():
    stdout = "tests\\test_gss.py::TestGroup::test_case[path\\value]\ntests/test_gss.py::test_second\n2 tests collected\n"
    assert collection_nodes(stdout) == ["tests/test_gss.py::TestGroup::test_case[path\\value]", "tests/test_gss.py::test_second"]


@pytest.mark.parametrize("failure", ["nonzero_with_nodes", "no_nodes", "duplicate_cross_platform_nodes", "timeout"])
def test_collection_does_not_promote_partial_output_to_pass(tmp_path, monkeypatch, failure):
    import run.stage6_10_regression as runner
    raw = b"tests/test_gss.py::test_one\n"
    if failure == "no_nodes": raw = b"no tests collected\n"
    elif failure == "duplicate_cross_platform_nodes": raw += b"tests\\test_gss.py::test_one\n"
    def fake_run(command, **kwargs):
        assert command[-1] == "tests" and kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
        if failure == "timeout": raise subprocess.TimeoutExpired(command, 120, output=raw)
        return SimpleNamespace(stdout=raw, returncode=2 if failure == "nonzero_with_nodes" else 0)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    with pytest.raises(ValueError): collect(tmp_path, tmp_path, tmp_path / "failed.log", os.environ)
    context = strict_json(tmp_path / "failed_context.json")
    assert context["status"] == "FAIL" and not context["acceptance_proven"]


def test_non_test_source_is_not_discovered_outside_component_tests(source_roots, tmp_path):
    mission, component = source_roots
    (component / "test_unrelated_root.py").write_text("raise RuntimeError('noncanonical root test was collected')\n")
    assert collect(component, mission, tmp_path / "canonical.log", os.environ) == ["tests/test_gss.py::test_gss"]


def test_utf8_collection_keeps_unicode_parameter_identity(source_roots, tmp_path):
    mission, component = source_roots
    (component / "tests" / "test_gss.py").write_text(
        "import pytest\n@pytest.mark.parametrize('value',[1],ids=['intel-\u03bb'])\ndef test_gss(value):\n    assert value == 1\n", encoding="utf-8")
    nodes = collect(component, mission, tmp_path / "unicode.log", os.environ)
    # Pytest's default escaped parameter spelling is part of the canonical ID.
    assert nodes == ["tests/test_gss.py::test_gss[intel-\\u03bb]"]
