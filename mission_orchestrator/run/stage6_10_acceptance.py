"""Read-only deployment preflight plus externally verified full APTS regression."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from execution_subsystem.apts_acceptance_contract import CONTROL_VERSION, canonical_apts_acceptance_contract, verify_apts_acceptance_contract
from execution_subsystem.cti_feedback_contract import verify_feedback_contract
from execution_subsystem.execution_contract import REQUIRED_AUTHORIZATION_CHECKS, canonical_json
from execution_subsystem.governance_client import strict_json
from mission_orchestrator.global_mission_acceptance_gate import verify_global_mission_acceptance_gate_contract
from pentest_subsystem.agentic_pentest_acceptance_gate import verify_agentic_pentest_acceptance_gate_contract
from run.stage6_10_regression import run_regression, verify_report, digest, write_json, strict_json as file_json

MISSION_CONTROL = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
PENTEST_CONTROL = "stage5.10-agentic-pentest-acceptance-regression-gate"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): raise ValueError("acceptance redirects are forbidden")


def get(base, path):
    parsed = urlsplit(base)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
        or parsed.query or parsed.fragment or parsed.path not in {"", "/"}): raise ValueError("invalid service base URL")
    with build_opener(NoRedirect(), ProxyHandler({})).open(base.rstrip("/")+path, timeout=15) as response:
        raw = response.read(4*1024*1024+1)
        if len(raw) > 4*1024*1024: raise ValueError("preflight response too large")
        return strict_json(raw), dict(response.headers)


def check(condition, message):
    if not condition: raise ValueError(message)


def validate_preflight(data):
    """A healthy process or contract declaration alone is never final acceptance."""
    mission, pentest, execution, gss, cti = [data[k]["health"] for k in ("mission", "pentest", "execution", "gss", "cti")]
    check(mission["status"] == "ok" and mission["control_version"] == MISSION_CONTROL
        and mission["mission_repository_migration_level"] == 53 and mission["storage_driver"] == "sqlite",
        "Mission must use the same canonical SQLite source supported by Stage 6 execution")
    check(pentest["status"] == "ok" and pentest["control_version"] == PENTEST_CONTROL
        and pentest["pentest_repository_migration_level"] == 16, "Pentest control/migration/readiness mismatch")
    check(execution["status"] == "ok" and execution["control_version"] == CONTROL_VERSION
        and execution["execution_repository_migration_level"] == 9 and execution["cti_knowledge_repository_migration_level"] == 1,
        "Stage 6.10 Execution inactive")
    check("APTSExecutionSubsystem/6.10" in data["execution"]["headers"].get("Server", ""), "Execution server version mismatch")
    check(gss["status"] == "ok" and gss["component_id"] == "GOV-PLANE"
        and gss["execution_revalidation_schema_version"] == "apts-gss-execution-revalidation-v1"
        and gss["execution_revalidation_checks"] == list(REQUIRED_AUTHORIZATION_CHECKS), "authoritative GSS unavailable")
    check(cti["status"] == "ok" and cti["component_id"] == "CTI-INF01" and cti["event_dispatcher_running"] is True,
        "VulnDesk CTI runtime unavailable")
    check(execution["runtime_owner_exclusive"] is True and execution["runtime_persistence_failures"] == 0
        and execution["runtime_completion_fence_enabled"] is True
        and execution["runtime_authorization_quiescence_seconds"] == 2.0, "Execution owner or completion fence degraded")
    for field in ("specialist_raw_target_access", "authorization_minted_locally", "worker_raw_target_access", "arbitrary_code_supported",
                  "automatic_retry_enabled", "caller_heartbeat_supported", "legacy_adapter_synchronous_dispatch_enabled", "runtime_self_certification",
                  "cti_feedback_external_vulndesk_writes", "cti_feedback_automatic_confirmation"):
        check(execution[field] is False, "Execution authority boundary changed: " + field)
    for field in ("mission_source_read_only", "pentest_source_read_only", "cti_knowledge_source_read_only", "cti_feedback_mission_handoff_enabled"):
        check(execution[field] is True, "Execution source isolation changed: " + field)
    check(execution["registered_adapter_count"] == 5 and execution["full_apts_acceptance_status"] == "DECLARED_ONLY",
        "Execution adapter or declaration mismatch")
    locations = execution["apts_source_locations"]
    check(mission["apts_source_locations"]["mission"] == locations["mission"]
        and mission["apts_source_locations"]["cti_feedback"] == locations["cti_feedback"]
        and pentest["apts_source_locations"]["pentest"] == locations["pentest"],
        "services point to different Mission/Pentest/CTI feedback database locations")
    check(mission["cti_pentest_feedback_ingestion_enabled"] is True and mission["cti_pentest_feedback_source_read_only"] is True,
        "Mission CTI consumer unavailable")
    check(verify_apts_acceptance_contract(data["execution"]["contract"]["contract"]), "exact Stage 6.10 contract mismatch")
    check(verify_feedback_contract(data["execution"]["feedback_contract"]["contract"]), "exact Stage 6.9 predecessor mismatch")
    check(verify_global_mission_acceptance_gate_contract(data["mission"]["contract"]["contract"]), "exact Mission closure contract mismatch")
    check(verify_agentic_pentest_acceptance_gate_contract(data["pentest"]["contract"]["contract"]), "exact Pentest closure contract mismatch")
    return True


def preflight(urls):
    data = {}
    for key, url in urls.items():
        health, headers = get(url, "/health")
        data[key] = {"health": health, "headers": headers}
    for component, route, field in (
        ("mission", "/api/e2e/global-mission-orchestrator-acceptance-regression-gate-contract", "contract"),
        ("pentest", "/api/pentest/agentic-pentest-acceptance-gate-contract", "contract"),
        ("execution", "/api/execution/full-apts-acceptance-contract", "contract"),
        ("execution", "/api/execution/closed-loop-cti-pentest-contract", "feedback_contract")):
        data[component][field] = get(urls[component], route)[0]
    validate_preflight(data)
    for component in ("mission", "execution"):
        check(data[component]["health"]["governance_base_url"].rstrip("/") == urls["gss"].rstrip("/"),
            component + " is configured against a different Governance URL")
    return data


def sandbox_probe():
    result = subprocess.run([sys.executable, str(ROOT / "run" / "execution_sandbox_probe.py")], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
    value = strict_json(result.stdout.strip())
    check(result.returncode == 0 and value["status"] == "PASS" and value["target_io_performed"] is False
        and value["arbitrary_code_supported"] is False
        and value["backend"] in {"SECCOMP_RLIMIT", "JOB_OBJECT_FIXED_WORKER"}, "native sandbox probe failed")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gss-root", required=True)
    parser.add_argument("--vulndesk-root", required=True)
    parser.add_argument("--mission-url", default="http://127.0.0.1:8780")
    parser.add_argument("--pentest-url", default="http://127.0.0.1:8790")
    parser.add_argument("--execution-url", default="http://127.0.0.1:8791")
    parser.add_argument("--governance-url", default=os.getenv("APTS_EXECUTION_GOVERNANCE_URL") or os.getenv("MISSION_GOVERNANCE_BASE_URL") or "http://127.0.0.1:8770")
    parser.add_argument("--cti-url", default="http://127.0.0.1:8765")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--build-only", action="store_true", help="explicitly omit deployment checks; cannot claim deployment acceptance")
    parser.add_argument("--output", default="evidence/stage6_10/acceptance-"+uuid.uuid4().hex)
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    roots = {"mission": ROOT, "gss": Path(args.gss_root).resolve(), "vulndesk": Path(args.vulndesk_root).resolve()}
    urls = {"mission": args.mission_url, "pentest": args.pentest_url, "execution": args.execution_url,
            "gss": args.governance_url, "cti": args.cti_url}
    created = False
    try:
        output.mkdir(parents=True, exist_ok=False)
        created = True
        print("Python: " + sys.executable, flush=True)
        print("Source roots: GSS=" + str(roots["gss"]) + "; VulnDesk=" + str(roots["vulndesk"]), flush=True)
        print("[0] " + ("BUILD mode; deployment NOT EXERCISED" if args.build_only else "Live read-only preflight: Mission / Pentest / Execution / GSS / CTI"), flush=True)
        before = None if args.build_only else preflight(urls)
        if before is not None: write_json(output / "preflight_before.json", before)
        print("[1] Native sandbox probe (synthetic bytes)", flush=True)
        probe = sandbox_probe(); write_json(output / "native_sandbox_probe.json", probe)
        print("[2] Full locked Stage 1-6 regression and connected trajectory", flush=True)
        report = run_regression(roots, output / "regression", args.workers)
        check(verify_report(output / "regression", roots), "full APTS regression evidence rejected")
        print("[3] Final source/evidence and deployment preflight verification", flush=True)
        after = None if args.build_only else preflight(urls)
        if after is not None: write_json(output / "preflight_after.json", after)
        check(verify_report(output / "regression", roots), "source changed during final preflight")
        summary = {"schema_version": "apts-stage6.10-external-acceptance-result-v1", "status": "PASS",
            "acceptance_scope": "BUILD_ISOLATED" if args.build_only else "DEPLOYMENT_PREFLIGHT_AND_ISOLATED_FULL_REGRESSION",
            "deployment_exercised": not args.build_only, "live_user_mission_execution_proven": False,
            "runtime_self_certification": False, "execution_authorized": False,
            "contract_sha256": canonical_apts_acceptance_contract()["integrity"]["canonical_sha256"],
            "component_counts": report["component_counts"], "total_tests": report["total_tests"],
            "required_gates": report["required_gates"], "sandbox_backend": probe["backend"],
            "regression_report_sha256": digest(output / "regression" / "regression_report.json")}
        write_json(output / "acceptance_result.json", summary)
        print(canonical_json(summary), flush=True)
        print("STAGE 6.10 " + ("BUILD" if args.build_only else "DEPLOYMENT") + " ACCEPTANCE: PASS", flush=True)
        print("Evidence: " + str(output), flush=True)
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, SyntaxError) as exc:
        if created: write_json(output / "acceptance_result.json", {"status": "FAIL", "error": str(exc), "execution_authorized": False})
        print("STAGE 6.10 ACCEPTANCE: FAIL; " + str(exc), flush=True)
        return 1


if __name__ == "__main__": raise SystemExit(main())
