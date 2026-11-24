# Patch Notes — Stage 3.5.2

Stage 3.5.2 adds the canonical `xelig-*` dispatch eligibility/execution-precondition gate. It consumes the immutable Stage-3.5.1 `xdispatch-*` contract plus current canonical Mission artifacts, evaluates 25 static/durable preconditions fail-closed, and persists only a PASSED result.

The patch intentionally does not introduce execution authority. The external APTS Governance service remains authoritative for the later pre-dispatch authorization/revalidation decision. No endpoint resolution, health probe, resource assignment, network dispatch, or target actuation is performed.

Engineering changes include migration level 28, a new durable gate table, canonical gate hashing/verification, REST routes, lineage event, repository reconstruction/integrity coverage, health declarations, and a 19-test focused suite.
