# Post-Exploitation & Impact: P1

The workspace and Stage 5.7 emit `assessment_contract` using the shared
`apts-impact-assessment-v2` contract and `bounded-impact-rules-v2` policy.
Stage 5.7 remains `STAGE5_PROJECTION`: it never promotes projected paths into
observations. The workspace uses verified `STAGE6_OBSERVATION` records.
Existing stored Stage 5.7 artifacts remain readable; newly generated artifacts
contain the additional contract. Reading the workspace performs no target I/O.

## Authoritative objectives

Declare structured criteria in the bound mission/task `objective` before task
creation. The workspace retrieves and verifies the authoritative task; it does
not accept objective overrides from query parameters or browser inputs. Task
objectives must retain the mission boundary objective under the existing task
contract. Existing prose objectives and planning `goal_predicates` remain
`UNKNOWN` until evaluable criteria are supplied through that lifecycle.

```json
{
  "success_criteria": [
    {
      "criterion_id": "endpoint-available",
      "target": "http://localhost:8080/",
      "signal": "endpoint_exists",
      "expected_verdict": "OBSERVED"
    }
  ]
}
```

Criteria use AND semantics. Each criterion has exactly these four nonempty
string fields, with a unique criterion_id. Use `target` to declare criteria
before path generation, or replace it with `attack_path_id` to bind a specific
known path. Target matching uses the exact target string in the execution signal.
The expected verdict is OBSERVED or
NOT_OBSERVED. Missing/malformed criteria, unsupported signals, conflicting or
inconclusive observations, projections, blocked execution and stale plans cannot
produce MET. A conclusive contrary observation produces NOT_MET. Only supported
read-only HTTP signal types can produce MET; the list is HTTP_SIGNALS in
impact_policy.py. Reaching an objective never authorizes mission completion.
The contract binds the objective digest and preserves each criterion's reason.

## Decisions and bounded replanning

| Condition | Recommendation |
| --- | --- |
| Scope denial / stale plan | ESCALATE |
| Expected technical signals sufficient | STOP validation |
| Candidate REFUTED | STOP candidate |
| Repeated unresolved observations without new information | ESCALATE |
| Third distinct persisted execution run in the task/orchestration/target | ESCALATE if unresolved |
| Probe error | REPLAN / PROBE_FAILED |
| Incomplete evidence | REPLAN / INSUFFICIENT_EVIDENCE |

The execution history, not refresh count, determines the budget. Historical
assessments only use preceding runs, independent of the UI page limit. Repetition
fingerprints exclude run and plan IDs and timings. A changed plan with unchanged
observations is not automatically new information. STOP does not assert
compromise or mission completion. Recommendations do not invoke the planner or
execution gateway; the existing controlled execution boundary remains in force.

The UI shows objective status, criterion evidence matching, decision reasons,
iteration count and repeated-observation detection. Full source lineage remains
available in the audit JSON.
