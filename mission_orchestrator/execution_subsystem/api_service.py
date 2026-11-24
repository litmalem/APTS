from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from sqlite3 import Error as SQLiteError
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .execution_contract import (
    MAX_INTAKE_BYTES, ExecutionRequestConflict, ExecutionRequestIntegrityError,
    ExecutionRequestValidationError, ExecutionSourceNotFound, ExecutionSourceRejected,
    ExecutionSourceUnavailable, canonical_json,
)
from .request_repository import ExecutionRepositoryError
from .request_service import ExecutionRequestService


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ExecutionRequestValidationError("duplicate JSON keys are forbidden")
        obj[key] = value
    return obj


def _reject_constant(value: str) -> None:
    raise ExecutionRequestValidationError(f"non-finite JSON value is forbidden: {value}")


class ExecutionSubsystemStage61Handler(BaseHTTPRequestHandler):
    server_version = "APTSExecutionSubsystem/6.1"
    service: ExecutionRequestService | None = None

    def _service(self) -> ExecutionRequestService:
        if self.service is None:
            self.service = ExecutionRequestService()
        return self.service

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        raw = canonical_json(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> Any:
        if self.headers.get("Transfer-Encoding"):
            raise ExecutionRequestValidationError("Transfer-Encoding is unsupported")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1:
            raise ExecutionRequestValidationError("one Content-Length header is required")
        try:
            length = int(lengths[0])
        except ValueError as exc:
            raise ExecutionRequestValidationError("Content-Length must be an integer") from exc
        if not 1 <= length <= MAX_INTAKE_BYTES:
            raise ExecutionRequestValidationError(f"JSON intake must be 1-{MAX_INTAKE_BYTES} bytes")
        if self.headers.get_content_type() != "application/json":
            raise ExecutionRequestValidationError("Content-Type must be application/json")
        self.connection.settimeout(10)
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ExecutionRequestValidationError("incomplete JSON body")
            return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
        except (ValueError, UnicodeError, RecursionError, TimeoutError) as exc:
            raise ExecutionRequestValidationError("invalid JSON body") from exc

    def _error(self, exc: Exception) -> None:
        if isinstance(exc, ExecutionRequestValidationError):
            code, status = 400, "invalid"
        elif isinstance(exc, ExecutionSourceNotFound):
            code, status = 404, "not_found"
        elif isinstance(exc, (ExecutionRequestIntegrityError, ExecutionRequestConflict, ExecutionSourceRejected)):
            code, status = 409, "rejected"
        else:
            code, status = 503, "unavailable"
        self._send_json(code, {"status": status, "error": str(exc)})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            service = self._service()
            if path == "/health":
                health = service.health()
                self._send_json(200 if health["status"] == "ok" else 503, health)
                return
            if path in {"/api/execution/execution-request-contract", "/api/contracts/canonical-execution-request"}:
                self._send_json(200, service.get_contract())
                return
            if path == "/api/execution/requests":
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) - {"mission_id", "task_id", "pentest_id", "limit"} or any(len(x) != 1 for x in query.values()):
                    raise ExecutionRequestValidationError("unsupported or duplicate request-list filters")
                filters = {key: value[0] for key, value in query.items()}
                try:
                    filters["limit"] = int(filters.get("limit", "100"))
                except ValueError as exc:
                    raise ExecutionRequestValidationError("limit must be an integer") from exc
                items = service.repository.list_requests(**filters)
                self._send_json(200, {"status": "ok", "count": len(items), "requests": items})
                return
            prefix = "/api/execution/requests/"
            if path.startswith(prefix):
                execution_id = unquote(path[len(prefix):])
                item = service.repository.get(execution_id)
                self._send_json(200 if item else 404, {"status": "ok", **item} if item else {"status": "not_found"})
                return
            self._send_json(404, {"status": "not_found"})
        except (ExecutionRequestValidationError, ExecutionRequestIntegrityError, ExecutionRequestConflict,
                ExecutionSourceUnavailable, ExecutionSourceNotFound, ExecutionSourceRejected,
                ExecutionRepositoryError, SQLiteError, ValueError) as exc:
            self._error(exc)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path in {"/api/execution/dispatches", "/api/execution/authorizations",
                        "/api/execution/results", "/api/execution/tool-invocations"}:
                self._send_json(409, self._service().reject_execution())
                return
            if path == "/api/execution/requests":
                result = self._service().create_request(self._read_json())
                self._send_json(201 if result["created"] else 200, result)
                return
            self._send_json(404, {"status": "not_found"})
        except (ExecutionRequestValidationError, ExecutionRequestIntegrityError, ExecutionRequestConflict,
                ExecutionSourceUnavailable, ExecutionSourceNotFound, ExecutionSourceRejected,
                ExecutionRepositoryError, SQLiteError) as exc:
            self._error(exc)


def serve(host: str = "127.0.0.1", port: int = 8791, *, service: ExecutionRequestService | None = None) -> None:
    active = service or ExecutionRequestService()
    handler = type("ActiveExecutionStage61Handler", (ExecutionSubsystemStage61Handler,), {"service": active})
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
