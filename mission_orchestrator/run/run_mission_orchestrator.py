from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mission_orchestrator.api_service import run_server


def main():
    parser = argparse.ArgumentParser(description="APTS Global Mission Orchestrator")
    parser.add_argument("--host", default=os.getenv("MISSION_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MISSION_PORT", "8780")))
    parser.add_argument("--cti-feedback-db", help="Trusted Stage 6.9 CTI feedback knowledge DB; read-only consumer")
    args = parser.parse_args()
    if args.cti_feedback_db:
        os.environ["APTS_CTI_FEEDBACK_DB"] = str(Path(args.cti_feedback_db).resolve())
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
