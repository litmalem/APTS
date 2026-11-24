from __future__ import annotations

from http.server import ThreadingHTTPServer
import ipaddress
from urllib.parse import parse_qs, unquote, urlparse

from .authorization_api import _ERRORS
from .execution_contract import ExecutionRequestValidationError
from .gateway_api import ExecutionSubsystemStage63Handler
from .adapter_service import ExecutionAdapterService

ROUTE = "/api/execution/gateway/tool-invocations"


class ExecutionSubsystemStage64Handler(ExecutionSubsystemStage63Handler):
    server_version = "APTSExecutionSubsystem/6.4"
    service: ExecutionAdapterService | None = None

    def _service(self):
        if self.service is None:
            self.service = ExecutionAdapterService()
        return self.service

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path in {"/api/execution/tool-adapters-contract", "/api/contracts/authorized-tool-adapters-sandboxing"}:
                if parsed.query:
                    raise ExecutionRequestValidationError("adapter contract forbids query overrides")
                self._send_json(200, self._service().get_adapter_contract())
                return
            if parsed.path.startswith(ROUTE + "/"):
                if parsed.query:
                    raise ExecutionRequestValidationError("adapter reads forbid query overrides")
                item = self._service().repository.get_adapter_invocation(unquote(parsed.path[len(ROUTE)+1:]))
                self._send_json(200 if item else 404, self._service().adapter_response(item) if item else {"status": "not_found", "execution_authorized": False})
                return
            if parsed.path == ROUTE:
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) - {"execution_id", "limit"} or "execution_id" not in query or any(len(x) != 1 for x in query.values()):
                    raise ExecutionRequestValidationError("adapter list requires exact execution_id and optional limit")
                try:
                    limit = int(query.get("limit", ["100"])[0])
                except ValueError as exc:
                    raise ExecutionRequestValidationError("invalid adapter list limit") from exc
                items = self._service().repository.list_adapter_invocations(query["execution_id"][0], limit)
                self._send_json(200, {"count": len(items), "invocations": [self._service().adapter_response(i) for i in items],
                                     "execution_authorized": False, "target_network_io_performed": False})
                return
            super().do_GET()
        except _ERRORS as exc:
            self._error(exc)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != ROUTE:
            super().do_POST()
            return
        try:
            if parsed.query:
                raise ExecutionRequestValidationError("adapter intake forbids query overrides")
            response = self._service().invoke_tool(self._read_json())
            self._send_json(201 if response["created"] else 200, response)
        except _ERRORS as exc:
            self._error(exc)


def serve(host="127.0.0.1", port=8791, *, service=None):
    try:
        allowed = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise ExecutionRequestValidationError("Stage 6.4 control API requires loopback bind")
    active = service or ExecutionAdapterService()
    active.repository.initialize()
    handler = type("ActiveStage64Handler", (ExecutionSubsystemStage64Handler,), {"service": active})
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
