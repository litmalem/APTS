# APTS Human Layer & Human Interaction — Implementation Note

**Release:** 2026-10-07  
**Baseline:** `aptsGSS(20261007-042143).zip` + `APTS_Control_Center(10).zip`  
**Database migration:** **none**

## 1. Audit conclusion

The baseline already contained most human-governance capabilities: authenticated human approvals,
Scope & RoE management, governance audit, emergency stop, and Mission lifecycle/observability.
However, there were no first-class runtime modules explicitly named **Human Layer** and
**Human Interaction**, and there was no single operator workspace that connected human mission
intent, governance approval, oversight, and emergency control while preserving subsystem authority.

This release makes the two architectural concepts explicit without creating duplicate sources of truth.

## 2. New first-class modules

### `HUMAN-LAYER`

Implemented in `app/human_layer.py` as an **External Human Authority / Oversight Layer**.
It is deliberately `agent=false` and `target_execution_authority=false`.

Responsibilities:

1. Define Goals
2. Define Scope & Rules of Engagement
3. Approve High-Risk Actions
4. Review & Oversight
5. Emergency Control

Authority remains separated:

- Human Layer: goal intent, scope intent, approval, review, emergency command
- Global Mission Orchestrator: mission identity/state/lifecycle/lineage
- aptsGSS: scope contract, policy, authorization, approval binding, emergency state, audit
- Controlled Execution Gateway: deterministic enforcement and controlled side effect

### `HUMAN-INTERACTION`

Implemented in `app/human_interaction.py` as an **Authenticated Human-System Interface / Workflow**.
It is also non-agentic and has no target execution authority.

Workflows:

- Mission authoring
- Scope & RoE management
- Human approval
- Mission review & oversight
- Emergency control

Security invariants include server-owned identity, short-lived server-side session, CSRF for writes,
no browser credential persistence, no arbitrary proxy route, and no direct tool/target execution.

## 3. New API surfaces

Read-only governance contracts:

- `GET /api/governance/human-layer`
- `GET /api/governance/human-interaction`

Human UI BFF routes on `aptsGSS Web`:

- `GET /api/human/missions`
- `GET /api/human/missions/{mission_id}`
- `GET /api/human/mission-attention`
- `POST /api/human/missions`

The BFF builds loopback Mission paths itself. It does not accept arbitrary upstream URLs.
Mission writes require the `mission_author` capability and the BFF injects the authenticated
server principal as `created_by` and `source_system=HUMAN_LAYER`.

Creating a mission is **not authorization**. It creates mission intent only. Scope/RoE, policy,
approval, revalidation, emergency state, and controlled execution remain separate authorities.

## 4. UI

`aptsGSS Web` now has two dedicated pages.

### Human Layer

- Displays the authority/oversight contract and invariants
- Defines canonical mission objective, success criteria, budgets, and required subsystems
- Lists missions whose source is `HUMAN_LAYER`
- Opens mission oversight detail
- Provides bounded navigation to Scope & RoE, Human Approvals, and Emergency Control

### Human Interaction

- Unified operator attention workspace
- Pending GSS approval queue
- Mission Orchestrator attention queue
- Risk/severity indicators
- Mission oversight detail with canonical objective/constraints and governance visibility
- Shortcuts to Scope & RoE, audit/trace, and emergency control

## 5. Roles

- `VIEWER` / `AUDITOR`: read only
- `OPERATOR`: read, **mission authoring**, activate emergency, retry
- `SECURITY_APPROVER`: read, approval decisions when the request requires the role
- `GOVERNANCE_ADMIN`: read, **mission authoring**, scope, policy, revoke, activate/release emergency, retry

`GOVERNANCE_ADMIN` does not automatically receive `SECURITY_APPROVER` authority.

## 6. Control Center integration

The `gss_web` launcher now passes both:

- `--api-port <GSS port>`
- `--mission-port <Mission port>`

Default topology:

```text
Browser
  -> aptsGSS Web :8802
      -> aptsGSS Governance API :8770
      -> Global Mission Orchestrator :8780
```

## 7. Changed source files

### aptsGSS

- `app/human_layer.py` (new)
- `app/human_interaction.py` (new)
- `app/console_auth.py`
- `app/architecture.py`
- `app/interface_catalog.py`
- `app/main.py`
- `gss_web/server.py`
- `gss_web/static/app.js`
- `gss_web/static/style.css`
- `README.md`
- `README_GSS_WEB.md`
- `tests/test_human_layer_modules.py` (new)
- `tests/test_web_console.py`
- `GSS_WEB_MANIFEST.json`

### APTS Control Center

- `server.py`
- `web/app.js`
- `README_GSS_WEB.md`

## 8. Validation performed in this workspace

- Python compilation of modified GSS and Control Center modules: **PASS**
- JavaScript syntax check (`node --check`) for modified UIs: **PASS**
- Targeted GSS Human Layer / BFF / interface tests: **35 passed**
- Control Center synthetic tests: **17 passed**

The GSS targeted suite used a minimal import-only PyMySQL stub because this isolated execution
environment does not contain the PyMySQL package and has no network access for package installation.
No real database, live APTS service, or penetration-testing target was contacted.

## 9. Windows startup

Start these processes from Control Center:

1. `aptsGS` / aptsGSS — port 8770
2. `Mission` — port 8780
3. `aptsGSS Web` — port 8802

Then choose **Buka Web** for aptsGSS Web and use the **Human Layer** / **Human Interaction** menus.

Manual alternative:

```powershell
cd D:\aptsGS
.\.venv\Scripts\python.exe .\run.py

# another terminal
cd D:\mission_orchestrator
python .\run\run_stage6_10_mission.py --host 127.0.0.1 --port 8780

# another terminal
cd D:\aptsGS
.\.venv\Scripts\python.exe .\run_web.py --port 8802 --api-port 8770 --mission-port 8780
```

Preserve your existing `.env`, principal registry, database, and local paths when applying this release.
