from __future__ import annotations

from http.server import ThreadingHTTPServer
import ipaddress
from urllib.parse import parse_qs, unquote, urlparse

from .authorization_api import ExecutionSubsystemStage62Handler, _ERRORS
from .execution_contract import ExecutionRequestValidationError
from .gateway_service import ExecutionGatewayService


class ExecutionSubsystemStage63Handler(ExecutionSubsystemStage62Handler):
    server_version = "APTSExecutionSubsystem/6.3"
    service: ExecutionGatewayService | None = None

    def _service(self):
        if self.service is None:
            self.service = ExecutionGatewayService()
        return self.service

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path in {"/api/execution/execution-gateway-contract", "/api/contracts/controlled-execution-gateway"}:
                if parsed.query:
                    raise ExecutionRequestValidationError("gateway contract does not accept query overrides")
                self._send_json(200, self._service().get_gateway_contract())
                return
            prefix = "/api/execution/gateway/submissions/"
            if parsed.path.startswith(prefix):
                if parsed.query:
                    raise ExecutionRequestValidationError("gateway reads do not accept query overrides")
                item = self._service().repository.get_gateway_submission(unquote(parsed.path[len(prefix):]))
                self._send_json(200 if item else 404, self._service().gateway_response(item) if item else {"status": "not_found", "execution_authorized": False})
                return
            if parsed.path == "/api/execution/gateway/submissions":
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) - {"execution_id", "limit"} or "execution_id" not in query or any(len(x) != 1 for x in query.values()):
                    raise ExecutionRequestValidationError("gateway list requires one execution_id and optional limit")
                try:
                    limit = int(query.get("limit", ["100"])[0])
                except ValueError as exc:
                    raise ExecutionRequestValidationError("invalid gateway list limit") from exc
                items = self._service().repository.list_gateway_submissions(query["execution_id"][0], limit)
                self._send_json(200, {"status": "ok", "count": len(items), "submissions": items,
                                     "historical_records": True, "gateway_admitted": False,
                                     "authorization_current": False, "execution_authorized": False,
                                     "usable_for_dispatch": False, "governance_query_performed": False})
                return
            super().do_GET()
        except _ERRORS as exc:
            self._error(exc)

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/execution/gateway/submissions":
            super().do_POST()
            return
        try:
            if parsed.query:
                raise ExecutionRequestValidationError("gateway intake does not accept query overrides")
            result = self._service().submit_execution(self._read_json())
            self._send_json(201 if result["created"] else 200, result)
        except _ERRORS as exc:
            self._error(exc)


def serve(host="127.0.0.1", port=8791, *, service=None):
    # This control plane has no remote authentication mechanism in the baseline.
    # Never broaden its authority by exposing it on a wildcard/remote interface.
    try:
        allowed = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise ExecutionRequestValidationError("Stage 6.3 control API requires a loopback bind address")
    active = service or ExecutionGatewayService()
    active.repository.initialize()
    handler = type("ActiveExecutionStage63Handler", (ExecutionSubsystemStage63Handler,), {"service": active})
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
