# Patch Notes — Stage 3.1.2 Canonical Mission State Model

## Architectural decision

Stage 3.1.2 keeps the Stage-3.1.1 immutable identity/envelope root intact and introduces mission lifecycle state as a **separate mutable projection**. The Global Mission Orchestrator (`APTS-MO01`) is authoritative for the global mission state, while subsystem-local states (for example CTI-A01's local mission execution state) remain local projections and must not overwrite the global state directly.

## Invariants added

1. Every registered global mission has exactly one canonical current-state row.
2. Initial state is `CREATED`, `state_version=1`.
3. State changes are allowed only through the canonical transition graph.
4. Every transition requires optimistic `expected_state_version` validation.
5. Every successful state transition increments the version exactly once.
6. Every successful transition creates an append-only transition record in the same database transaction.
7. `COMPLETED`, `ABORTED`, `FAILED`, and `EXPIRED` are terminal and immutable.
8. `COMPLETED` cannot bypass `CLEANING_UP`.
9. Existing Stage-3.1.1 missions are backfilled without mutating their immutable envelope.
10. No Stage-3.1.2 endpoint dispatches a task, evaluates Governance policy, or actuates a target.

## Compatibility observations from uploaded Stage-2 services

The current VulnDesk CTI subsystem already maintains its own local `state_version` and `plan_version` and exposes local states such as `RUNNING`, `COMPLETED`, `QUALITY_REVIEW`, `FAILED`, and `CANCELLED`. Stage 3.1.2 does not replace those local semantics. It creates a higher-level global lifecycle that later stages can project from subsystem events.

The uploaded aptsGSS Governance schema remains the authoritative scope/policy/approval plane. Stage 3.1.2 therefore does not reinterpret a mission-state transition as a Governance `ALLOW`, approval, or authorization result.
