"""Intersect current source and external policy limits; unknown controls fail closed."""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import math

from .authorization_contract import parse_time, utc_timestamp
from .execution_contract import ExecutionSourceRejected
from .gateway_policy import SUPPORTED_POLICY_CONSTRAINTS, admission_policy

RUNTIME_CONSTRAINTS = (
    "timeout", "max_duration", "rate_limit", "maximum_concurrency", "sandbox", "credentials_lease",
    "resource_budget", "command_allowlist", "technique_allowlist", "data_handling_policy",
)
DEFAULT_LIMITS = {"timeout_seconds": 5.0, "cpu_seconds": 2, "memory_mb": 128,
                  "max_output_bytes": 16384, "max_network_bytes": 16384,
                  "max_network_requests": 10, "maximum_concurrency": 1,
                  "rate_requests": 1, "rate_window_seconds": 1.0}
RESOURCE_FIELDS = {"cpu_seconds", "memory_mb", "max_output_bytes", "max_network_bytes", "max_network_requests"}


def _number(value, field, *, zero=False):
    if type(value) not in (int, float) or not math.isfinite(value) or not (0 if zero else 0.001) <= value <= 2**31 - 1:
        raise ExecutionSourceRejected("MALFORMED_RUNTIME_CONSTRAINT:" + field)
    return value


def _integer(value, field, *, zero=False):
    if type(value) is not int:
        raise ExecutionSourceRejected("MALFORMED_RUNTIME_CONSTRAINT:" + field)
    _number(value, field, zero=zero)
    return value


