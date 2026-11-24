# Stage 3.2.3 — Mission Activation: CREATED → PIP_BOUND

Stage 3.2.3 turns the first operational lifecycle edge into an explicit **Mission PIP Activation Contract**. The Mission Orchestrator does not fetch, approve, or execute a PIP artifact. It proves locally that the immutable canonical Mission envelope already binds an exact PIP identity/version and then activates that binding through the existing versioned `BIND_PIP` lifecycle command.

## Activation contract

Schema: `apts-mission-pip-activation-v1`

Mode: `CREATED_TO_PIP_BOUND_FROM_IMMUTABLE_CANONICAL_PIP_BINDING`

Command: `BIND_PIP`

Transition: `CREATED -> PIP_BOUND`

Binding source: `IMMUTABLE_CANONICAL_MISSION_ENVELOPE`

The contract evaluates four local readiness checks:

1. `ACTIVATION_SOURCE_STATE_CREATED`
2. `ACTIVATION_TARGET_TOPOLOGY_PIP_BOUND`
3. `ACTIVATION_PIP_BINDING_COMPLETE`
4. `ACTIVATION_CANONICAL_ENVELOPE_INTEGRITY`

Activation readiness is not Governance authorization and does not imply target execution authority.

## Read API

`GET /api/missions/{mission_id}/activation-contract`

The projection exposes:

- exact `pip_id` and `pip_version` from the immutable canonical envelope;
- envelope id/version/hash and integrity verification status;
- current-state activation readiness;
- explicit no-query/no-authorization/no-execution semantics.

The existing lifecycle discovery endpoint also embeds the same `mission_activation` projection:

`GET /api/missions/{mission_id}/lifecycle-command-contract`

## BIND_PIP execution

`POST /api/missions/{mission_id}/lifecycle/commands`

A successful `BIND_PIP` still passes through the Stage-3.1.6 version-vector/idempotency command journal and the Stage-3.2.2 lifecycle guard matrix. Stage 3.2.3 additionally requires the canonical envelope hash to verify at the activation boundary.

Successful `BIND_PIP` responses include `mission_activation` evidence. The same evidence is embedded in transition metadata, making the activation durable and auditable through the existing state-transition ledger and command journal.

The PIP binding itself is **not mutated** by activation. `BIND_PIP` means “activate the exact PIP binding already committed in the immutable Mission envelope”, not “write a new PIP binding”.

## Authority boundary

Stage 3.2.3 deliberately does not:

- query a PIP service or artifact repository;
- synthesize PIP validity beyond local canonical binding/integrity checks;
- query or replace aptsGSS Governance authority;
- grant authorization;
- dispatch target actions;
- actuate against a target;
- add a database migration;
- introduce a new event type.

Governance remains `EXTERNAL_APTS_GSS`. Repository migration level remains **8**.

## Deferred work

- planning/run activation: Stage 3.2.4;
- evidence/approval dependency satisfaction: Stage 3.2.5;
- cleanup verification/completion gate: Stage 3.2.8.

## Regression baseline

`152 passed`.
