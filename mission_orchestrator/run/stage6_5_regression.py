"""Run every canonical test once, retaining auditable, isolated JUnit batches."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def test_key(node):
    # Parametrized ids may themselves contain :: (for example IPv6).
    # Only the portion before the first '[' carries pytest topology.
    qualified, bracket, parameters = node.partition("[")
    parts = qualified.split("::")
    classname = parts[0][:-3].replace("/", ".").replace("\\", ".")
    if len(parts) > 2:
        classname += "." + ".".join(parts[1:-1])
    return classname, parts[-1] + bracket + parameters


def source_snapshot():
    result = {}
    for folder in ("mission_orchestrator", "pentest_subsystem", "execution_subsystem", "run", "tests",
                   "migrations", "pentest_migrations", "execution_migrations"):
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file() and path.suffix in {".py", ".sql", ".json"} and "__pycache__" not in path.parts:
                result[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--expected-tests", type=int, default=2539)
    parser.add_argument("--output", default="evidence/stage6_5")
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error("workers must be 1-8")
    output = (ROOT / args.output).resolve()
    output.mkdir(parents=True,exist_ok=True)
    snapshot = source_snapshot()
    (output/"source_snapshot.json").write_text(json.dumps(snapshot,indent=2)+"\n",encoding="utf-8")
    collection = subprocess.run([sys.executable,"-m","pytest","--collect-only","-q"],cwd=ROOT,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (output/"inventory.log").write_text(collection.stdout,encoding="utf-8")
    nodes = [line.strip() for line in collection.stdout.splitlines() if line.startswith("tests/") and "::" in line]
    if collection.returncode or len(nodes) != args.expected_tests or len(set(nodes)) != len(nodes):
        print("FAIL: canonical inventory mismatch",len(nodes),flush=True)
        return 1
    files = {}
    for node in nodes:
        files.setdefault(node.split("::")[0],[]).append(node)
    groups, current, size = [], [], 0
    for name, members in sorted(files.items()):
        if current and size+len(members)>50:
            groups.append({"files":current,"tests":size}); current,size=[],0
        current.append(name); size+=len(members)
    if current:
        groups.append({"files":current,"tests":size})
    (output/"regression_groups.json").write_text(json.dumps({"total_tests":len(nodes),"workers":args.workers,"groups":groups},indent=2)+"\n",encoding="utf-8")
    started=time.monotonic()
    def run_group(index,group):
        log=output/f"full_batch_{index:03d}.log"
        xml=output/f"full_batch_{index:03d}.xml"
        with tempfile.TemporaryDirectory(prefix=f"apts-regression-{index:03d}-") as temp, log.open("w",encoding="utf-8") as handle:
            command=[sys.executable,"-m","pytest","-q",*group["files"],"--basetemp",str(Path(temp)/"pytest"),"--junitxml",str(xml)]
            completed=subprocess.run(command,cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT)
        return index,completed.returncode,xml
    outcomes=[]
    node_by_key={test_key(node):node for node in nodes}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(run_group,index,group) for index,group in enumerate(groups,1)]
        for future in as_completed(futures):
            index,code,xml=future.result()
            outcomes.append((index,code,xml))
            print(f"Group {index:03d}/{len(groups)}: {'PASS' if code==0 else 'FAIL'} ({len(outcomes)} completed)",flush=True)
            if code:
                print(f"Failure log: {output/f'full_batch_{index:03d}.log'}",flush=True)
                if xml.exists():
                    try:
                        failures=ET.parse(xml).getroot().iter("testcase")
                        for testcase in failures:
                            for tag in ("failure", "error"):
                                finding=testcase.find(tag)
                                if finding is not None:
                                    key=(testcase.get("classname"),testcase.get("name"))
                                    print(f"FAILED {node_by_key.get(key, '::'.join(key))}",flush=True)
                                    print(finding.text or finding.get("message",tag),flush=True)
                    except ET.ParseError:
                        print(f"Unreadable failure JUnit: {xml}",flush=True)
    combined=ET.Element("testsuites",{"name":"Stage 6.5 complete isolated regression"})
    seen=[]
    totals={"tests":0,"failures":0,"errors":0,"skipped":0}
    failed=any(code for _,code,_ in outcomes)
    for index,code,xml in sorted(outcomes):
        if not xml.exists():
            failed=True
            continue
        document=ET.parse(xml).getroot()
        for suite in document.findall("testsuite") if document.tag=="testsuites" else [document]:
            copied=deepcopy(suite); copied.set("name",f"pytest_group_{index:03d}")
            combined.append(copied)
            for key in totals:
                totals[key]+=int(suite.get(key,"0"))
            seen += [(t.get("classname"),t.get("name")) for t in suite.findall("testcase")]
    for key,value in totals.items():
        combined.set(key,str(value))
    ET.indent(combined)
    ET.ElementTree(combined).write(output/"full_regression.xml",encoding="utf-8",xml_declaration=True)
    exact=Counter(seen)==Counter(test_key(n) for n in nodes)
    unchanged=snapshot==source_snapshot()
    passed=(not failed and exact and unchanged and totals=={"tests":len(nodes),"failures":0,"errors":0,"skipped":0})
    report={"status":"PASS" if passed else "FAIL", "canonical_inventory":len(nodes),"executed_testcases":len(seen),
        "totals":totals,"exact_canonical_coverage":exact,"source_snapshot_unchanged":unchanged,
        "source_file_count":len(snapshot),"isolated_groups":len(groups),"parallel_pytest_workers":args.workers,
        "wall_seconds":round(time.monotonic()-started,3),"target_scope":"ISOLATED_LOOPBACK_ONLY",
        "live_user_mission_exercised":False}
    (output/"regression_summary.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report),flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
