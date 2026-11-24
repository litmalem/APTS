# Post-Approval Governance Decision Reconciliation

## Change

Mission Orchestrator now exposes:

`POST /api/missions/{mission_id}/authorization-bindings/{authorization_binding_id}/reconcile`

The endpoint reads the authoritative aptsGSS mission correlation snapshot. It does not create a new authorization request or approval. It accepts a newer terminal PolicyDecision only when the original binding is `REVIEW`, the request/capability/resource/scope identities still match, the current Governance scope and Mission scope binding remain unchanged, the decision is active and within its validity window, and an `ALLOW` carries `HUMAN_APPROVAL_GRANTED` evidence.

A successful reconciliation appends a new immutable Authorization Binding with explicit supersession lineage. The original `REVIEW` record remains unchanged. The new record still has `execution_authorized=false`; pre-dispatch revalidation remains required. Repeated reconciliation of the same decision is idempotent. Expired, future, inactive, stale-scope, mismatched, and nonterminal decisions fail closed.

## Example (PowerShell)

```powershell
$mid = "<mission-id>"
$mo = "http://127.0.0.1:8780"
$reviewBindingId = "<original-review-authorization-binding-id>"

$result = Invoke-RestMethod `
    -Uri "$mo/api/missions/$mid/authorization-bindings/$reviewBindingId/reconcile" `
    -Method Post `
    -ErrorAction Stop

$result | ConvertTo-Json -Depth 12
```

Call this after deploying/restarting Mission Orchestrator and after aptsGSS has issued a fresh, currently valid post-approval decision. Reconciliation does not dispatch or execute a target action.

## Validation

- Python compilation passed for the modified service, governance binding, API service, and tests.
- Added focused tests for `REVIEW -> APPROVED -> ALLOW`, append-only history, idempotent replay, and expired-decision rejection.
- The two focused tests passed in the provided environment. The pytest package is not installed, so they were invoked directly with a minimal `pytest.raises` compatibility shim.