def compile_runtime_policy(authorization, adapter, now, *, bounded_web=True, separate_network_budget=True, observed_tightening=None):
    if authorization["decision"] != "ALLOW":
        raise ExecutionSourceRejected("AUTHORITATIVE_" + authorization["decision"])
    constraints = authorization["policy_decision"]["constraints"]
    profile_keys = {"read_only","target_actuation","workflow_profile","max_network_requests","compliance_obligations","max_requests","allowed_methods","execution_profile"} if bounded_web and adapter.operation in {"WEB_PROFILE_FINGERPRINT", "WEB_PROFILE_ENUMERATION"} else set()
    unknown = set(constraints) - set(SUPPORTED_POLICY_CONSTRAINTS) - set(RUNTIME_CONSTRAINTS) - profile_keys
    if unknown:
        raise ExecutionSourceRejected("UNSUPPORTED_POLICY_CONSTRAINT:" + ",".join(sorted(unknown)))
    admission_auth = deepcopy(authorization)
    admission_auth["policy_decision"]["constraints"] = {k: v for k, v in constraints.items() if k in SUPPORTED_POLICY_CONSTRAINTS}
    base = admission_policy(admission_auth, now)
    if base["reason_codes"] or base["human_review_required"]:
        raise ExecutionSourceRejected(";".join(base["reason_codes"]) or "POLICY_REQUIRES_VERIFIED_HUMAN_APPROVAL")
    limits = dict(DEFAULT_LIMITS)
    web = bounded_web and adapter.operation in {"WEB_PROFILE_FINGERPRINT", "WEB_PROFILE_ENUMERATION"}
    enumeration = adapter.operation == "WEB_PROFILE_ENUMERATION"
    if web: limits.update(timeout_seconds=30.0 if enumeration else 15.0,max_network_bytes=262144 if enumeration else 393216,max_output_bytes=60000)
    context = authorization["evaluation"]["current_context"]
    sources = [context["mission_scope"], context["pentest_context"]["boundary"], context["pentest_context"]["task"]]
    deadlines = [parse_time(authorization["valid_until"], "valid_until")]
    credential = None
    durations = {}
    for name, source in zip(("mission", "pentest", "task"), sources):
        src = source["constraints"]
        roe = source.get("roe", context["pentest_context"]["boundary"]["roe"])
        if set(src) - {"max_actions", "max_duration", "risk_threshold", "impact_limit", "resource_budget", "data_handling_policy"}:
            raise ExecutionSourceRejected("UNSUPPORTED_SOURCE_RUNTIME_CONSTRAINT")
        if roe.get("stop_conditions"):
            raise ExecutionSourceRejected("UNSUPPORTED_DECLARED_STOP_CONDITIONS")
        if "maximum_concurrency" in roe:
            limits["maximum_concurrency"] = min(limits["maximum_concurrency"], _integer(roe["maximum_concurrency"], "maximum_concurrency"))
        if "max_duration" in src:
            limits["timeout_seconds"] = min(limits["timeout_seconds"], _number(src["max_duration"], "max_duration"))
            durations[name] = src["max_duration"]
        window = roe.get("allowed_time_window")
        if window:
            deadlines.append(parse_time(window["end_at"], "source_time_window.end_at"))
        _apply_resources(limits, src.get("resource_budget", {}))
        _data_policy(src.get("data_handling_policy", {}))
    for key, value in constraints.items():
        if key in {"timeout", "max_duration"}:
            limits["timeout_seconds"] = min(limits["timeout_seconds"], _number(value, key))
        elif key == "maximum_concurrency":
            limits[key] = min(limits[key], _integer(value, key))
        elif key == "rate_limit":
            if not isinstance(value, dict) or set(value) != {"requests", "window_seconds"}:
                raise ExecutionSourceRejected("MALFORMED_RUNTIME_CONSTRAINT:rate_limit")
            limits["rate_requests"] = min(limits["rate_requests"], _integer(value["requests"], "rate_limit.requests", zero=True))
            # A longer rolling window is a conservative intersection.
            limits["rate_window_seconds"] = max(limits["rate_window_seconds"], _number(value["window_seconds"], "rate_limit.window_seconds"))
        elif key == "resource_budget":
            _apply_resources(limits, value)
        elif key == "sandbox":
            if value != "FIXED_WORKER_BROKER_V1":
                raise ExecutionSourceRejected("UNSUPPORTED_SANDBOX_PROFILE")
        elif key in {"command_allowlist", "technique_allowlist"}:
            if not isinstance(value, list) or any(type(x) is not str for x in value) or len(value) > 100 or len(set(value)) != len(value):
                raise ExecutionSourceRejected("MALFORMED_RUNTIME_CONSTRAINT:" + key)
            wanted = adapter.operation if key == "command_allowlist" else adapter.technique
            if wanted not in value:
                raise ExecutionSourceRejected("POLICY_RESTRICTS:" + key)
        elif key == "data_handling_policy":
            _data_policy(value)
        elif key == "credentials_lease":
            if not isinstance(value, dict) or set(value) != {"lease_id", "required"} or type(value["required"]) is not bool or not value["required"]:
                raise ExecutionSourceRejected("MALFORMED_CREDENTIAL_LEASE")
            from .execution_contract import require_id
            require_id(value["lease_id"], "lease_id", "credlease-")
            if not adapter.credential_support or constraints.get("credential_usage_allowed") is not True or any(s.get("roe", context["pentest_context"]["boundary"]["roe"]).get("credential_usage_allowed") is not True for s in sources):
                raise ExecutionSourceRejected("CREDENTIAL_USE_NOT_AUTHORIZED")
            credential = value["lease_id"]
        elif key == "allowed_time_window":
            deadlines.append(parse_time(value["end_at"], "policy_time_window.end_at"))
        elif key == "max_network_requests": limits[key] = min(limits[key], _integer(value,key))
        elif key == "max_requests": limits["max_network_requests"] = min(limits["max_network_requests"], _integer(value,key))
        elif key == "read_only":
            if type(value) is not bool: raise ExecutionSourceRejected("MALFORMED_READ_ONLY")
        elif key == "target_actuation":
            if value is not False: raise ExecutionSourceRejected("TARGET_ACTUATION_UNSUPPORTED")
        elif key == "workflow_profile":
            if value != "PENTEST_AUTONOMOUS_BOUNDED_V1": raise ExecutionSourceRejected("UNSUPPORTED_WORKFLOW_PROFILE")
        elif key == "allowed_methods":
            if not isinstance(value,list) or "GET" not in value or any(v not in {"GET","HEAD"} for v in value): raise ExecutionSourceRejected("GET_NOT_AUTHORIZED")
        elif key == "execution_profile":
            if value != ("wpt.bounded-enumeration.v1" if enumeration else "wpt.fingerprinting.v1"): raise ExecutionSourceRejected("UNSUPPORTED_EXECUTION_PROFILE")
        elif key == "compliance_obligations":
            if not isinstance(value,list) or len(value)>50 or any(not isinstance(v,dict) or v.get("obligation_type")!="AUDIT" for v in value): raise ExecutionSourceRejected("UNSUPPORTED_COMPLIANCE_OBLIGATION")
    # Adaptive degradation (Jalur 1 pacing): a tighten-only delta derived from a
    # predecessor attempt's sealed condition signal may only lengthen the rate
    # window or shorten the timeout. Applied before the deadline is computed so a
    # shortened timeout also tightens the wall deadline. Fail-closed: it can
    # never loosen a limit, and never touches budget or concurrency.
    limits = apply_observed_tightening(limits, observed_tightening)
    deadlines.append(now + timedelta(seconds=limits["timeout_seconds"]))
    deadline = min(deadlines)
    if deadline <= now or limits["max_network_requests"] < 1 or limits["rate_requests"] < 1 or limits["memory_mb"] < 32:
        raise ExecutionSourceRejected("RUNTIME_QUOTA_EXHAUSTED_OR_UNSUPPORTED")
    cost = 1
    if web:
        cost=min(9 if enumeration else 6,limits["max_network_requests"],_wpt_reserved_requests(authorization["evaluation"]["execution_request"]))
        for cap in (context.get("governance_binding") or {}).get("capabilities",[]):
            if cap.get("capability_id")==adapter.capability_id:
                cost=min(cost,_integer(cap.get("constraints",{}).get("max_requests",1),"capability.max_requests"))
    web_budget = {}
    if web and separate_network_budget:
        # max_requests bounds one profile collection; max_network_requests
        # bounds the aggregate across attempts. Do not use the per-run limit
        # as a lifetime quota, which would prohibit every explicit WPT retry.
        budgets = [s['constraints'].get('resource_budget', {}).get('max_network_requests') for s in sources]
        budgets += [constraints.get('max_network_requests'),
                    constraints.get('resource_budget', {}).get('max_network_requests')]
        budgets = [_integer(b,'max_network_requests',zero=True) for b in budgets if b is not None]
        web_budget = {'web_profile_version':2,
                      'network_request_budget':min(budgets) if budgets else DEFAULT_LIMITS['max_network_requests']}
    return {**({'web_profile_version':2} if web else {}), **web_budget, "limits": limits, "action_limits": base["action_limits"], "deadline": utc_timestamp(deadline),
            "source_duration_seconds": durations,
            "credential_lease_id": credential, "sandbox_profile": "FIXED_WORKER_BROKER_V1",
            "adapter_id": adapter.adapter_id, "operation": adapter.operation,
            "sensitive_output_retained": False, "network_request_cost": cost}


