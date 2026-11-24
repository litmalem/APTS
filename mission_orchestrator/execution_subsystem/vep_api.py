from __future__ import annotations

from http.server import ThreadingHTTPServer
import ipaddress
from urllib.parse import parse_qs, unquote, urlparse

from .authorization_api import _ERRORS
from .evidence_api import ExecutionSubsystemStage66Handler
from .execution_contract import ExecutionRequestValidationError, canonical_json
from .vep_service import ExecutionVEPService

ROUTE = "/api/execution/veps"
CONTRACT_ROUTES = {"/api/execution/vep-construction-integrity-contract", "/api/contracts/vep-construction-integrity"}


class ExecutionSubsystemStage67Handler(ExecutionSubsystemStage66Handler):
    server_version = "APTSExecutionSubsystem/6.7"
    service: ExecutionVEPService | None = None

    def _service(self):
        if self.service is None:
            self.service = ExecutionVEPService()
        return self.service

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path in CONTRACT_ROUTES:
                if parsed.query:
                    raise ExecutionRequestValidationError("VEP contract forbids query overrides")
                self._send_json(200, self._service().get_vep_contract())
                return
            if parsed.path == ROUTE:
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) - {"execution_id", "limit"} or "execution_id" not in query or any(len(v) != 1 for v in query.values()):
                    raise ExecutionRequestValidationError("VEP list requires exact execution_id and optional limit")
                try:
                    limit = int(query.get("limit", ["100"])[0])
                except ValueError as exc:
                    raise ExecutionRequestValidationError("invalid VEP limit") from exc
                self._send_json(200, self._service().list_veps(query["execution_id"][0], limit))
                return
            if parsed.path.startswith(ROUTE + "/"):
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) != {"attempt_id"} or len(query["attempt_id"]) != 1:
                    raise ExecutionRequestValidationError("VEP read requires one exact attempt_id")
                identity = unquote(parsed.path[len(ROUTE)+1:])
                if identity.endswith("/verify"):
                    self._send_json(200, self._service().verify_vep_record(identity[:-7], query["attempt_id"][0]))
                elif identity.endswith("/export"):
                    ident = identity[:-7]
                    value = self._service().export_vep(ident, query["attempt_id"][0])
                    raw = canonical_json(value).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Disposition", f'attachment; filename="{value["vep"]["vep_id"]}.json"')
                    self.send_header("Content-Length", str(len(raw)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("X-VEP-SHA256", value["vep"]["integrity"]["canonical_sha256"])
                    self.end_headers()
                    self.wfile.write(raw)
                else:
                    self._send_json(200, self._service().get_vep(identity, query["attempt_id"][0]))
                return
            super().do_GET()
        except _ERRORS as exc:
            self._error(exc)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == ROUTE:
            try:
                if parsed.query:
                    raise ExecutionRequestValidationError("VEP construction forbids query overrides")
                value = self._service().construct_vep(self._read_json())
                self._send_json(201 if value["created"] else 200, value)
            except _ERRORS as exc:
                self._error(exc)
            return
        if parsed.path.startswith(ROUTE + "/") or parsed.path in CONTRACT_ROUTES:
            self._send_json(409, self._service().reject_execution())
            return
        super().do_POST()


def serve(host="127.0.0.1", port=8791, *, service=None):
    try:
        allowed = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise ExecutionRequestValidationError("Stage 6.7 VEP API requires loopback bind")
    active = service or ExecutionVEPService()
    handler = type("ActiveStage67Handler", (ExecutionSubsystemStage67Handler,), {"service":active})
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
