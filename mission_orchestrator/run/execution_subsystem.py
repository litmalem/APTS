from __future__ import annotations

import argparse
from pathlib import Path
import sys

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from execution_subsystem.api_service import serve
from execution_subsystem.proposal_source import PentestProposalSource
from execution_subsystem.request_repository import ExecutionRequestRepository
from execution_subsystem.request_service import ExecutionRequestService


def main() -> int:
    parser = argparse.ArgumentParser(description="APTS Stage 6.1 Canonical Execution Request Contract")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--execution-db", default=None)
    parser.add_argument("--pentest-db", default=None)
    args = parser.parse_args()
    service = ExecutionRequestService(ExecutionRequestRepository(args.execution_db), PentestProposalSource(args.pentest_db))
    serve(args.host, args.port, service=service)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
