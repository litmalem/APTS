# Patch Notes — Stage 4.7

## Added

- `pentest_subsystem/capability_contract.py`
  - Stage-4.7 canonical control contract;
  - seven roadmap capability contracts;
  - explicit input/output schemas, permission requirements, tool requirements, and safety classes;
  - eight logical tool contracts;
  - eight capability-to-tool mappings;
  - exact Stage-4.6 predecessor SHA binding;
  - canonical nested SHA-256 integrity;
  - explicit Stage-4.8 and Stage-6 authority boundaries.
- `pentest_subsystem/capability_repository.py`
  - Pentest repository migration level 5;
  - deterministic canonical registry seed;
  - durable registry/capability/tool/mapping stores;
  - restart reconstruction;
  - tamper/integrity detection;
  - exact capability/tool lookup.
- `pentest_subsystem/capability_service.py`
  - Stage-4.7 health and contract projection;
  - registry/capability/tool/mapping query services;
  - explicit non-selection/non-execution response semantics.
- `pentest_migrations/005_stage4_7_capability_registry_tool_contract.sql`
- `tests/test_stage4_7_capability_registry_tool_contract.py`
  - 27 focused tests.
- `START_STAGE4_7_PENTEST.ps1`
- `STAGE4_7_ACCEPTANCE.ps1`
- Stage-4.7 install/readme/evidence/manifest/hash files.

## Updated

- `pentest_subsystem/api_service.py`
  - historical Stage-4.1 through Stage-4.6 handlers retained;
  - active Stage-4.7 handler added;
  - capability registry, capability, mapping, and tool query endpoints added;
  - execution dispatch remains fail-closed.
- `pentest_subsystem/__init__.py`
  - exports Stage-4.7 capability/tool registry symbols.
- `run/pentest_subsystem.py`
  - active runtime description moved to Stage 4.7.
- `tests/test_stage4_5_pentest_event_runtime_contract.py`
- `tests/test_stage4_6_pentest_workflow_orchestrator_skeleton.py`
  - runtime-facing PIP fixtures now use a fresh UTC timestamp so the historical regression
    suite does not time-expire after the original fixed `2026-09-30T08:30:00Z` PIP expiry;
  - production stale-PIP validation logic is unchanged.

## Persistence change

```text
Mission repository migration: 53 (unchanged)
Pentest repository migration:  4 -> 5
```

Stage 4.7 adds:

```text
pentest_capability_registry_snapshots
pentest_capability_contracts
pentest_tool_contracts
pentest_capability_tool_mappings
```

## Capability set

```text
reconnaissance
enumeration
vulnerability_analysis
attack_path_analysis
validation
exploitation
impact_analysis
```

Each capability has a canonical input schema, output schema, permission requirement, logical
tool requirement, and safety class.

## Tool boundary

Tool entries are logical contracts only. Stage 4.7 does not bind:

- executables;
- commands;
- runtime endpoints;
- credentials;
- shells;
- raw target connections.

Capability registration and capability-to-tool mapping are explicitly **not** permission,
selection, authorization, invocation, or execution.

## Safety / authority boundary

This patch does **not** add capability selection, specialist-agent autonomy, scope/RoE
enforcement, scanning execution, enumeration execution, validation execution, exploitation,
network I/O, target actuation, or authorization minting.

Stage 4.8 will add machine-enforceable governance/scope/RoE checks. Controlled tool execution
remains Stage 6.
