"""Start the canonical Mission source restored by the Stage 6.10 health fix."""
from __future__ import annotations

import argparse
import hashlib
import inspect
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
# The project named by this launcher owns these imports, including when a
# different project's directory was already present in PYTHONPATH.
sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("MISSION_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MISSION_PORT", "8780")))
    parser.add_argument("--cti-feedback-db")
    parser.add_argument("--check-source", action="store_true", help="Verify imports without starting the service or opening its database")
    args = parser.parse_args(argv)
    if args.cti_feedback_db:
        os.environ["APTS_CTI_FEEDBACK_DB"] = str(Path(args.cti_feedback_db).resolve())

    from mission_orchestrator import service as mission_service
    from mission_orchestrator import api_service
    from mission_orchestrator import apts_source_binding

    for module, relative in (
        (mission_service, "mission_orchestrator/service.py"),
        (api_service, "mission_orchestrator/api_service.py"),
        (apts_source_binding, "mission_orchestrator/apts_source_binding.py"),
    ):
        if Path(module.__file__).resolve() != (ROOT / relative).resolve():
            raise RuntimeError("Mission loaded a module from a different project: " + relative)
    if api_service.CanonicalMissionService is not mission_service.CanonicalMissionService:
        raise RuntimeError("Mission API uses a different service implementation")
    if "apts_source_locations" not in inspect.getsource(mission_service.CanonicalMissionService.health):
        raise RuntimeError("Mission health implementation is missing apts_source_locations; apply the complete health fix")
    source = Path(mission_service.__file__).resolve()
    print("Python: " + sys.executable, flush=True)
    print("Mission source: " + str(source), flush=True)
    print("Mission source SHA256: " + hashlib.sha256(source.read_bytes()).hexdigest(), flush=True)
    print("Mission health source binding: PRESENT", flush=True)
    if args.check_source:
        return 0
    api_service.run_server(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
