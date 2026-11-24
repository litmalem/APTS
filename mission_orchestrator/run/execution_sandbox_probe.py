"""Exercise native sandbox with fixed synthetic bytes; never authorize or contact a target."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution_subsystem.adapter_policy import DEFAULT_LIMITS
from execution_subsystem.sandbox_runtime import ResourceSandbox


def main():
    raw = b"HTTP/1.1 200 OK\r\nServer: SyntheticAcceptance\r\n\r\n"
    observation = {"connected": True, "peer_ip": "127.0.0.1", "response_bytes": len(raw),
                   "response_sha256": hashlib.sha256(raw).hexdigest(), "response_b64": base64.b64encode(raw).decode(),
                   "byte_limit_reached": False}
    with ResourceSandbox(DEFAULT_LIMITS) as sandbox:
        result = sandbox.parse("HTTP_HEAD", observation, deadline=time.monotonic()+3)
        if result["http_status"] != 200 or not result["server_header_present"]:
            raise RuntimeError("sandbox parser probe failed")
        print(json.dumps({"status": "PASS", "backend": sandbox.backend, "target_io_performed": False, "arbitrary_code_supported": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
