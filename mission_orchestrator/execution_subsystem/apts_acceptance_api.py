from http.server import ThreadingHTTPServer
import ipaddress
from urllib.parse import urlparse

from .apts_acceptance_service import APTSAcceptanceService
from .cti_feedback_api import ExecutionSubsystemStage69Handler
from .execution_contract import ExecutionRequestValidationError

CONTRACT_ROUTES = {"/api/execution/full-apts-acceptance-contract", "/api/contracts/full-apts-acceptance"}


class ExecutionSubsystemStage610Handler(ExecutionSubsystemStage69Handler):
    server_version = "APTSExecutionSubsystem/6.10"
    service: APTSAcceptanceService | None = None

    def _service(self):
        if self.service is None:
            self.service = APTSAcceptanceService()
        return self.service

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in CONTRACT_ROUTES:
            try:
                if parsed.query:
                    raise ExecutionRequestValidationError("APTS acceptance contract forbids query overrides")
                self._send_json(200, self._service().get_apts_acceptance_contract())
            except ExecutionRequestValidationError as exc:
                self._error(exc)
            return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path in CONTRACT_ROUTES or path.startswith("/api/execution/full-apts-acceptance"):
            self._send_json(409, self._service().reject_execution())
            return
        super().do_POST()


def serve(host="127.0.0.1", port=8791, *, service=None):
    try:
        allowed = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise ExecutionRequestValidationError("Stage 6.10 requires loopback bind")
    active = service or APTSAcceptanceService()
    handler = type("ActiveStage610Handler", (ExecutionSubsystemStage610Handler,), {"service": active})
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
