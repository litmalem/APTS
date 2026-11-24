"""Isolate component pytest imports and resolve GSS's copied Mission test dependencies."""
from pathlib import Path
import importlib
import os
import sys
import tempfile
import types


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage: stage6_10_pytest.py COMPONENT_ROOT MISSION_ROOT [pytest arguments]")
    component, mission = [Path(p).resolve() for p in sys.argv[1:3]]
    if not (component / "tests").is_dir() or not mission.is_dir():
        raise SystemExit("component tests directory and complete Mission source root are required")
    os.chdir(component)
    os.environ["PYTEST_ADDOPTS"] = ""
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ.pop("PYTEST_PLUGINS", None)
    # GSS includes a copy of the Stage 6.9 integration test and partial namespace
    # packages. Load its dependencies from the complete Mission source, never
    # from the incomplete copies or the unrelated GSS run.py entry point.
    # Historical Mission files also use unqualified imports of test helpers.
    # Keep their complete source roots explicit under pytest importlib mode.
    sys.path[:0] = [str(mission), str(component), str(component / "tests"), str(mission / "tests")]
    if component != mission and (component / "app").is_dir():
        # Bind Mission-owned packages first; GSS ships partial copies and run.py.
        # Then give the selected component ownership of app imports, even if
        # Mission has an accidental app/ copy. Both roots remain explicit.
        for name in ("run", "mission_orchestrator", "pentest_subsystem", "execution_subsystem"):
            if (mission / name).is_dir():
                module = importlib.import_module(name)
                if not Path(module.__file__).resolve().is_relative_to(mission):
                    raise SystemExit("Mission dependency imported outside its source root: " + name)
        sys.path[:0] = [str(component)]
    package = types.ModuleType("tests")
    package.__path__ = [str(component / "tests"), str(mission / "tests")]
    sys.modules["tests"] = package
    import pytest
    # Ancestor pytest configuration/conftest can belong to a different project.
    # A real temporary INI works on both Windows and POSIX; an OS null device
    # does not provide a portable pytest configuration filename.
    with tempfile.TemporaryDirectory(prefix="apts-stage610-pytest-") as temp:
        config = Path(temp) / "pytest.ini"
        config.write_text("[pytest]\n", encoding="utf-8")
        return pytest.main(["-c", str(config), "--rootdir", str(component),
            "--confcutdir", str(component), "--color=no", "--import-mode=importlib", *sys.argv[3:]])


if __name__ == "__main__":
    raise SystemExit(main())
