from __future__ import annotations

from http.server import ThreadingHTTPServer
from sqlite3 import Error as SQLiteError
from urllib.parse import parse_qs, unquote, urlparse

from .api_service import ExecutionSubsystemStage61Handler
from .authorization_contract import ExecutionGovernanceProtocolError, ExecutionGovernanceUnavailable
from .authorization_service import ExecutionAuthorizationService
from .execution_contract import (
    ExecutionRequestConflict, ExecutionRequestIntegrityError, ExecutionRequestValidationError,
    ExecutionSourceNotFound, ExecutionSourceRejected, ExecutionSourceUnavailable,
)
from .request_repository import ExecutionRepositoryError

_ERRORS = (ExecutionRequestValidationError, ExecutionRequestIntegrityError, ExecutionRequestConflict,
           ExecutionSourceNotFound, ExecutionSourceRejected, ExecutionSourceUnavailable,
           ExecutionGovernanceProtocolError, ExecutionGovernanceUnavailable, ExecutionRepositoryError, SQLiteError)


class ExecutionSubsystemStage62Handler(ExecutionSubsystemStage61Handler):
    server_version = "APTSExecutionSubsystem/6.2"
    service: ExecutionAuthorizationService | None = None

    def _service(self) -> ExecutionAuthorizationService:
        if self.service is None:
            self.service = ExecutionAuthorizationService()
        return self.service

    def _error(self, exc):
        if isinstance(exc, (ExecutionGovernanceProtocolError, ExecutionGovernanceUnavailable)):
            self._send_json(503, {"status": "unavailable", "error_code": "AUTHORITATIVE_GOVERNANCE_REVALIDATION_FAILED",
                                  "error": str(exc), "execution_authorized": False, "authorization_current": False})
        else:
            if isinstance(exc, ExecutionRequestValidationError):
                code, status = 400, "invalid"
            elif isinstance(exc, ExecutionSourceNotFound):
                code, status = 404, "not_found"
            elif isinstance(exc, (ExecutionRequestIntegrityError, ExecutionRequestConflict, ExecutionSourceRejected)):
                code, status = 409, "rejected"
            else:
                code, status = 503, "unavailable"
            self._send_json(code, {"status": status, "error": str(exc),
                                  "execution_authorized": False, "authorization_current": False})

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path in {"/api/execution/execution-authorization-contract", "/api/contracts/authoritative-execution-authorization"}:
                self._send_json(200, self._service().get_authorization_contract())
                return
            if parsed.path.startswith("/api/execution/authorizations/"):
                if parsed.query:
                    raise ExecutionRequestValidationError("authorization reads do not accept query overrides")
                ident = unquote(parsed.path[len("/api/execution/authorizations/"):])
                item = self._service().repository.get_authorization(ident)
                self._send_json(200 if item else 404, self._service().audit_response(item) if item else {"status": "not_found"})
                return
            if parsed.path == "/api/execution/authorizations":
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) - {"execution_id", "limit"} or "execution_id" not in query or any(len(x) != 1 for x in query.values()):
                    raise ExecutionRequestValidationError("authorization list requires one execution_id and optional limit")
                try:
                    limit = int(query.get("limit", ["100"])[0])
                except ValueError as exc:
                    raise ExecutionRequestValidationError("invalid limit") from exc
                items = self._service().repository.list_authorizations(query["execution_id"][0], limit)
                self._send_json(200, {"status": "ok", "count": len(items), "authorizations": items,
                                     "historical_records": True, "authorization_current": False,
                                     "execution_authorized": False, "fresh_revalidation_required": True})
                return
            super().do_GET()
        except _ERRORS as exc:
            self._error(exc)

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/execution/authorizations":
            super().do_POST()
            return
        try:
            if parsed.query:
                raise ExecutionRequestValidationError("authorization intake does not accept query overrides")
            result = self._service().authorize_execution(self._read_json())
            self._send_json(201 if result["created"] else 200, result)
        except _ERRORS as exc:
            self._error(exc)


def serve(host="127.0.0.1", port=8791, *, service=None):
    active = service or ExecutionAuthorizationService()
    handler = type("ActiveExecutionStage62Handler", (ExecutionSubsystemStage62Handler,), {"service": active})
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
