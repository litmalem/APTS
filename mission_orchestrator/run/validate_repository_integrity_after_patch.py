from mission_orchestrator.service import CanonicalMissionService

MISSION_ID = "mission-gmo-e672e544-c49e-4ece-a08c-f3a9f8c972d7"

svc = CanonicalMissionService()

try:
    result = svc.get_mission_repository(MISSION_ID)
    print("REPOSITORY_INTEGRITY: PASS")
    print("top_level_keys:", sorted(result.keys()))
except Exception as exc:
    print("REPOSITORY_INTEGRITY: FAIL")
    print("exception_type:", type(exc).__name__)
    print("message:", str(exc))
