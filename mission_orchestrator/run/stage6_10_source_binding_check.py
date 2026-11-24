"""Read-only check of Mission, Pentest and Execution database location bindings."""
from __future__ import annotations

import argparse
import json
import re
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

CONTROLS = {
    "Mission": "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate",
    "Pentest": "stage5.10-agentic-pentest-acceptance-regression-gate",
    "Execution": "stage6.10-full-apts-end-to-end-acceptance-regression-gate",
}
KINDS = {"Mission": ("mission", "cti_feedback"), "Pentest": ("pentest",),
         "Execution": ("mission", "pentest", "cti_feedback")}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate health key: " + key)
        result[key] = value
    return result


def read_health(base):
    parsed = urlsplit(base)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise ValueError("invalid service base URL")
    with build_opener(NoRedirect(), ProxyHandler({})).open(base.rstrip("/") + "/health", timeout=10) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("health response too large")
        return json.loads(raw, object_pairs_hook=unique_pairs)


def validate_bindings(healths):
    for name, kinds in KINDS.items():
        health = healths[name]
        if not isinstance(health, dict) or health.get("status") != "ok":
            raise ValueError(name + ": health status is not ok")
        if health.get("control_version") != CONTROLS[name]:
            raise ValueError(name + ": runtime control version mismatch")
        locations = health.get("apts_source_locations")
        if not isinstance(locations, dict):
            raise ValueError(name + ": /health missing apts_source_locations")
        for kind in kinds:
            value = locations.get(kind)
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError(name + ": invalid or missing source fingerprint " + kind)
    execution = healths["Execution"]["apts_source_locations"]
    for name, kind in (("Mission", "mission"), ("Mission", "cti_feedback"), ("Pentest", "pentest")):
        if healths[name]["apts_source_locations"][kind] != execution[kind]:
            raise ValueError(name + "/Execution: different database locations for " + kind)
    return {"status": "PASS", "check": "SOURCE_LOCATIONS_ONLY", "full_apts_acceptance_proven": False,
            "execution_authorized": False, "apts_source_locations": execution}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission-url", default="http://127.0.0.1:8780")
    parser.add_argument("--pentest-url", default="http://127.0.0.1:8790")
    parser.add_argument("--execution-url", default="http://127.0.0.1:8791")
    args = parser.parse_args(argv)
    urls = {"Mission": args.mission_url, "Pentest": args.pentest_url, "Execution": args.execution_url}
    try:
        healths = {}
        for name, url in urls.items():
            try:
                healths[name] = read_health(url)
            except (OSError, ValueError) as exc:
                raise ValueError(name + " " + url + "/health: " + str(exc)) from exc
        print(json.dumps(validate_bindings(healths), sort_keys=True), flush=True)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("SOURCE BINDING CHECK: FAIL; " + str(exc), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
