from __future__ import annotations

from copy import deepcopy
import hashlib
import hmac
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .execution_contract import (
    ExecutionRequestConflict, ExecutionRequestIntegrityError, ExecutionRequestValidationError,
    ExecutionSourceNotFound, ExecutionSourceRejected, ExecutionSourceUnavailable,
    canonical_execution_request_contract, sha256_hex,
)
from .tool_registry import wpt_capability_profile_definitions
from .wpt_intake_contract import normalize_wpt_intake
from .wpt_intake_repository import WPTIntakeRepository, _seal, _seal_handoff
from .wpt_intake_source import WPTIntakeAuthoritySource


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Stage 6 request API redirect rejected")


class WPTIntakeService:
    def __init__(self, repository: WPTIntakeRepository | None = None,
                 authority_source: WPTIntakeAuthoritySource | None = None,
                 stage6_result_source=None,
                 token: str | None = None,
                 recon_handoff_provider=None,
                 stage6_gateway=None) -> None:
        self.repository = repository or WPTIntakeRepository()
        self.authority_source = authority_source or WPTIntakeAuthoritySource()
        self.stage6_result_source = stage6_result_source
        self.recon_handoff_provider = recon_handoff_provider
        self.stage6_gateway = stage6_gateway
        self._token = token if token is not None else os.environ.get("MISSION_WPT_INTAKE_TOKEN", "")

    @property
    def configured(self) -> bool:
        return isinstance(self._token, str) and len(self._token) >= 32

    def authenticate(self, authorization: str | None) -> bool:
        if not self.configured or not isinstance(authorization, str):
            return False
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return False
        supplied = parts[1].encode("utf-8")
        expected = self._token.encode("utf-8")
        return hmac.compare_digest(hashlib.sha256(supplied).digest(), hashlib.sha256(expected).digest())

    def health(self) -> dict[str, Any]:
        profiles = wpt_capability_profile_definitions()
        return {
            "status": "ok" if self.configured else "degraded",
            "component": "MISSION_WPT_GOVERNED_INTAKE",
            "schema_version": "apts-wpt-governed-intake-v1",
            "profiles": [{"profile_id": p["profile_id"], "execution_status": p["execution_status"]} for p in profiles],
            "request_is_authorization": False, "execution_authorized": False,
            "dispatch_performed": False, "target_io_performed": False,
        }

    def submit(self, payload: Any) -> dict[str, Any]:
        intake = normalize_wpt_intake(payload)
        previous = self.repository.get(intake["intake_id"])
        if previous:
            if previous["record"]["intake"] != intake:
                raise ExecutionRequestConflict("intake_id already exists with different content")
            admission = self._submit_stage6_admission(previous)
            job_delivery = self._publish_stage6_job(intake, admission)
            return {"created": False, **previous,
                    "stage6_admission": admission, "stage6_job_delivery": job_delivery}
        authority = self.authority_source.resolve(intake)
        record = _seal({
            "schema_version": "apts-wpt-governed-intake-record-v1",
            "status": "ACCEPTED_PENDING_STAGE6",
            "intake": deepcopy(intake),
            "authority_snapshot": authority,
            "semantics": {"scope_checked": True, "roe_checked": True, "task_state_checked": True,
                          "budget_checked": True, "request_is_authorization": False,
                          "execution_authorized": False, "dispatch_performed": False,
                          "target_io_performed": False},
            "stage6_contract_sha256": canonical_execution_request_contract()["integrity"]["canonical_sha256"],
            "limitation": "WPT intake is a governed request source only; authorization and gateway admission are separate, and this record performs no target I/O.",
        })
        stored, created = self.repository.append(record)
        admission = self._submit_stage6_admission(stored)
        job_delivery = self._publish_stage6_job(intake, admission)
        return {"created": created, **stored,
                "stage6_admission": admission, "stage6_job_delivery": job_delivery}

    def _submit_stage6_admission(self, stored: dict[str, Any]) -> dict[str, Any]:
        """Create the canonical request through Stage 6, without legacy gateway admission.

        Stage 6.5 performs the fresh GSS authorization and runtime reservation at
        /api/execution/runtime/attempts. Creating the immutable request here is
        not authorization and performs no target I/O.
        """
        record = stored["record"]
        intake = record["intake"]
        authority = record["authority_snapshot"]
        if self.repository.get_result(intake['intake_id']) is not None:
            return {'status':'RESULT_STORED','reason_code':'WPT_RESULT_ALREADY_STORED',
                    'execution_authorized':False,'target_io_performed':False}
        if (intake["profile"] not in {"fingerprinting", "enumeration"}
                or authority.get("execution_status") != "EXECUTABLE"
                or authority.get("task_lifecycle_state") != "RUNNING"
                or authority.get("orchestration_status") != "ACTIVE"):
            return {"status": "BLOCKED", "reason_code": "WPT_CAPABILITY_OR_TASK_NOT_EXECUTABLE",
                    "execution_authorized": False, "gateway_admitted": False,
                    "dispatch_performed": False, "target_io_performed": False}
        if os.getenv("APTS_WPT_GOVERNED_AUTODISPATCH", "1").strip() == "0":
            return {"status": "PENDING", "reason_code": "AUTOMATIC_STAGE6_ADMISSION_DISABLED",
                    "execution_authorized": False, "gateway_admitted": False,
                    "dispatch_performed": False, "target_io_performed": False}

        try:
            from .execution_contract import WPT_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION, sha256_hex
            base = os.getenv("APTS_STAGE6_RUNTIME_URL", "").strip().rstrip("/")
            if not base:
                return {"status": "PENDING", "reason_code": "STAGE6_RUNTIME_URL_NOT_CONFIGURED",
                        "execution_authorized": False, "gateway_admitted": False,
                        "dispatch_performed": False, "target_io_performed": False}
            parsed = urlparse(base)
            if parsed.scheme != "https" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
                return {"status": "BLOCKED", "reason_code": "STAGE6_RUNTIME_URL_MUST_USE_HTTPS_OR_LOOPBACK",
                        "execution_authorized": False, "gateway_admitted": False,
                        "dispatch_performed": False, "target_io_performed": False}

            intake_sha = record["integrity"]["canonical_sha256"]
            seed = sha256_hex({"intake_id": intake["intake_id"], "intake_sha256": intake_sha})[:32]
            payload = {
                "schema_version": WPT_EXECUTION_REQUEST_INTAKE_SCHEMA_VERSION,
                "source_type": "WPT_GOVERNED_INTAKE",
                "request_id": "ereq-wpt-" + seed,
                "idempotency_key": intake["idempotency_key"],
                "wpt_intake_id": intake["intake_id"],
                "wpt_intake_sha256": intake_sha,
            }
            if self.stage6_gateway is not None:
                # Injectable request creator remains useful to isolated callers;
                # it must only create the immutable request, never admit it.
                response = self.stage6_gateway.create_request(payload)
            else:
                request = Request(base + "/api/execution/requests",
                    data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Accept": "application/json",
                             "User-Agent": "APTS-Mission-WPT-Request/1.0"}, method="POST")
                with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=8) as result:
                    raw = result.read(65537)
                    if len(raw) > 65536 or result.status not in (200, 201):
                        raise RuntimeError("Stage 6 request API returned an invalid response")
                    response = json.loads(raw.decode("utf-8"))
            if not isinstance(response, dict):
                raise RuntimeError("Stage 6 request response must be an object")
            envelope = response.get("envelope") or {}
            execution_request = envelope.get("execution_request") or {}
            execution_id = execution_request.get("execution_id")
            envelope_sha = (envelope.get("integrity") or {}).get("canonical_sha256")
            if (not isinstance(execution_id, str) or not execution_id.startswith("exec-")
                    or not isinstance(envelope_sha, str) or len(envelope_sha) != 64
                    or any(c not in "0123456789abcdef" for c in envelope_sha)):
                raise RuntimeError("Stage 6 request response binding is invalid")
            return {"status": "REQUEST_CREATED", "execution_id": execution_id,
                    "envelope_sha256": envelope_sha, "request_created": bool(response.get("created")),
                    "authorization_recorded": False, "governance_query_performed": False,
                    "execution_authorized": False, "gateway_admitted": False,
                    "dispatch_performed": False, "target_io_performed": False}
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            # Keep the proposal durable and let the periodic sweep retry the same
            # idempotent request. Never infer authorization or target I/O here.
            return {"status": "PENDING", "reason_code": type(exc).__name__[:80],
                    "execution_authorized": False, "gateway_admitted": False,
                    "dispatch_performed": False, "target_io_performed": False}

    @staticmethod
    def _publish_stage6_job(intake: dict[str, Any], admission: dict[str, Any]) -> dict[str, Any]:
        execution_id = admission.get("execution_id")
        if not execution_id:
            return {"status": "NOT_READY", "target_io_performed": False}
        gateway_status = str(admission.get("status") or "").upper()
        status_map = {
            "REQUEST_CREATED": "AWAITING_STAGE6",
            "ADMITTED_AWAITING_ADAPTER": "AUTHORIZED",
            "REVIEW_REQUIRED": "AWAITING_APPROVAL",
            "DENIED": "BLOCKED",
            "BLOCKED_CONSTRAINTS": "BLOCKED",
            "BLOCKED_BUDGET": "BLOCKED",
            "BLOCKED_DUPLICATE": "BLOCKED",
            "PENDING": "AWAITING_STAGE6",
        }
        status = status_map.get(gateway_status, "AWAITING_STAGE6")
        try:
            from .wpt_job_callback import publish_job_status
            return publish_job_status(intake, admission, status)
        except Exception as exc:
            return {"status": "PENDING", "error_code": type(exc).__name__[:80],
                    "target_io_performed": False}

    def get(self, intake_id: str) -> dict[str, Any] | None:
        value = self.repository.get(intake_id)
        if value is not None:
            value["stage6_result"] = self.repository.get_result(intake_id)
        return value

    def list_for_task(self, mission_id: str, task_id: str, limit: int = 50) -> list[dict[str, Any]]:
        values = self.repository.list_for_task(mission_id, task_id, limit)
        for value in values:
            value["stage6_result"] = self.repository.get_result(value["record"]["intake"]["intake_id"])
        return values

    @staticmethod
    def _safe_observation(value, depth=0):
        """Bound and reject sensitive/raw response fields before result persistence."""
        if depth==0 and isinstance(value,dict) and value.get("schema_version")=="web-technology-observation-v4":
            from adapters.profile_contract import validate_profile
            try:return deepcopy(validate_profile(value))
            except (ValueError,TypeError,KeyError,AttributeError) as exc:raise ExecutionRequestValidationError("Invalid sanitized bounded WPT result") from exc
        if depth > 12:
            raise ExecutionRequestValidationError("Stage 6 WPT result nesting exceeds the limit")
        if value is None or type(value) in (bool, int, float, str):
            if isinstance(value, str) and len(value) > 8192:
                raise ExecutionRequestValidationError("Stage 6 WPT result string exceeds the limit")
            return value
        if isinstance(value, list):
            if len(value) > 2000:
                raise ExecutionRequestValidationError("Stage 6 WPT result array exceeds the limit")
            return [WPTIntakeService._safe_observation(item, depth + 1) for item in value]
        if isinstance(value, dict):
            if len(value) > 200:
                raise ExecutionRequestValidationError("Stage 6 WPT result object exceeds the limit")
            forbidden = {"body", "body_html", "raw", "raw_body", "raw_content", "html", "html_content",
                         "response_body", "response_headers", "cookie", "cookies", "authorization",
                         "authorization_header", "token", "secret", "credential", "set_cookie"}
            result = {}
            for key, item in value.items():
                normalized_key = key.lower().replace("-", "_") if isinstance(key, str) else ""
                if (not isinstance(key, str) or len(key) > 100 or normalized_key in forbidden
                        or normalized_key == "headers"
                        or any(marker in normalized_key for marker in ("raw", "body", "cookie", "authorization", "token", "credential", "secret"))):
                    raise ExecutionRequestValidationError("Stage 6 WPT result contains a forbidden field")
                result[key] = WPTIntakeService._safe_observation(item, depth + 1)
            return result
        raise ExecutionRequestValidationError("Stage 6 WPT result contains an unsupported value")

    _COMPLETE_COVERAGE = frozenset({"PRESENT", "NO_TARGET_IO", "NOT_PRODUCED",
                                    "NOT_SUPPORTED_BY_CURRENT_FIXED_ADAPTERS", "NOT_MEASURED"})

    @classmethod
    def _only_response_truncation_gap(cls, manifest: dict, observation: Any) -> bool:
        """True only if TARGET_RESPONSE is the sole incomplete capture and the byte limit explains it."""
        coverage = manifest.get("coverage")
        artifacts = manifest.get("artifacts")
        binding = observation.get("network_binding") if isinstance(observation, dict) else None
        if (manifest.get("capture_status") != "PARTIAL" or manifest.get("target_io_uncertain") is not False
                or not isinstance(coverage, dict) or not isinstance(artifacts, list)
                or not isinstance(binding, dict) or binding.get("byte_limit_reached") is not True
                or coverage.get("TARGET_RESPONSE") != "PARTIAL"):
            return False
        if any(v not in cls._COMPLETE_COVERAGE for k, v in coverage.items() if k != "TARGET_RESPONSE"):
            return False
        incomplete = [a.get("kind") for a in artifacts if isinstance(a, dict) and a.get("capture_complete") is not True]
        return incomplete == ["TARGET_RESPONSE"]

    def submit_stage6_result(self, payload: Any) -> dict[str, Any]:
        fields = {"schema_version", "intake_id", "execution_id", "attempt_id"}
        if not isinstance(payload, dict) or set(payload) != fields or payload.get("schema_version") != "apts-wpt-stage6-result-reference-v1":
            raise ExecutionRequestValidationError("Stage 6 result reference must contain exactly schema_version, execution_id, and attempt_id")
        from .execution_contract import require_id
        execution_id = require_id(payload["execution_id"], "execution_id", "exec-")
        attempt_id = require_id(payload["attempt_id"], "attempt_id", "xattempt-")
        intake_id = require_id(payload["intake_id"], "intake_id", "wptreq-")
        intake_record = self.repository.get(intake_id)
        if intake_record is None:
            raise ExecutionSourceNotFound("unknown WPT intake")
        intake = intake_record["record"]["intake"]
        authority = intake_record["record"]["authority_snapshot"]
        if authority.get("execution_status") != "EXECUTABLE":
            raise ExecutionSourceRejected("WPT Stage 6 capability is not executable")
        source = self.stage6_result_source
        if source is None:
            from .cti_feedback_repository import ReadOnlyExecutionFeedbackSource
            repository = ReadOnlyExecutionFeedbackSource()
            if not repository.sqlite_path.exists():
                raise ExecutionSourceUnavailable("authoritative Stage 6 evidence store is unavailable")
            source = repository
        try:
            snapshot = source.get_wpt_result_snapshot(execution_id, attempt_id)
        except (ExecutionSourceNotFound, ExecutionRequestIntegrityError, ExecutionSourceRejected,
                ExecutionSourceUnavailable):
            raise
        except Exception as exc:
            raise ExecutionSourceUnavailable("authoritative Stage 6 result lookup failed") from exc
        expected_profile = authority["profile_id"]
        profile = {p["profile_id"]: p for p in wpt_capability_profile_definitions()}.get(expected_profile)
        if profile is None or snapshot.get("runtime_state") != "SUCCEEDED":
            raise ExecutionSourceRejected("Stage 6 WPT attempt is not a successful terminal attempt")
        action = snapshot.get("action") or {}
        target = snapshot.get("target") or {}
        expected_action = profile["action"]
        if (snapshot.get("execution_id") != execution_id or snapshot.get("attempt_id") != attempt_id
                or snapshot.get("mission_id") != intake["mission_id"]
                or snapshot.get("task_id") != intake["task_id"]
                or action != expected_action
                or target != intake["target"]):
            raise ExecutionRequestIntegrityError("Stage 6 result mission/task/target/capability binding mismatch")
        evidence = snapshot.get("evidence")
        runtime_result = snapshot.get("runtime_result")
        if (not isinstance(evidence, dict) or evidence.get("sealed") is not True
                or not isinstance(evidence.get("manifest_sha256"), str)
                or len(evidence["manifest_sha256"]) != 64
                or not isinstance(runtime_result, dict)
                or runtime_result.get("status") != "SUCCEEDED"
                or not isinstance(runtime_result.get("integrity"), dict)):
            raise ExecutionSourceRejected("Stage 6 result is missing successful runtime result or sealed evidence")
        manifest = evidence.get("manifest") or {}
        if (manifest.get("attempt_id") != attempt_id
                or manifest.get("mission_id") != intake["mission_id"]
                or manifest.get("task_id") != intake["task_id"]
                or manifest.get("capture_status") not in ("CAPTURED", "PARTIAL")
                or manifest.get("adapter_result_sha256") != runtime_result["integrity"].get("canonical_sha256")
                or manifest.get("integrity", {}).get("canonical_sha256") != evidence["manifest_sha256"]):
            raise ExecutionRequestIntegrityError("Stage 6 sealed evidence binding mismatch")
        # PARTIAL is accepted only when the single gap is a target response cut
        # off by the broker's byte limit (bounded I/O by design); the result is
        # then explicitly marked truncated instead of being reported CAPTURED.
        response_truncated = False
        if manifest.get("capture_status") == "PARTIAL":
            if not self._only_response_truncation_gap(manifest, runtime_result.get("observation")):
                raise ExecutionRequestIntegrityError("Stage 6 sealed evidence is partial beyond response truncation")
            response_truncated = True
        safe_result = {
            "status": "SUCCEEDED", "reason_codes": list(runtime_result.get("reason_codes", [])),
            "observation": self._safe_observation(runtime_result.get("observation")),
            "result_sha256": runtime_result["integrity"].get("canonical_sha256"),
        }
        observation = safe_result['observation']
        if isinstance(observation, dict) and observation.get('schema_version') == 'web-technology-observation-v4':
            if observation.get('target') != intake['target']['target_value'] or observation.get('mode') != intake['profile']:
                raise ExecutionRequestIntegrityError('WPT observation target/profile binding mismatch')
        record = {
            "schema_version": "apts-wpt-stage6-result-record-v1", "status": "VALIDATED_AND_STORED",
            "intake_id": intake_id, "mission_id": intake["mission_id"], "task_id": intake["task_id"],
            "target": deepcopy(intake["target"]), "profile_id": expected_profile,
            "action": deepcopy(expected_action), "execution_id": execution_id, "attempt_id": attempt_id,
            "evidence": {"evidence_id": evidence["evidence_id"], "manifest_sha256": evidence["manifest_sha256"],
                         "capture_status": "SEALED", **({"response_truncated": True} if response_truncated else {})},
            "result": safe_result,
            "semantics": {"stage6_origin_verified": True, "mission_task_target_capability_bound": True,
                          "sealed_evidence_verified": True, "target_io_authorized_by_this_record": False,
                          "result_is_vulnerability_finding": False},
        }
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 524288:
            raise ExecutionRequestValidationError("sanitized Stage 6 WPT result exceeds 512 KiB")
        from .wpt_intake_repository import _seal_result
        stored, created = self.repository.append_result(_seal_result(record))
        try:
            from .wpt_job_callback import publish_stage6_result
            callback = publish_stage6_result(intake, stored["record"])
        except Exception as exc:
            callback = {"status": "PENDING", "error_code": type(exc).__name__[:80]}
        return {"created": created, **stored, "wpt_job_delivery": callback}

    def get_handoff(self, intake_id: str) -> dict[str, Any] | None:
        return self.repository.get_handoff(intake_id)

    def handoff_to_recon(self, intake_id: str, payload: Any) -> dict[str, Any]:
        """Durably enqueue a verified Stage 6 result and retry delivery safely."""
        from .execution_contract import require_id
        initial = payload == {"schema_version": "apts-wpt-recon-initial-request-v1"}
        if not initial and (not isinstance(payload, dict)
                or set(payload) != {"schema_version", "parent_recon_run_id", "action_id"}
                or payload.get("schema_version") != "apts-wpt-recon-handoff-request-v1"):
            raise ExecutionRequestValidationError(
                "Recon handoff requires exactly schema_version, parent_recon_run_id, and action_id"
            )
        intake_id = require_id(intake_id, "intake_id", "wptreq-")
        parent_id = None if initial else require_id(payload["parent_recon_run_id"], "parent_recon_run_id", "reconrun-")
        action_id = None if initial else require_id(payload["action_id"], "action_id", "rareq-")
        intake_record = self.repository.get(intake_id)
        result_entry = self.repository.get_result(intake_id)
        if intake_record is None or result_entry is None:
            raise ExecutionSourceNotFound("a validated Stage 6 result is required before Recon handoff")
        intake = intake_record["record"]["intake"]
        authority = intake_record["record"]["authority_snapshot"]
        result = result_entry["record"]
        handoff = _seal_handoff({
            "schema_version": "apts-wpt-recon-initial-event-v1" if initial else "apts-wpt-recon-handoff-event-v1",
            "handoff_id": "wpthandoff-" + hashlib.sha256(
                f"{intake_id}:{parent_id}:{action_id}:{result['integrity']['canonical_sha256']}".encode("utf-8")
            ).hexdigest()[:32],
            "intake_id": intake_id,
            "mission_id": intake["mission_id"], "task_id": intake["task_id"],
            "orchestration_id": authority["orchestration_id"],
            "target": deepcopy(intake["target"]), "profile_id": authority["profile_id"],
            "action": deepcopy(authority["action"]),
            "parent_recon_run_id": parent_id, "action_id": action_id,
            "execution_id": result["execution_id"], "attempt_id": result["attempt_id"],
            "result_stored_at": result_entry["stored_at"],
            "source_result_sha256": result["integrity"]["canonical_sha256"],
            "evidence": deepcopy(result["evidence"]),
            "result": deepcopy(result["result"]),
            "semantics": {"result_is_authorization": False, "result_is_vulnerability_finding": False,
                          "target_io_performed_by_handoff": False, "previous_recon_run_mutated": False},
        })
        queued, newly_created = self.repository.enqueue_handoff(handoff)
        if queued["delivery_status"] == "DELIVERED":
            return {"status": "delivered", "created": False, **queued}
        provider = self.recon_handoff_provider or self._deliver_to_recon
        try:
            acknowledgement = provider(handoff)
            saved = self.repository.record_handoff_attempt(intake_id, acknowledgement=acknowledgement)
        except Exception as exc:
            # Store only a bounded error class; request/result material never enters logs or error fields.
            saved = self.repository.record_handoff_attempt(
                intake_id, error_code=type(exc).__name__[:80] or "RECON_DELIVERY_FAILED"
            )
        return {"status": "delivered" if saved["delivery_status"] == "DELIVERED" else "pending",
                "created": newly_created, **saved}

    @staticmethod
    def _deliver_to_recon(handoff: dict[str, Any]) -> dict[str, Any]:
        from .wpt_recon_source import recon_service
        receiver = recon_service()
        if handoff.get("schema_version") == "apts-wpt-recon-initial-event-v1":
            return receiver.run_wpt_initial_observation(handoff)
        return receiver.run_wpt_reconnaissance_iteration(handoff)
