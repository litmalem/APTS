# Patch Notes — Stage 3.1.3 Mission Scope, RoE & Constraint Contract

## Added

- canonical `apts-mission-scope-roe-constraint-v1` model;
- stable `mission_scope_contract_id` per global mission;
- immutable per-version `snapshot_id` and SHA-256 integrity hash;
- optimistic `expected_contract_version` revision gate;
- request-level idempotency for safe retries;
- append-only contract history;
- semantic validation for targets, CIDRs, domains, URLs, services, time windows, action classes, risk ceilings, and hard RoE flags;
- SQLite + MariaDB/MySQL persistence;
- HTTP create/revise/read/history endpoints;
- focused Stage-3.1.3 regression and PowerShell acceptance.

## Preserved invariants

- Stage-3.1.1 canonical mission identity and envelope remain immutable.
- Stage-3.1.2 global mission state remains a separate projection.
- A contract revision does not implicitly transition mission state.
- `APTS-MO01` does not evaluate Governance policy.
- `aptsGSS` remains authoritative for authorization, approval, revocation, and emergency stop.
- no task dispatch;
- no target actuation.

## Compatibility observation

The uploaded Governance service already defines `GOV-D02 — Rules of Engagement Contract` and exposes a Governance-owned versioned ScopeContract. Stage 3.1.3 deliberately does not replace that artifact. The new GMO contract is the canonical **mission definition** that later Governance Binding can correlate with the Governance contract/decision plane.
