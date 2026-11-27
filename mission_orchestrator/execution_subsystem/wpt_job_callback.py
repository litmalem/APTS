"""Authenticated, idempotent Mission -> WPT job and result callbacks."""
from __future__ import annotations

import hashlib
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("WPT callback redirect rejected")


def _configuration():
    base = os.getenv("APTS_WPT_INBOX_URL", "").rstrip("/")
    token = os.getenv("APTS_WPT_INBOX_TOKEN", "")
    if not base or len(token) < 32:
        raise RuntimeError("WPT callback is not configured")
    parsed = urlparse(base)
    if parsed.scheme != "https" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError("WPT callback URL must use HTTPS or loopback HTTP")
    return base, token


def _post(path: str, payload: dict) -> dict:
    base, token = _configuration()
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    req = Request(base + path, data=encoded,
                  headers={"Content-Type": "application/json", "Accept": "application/json",
                           "X-APTS-Client-Token": token,
                           "User-Agent": "APTS-Mission-WPT-Job-Callback/1.0"}, method="POST")
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(req, timeout=8) as response:
            data = json.loads(response.read(65537).decode("utf-8"))
            if response.status not in (200, 201):
                raise RuntimeError("WPT callback rejected")
            return data
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError("WPT callback failed") from exc


def canonical_target(value: str) -> str:
    parsed = urlparse(str(value or ""))
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("WPT callback target must be a credential-free HTTP(S) URL")
    canonical = urlunparse(parsed._replace(fragment="")).rstrip("/")
    return canonical or parsed.scheme + "://" + parsed.netloc


def job_id_for_intake(intake_id: str) -> str:
    return "wpt-" + hashlib.sha256(intake_id.encode("utf-8")).hexdigest()[:32]


def publish_job_status(intake: dict, admission: dict, status: str) -> dict:
    target = intake.get("target") or {}
    payload = {
        "schema_version": "apts-wpt-stage6-job-v1",
        "mission_id": intake["mission_id"], "task_id": intake["task_id"],
        "target": canonical_target(target["target_value"]), "profile": intake["profile"],
        "execution_id": admission["execution_id"], "status": status,
        "authorization_id": admission.get("authorization_id"),
    }
    if admission.get('runtime_attempt_number') and admission.get('runtime_attempt_id'):
        payload['runtime_attempt_number'] = admission['runtime_attempt_number']
        payload['runtime_attempt_id'] = admission['runtime_attempt_id']
    if admission.get('reason_code'):
        payload['reason_code'] = str(admission['reason_code'])[:180]
    result = _post("/api/stage6/intakes/" + quote(intake["intake_id"], safe="") + "/job", payload)
    return {"status": "DELIVERED", "job_id": (result.get("job") or {}).get("job_id"),
            "created": bool(result.get("created")), "target_io_performed": False}


def publish_stage6_result(intake: dict, result_record: dict) -> dict:
    job_id = job_id_for_intake(intake["intake_id"])
    evidence = result_record["evidence"]
    observation = result_record.get("result", {}).get("observation")
    if isinstance(observation, dict):
        result = dict(observation)
    else:
        result = {"stage6_observation": observation}
    result.update({
        "mission_id": intake["mission_id"], "task_id": intake["task_id"],
        "target": canonical_target(intake["target"]["target_value"]), "profile": intake["profile"],
        "status": result_record.get("result", {}).get("status", "SUCCEEDED"),
        "evidence": {
            "capture_status": "SEALED",
            "manifest_sha256": evidence["manifest_sha256"],
            "evidence_ref": "stage6-evidence://" + evidence["evidence_id"],
            **({"response_truncated": True} if evidence.get("response_truncated") else {}),
        },
    })
    result_sha256 = hashlib.sha256(json.dumps(
        result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    payload = {"status": "COMPLETED", "execution_id": result_record["execution_id"],
               "result": result, "result_sha256": result_sha256}
    response = _post("/api/jobs/" + quote(job_id, safe="") + "/result", payload)
    return {"status": "DELIVERED", "job_id": response.get("job_id"),
            "result_sha256": response.get("result_sha256"), "evidence_ref": response.get("evidence_ref")}


def publish_recon_receipt(intake: dict, result_record: dict, handoff: dict) -> dict:
    ack = handoff.get("acknowledgement") or {}
    if (handoff.get("delivery_status") != "DELIVERED" or ack.get("accepted") is not True
            or ack.get("intake_id") != intake["intake_id"]
            or ack.get("source_result_sha256") != result_record["integrity"]["canonical_sha256"]):
        raise ValueError("Recon receipt requires a bound durable acknowledgement")
    return _post("/api/jobs/" + quote(job_id_for_intake(intake["intake_id"]), safe="") + "/deliveries/reconnaissance",
        {"delivery_id": ack["recon_run_id"], "intake_id": intake["intake_id"],
         "mission_id": intake["mission_id"], "task_id": intake["task_id"],
         "execution_id": result_record["execution_id"],
         "evidence_manifest_sha256": result_record["evidence"]["manifest_sha256"]})


def publish_enumeration_receipt(intake: dict, result_record: dict, acknowledgement: dict) -> dict:
    expected = {k: intake[k] for k in ('intake_id', 'mission_id', 'task_id')}
    expected.update(execution_id=result_record['execution_id'],
        enumeration_run_id=intake['enumeration_context']['enumeration_run_id'],
        source_result_sha256=result_record['integrity']['canonical_sha256'],
        evidence_manifest_sha256=result_record['evidence']['manifest_sha256'])
    if (acknowledgement.get('accepted') is not True or not acknowledgement.get('delivery_id')
            or any(acknowledgement.get(k) != v for k, v in expected.items())):
        raise ValueError("Enumeration receipt requires a bound durable acknowledgement")
    return _post('/api/jobs/' + quote(job_id_for_intake(intake['intake_id']), safe='')
        + '/deliveries/enumeration', {**expected, 'delivery_id': acknowledgement['delivery_id']})
