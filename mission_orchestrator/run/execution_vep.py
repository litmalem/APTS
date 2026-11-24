from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution_subsystem.vep_api import serve
from execution_subsystem.vep_repository import ExecutionVEPRepository
from execution_subsystem.vep_service import ExecutionVEPService
from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
from execution_subsystem.credential_leases import CredentialLeaseStore
from execution_subsystem.governance_client import ExecutionGovernanceClient


def main():
    parser = argparse.ArgumentParser(description="APTS Stage 6.7 VEP Construction & Integrity")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--execution-db")
    parser.add_argument("--pentest-db")
    parser.add_argument("--mission-db")
    parser.add_argument("--governance-url")
    parser.add_argument("--governance-timeout", type=float)
    parser.add_argument("--credential-leases-file")
    args = parser.parse_args()
    service = ExecutionVEPService(ExecutionVEPRepository(args.execution_db),
        ExecutionAuthorizationProposalSource(args.pentest_db), MissionAuthorizationSource(args.mission_db),
        ExecutionGovernanceClient(args.governance_url, args.governance_timeout),
        credential_store=CredentialLeaseStore(args.credential_leases_file))
    serve(args.host, args.port, service=service)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
