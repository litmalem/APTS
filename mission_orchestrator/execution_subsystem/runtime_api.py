from __future__ import annotations

from http.server import ThreadingHTTPServer
import ipaddress
from urllib.parse import parse_qs, unquote, urlparse

from .adapter_api import ExecutionSubsystemStage64Handler, ROUTE as ADAPTER_ROUTE
from .authorization_api import _ERRORS
from .execution_contract import ExecutionRequestValidationError
from .runtime_service import ExecutionRuntimeService

ROUTE = "/api/execution/runtime/attempts"


class ExecutionSubsystemStage65Handler(ExecutionSubsystemStage64Handler):
    server_version = "APTSExecutionSubsystem/6.5"
    service: ExecutionRuntimeService | None = None

    def _service(self):
        if self.service is None:
            raise ExecutionRequestValidationError("runtime service must be initialized with an exclusive owner")
        return self.service

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path in {"/api/execution/execution-runtime-contract", "/api/contracts/execution-runtime-control"}:
                if parsed.query:
                    raise ExecutionRequestValidationError("runtime contract forbids query overrides")
                self._send_json(200, self._service().get_runtime_contract())
                return
            if parsed.path.startswith(ROUTE + "/"):
                if parsed.query:
                    raise ExecutionRequestValidationError("runtime read forbids query overrides")
                self._send_json(200, self._service().get_attempt(unquote(parsed.path[len(ROUTE)+1:])))
                return
            if parsed.path == ROUTE:
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) - {"execution_id", "limit"} or "execution_id" not in query or any(len(x) != 1 for x in query.values()):
                    raise ExecutionRequestValidationError("runtime list requires exact execution_id and optional limit")
                try:
                    limit = int(query.get("limit", ["100"])[0])
                except ValueError as exc:
                    raise ExecutionRequestValidationError("invalid runtime limit") from exc
                items = self._service().repository.list_attempts(query["execution_id"][0], limit)
                self._send_json(200, {"count":len(items), "attempts":[self._service().runtime_response(i) for i in items],
                    "execution_authorized":False, "target_network_io_performed":False})
                return
            super().do_GET()
        except _ERRORS as exc:
            self._error(exc)

    def do_POST(self):
        parsed = urlparse(self.path)
        paths = {ROUTE, ADAPTER_ROUTE, "/api/execution/runtime/retries", "/api/execution/runtime/cancellations",
                 "/api/execution/runtime/emergency-kills", "/api/execution/runtime/heartbeats",
                 "/api/execution/runtime/results", "/api/execution/runtime/transitions"}
        if parsed.path not in paths:
            super().do_POST()
            return
        try:
            if parsed.query:
                raise ExecutionRequestValidationError("runtime intake forbids query overrides")
            if parsed.path.endswith(("/heartbeats", "/results", "/transitions")):
                self._send_json(409, self._service().reject_execution())
                return
            payload = self._read_json()
            if parsed.path == ADAPTER_ROUTE:
                response = self._service().invoke_tool(payload)
            elif parsed.path in {ROUTE, "/api/execution/runtime/retries"}:
                response = self._service().start_execution(payload, retry=parsed.path.endswith("/retries"))
            else:
                response = self._service().control(payload, kill=parsed.path.endswith("/emergency-kills"))
            self._send_json(202 if response["created"] else 200, response)
        except _ERRORS as exc:
            self._error(exc)


def serve(host="127.0.0.1", port=8791, *, service=None):
    try:
        allowed = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise ExecutionRequestValidationError("Stage 6.5 control API requires loopback bind")
    active = service or ExecutionRuntimeService()
    handler = type("ActiveStage65Handler", (ExecutionSubsystemStage65Handler,), {"service":active})
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
