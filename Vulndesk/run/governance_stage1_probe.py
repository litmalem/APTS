from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cti_services.governance_client import GovernanceClient, GovernanceClientError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe Stage-1 VulnDesk -> aptsGSS CTI source authorization"
    )
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--scope-contract-id", default=None)
    parser.add_argument("--source-id", default="nvd-cve")
    parser.add_argument("--action-name", default="INCREMENTAL_FETCH")
    args = parser.parse_args()

    client = GovernanceClient()
    print("Governance client configuration:")
    print(json.dumps(client.status.as_dict(), indent=2))

    try:
        health = client.health_check()
        print("\nGovernance health:")
        print(json.dumps(health, indent=2, default=str))

        decision = client.evaluate_cti_source_read(
            mission_id=args.mission_id,
            scope_contract_id=args.scope_contract_id,
            source_id=args.source_id,
            action_name=args.action_name,
            context={
                "environment": "LAB",
                "reversible": True,
                "blast_radius": 1,
                "read_only": True,
                "target_actuation": False,
                "probe": "governance_stage1_probe",
            },
            requested_by="CTI-A02",
        )
        print("\nPolicy decision:")
        print(json.dumps(decision, indent=2, default=str))
        return 0 if decision.get("decision") == "ALLOW" else 2
    except GovernanceClientError as exc:
        print(f"\nFAIL-CLOSED: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