_OBSERVED_TIGHTENING_GROW_ONLY = ("rate_window_seconds",)
_OBSERVED_TIGHTENING_SHRINK_ONLY = ("timeout_seconds",)


def apply_observed_tightening(limits, observed_tightening):
    """Apply a tighten-only adaptive pacing delta to compiled limits.

    Only lengthens ``rate_window_seconds`` (``max``) and shortens
    ``timeout_seconds`` (``min``); any value that would loosen a limit, and every
    other key (including budget or concurrency), is ignored. This mirrors the
    conservative-intersection semantics of ``compile_runtime_policy`` and cannot
    raise the probing footprint.
    """
    if not observed_tightening:
        return limits
    if not isinstance(observed_tightening, dict):
        raise ExecutionSourceRejected("MALFORMED_OBSERVED_TIGHTENING")
    for key in _OBSERVED_TIGHTENING_GROW_ONLY:
        if key in observed_tightening:
            limits[key] = max(limits[key], _number(observed_tightening[key], "observed_tightening." + key))
    for key in _OBSERVED_TIGHTENING_SHRINK_ONLY:
        if key in observed_tightening:
            limits[key] = min(limits[key], _number(observed_tightening[key], "observed_tightening." + key))
    return limits


def _apply_resources(limits, budget):
    if not isinstance(budget, dict) or set(budget) - RESOURCE_FIELDS:
        raise ExecutionSourceRejected("UNSUPPORTED_RESOURCE_BUDGET")
    for key, value in budget.items():
        limits[key] = min(limits[key], _integer(value, "resource_budget." + key, zero=True))
    if any(limits[k] <= 0 for k in {"cpu_seconds", "memory_mb", "max_output_bytes", "max_network_bytes"}):
        raise ExecutionSourceRejected("RESOURCE_QUOTA_ZERO")


