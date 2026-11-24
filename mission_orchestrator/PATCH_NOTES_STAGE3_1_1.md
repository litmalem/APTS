# Patch Notes — Stage 3.1.1 Canonical Mission Identity & Envelope

## Architectural decision

`mission_orchestrator/` is a new service. VulnDesk remains the **Actionable–Adaptive CTI
Subsystem** and CTI-A01 remains its local orchestrator. aptsGSS remains the authoritative
**Governance & Safety Plane**. Stage 3.1.1 therefore does not patch either service's internal
domain reasoning.

## Invariants established

1. One Global Mission Orchestrator is the authority that assigns the canonical `mission_id`.
2. A client-supplied/pre-existing mission identifier is only an external alias (`client_mission_ref`).
3. The canonical envelope is immutable once registered.
4. The envelope is versioned from `envelope_version=1`.
5. Mission creation is idempotent per `(source_system, idempotency_key)`.
6. Same key + changed canonical request is rejected with conflict; it is never silently aliased.
7. Every envelope has a named canonicalization algorithm, hash domain and SHA-256 digest.
8. Scope/RoE/PIP/policy are references at this stage; a reference does not imply authorization.
9. Stage 3.1.1 has no dispatch path and no target actuation.
10. Future mutable mission state must live outside the immutable identity/envelope records.

## Compatibility with the Stage-2 deployment

The binding model accepts the existing aptsGSS-style `scope_contract_id` + `scope_version` and
projects them into a deterministic `scope_snapshot_id` of `<scope_contract_id>@v<scope_version>`.
Downstream dispatch is intentionally deferred; when it is implemented, VulnDesk should receive the
Global Mission Orchestrator's `mission_id` instead of inventing another global identity.
