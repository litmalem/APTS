from __future__ import annotations
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution_subsystem.apts_acceptance_api import serve
from execution_subsystem.apts_acceptance_service import APTSAcceptanceService
from execution_subsystem.authorization_source import ExecutionAuthorizationProposalSource, MissionAuthorizationSource
from execution_subsystem.credential_leases import CredentialLeaseStore
from execution_subsystem.cti_feedback_repository import ExecutionCTIFeedbackRepository
from execution_subsystem.cti_knowledge_repository import CTIKnowledgeRepository
from execution_subsystem.governance_client import ExecutionGovernanceClient


def main():
    parser = argparse.ArgumentParser(description="APTS Stage 6.10 runtime and external acceptance declaration")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    for name in ("execution-db", "pentest-db", "mission-db", "cti-feedback-db", "governance-url", "credential-leases-file"):
        parser.add_argument("--" + name)
    parser.add_argument("--governance-timeout", type=float)
    args = parser.parse_args()
    service = APTSAcceptanceService(ExecutionCTIFeedbackRepository(args.execution_db),
        ExecutionAuthorizationProposalSource(args.pentest_db), MissionAuthorizationSource(args.mission_db),
        ExecutionGovernanceClient(args.governance_url, args.governance_timeout),
        credential_store=CredentialLeaseStore(args.credential_leases_file),
        knowledge_repository=CTIKnowledgeRepository(args.cti_feedback_db))
    serve(args.host, args.port, service=service)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
