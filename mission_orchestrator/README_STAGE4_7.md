# Stage 4.7 — Capability Registry & Tool Contract

## Status

Implementation candidate for deployment-host acceptance.

Stage 4.7 extends the Stage-4.6 local Pentest workflow skeleton with a **durable canonical
capability registry** and **logical tool contracts**. The registry describes what the Pentest
Subsystem may eventually be able to do, the data contracts for each capability, the permission
and safety requirements, and which logical tool interfaces are required.

This stage remains deliberately **non-executing**. Registering a capability or tool does not
select it, authorize it, bind it to a binary/command/runtime endpoint, invoke it, perform network
I/O, or actuate a target.

The Global Mission Orchestrator remains closed at:

`stage3.9.10-global-mission-orchestrator-acceptance-regression-gate`

The active Pentest control becomes:

`stage4.7-capability-registry-tool-contract`

Default endpoints:

- Global Mission Orchestrator: `http://127.0.0.1:8780`
- Pentest Subsystem: `http://127.0.0.1:8790`

## Roadmap objective

Stage 4.7 implements the roadmap capability set:

```text
reconnaissance
enumeration
vulnerability_analysis
attack_path_analysis
validation
exploitation
impact_analysis
```

Every capability carries:

- input schema;
- output schema;
- permission requirement;
- tool requirement;
- safety class.

Deliverables:

- canonical capability registry;
- capability → logical-tool mapping.

## Canonical contracts

`pentest_subsystem/capability_contract.py` adds:

- control contract: `apts-stage4.7-capability-registry-tool-contract-v1`;
- registry schema: `apts-pentest-capability-registry-v1`;
- capability contract schema: `apts-pentest-capability-contract-v1`;
- logical tool contract schema: `apts-pentest-tool-contract-v1`;
- mapping schema: `apts-pentest-capability-tool-mapping-v1`;
- exact SHA-256 predecessor binding to the Stage-4.6 workflow contract;
- canonical nested SHA-256 integrity for registry, capability, tool, and mapping records.

Registry identity:

```text
registry_id      = pentest-capability-registry
registry_version = 1
```

## Capability registry

The registry contains exactly seven roadmap capabilities:

| Capability | Safety class | Permission requirement | Logical tool requirement |
|---|---|---|---|
| `reconnaissance` | `CONTROLLED_DISCOVERY` | `MISSION_SCOPE_AND_ROE_REQUIRED` | `pentest.tool.passive_discovery` |
| `enumeration` | `CONTROLLED_ACTIVE_DISCOVERY` | `EXPLICIT_GOVERNANCE_ALLOW_AND_SCOPE_REQUIRED` | network discovery + service enumeration |
| `vulnerability_analysis` | `READ_ONLY_ANALYSIS` | `BOUND_TASK_CONTEXT_REQUIRED` | `pentest.tool.vulnerability_analyzer` |
| `attack_path_analysis` | `READ_ONLY_ANALYSIS` | `BOUND_TASK_CONTEXT_REQUIRED` | `pentest.tool.attack_path_analyzer` |
| `validation` | `CONTROLLED_VALIDATION` | `EXPLICIT_GOVERNANCE_ALLOW_REQUIRED` | `pentest.tool.validation_probe` |
| `exploitation` | `HIGH_RISK_CONTROLLED` | `EXPLICIT_GOVERNANCE_ALLOW_AND_STAGE6_EXECUTION_GATEWAY_REQUIRED` | `pentest.tool.exploitation_adapter` |
| `impact_analysis` | `READ_ONLY_ANALYSIS` | `BOUND_RESULT_EVIDENCE_REQUIRED` | `pentest.tool.impact_analyzer` |

The local capability IDs preserve Stage-3 routing compatibility without widening Stage-3
routing identity:

```text
reconnaissance -> routing alias pentest.recon
validation     -> routing alias pentest.validate
```

Aliases are compatibility metadata only. Stage 4.7 does not perform route selection or local
capability selection.

## Logical tool contracts

Eight logical tool contracts are registered:

```text
pentest.tool.passive_discovery
pentest.tool.network_discovery
pentest.tool.service_enumerator
pentest.tool.vulnerability_analyzer
pentest.tool.attack_path_analyzer
pentest.tool.validation_probe
pentest.tool.exploitation_adapter
pentest.tool.impact_analyzer
```

A Stage-4.7 tool contract is an **interface declaration**, not an executable adapter. Every
logical tool contract explicitly records:

