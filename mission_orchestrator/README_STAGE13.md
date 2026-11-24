# Stage 13 — Enumeration Agent to Stage 6 handoff

Stage 13 closes one controlled path from a persisted Stage-5.3 Enumeration proposal through Stage 6.6. The only enabled action tuple is:

```text
capability_id = enumeration
action_class  = TARGET_RECON
technique     = TCP_BANNER_READ
```

Stage 5.3 remains non-executing. It may persist the explicit technique as a governed proposal, but it cannot create a Stage-6 request, authorization, or target I/O. Stage 6.1 verifies the exact run, output/evidence hashes, task, orchestration node, proposal lineage, Stage-4.8 decision, current scope/RoE, and a one-request/one-worker budget. `SERVICE_ENUMERATION` and the other semantic proposal labels are rejected before Stage-6.1 creates a request.

Stage 6.2/GSS must freshly ALLOW the immutable request. Stage 6.3 admits the exact registry tuple; Stage 6.4 selects `network.tcp-banner.v1` server-side; Stage 6.5 executes through the fixed sandbox; Stage 6.6 seals metadata-only evidence. The raw banner is not returned or retained. The Stage-6.6 result lookup is read-only and keyed by the exact `actp-...` proposal reference. Enumeration iteration validates the result and emits a separate integrity-bound projection without mutating the parent Enumeration run.

## API additions

- Stage 6.6 read-only lookup: `GET /api/execution/enumeration-proposals/{proposal_ref}/results`
- Stage 6.6 result contract: `GET /api/contracts/enumeration-execution-result`
- Pentest read-only proxy: `GET /api/pentest/ui/enumeration-proposals/{proposal_ref}/results`
- Enumeration iteration: `POST /api/pentest/agentic-orchestrations/{orchestration_id}/enumeration/iterations/run`

The Stage-5.3 process fetches results only from the configured loopback Stage-6 result API (`APTS_STAGE6_RESULT_API_BASE`, default `http://127.0.0.1:8791`).

## Apply and verify on Windows

From `D:\mission_orchestrator`, first check and apply `Stage13_Enumeration_Stage6_Handoff.patch`, then run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE13_ACCEPTANCE.ps1
```

The E2E uses an ephemeral loopback TCP server. It checks one banner-read connection, verifies that the banner bytes are not retained, and validates proposal-to-GSS/gateway/runtime/evidence/result/iteration binding.
