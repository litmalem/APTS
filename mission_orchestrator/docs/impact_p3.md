# Post-Exploitation & Impact: P3

P3 adds reporting policy `impact-report-rules-v1` and sealed
`apts-impact-report-v1` reports. Assessment policy remains
`bounded-impact-rules-v3`: generating a report does not change the P1/P2
assessment identity or publish new coordination feedback.

## Summary and recommendations

The workspace returns `report_preview` without report writes. A preview groups
technical observations by exact signal and target, retaining claim IDs,
hypothesis references, execution/path hashes, source timestamps and JSON
pointers. Observations from multiple paths are not counted as distinct
vulnerabilities. Conflicting grouped verdicts remain explicit.

The summary includes the objective and its criteria, technical decision, status
counts, contextual business exposure and limitations. Missing criteria remain
UNKNOWN. Business declarations remain potential context; reports do not assert
actual business loss or mission completion.

Recommendations are deterministic and traceable to each technical observation:

| Signal family | Recommendation |
| --- | --- |
| Product version | Review unnecessary version disclosure and validate inventory/advisories; a missing banner is not proof of patching |
| Configuration metadata | Review nonessential published metadata while retaining required/security headers |
| Endpoint reachability | Review intended publication and access requirements; a responding endpoint is not automatically a vulnerability |
| Authentication boundary | Match access requirements to endpoint design; 401/403 does not prove a bypass and public endpoints may legitimately omit login |
| Inconclusive, conflicting, unsupported or blocked evidence | Review evidence and scope; do not propose a confirmed vulnerability fix |

No CVE-specific patch, severity score, exploit success or financial loss is
invented from HTTP metadata. Recommendations are for the service owner's review
and are not executed automatically.

## Immutable baseline and retest

The UI saves reports to `pentest_impact_reports`, independently of mutable
execution cache rows. A report freezes the full verified execution record,
assessment, business context and followup status at capture. This preserves a
baseline even if a later forced execution replaces the original execution row
using the same deterministic execution_run_id. Report identity binds the full
contents and baseline reference; identical saves are idempotent.

Retest uses an explicitly selected stored baseline from the same mission and
exact target value. It can span different task/path/hypothesis IDs within that
mission, since the comparison is about measured HTTP signals rather than
identity changes in the planning model. It requires a different execution
digest and strictly later source completion time. A changed declaration alone
is not new execution evidence. Same-second timestamps with no established
ordering remain NOT_COMPARABLE.

Signal matching uses exact signal and signal-target values. Compatibility also
checks execution method, control/schema versions, HTTP methods, validation
techniques and assessment policy. Missing probe metadata or incompatible
measurement definitions cannot prove a change. Objective-definition changes are
reported separately and cannot be presented as objective progress.

| Comparison | Meaning |
| --- | --- |
| SIGNAL_NO_LONGER_OBSERVED | Conclusive OBSERVED changed to NOT_OBSERVED |
| SIGNAL_NEWLY_OBSERVED | Conclusive NOT_OBSERVED changed to OBSERVED |
| UNCHANGED | Same conclusive verdict |
| INCONCLUSIVE | One or both observations are nonconclusive/conflicting |
| NOT_RETESTED | Baseline signal/target was omitted from retest |
| NEW_COVERAGE | Retest signal/target has no baseline measurement |
| NOT_COMPARABLE | No new evidence, ambiguous chronology, a historical plan at capture or incompatible/missing measurement metadata |

None of these statuses establishes vulnerability remediation. Version-disclosure
recommendations can show `technical_expectation_met` when the same measurement
no longer observes a version, but `vulnerability_remediation_confirmed` stays
false. Generic header presence, endpoint reachability and authentication signals
have no invented universal desired verdict.

## Using the UI

1. Select the execution context and review the summary/recommendations.
2. Save an initial report without a baseline before remediation.
3. Record remediation separately with the service owner and obtain a later
   execution result through the existing controlled execution workflow.
4. Select that result, select the saved baseline and optionally enter an operator
   remediation note. Save the retest report.
5. Review comparability and coverage before interpreting signal changes.

The report action never invokes a probe, replays a specialist, publishes an
assessment, grants governance approval or completes a mission. Historical
reports can be saved for audit but are labelled and cannot establish a valid
retest result. Operator remediation notes are declarations, not verified proof.

Reports can be reopened after restart and exported as JSON or Markdown. JSON
contains the complete current frozen source snapshot. Retest reports include the
baseline ID/hash and before/after claim references; a separate baseline JSON
download preserves access to its complete source snapshot. Markdown includes
objective criteria, contextual impact, recommendations, source hashes, retest
table, notes and limitations. User-controlled text is escaped in rendered HTML
and Markdown exports.

## API

- `POST /api/pentest/ui/post-exploitation-impact/reports` accepts required
  `execution_run_id` and `expected_assessment_id`, plus optional
  `baseline_report_id` (null means none) and `remediation_note` (up to 2000 chars).
  The server recomputes the assessment and verifies its source execution; caller
  report contents and stale assessment identities are rejected.
- `GET /api/pentest/ui/post-exploitation-impact/reports?mission_id=...&limit=100`
  lists verified report summaries, newest insertion first (limit 1–500).
- `GET /api/pentest/ui/post-exploitation-impact/report?report_id=...&format=json`
  retrieves a verified report. `format=markdown` downloads its Markdown export.

POST uses the existing same-origin UI check. Reads verify report and nested
source integrity. Source lineage, source digest, execution ID, source plan
snapshot and source completion time must agree. The UI lists up to 500 newest
mission reports and filters them to the selected exact target.

Restart the Pentest service and refresh the browser after upgrading so the new
report endpoint and `impact-report.js` asset route are loaded.