```text
adapter_bound              = false
runtime_endpoint_bound     = false
binary_or_command_bound    = false
credential_binding_present = false
invocation_enabled         = false
direct_raw_target_access   = false
shell_access_exposed       = false
target_actuation           = false
```

For target-interacting capabilities, the contract also declares that a later authorized adapter
and sandbox are required. In particular, the exploitation tool remains a high-risk logical
contract and exposes no exploit command, shell, binary binding, credential binding, or raw
network access.

## Durable repository

Stage 4.7 upgrades the isolated Pentest repository from migration **4 → 5**.

Migration:

`pentest_migrations/005_stage4_7_capability_registry_tool_contract.sql`

New tables:

```text
pentest_capability_registry_snapshots
pentest_capability_contracts
pentest_tool_contracts
pentest_capability_tool_mappings
```

Canonical rows are seeded deterministically by the Stage-4.7 repository and verified against
code-defined canonical hashes after initialization/restart. Existing Stage-4.3 task, Stage-4.4
lifecycle, Stage-4.5 event, and Stage-4.6 workflow records are preserved.

The Global Mission Orchestrator repository remains migration **53** and is not modified.

## HTTP API

Stage-4.7 control contract:

```text
GET /api/pentest/capability-contract
GET /api/contracts/pentest-capability-registry
```

Registry and capability inspection:

```text
GET /api/pentest/capability-registry
GET /api/pentest/capabilities
GET /api/pentest/capabilities/{capability_id}
GET /api/pentest/capabilities/{capability_id}/tools
```

Logical tool inspection:

```text
GET /api/pentest/tools
GET /api/pentest/tools/{tool_id}
```

All endpoints are read-only. Unknown capability/tool IDs fail closed with `404`; registry
integrity failures return `409`.

Historical Stage-4.1 through Stage-4.6 endpoints remain available and project the Stage-4.7
active control without mutating their historical canonical definitions.

## Deliberate Stage-4.7 boundary

Enabled:

- canonical capability registry;
- input/output schema metadata;
- permission requirement metadata;
- safety classification;
- logical tool contracts;
- durable capability/tool/mapping persistence;
- capability-to-tool lookup.

Explicitly disabled:

- capability selection;
- specialist-agent reasoning;
- replanning;
- scope/RoE enforcement engine (Stage 4.8);
- execution intake/dispatch;
- raw tool/binary/command binding;
- tool invocation;
- credentials binding;
- external network I/O;
- target actuation;
- authorization minting;
- Stage-4.9 evidence/finding semantics.

`POST /api/execution/dispatches` remains fail-closed with HTTP `409` and:

`STAGE4_7_EXECUTION_INTAKE_NOT_ENABLED`

## Running Stage 4.7

From `D:\mission_orchestrator` in a separate PowerShell window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\START_STAGE4_7_PENTEST.ps1
```

Equivalent direct command:

```powershell
python -m run.pentest_subsystem --host 127.0.0.1 --port 8790
```

Keep the Global Mission Orchestrator running on port `8780`.

## Acceptance

Run:

```powershell
.\STAGE4_7_ACCEPTANCE.ps1
```

The gate verifies live Stage-3.9.10 + Stage-4.7 runtime metadata, canonical predecessor
binding, persisted registry identity, capability contract completeness, logical-tool safety
boundaries, deterministic capability-tool mapping, execution-intake rejection, test inventory,
focused regression, Stage-4 chain regression, critical predecessor regression, and then the full
historical regression as final PASS/FAIL authority.

## Regression status in the implementation environment

Validated before packaging:

- Python compile: **PASS**;
- focused Stage 4.7: **27 passed**;
- Stage 4.1 → 4.7: **149 passed**;
- critical Stage-3 + Stage-4 predecessor chain: **208 passed**;
- canonical inventory: **1724 tests collected**.

A historical regression-fixture stability fix is also included for four Stage-4.5/4.6 tests that
had embedded PIP expiry timestamps ending at `2026-09-30T08:30:00Z`. Those runtime-facing
tests now create fresh time-bounded PIPs while preserving the production stale-PIP rejection
semantics.

The full 1724-test suite was not executed in the packaging environment; the deployment-host
`STAGE4_7_ACCEPTANCE.ps1` remains the final full-regression authority.

## Next stage

**Stage 4.8 — Governance, Scope & Rules-of-Engagement Enforcement**
