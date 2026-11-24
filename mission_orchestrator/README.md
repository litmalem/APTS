# APTS Governance & Safety Service

**Web console available:** see [README_GSS_WEB.md](README_GSS_WEB.md) for the separate
`run_web.py` application, authenticated administration, and updated acceptance.


Independent, deterministic, **non-agent** Governance & Safety Plane for the Autonomous Penetration Testing System (APTS).

This service is intentionally separated from the CTI and Pentest reasoning agents. It owns **scope, Rules of Engagement (RoE), policy, authorization, pre-action risk classification, human approval records, emergency stop, audit, and authoritative PolicyDecision artifacts**. It does not perform CTI reasoning, penetration testing, exploit selection, or target execution.

## 1. Architecture

Implemented components:

- **GOV-S01 — Scope & Rules of Engagement Service**
- **GOV-S02 — Policy & Authorization Service**
- **GOV-S03 — Risk Assessment Service**
- **GOV-S04 — Deterministic Action Gate**
- **GOV-S05 — Compliance & Regulatory Service** (persistence/obligation baseline)
- **GOV-S06 — Kill Switch & Emergency Stop Service**
- **GOV-D01 — Policy Decision**
- **GOV-D02 — Rules of Engagement Contract**
- **GOV-D03 — Approval Record**

Core precedence:

```text
Emergency Stop
      >
Hard Deny
      >
Scope / RoE
      >
Action Constraint
      >
Risk Limit
      >
Human Approval
      >
ALLOW
```

The default is **DENY**. A high utility/recommendation score from any agent cannot bypass a hard governance constraint.

## 2. Runtime requirements

- Python 3.11+ recommended
- MariaDB 10.5+ recommended
- VulnDesk CTI API is optional for event delivery; the Governance API works even if VulnDesk is temporarily offline.

## 3. MariaDB setup

Run the SQL files in order:

```bash
mysql -u root -p < sql/01_governance_schema.sql
mysql -u root -p < sql/02_seed_default_policies.sql
```

Optional lab-only sample data:

```bash
mysql -u root -p < sql/03_example_lab_scope.sql
```

The schema creates a **separate database**:

```text
apts_governance
```

This is deliberate. Governance has independent database ownership and communicates with VulnDesk through an API/event contract rather than by directly modifying CTI tables.

## 4. VS Code / Python setup

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python run.py
```

Or run:

```text
run_windows.bat
```

Linux/macOS:

```bash
./run_linux.sh
```

Then open:

```text
http://127.0.0.1:8770/docs
```

FastAPI exposes Swagger/OpenAPI automatically.

## 5. Environment configuration

Edit `.env`:

```dotenv
GOV_DB_HOST=127.0.0.1
GOV_DB_PORT=3306
GOV_DB_NAME=apts_governance
GOV_DB_USER=root
GOV_DB_PASSWORD=your_password

GOV_HOST=127.0.0.1
GOV_PORT=8770

CTI_EVENT_API_URL=http://127.0.0.1:8765/api/cti/events/publish
```

Do not commit `.env`.

## 6. Main APIs

### Health and architecture

```text
GET /health
GET /api/governance/architecture
```

### Scope / Rules of Engagement

```text
POST /api/governance/scope-contracts
GET  /api/governance/scope-contracts/{scope_contract_id}
```

### Authorization

```text
POST /api/governance/authorization/evaluate
GET  /api/governance/decisions/{decision_id}
POST /api/governance/decisions/{decision_id}/revoke
```

### Human approval contract

The browser UI runs as a separate process (`run_web.py`) and calls these endpoints through its authenticated backend. See README_GSS_WEB.md.

The decision endpoint requires a bearer credential from the server-owned human
principal registry configured by `GOV_APPROVAL_PRINCIPALS_FILE`. Identities and
roles in the JSON body are optional compatibility assertions and cannot grant
authority. See `README_GSS_APPROVAL_FIX.md` for provisioning and the new source
acceptance gate. Install test dependencies with `requirements-dev.txt`.

```text
GET  /api/governance/approvals/{approval_request_id}
POST /api/governance/approvals/{approval_request_id}/decision
```

### Emergency stop

```text
GET  /api/governance/emergency-stop
POST /api/governance/emergency-stop/activate
POST /api/governance/emergency-stop/release
```

### Event outbox

```text
POST /api/governance/events/retry
```

The service persists outbound events in `gov_event_outbox` before attempting delivery to VulnDesk. CTI downtime therefore does not erase Governance decisions.

## 7. Example: create a CTI scope

```json
{
  "mission_id": "mission-cti-001",
  "name": "CTI Research Mission",
  "created_by": "operator-01",
  "approved_by": "operator-01",
  "targets": [],
  "sources": [
    {
      "source_id": "nvd-cve",
      "source_type": "CTI",
      "allowed": true,
      "constraints": {"read_only": true}
    },
    {
      "source_id": "mitre-attack",
      "source_type": "CTI",
      "allowed": true,
      "constraints": {"read_only": true}
    }
  ],
  "action_constraints": [
    {
      "action_class": "CTI_SOURCE_READ",
      "action_name": "*",
      "effect": "ALLOW",
      "max_risk_level": "LOW",
      "requires_approval": false,
      "constraints": {
        "read_only": true,
        "target_actuation": false
      }
    }
  ]
}
```

## 8. Example: CTI-A02 asks for authorization

```json
{
  "mission_id": "mission-cti-001",
  "scope_contract_id": "scope-...",
  "subject_component": "CTI-A02",
  "action_class": "CTI_SOURCE_READ",
  "action_name": "INCREMENTAL_FETCH",
  "resource_type": "CTI_SOURCE",
  "resource_value": "nvd-cve",
  "context": {
    "environment": "LAB"
  },
  "evidence_refs": []
}
```

Possible result:

```json
{
  "decision": "ALLOW",
  "reason_codes": [
    "ACTION_CONSTRAINT_ALLOW",
    "SOURCE_ALLOWLIST_MATCH"
  ],
  "constraints": {
    "read_only": true,
    "target_actuation": false
  }
}
```

If there is no active scope, no allowlisted source, no matching action constraint, or an emergency stop is active, the result is **DENY**.

## 9. Example: action requiring human approval

A scope action constraint may use:

```json
{
  "action_class": "VULNERABILITY_VALIDATION",
  "action_name": "*",
  "effect": "REVIEW",
  "max_risk_level": "HIGH",
  "requires_approval": true,
  "constraints": {
    "required_approver_role": "SECURITY_APPROVER"
  }
}
```

The first authorization evaluation returns `REVIEW` and an `approval_request_id`. Human Interaction later submits:

```json
{
  "approver_id": "operator-security-01",
  "approver_role": "SECURITY_APPROVER",
  "decision": "APPROVE",
  "reason": "Authorized scoped laboratory validation"
}
```

The service **re-evaluates all hard constraints after approval**. Approval cannot override emergency stop, destructive-action hard deny, out-of-scope target, or risk above the scope ceiling.

## 10. Database tables

Primary tables:

```text
gov_policy_sets
gov_policy_rules

