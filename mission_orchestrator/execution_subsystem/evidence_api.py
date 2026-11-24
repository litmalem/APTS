from __future__ import annotations

from http.server import ThreadingHTTPServer
import ipaddress
from urllib.parse import parse_qs, unquote, urlparse

from .authorization_api import _ERRORS
from .evidence_service import ExecutionEvidenceService
from .execution_contract import ExecutionRequestValidationError, ExecutionSourceNotFound
from .runtime_api import ExecutionSubsystemStage65Handler

EVIDENCE_ROUTE = "/api/execution/evidence"
ARTIFACT_ROUTE = "/api/execution/artifacts"
ATTEMPT_ROUTE = EVIDENCE_ROUTE + "/attempts/"
RECON_RESULT_PREFIX = "/api/execution/recon-action-requests/"
RECON_RESULT_SUFFIX = "/results"
ENUMERATION_RESULT_PREFIX = "/api/execution/enumeration-proposals/"


class ExecutionSubsystemStage66Handler(ExecutionSubsystemStage65Handler):
    server_version = "APTSExecutionSubsystem/6.6"
    service: ExecutionEvidenceService | None = None

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path in {"/api/execution/artifact-evidence-contract", "/api/contracts/artifact-evidence-capture"}:
                if parsed.query:
                    raise ExecutionRequestValidationError("evidence contract forbids query overrides")
                self._send_json(200, self._service().get_evidence_contract())
                return
            if parsed.path == "/api/contracts/recon-execution-result":
                if parsed.query:
                    raise ExecutionRequestValidationError("Recon ExecutionResult contract forbids query overrides")
                self._send_json(200, self._service().get_recon_execution_result_contract())
                return
            if parsed.path == "/api/contracts/enumeration-execution-result":
                if parsed.query:
                    raise ExecutionRequestValidationError("Enumeration ExecutionResult contract forbids query overrides")
                self._send_json(200, self._service().get_enumeration_execution_result_contract())
                return
            if parsed.path.startswith(RECON_RESULT_PREFIX) and parsed.path.endswith(RECON_RESULT_SUFFIX):
                if parsed.query:
                    raise ExecutionRequestValidationError("Recon result read forbids query overrides")
                identity = unquote(parsed.path[len(RECON_RESULT_PREFIX):-len(RECON_RESULT_SUFFIX)])
                if not identity or "/" in identity:
                    raise ExecutionRequestValidationError("Recon result route requires one exact Action Request ID")
                try:
                    result = self._service().get_recon_execution_results(identity)
                except ExecutionSourceNotFound as exc:
                    self._send_json(404, {"status":"not_found", "error":str(exc), "action_id":identity})
                    return
                self._send_json(200, result)
                return
            if parsed.path.startswith(ENUMERATION_RESULT_PREFIX) and parsed.path.endswith(RECON_RESULT_SUFFIX):
                if parsed.query:
                    raise ExecutionRequestValidationError("Enumeration result read forbids query overrides")
                identity = unquote(parsed.path[len(ENUMERATION_RESULT_PREFIX):-len(RECON_RESULT_SUFFIX)])
                if not identity or "/" in identity:
                    raise ExecutionRequestValidationError("Enumeration result route requires one exact proposal reference")
                try:
                    result = self._service().get_enumeration_execution_results(identity)
                except ExecutionSourceNotFound as exc:
                    self._send_json(404, {"status":"not_found", "error":str(exc), "proposal_ref":identity})
                    return
                self._send_json(200, result)
                return
            if parsed.path.startswith(ATTEMPT_ROUTE):
                if parsed.query:
                    raise ExecutionRequestValidationError("evidence read forbids query overrides")
                identity = unquote(parsed.path[len(ATTEMPT_ROUTE):])
                verify = identity.endswith("/verify")
                if verify:
                    identity = identity[:-len("/verify")]
                result = self._service().verify_capture(identity) if verify else self._service().get_evidence(identity)
                self._send_json(200, result)
                return
            if parsed.path == EVIDENCE_ROUTE:
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) - {"execution_id", "limit"} or "execution_id" not in query or any(len(v) != 1 for v in query.values()):
                    raise ExecutionRequestValidationError("evidence list requires exact execution_id and optional limit")
                try:
                    limit = int(query.get("limit", ["100"])[0])
                except ValueError as exc:
                    raise ExecutionRequestValidationError("invalid evidence limit") from exc
                result = self._service().list_evidence(query["execution_id"][0], limit)
                self._send_json(200, {**result, "count": len(result["captures"])})
                return
            if parsed.path.startswith(ARTIFACT_ROUTE + "/"):
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) != {"attempt_id"} or len(query["attempt_id"]) != 1:
                    raise ExecutionRequestValidationError("artifact read requires one exact attempt_id")
                identity = unquote(parsed.path[len(ARTIFACT_ROUTE)+1:])
                content = identity.endswith("/content")
                if content:
                    identity = identity[:-len("/content")]
                if not content:
                    self._send_json(200, self._service().get_artifact(identity, query["attempt_id"][0]))
                else:
                    descriptor, payload = self._service().repository.get_artifact(identity, query["attempt_id"][0])
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("X-Artifact-SHA256", descriptor["content_sha256"])
                    self.end_headers()
                    self.wfile.write(payload)
                return
            super().do_GET()
        except _ERRORS as exc:
            self._error(exc)

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith(RECON_RESULT_PREFIX) and path.endswith(RECON_RESULT_SUFFIX):
            self._send_json(409, self._service().reject_execution())
            return
        if path.startswith(ENUMERATION_RESULT_PREFIX) and path.endswith(RECON_RESULT_SUFFIX):
            self._send_json(409, self._service().reject_execution())
            return
        if any(path == p or path.startswith(p + "/") for p in (EVIDENCE_ROUTE, ARTIFACT_ROUTE)):
            self._send_json(409, self._service().reject_execution())
            return
        super().do_POST()


def serve(host="127.0.0.1", port=8791, *, service=None):
    try:
        allowed = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise ExecutionRequestValidationError("Stage 6.6 control API requires loopback bind")
    active = service or ExecutionEvidenceService()
    handler = type("ActiveStage66Handler", (ExecutionSubsystemStage66Handler,), {"service": active})
    try:
        server = ThreadingHTTPServer((host, port), handler)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    finally:
        active.close()
