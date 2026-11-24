# PATCH NOTES — Stage 3.4.2 Hotfix 1

Cause: Stage-3.4.1 canonical subsystem registry service methods existed, but their documented HTTP GET routes were not registered in `MissionOrchestratorHandler.do_GET`. The Stage-3.4.2 acceptance probe therefore received `ROUTE_NOT_FOUND` at `/api/subsystem-registry`.

Changes:
- register all six documented Stage-3.4.1 canonical registry read-model routes;
- preserve all Stage-3.4.2 authority/execution boundaries;
- add real HTTP-server regression coverage for the routes;
- correct the stale server startup banner to Stage 3.4.2.

No schema or database migration changes. Migration level remains 19.
