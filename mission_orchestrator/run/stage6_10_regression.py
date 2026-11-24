"""Run and verify the complete supplied APTS corpus, including GSS and VulnDesk."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from importlib.metadata import PackageNotFoundError, version as distribution_version
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from execution_subsystem.apts_acceptance_contract import canonical_apts_acceptance_contract, REQUIRED_GATES
from execution_subsystem.execution_contract import canonical_json
from run.stage6_10_component_baselines import ignored_test_files, verify_component_baselines

SCHEMA = "apts-stage6.10-external-regression-evidence-v1"
LOCK_PATH = ROOT / "acceptance" / "stage6_10_inventory.json"
EXCLUDED = {"data", "evidence", "__pycache__", ".pytest_cache", ".git", ".venv", "venv", "build", "dist", "node_modules"}


def strict_json(path):
    def unique(pairs):
        value = {}
        for k, v in pairs:
            if k in value: raise ValueError("duplicate JSON key")
            value[k] = v
        return value
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def source_snapshot(root):
    root = Path(root).resolve()
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(p in EXCLUDED for p in relative.parts): continue
        if path.is_file() and (path.suffix in {".py", ".sql", ".json", ".ps1"} or path.name.startswith("requirements")):
            if path.is_symlink(): raise ValueError("source symlinks are unsupported")
            result[relative.as_posix()] = digest(path)
    if not result: raise ValueError("empty source snapshot")
    return result


def compile_snapshot(root, snapshot):
    files = [p for p in snapshot if p.endswith(".py")]
    for relative in files:
        source = Path(root, relative)
        compile(source.read_bytes(), str(source), "exec")
    return len(files)


def test_key(node):
    qualified, bracket, parameters = node.partition("[")
    parts = qualified.split("::")
    classname = parts[0][:-3].replace("/", ".").replace("\\", ".")
    if len(parts) > 2: classname += "." + ".".join(parts[1:-1])
    return classname, parts[-1] + bracket + parameters


def junit_results(path):
    raw = Path(path).read_bytes()
    if len(raw) > 32 * 1024 * 1024 or b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ValueError("untrusted JUnit document")
    document = ET.fromstring(raw)
    suites = list(document) if document.tag == "testsuites" else [document]
    if not suites or any(s.tag != "testsuite" for s in suites): raise ValueError("invalid JUnit suites")
    totals = Counter(tests=0, failures=0, errors=0, skipped=0)
    seen = []
    for suite in suites:
        cases = suite.findall("testcase")
        actual = {"tests": len(cases), **{k: sum(len(c.findall(tag)) for c in cases)
            for k, tag in (("failures", "failure"), ("errors", "error"), ("skipped", "skipped"))}}
        if any(int(suite.get(k, "-1")) != v for k, v in actual.items()): raise ValueError("JUnit totals do not match cases")
        for case in cases:
            if not case.get("classname") or not case.get("name"): raise ValueError("JUnit testcase identity missing")
            seen.append((case.get("classname"), case.get("name")))
        totals.update(actual)
    return seen, dict(totals)


def verify_batch(xml, nodes, exit_code):
    try:
        seen, totals = junit_results(xml)
        return (type(exit_code) is int and exit_code == 0 and len(nodes) == len(set(nodes))
            and len(set(test_key(n) for n in nodes)) == len(nodes)
            and Counter(seen) == Counter(test_key(n) for n in nodes)
            and totals == {"tests": len(nodes), "failures": 0, "errors": 0, "skipped": 0})
    except (OSError, ValueError, ET.ParseError, TypeError): return False


def pytest_command(component, mission, *args):
    return [sys.executable, str(ROOT / "run" / "stage6_10_pytest.py"), str(component), str(mission), *args]


def collection_nodes(stdout):
    """Normalize only node file paths; preserve parameter values verbatim."""
    nodes = []
    for line in stdout.splitlines():
        filename, separator, identity = line.strip().partition("::")
        if separator and filename.startswith(("tests/", "tests\\")):
            nodes.append(filename.replace("\\", "/") + separator + identity)
    return nodes


def collection_versions():
    values = {}
    for name in ("pytest", "PyMySQL", "pydantic", "python-dotenv", "requests", "SQLAlchemy"):
        try: values[name] = distribution_version(name)
        except PackageNotFoundError: values[name] = None
    return values


def collect(root, mission, log, env, ignored_files=()):
    command = pytest_command(root, mission, "--collect-only", "-q",
        *("--ignore=" + relative for relative in ignored_files), "tests")
    child_env = dict(env, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    timed_out = False
    try:
        result = subprocess.run(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=child_env, timeout=120)
        raw, exit_code = result.stdout, result.returncode
    except subprocess.TimeoutExpired as exc:
        raw, exit_code, timed_out = exc.stdout or b"", 124, True
    stdout = raw.decode("utf-8", errors="replace")
    Path(log).write_text(stdout, encoding="utf-8")
    nodes = collection_nodes(stdout)
    valid = exit_code == 0 and bool(nodes) and len(set(nodes)) == len(nodes)
    context_path = Path(log).with_name(Path(log).stem + "_context.json")
    write_json(context_path, {"schema_version": "apts-stage6.10-collection-context-v1",
        "status": "COLLECTED" if valid else "FAIL", "acceptance_proven": False,
        "python_executable": sys.executable, "python_version": sys.version,
        "component_root": str(Path(root).resolve()), "mission_dependency_root": str(Path(mission).resolve()),
        "command": command, "dependency_versions": collection_versions(), "exit_code": exit_code,
        "timed_out": timed_out, "collected_nodes": len(nodes), "log_file": str(Path(log).resolve())})
    if not valid:
        reason = "timeout" if timed_out else ("pytest exit code " + str(exit_code) if exit_code else
            ("no canonical test nodes" if not nodes else "duplicate canonical test nodes"))
        detail = "\n".join(stdout.splitlines()[-45:])[-7000:]
        raise ValueError("canonical collection failed (" + reason + "); inspect " + str(log)
            + "\nPython: " + sys.executable + "\nCollection diagnostics: " + str(context_path)
            + "\n" + detail
            + '\nFor a missing/incompatible Python dependency, use this same interpreter:\n& "'
            + sys.executable + '" -m pip install -r "' + str(ROOT / "requirements-stage6_10.txt") + '"')
    return nodes


def groups_for(nodes, batch_size=50):
    files = {}
    for node in nodes: files.setdefault(node.split("::")[0], []).append(node)
    groups, current = [], []
    for filename in sorted(files):
        if current and sum(len(files[f]) for f in current)+len(files[filename]) > batch_size:
            groups.append(current); current = []
        current.append(filename)
    if current: groups.append(current)
    return [{"files": g, "nodes": [n for f in g for n in files[f]]} for g in groups]


def run_regression(roots, output, workers=4, lock=None):
    if set(roots) != {"mission", "gss", "vulndesk"}: raise ValueError("all three component source roots are required")
    roots = {k: Path(v).resolve() for k, v in roots.items()}
    if len(set(roots.values())) != 3: raise ValueError("component source roots must be distinct")
    if not 1 <= workers <= 8: raise ValueError("workers must be 1-8")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    lock = lock if lock is not None else strict_json(LOCK_PATH)
    if set(lock["components"]) != set(roots) or set(lock["gate_nodes"]) != set(REQUIRED_GATES):
        raise ValueError("inventory lock lacks component or roadmap gate coverage")
    baseline_checks = verify_component_baselines(roots, lock)
    env = dict(os.environ, APTS_ACCEPTANCE_GSS_ROOT=str(roots["gss"]), APTS_ACCEPTANCE_VULNDESK_ROOT=str(roots["vulndesk"]),
        APTS_ACCEPTANCE_TRAJECTORY_OUTPUT=str(output / "trajectory"), PYTEST_ADDOPTS="", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    # Per-process import roots are explicit. All tests use their own isolated DBs.
    snapshots = {k: source_snapshot(root) for k, root in roots.items()}
    compiled = {k: compile_snapshot(roots[k], snapshots[k]) for k in roots}
    write_json(output / "source_snapshot.json", snapshots)
    inventories, groups = {}, []
    for component, root in roots.items():
        print(f"Collecting {component}", flush=True)
        nodes = collect(root, roots["mission"], output / (component+"_inventory.log"), env,
            ignored_test_files(component, lock))
        if nodes != lock["components"][component]:
            expected = lock["components"][component]
            missing = sorted((Counter(expected) - Counter(nodes)).elements())[:8]
            unexpected = sorted((Counter(nodes) - Counter(expected)).elements())[:8]
            raise ValueError(f"locked inventory mismatch: {component}; expected {len(expected)}, collected {len(nodes)}"
                + "\nMissing (first 8): " + repr(missing) + "\nUnexpected (first 8): " + repr(unexpected)
                + ("\nIf these are misplaced GSS copies, run run/stage6_10_component_cleanup.py --gss-root <GSS> --apply; only exact source copies can be moved."
                   if component == "mission" else ""))
        inventories[component] = nodes
        groups += [{"component": component, **g} for g in groups_for(nodes)]
    write_json(output / "inventory.json", inventories)
    for index, group in enumerate(groups, 1):
        group.update(index=index, xml=f"batch_{index:03d}.xml", log=f"batch_{index:03d}.log")
    started = time.monotonic()
    def run_one(group):
        with tempfile.TemporaryDirectory(prefix="apts-stage610-") as temp, (output / group["log"]).open("w", encoding="utf-8") as log_file:
            cmd = pytest_command(roots[group["component"]], roots["mission"], "-q", *group["files"],
                "--basetemp", str(Path(temp) / "pytest"), "--junitxml", str(output / group["xml"]))
            try: code = subprocess.run(cmd, cwd=roots[group["component"]], env=env,
                stdout=log_file, stderr=subprocess.STDOUT, timeout=900).returncode
            except subprocess.TimeoutExpired: code = 124
        return {**group, "exit_code": code, "verified": verify_batch(output / group["xml"], group["nodes"], code)}
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_one, g) for g in groups]
        for future in as_completed(futures):
            result = future.result(); results.append(result)
            print(f"[{len(results):02d}/{len(groups):02d}] {result['component']} batch {result['index']:03d}: "
                + ("PASS" if result["verified"] else "FAIL; " + result["log"]), flush=True)
    results.sort(key=lambda g: g["index"])
    unchanged = all(source_snapshot(root) == snapshots[k] for k, root in roots.items())
    passed_nodes = {k: set() for k in roots}
    for group in results:
        if group["verified"]: passed_nodes[group["component"]].update(group["nodes"])
    gates = {}
    for gate, refs in lock["gate_nodes"].items():
        gates[gate] = bool(refs) and all(ref["node"] in passed_nodes[ref["component"]] for ref in refs)
    from run.stage6_10_audit import audit_files
    trajectory = audit_files(output / "trajectory" / "knowledge_export.json", output / "trajectory" / "mission_forensic_bundle.json",
        output / "trajectory" / "cti_pip.json", output / "trajectory" / "pentest_pip.json")
    write_json(output / "trajectory_audit.json", trajectory)
    passed = (unchanged and all(g["verified"] for g in results) and all(gates.values())
        and trajectory["status"] == "VERIFIED_CONNECTED_INTERNAL_LINEAGE")
    report = {"schema_version": SCHEMA, "status": "PASS" if passed else "FAIL",
        "contract_sha256": canonical_apts_acceptance_contract()["integrity"]["canonical_sha256"],
        "inventory_lock_sha256": hashlib.sha256(canonical_json(lock).encode()).hexdigest(),
        "component_counts": {k: len(v) for k, v in inventories.items()},
        "component_baseline_checks": baseline_checks,
        "total_tests": sum(len(v) for v in inventories.values()), "compile_counts": compiled,
        "source_snapshot_unchanged": unchanged, "required_gates": gates, "groups": results,
        "workers": workers, "wall_seconds": round(time.monotonic()-started, 3),
        "python": sys.version, "platform": platform.platform(),
        "scope": "ISOLATED_LOOPBACK_WITH_NATIVE_GSS_SERVICE_AND_AUTHORITY_REPOSITORY_FIXTURES",
        "live_user_mission_execution_proven": False, "independent_signature": False,
        "connected_trajectory_status": trajectory["status"]}
    report["artifacts"] = {p.relative_to(output).as_posix(): digest(p) for p in sorted(output.rglob("*")) if p.is_file()}
    write_json(output / "regression_report.json", report)
    print(json.dumps({k: report[k] for k in ("status", "component_counts", "total_tests", "source_snapshot_unchanged", "wall_seconds")}), flush=True)
    return report


def safe_artifact(root, relative):
    if not isinstance(relative, str) or "\\" in relative: raise ValueError("invalid artifact name")
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(x in {"..", "."} for x in path.parts): raise ValueError("artifact traversal")
    candidate = Path(root)
    for part in path.parts:
        candidate = candidate / part
        if candidate.is_symlink(): raise ValueError("evidence symlink")
    result = candidate.resolve()
    if not result.is_relative_to(Path(root).resolve()): raise ValueError("artifact outside evidence root")
    return result


def verify_report(output, roots, lock=None):
    """Recompute coverage and sources instead of trusting reported booleans or totals."""
    try:
        output = Path(output).resolve()
        lock = lock if lock is not None else strict_json(LOCK_PATH)
        report = strict_json(output / "regression_report.json")
        snapshots = strict_json(output / "source_snapshot.json")
        inventory = strict_json(output / "inventory.json")
        if set(roots) != {"mission", "gss", "vulndesk"} or set(snapshots) != set(roots): return False
        if "component_baselines" in lock and report.get("component_baseline_checks") != verify_component_baselines(roots, lock):
            return False
        if (report["schema_version"] != SCHEMA or report["status"] != "PASS"
            or report["live_user_mission_execution_proven"] is not False or report["independent_signature"] is not False
            or report["contract_sha256"] != canonical_apts_acceptance_contract()["integrity"]["canonical_sha256"]
            or report["inventory_lock_sha256"] != hashlib.sha256(canonical_json(lock).encode()).hexdigest()
            or inventory != lock["components"] or set(lock["gate_nodes"]) != set(REQUIRED_GATES)): return False
        for relative, sha in report["artifacts"].items():
            if digest(safe_artifact(output, relative)) != sha: return False
        actual_artifacts = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()
                            and p != output / "regression_report.json"}
        if actual_artifacts != set(report["artifacts"]): return False
        if not {"inventory.json", "source_snapshot.json"} <= set(report["artifacts"]): return False
        passed, covered = {k: set() for k in roots}, {k: [] for k in roots}
        expected_groups = [(component, g["files"], g["nodes"]) for component in roots for g in groups_for(inventory[component])]
        actual_groups = [(g["component"], g["files"], g["nodes"]) for g in report["groups"]]
        if actual_groups != expected_groups: return False
        for index, group in enumerate(report["groups"], 1):
            if (group["index"] != index or group["xml"] != f"batch_{index:03d}.xml" or group["log"] != f"batch_{index:03d}.log"
                or not {group["xml"], group["log"]} <= set(report["artifacts"])
                or not verify_batch(safe_artifact(output, group["xml"]), group["nodes"], group["exit_code"])): return False
            covered[group["component"]] += group["nodes"]
            passed[group["component"]].update(group["nodes"])
        for k, root in roots.items():
            if (Counter(covered[k]) != Counter(inventory[k]) or source_snapshot(root) != snapshots[k]
                or compile_snapshot(root, snapshots[k]) != report["compile_counts"][k]): return False
        counts = {k: len(v) for k, v in inventory.items()}
        gates = {k: bool(refs) and all(r["node"] in passed[r["component"]] for r in refs) for k, refs in lock["gate_nodes"].items()}
        required_exports = {"trajectory/knowledge_export.json", "trajectory/mission_forensic_bundle.json", "trajectory/cti_pip.json",
                            "trajectory/pentest_pip.json", "trajectory_audit.json"}
        if not required_exports <= set(report["artifacts"]): return False
        from run.stage6_10_audit import audit_files
        trajectory = audit_files(output / "trajectory" / "knowledge_export.json", output / "trajectory" / "mission_forensic_bundle.json",
            output / "trajectory" / "cti_pip.json", output / "trajectory" / "pentest_pip.json")
        return (counts == report["component_counts"] and sum(counts.values()) == report["total_tests"]
            and all(gates.values()) and report["required_gates"] == gates and report["source_snapshot_unchanged"] is True
            and trajectory["status"] == report["connected_trajectory_status"] == "VERIFIED_CONNECTED_INTERNAL_LINEAGE"
            and trajectory == strict_json(output / "trajectory_audit.json"))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, SyntaxError, ET.ParseError): return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gss-root", required=True)
    parser.add_argument("--vulndesk-root", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", default="evidence/stage6_10/"+uuid.uuid4().hex)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    roots = {"mission": ROOT, "gss": Path(args.gss_root).resolve(), "vulndesk": Path(args.vulndesk_root).resolve()}
    output = (ROOT / args.output).resolve()
    try:
        if not args.verify_only: run_regression(roots, output, args.workers)
        valid = verify_report(output, roots)
        print("FULL APTS REGRESSION: " + ("PASS" if valid else "FAIL"), flush=True)
        return 0 if valid else 1
    except (OSError, ValueError, subprocess.SubprocessError, SyntaxError) as exc:
        print("FAIL: " + str(exc), flush=True)
        return 1


if __name__ == "__main__": raise SystemExit(main())
