from __future__ import annotations

from http.server import ThreadingHTTPServer
import ipaddress
from urllib.parse import parse_qs, unquote, urlparse

from .authorization_api import _ERRORS
from .cleanup_api import ExecutionSubsystemStage68Handler
from .cti_feedback_service import ExecutionCTIFeedbackService
from .execution_contract import ExecutionRequestValidationError, canonical_json

FEEDBACK_ROUTE = "/api/execution/cti-feedback"
KNOWLEDGE_ROUTE = "/api/cti/knowledge"
UPDATE_ROUTE = "/api/cti/knowledge-updates"
CONTRACT_ROUTES = {"/api/execution/closed-loop-cti-pentest-contract", "/api/contracts/closed-loop-cti-pentest"}


def _query(parsed, required, optional=()):
    values = parse_qs(parsed.query, keep_blank_values=True)
    if not set(required) <= set(values) or set(values) - set(required) - set(optional) or any(len(v) != 1 for v in values.values()):
        raise ExecutionRequestValidationError("CTI read requires exact scoped query keys")
    return {k:v[0] for k,v in values.items()}


def _int(value, field):
    try:
        return int(value)
    except ValueError as exc:
        raise ExecutionRequestValidationError("invalid " + field) from exc


class ExecutionSubsystemStage69Handler(ExecutionSubsystemStage68Handler):
    server_version = "APTSExecutionSubsystem/6.9"
    service: ExecutionCTIFeedbackService | None = None

    def _service(self):
        if self.service is None:
            self.service = ExecutionCTIFeedbackService()
        return self.service

    def _export_json(self, value, identity, digest):
        raw = canonical_json(value).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{identity}.json"')
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-CTI-SHA256", digest)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path in CONTRACT_ROUTES:
                if parsed.query:
                    raise ExecutionRequestValidationError("CTI contract forbids query overrides")
                self._send_json(200, self._service().get_feedback_contract())
                return
            if parsed.path == FEEDBACK_ROUTE:
                query = _query(parsed, {"execution_id"}, {"limit"})
                self._send_json(200, self._service().list_feedback(query["execution_id"], _int(query.get("limit", "100"), "limit")))
                return
            if parsed.path.startswith(FEEDBACK_ROUTE + "/"):
                query = _query(parsed, {"attempt_id"})
                identity = unquote(parsed.path[len(FEEDBACK_ROUTE)+1:])
                if identity.endswith("/export"):
                    value = self._service().export_feedback(identity[:-7], query["attempt_id"])
                    self._export_json(value, value["feedback"]["feedback_id"], value["feedback"]["integrity"]["canonical_sha256"])
                elif identity.endswith("/verify"):
                    value = self._service().get_feedback(identity[:-7], query["attempt_id"])
                    self._send_json(200, {k:v for k,v in value.items() if k != "feedback"})
                else:
                    self._send_json(200, self._service().get_feedback(identity, query["attempt_id"]))
                return
            if parsed.path == KNOWLEDGE_ROUTE:
                query = _query(parsed, {"mission_id"}, {"limit"})
                self._send_json(200, self._service().list_knowledge(query["mission_id"], _int(query.get("limit", "100"), "limit")))
                return
            if parsed.path.startswith(KNOWLEDGE_ROUTE + "/"):
                query = _query(parsed, {"mission_id"}, {"revision"})
                revision = None if "revision" not in query else _int(query["revision"], "revision")
                identity = unquote(parsed.path[len(KNOWLEDGE_ROUTE)+1:])
                if identity.endswith("/export"):
                    value = self._service().export_knowledge(identity[:-7], query["mission_id"], revision)
                    record = value["revisions"][-1]["record"]
                    self._export_json(value, record["revision_id"], record["integrity"]["canonical_sha256"])
                else:
                    self._send_json(200, self._service().get_knowledge(identity, query["mission_id"], revision))
                return
            super().do_GET()
        except _ERRORS as exc:
            self._error(exc)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path in {FEEDBACK_ROUTE, UPDATE_ROUTE}:
            try:
                if parsed.query:
                    raise ExecutionRequestValidationError("CTI intake forbids query overrides")
                method = self._service().create_feedback if parsed.path == FEEDBACK_ROUTE else self._service().update_knowledge
                value = method(self._read_json())
                self._send_json(201 if value["created"] else 200, value)
            except _ERRORS as exc:
                self._error(exc)
            return
        if (parsed.path.startswith(FEEDBACK_ROUTE + "/") or parsed.path.startswith("/api/cti/") or parsed.path in CONTRACT_ROUTES):
            self._send_json(409, self._service().reject_execution())
            return
        super().do_POST()


def serve(host="127.0.0.1", port=8791, *, service=None):
    try:
        allowed = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise ExecutionRequestValidationError("Stage 6.9 CTI feedback API requires loopback bind")
    active = service or ExecutionCTIFeedbackService()
    handler = type("ActiveStage69Handler", (ExecutionSubsystemStage69Handler,), {"service":active})
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
