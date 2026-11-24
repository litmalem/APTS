# Patch notes — Stage 13 Enumeration to Stage 6

## Changes

- Adds a versioned Stage 6.1 intake for exact persisted Stage-5.3 proposals.
- Adds read-only source verification for the completed Enumeration run, its immutable output/evidence bundle, proposal lineage, Stage-4.8 eligibility, task/orchestration binding, current scope/RoE, and bounded resource budget.
- Enables only the exact `enumeration / TARGET_RECON / TCP_BANNER_READ` adapter tuple. Semantic enumeration labels remain rejected.
- Carries Stage-5.3 proposal lineage through GSS, gateway admission, runtime, and Stage 6.6 evidence without coercing it into a Recon Action Request identity.
- Adds a read-only Stage-6.6 Enumeration result route and a read-only Enumeration iteration projection. The parent run is not modified.
- Allows the Stage-5.3 repository reader to open later append-only schema heads when required Stage-5.2/5.3 tables exist; it does not downgrade the metadata head.
- Adds a loopback E2E acceptance and focused PowerShell runner.

## Verification performed here

- `py_compile` succeeded for all modified Python modules and the new E2E test.
- Intake normalization and registry selection smoke check resolved a URL target to `network.tcp-banner.v1`.
- Static Stage-6 JSON schemas were regenerated from the canonical schema functions.
- Pytest could not run in this environment because the runtime does not include the `pytest` module. Run `STAGE13_ACCEPTANCE.ps1` on Windows before treating Stage 13 acceptance as complete.