def _data_policy(policy):
    if not isinstance(policy, dict) or set(policy) - {"retain_sensitive_output","execution_authorized"}:
        raise ExecutionSourceRejected("UNSUPPORTED_DATA_HANDLING_POLICY")
    if "execution_authorized" in policy and policy["execution_authorized"] is not False:
        raise ExecutionSourceRejected("DATA_HANDLING_POLICY_CANNOT_GRANT_EXECUTION")
    if "retain_sensitive_output" in policy and type(policy["retain_sensitive_output"]) is not bool:
        raise ExecutionSourceRejected("MALFORMED_DATA_HANDLING_POLICY")


def _wpt_reserved_requests(request):
    import json,sqlite3
    from contextlib import closing
    from .wpt_intake_repository import default_wpt_intake_path,_verify
    intake_id=request["parameters"].get("source_wpt_intake_id")
    if not intake_id: return 1
    try:
        with closing(sqlite3.connect(default_wpt_intake_path().as_uri()+"?mode=ro",uri=True,timeout=5)) as conn:
            row=conn.execute("SELECT record_json FROM wpt_governed_intakes WHERE intake_id=?",(intake_id,)).fetchone()
        record=json.loads(row[0]) if row else None
        if (not record or not _verify(record) or record["intake"]["intake_id"]!=intake_id
            or not any(e.get("canonical_sha256")==record["integrity"]["canonical_sha256"] for e in request["evidence_basis"])):
            raise ExecutionSourceRejected("WPT_INTAKE_BUDGET_BINDING_MISMATCH")
        return _integer(record["authority_snapshot"]["limits"]["max_requests"],"intake.max_requests")
    except (sqlite3.Error,TypeError,ValueError,KeyError) as exc:
        raise ExecutionSourceRejected("WPT_INTAKE_BUDGET_UNAVAILABLE") from exc


def _wpt_enumeration_context(request):
    """Resolve the sealed, authority-bound CTI enumeration context for a WPT
    enumeration execution. Returns None when the bound intake carries none
    (plain enumeration / fingerprinting). Read-only and deterministic: it never
    affects scope/RoE/authorization, and every CTI-derived probe is still
    validated per-request by the broker pin. Verification mirrors
    ``_wpt_reserved_requests`` so budget and probe-set bind to the same sealed
    intake the execution request was authorized against."""
    import json,sqlite3
    from contextlib import closing
    from .wpt_intake_repository import default_wpt_intake_path,_verify
    intake_id=request["parameters"].get("source_wpt_intake_id")
    if not intake_id: return None
    try:
        with closing(sqlite3.connect(default_wpt_intake_path().as_uri()+"?mode=ro",uri=True,timeout=5)) as conn:
            row=conn.execute("SELECT record_json FROM wpt_governed_intakes WHERE intake_id=?",(intake_id,)).fetchone()
        record=json.loads(row[0]) if row else None
        if (not record or not _verify(record) or record["intake"]["intake_id"]!=intake_id
            or not any(e.get("canonical_sha256")==record["integrity"]["canonical_sha256"] for e in request["evidence_basis"])):
            raise ExecutionSourceRejected("WPT_INTAKE_CONTEXT_BINDING_MISMATCH")
        return record["intake"].get("enumeration_context")
    except (sqlite3.Error,TypeError,ValueError,KeyError) as exc:
        raise ExecutionSourceRejected("WPT_INTAKE_CONTEXT_UNAVAILABLE") from exc
