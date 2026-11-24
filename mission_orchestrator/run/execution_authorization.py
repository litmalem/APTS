from __future__ import annotations

import argparse
from pathlib import Path
import sys

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from execution_subsystem.authorization_api import serve
from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
from execution_subsystem.authorization_repository import ExecutionAuthorizationRepository
from execution_subsystem.authorization_service import ExecutionAuthorizationService
from execution_subsystem.governance_client import ExecutionGovernanceClient


def main() -> int:
    parser = argparse.ArgumentParser(description="APTS Stage 6.2 Authoritative Execution Authorization")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--execution-db", default=None)
    parser.add_argument("--pentest-db", default=None)
    parser.add_argument("--mission-db", default=None)
    parser.add_argument("--governance-url", default=None)
    parser.add_argument("--governance-timeout", type=float, default=None)
    args = parser.parse_args()
    service = ExecutionAuthorizationService(
        ExecutionAuthorizationRepository(args.execution_db), ExecutionAuthorizationProposalSource(args.pentest_db),
        MissionAuthorizationSource(args.mission_db), ExecutionGovernanceClient(args.governance_url, args.governance_timeout))
    serve(args.host, args.port, service=service)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