gov_scope_contracts
gov_scope_targets
gov_scope_sources
gov_scope_action_constraints

gov_authorization_requests
gov_risk_assessments
gov_policy_decisions

gov_approval_requests
gov_approval_decisions

gov_compliance_obligations

gov_emergency_state
gov_emergency_actions

gov_audit_log
gov_event_outbox
```

`gov_audit_log` uses a SHA-256 hash chain (`previous_hash` -> `record_hash`) to make silent history rewriting detectable. It is not a replacement for database access control or external immutable storage, but gives the research prototype an auditable chain.

## 11. Event integration with VulnDesk CTI

Governance can publish events to the existing VulnDesk endpoint:

```text
POST http://127.0.0.1:8765/api/cti/events/publish
```

Events produced by this implementation include:

```text
SCOPE_CHANGED
POLICY_DECISION_ISSUED
AUTHORIZATION_REVOKED
```

The current VulnDesk event-driven CTI runtime already understands `AUTHORIZATION_REVOKED` and `POLICY_CHANGED`. A subsequent integration patch should modify CTI-A01/CTI-A02 so that **SourceSyncConnector is committed only after this Governance service returns an authoritative ALLOW PolicyDecision**.

That integration is intentionally a separate change: Governance remains independently deployable and must not import CTI agent code.

## 12. Tests

Run:

```bash
pytest -q
```

The tests validate:

- deterministic risk scoring,
- CIDR/source scope matching,
- emergency-stop precedence,
- destructive-action hard deny,
- source allowlist enforcement,
- REVIEW -> human approval -> ALLOW behavior,
- human approval cannot bypass the risk ceiling.

After MariaDB and the API are running:

```bash
python scripts/smoke_test.py
```

## 13. Safety and architectural boundary

This prototype intentionally does **not** contain penetration-testing tools, exploit payloads, credential harvesters, or target execution code. Governance issues bounded policy decisions; the future Controlled Execution Gateway is responsible for deterministic enforcement at the execution boundary.

## 13. Governance Operations Console — Phase GUI-1

A PySide6 desktop operations console is included as a separate process from FastAPI. It is intentionally **not** embedded inside `app.main`, so the GUI can remain available while the Governance API is stopped or restarted.

Install dependencies and run:

```powershell
cd D:\aptsGS
.\.venv\Scripts\activate
pip install -r requirements-gui.txt
python run_gui.py
```

or:

```text
run_gui_windows.bat
```

Phase GUI-1 includes:

- Dashboard for Governance API, MariaDB, VulnDesk Event API, outbox worker, and Emergency Stop.
- Governance component registry for GOV-S01..GOV-S06 and GOV-D01..GOV-D03.
- Provided and consumed **Interfaces & Ports** inventory.
- Governance API Start / Stop / Restart process supervision.
- Emergency Stop Activate / Release with actor, reason, and explicit confirmation.
- Transactional outbox statistics, recent delivery records, and Retry Pending/Failed.
- Swagger launch and periodic non-blocking runtime refresh.

Important operational behavior:

- `GOV-S01..GOV-S06` are logical safety-critical components inside the single Governance API process. They do not have separate TCP ports and cannot be individually disabled from this console.
- **Emergency Stop is not the same as Stop API.** Emergency Stop keeps Governance online so it can continue to return authoritative decisions, while stopping the API causes clients such as VulnDesk to fail closed.
- Human approval remains outside the desktop console and is available in the separate aptsGSS Web application.
- The GUI never displays `GOV_DB_PASSWORD` or other secret values.

Additional read-only operational endpoints used by the console:

```text
GET /api/governance/runtime/status
GET /api/governance/interfaces
GET /api/governance/outbox/status
```

Existing write endpoints are reused for Emergency Stop and outbox retry.


## Human Layer & Human Interaction (2026-10-07)

Rilis ini menambahkan kontrak eksplisit `HUMAN-LAYER` dan `HUMAN-INTERACTION` serta dua
halaman pada aptsGSS Web. Human Layer adalah boundary otoritas/oversight, bukan agent dan
bukan executor. Human Interaction menghubungkan operator ke Global Mission Orchestrator
untuk mission intent dan ke aptsGSS untuk Scope/RoE, approval, audit, dan emergency control.
Lihat `README_GSS_WEB.md` untuk instalasi dan batas kewenangan.
