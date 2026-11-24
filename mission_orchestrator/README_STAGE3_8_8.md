# Stage 3.8.8 — Observability Metrics, Health & Operator Diagnostics

Stage 3.8.8 derives one read-only, deterministic report per Mission from the same verified source bundle as Stage 3.8.7. The report exposes event, causal, decision, timestamp observation and live projection counts; a separate observability data-quality health status; and operator findings linked to the Stage 3.8.7 diagnostic report.

| Diagnostics 3.8.7 | Observability health | Metrics | Operator interpretation |
| --- | --- | --- | --- |
| `PASS` | `HEALTHY` | `AVAILABLE` | Sources agree; informational observations may still appear. |
| `FINDINGS` | `DEGRADED` | `WITHHELD` (`null`) | At least one blocking integrity, gap or consistency finding needs review. |
| `INDETERMINATE` | `UNKNOWN` | `WITHHELD` (`null`) | A required source could not be read; inspect source statuses. |

`HEALTHY` describes **observability data quality**, not Mission success, runtime liveness or authorization. A Mission with state `FAILED` can still have healthy observability. No missing or untrusted count is displayed as zero. Operator entries retain the finding IDs and codes from Stage 3.8.7 and point to the existing Mission diagnostics route. Unresolved external causation and backward source timestamps are informational observations unless accompanied by a blocking finding.

Metrics include event counts by type and source component; counts of decision events and potentially overlapping decision categories; causal nodes, edges and unresolved external references; backward timestamp observations; and counts from the Stage 3.8.4 live Mission projection. The first and last timestamp fields are ledger endpoint observations, not clock-authoritative order. The report does not infer throughput or latency from source timestamps.

Read APIs:

- `GET /api/missions/{mission_id}/observability-metrics-health`
- `GET /api/observability/metrics-health-contract`

Runtime control: `stage3.8.8-observability-metrics-health-operator-diagnostics`; HTTP server `APTSMissionOrchestrator/3.8.8`. Repository migration remains **53**. The report adds no durable store, Governance query, authorization decision, runtime probe, external network request, telemetry export, routing, delegation, dispatch, execution attempt, Mission state transition, target action or automatic repair. Its domain-separated SHA-256 digest detects changes to the read result; it is not an external signature.

Stage 3.8.7 reads are not an atomic database snapshot. Concurrent writes can cause `DEGRADED` or `UNKNOWN`; retry after writers settle before diagnosing a cross-source difference. A corrupt canonical Mission envelope still fails closed; an unknown Mission returns 404. Without an independent external checkpoint, internally consistent removal of the entire event tail cannot be proven absent.

The ZIP is an overlay for a Stage 3.8.7 installation. It contains changed sources/tests, this description, installation and acceptance instructions, and a SHA-256 manifest. It contains no deployment `data/` directory or migration. Run `STAGE3_8_8_ACCEPTANCE.ps1` after restarting the Windows service; supply `-MissionId` to check the live Mission route. Windows deployment acceptance is a separate host step.

Local verification on Python 3.12 / SQLite (25 September 2026 UTC): compilation passed, **1,417 tests collected**, **1,417 passed in 924.23 seconds**, and **9 focused Stage 3.8.8 tests passed in 0.97 seconds**. The focused suite covers stable read-only reports, categorical metrics, degraded and unknown health, withholding, source binding, report integrity, operator findings, HTTP routes and 404 handling.
