# Stage 3.8.2 — Cross-Subsystem Event Normalization & Ingestion

This stage exposes a read-only normalized view of the verified durable Mission event ledger at `GET /api/missions/{mission_id}/observability-events`. It retains original source component and source event identity, normalizes timezone-aware timestamps to UTC, binds every event to the deterministic Mission root trace from Stage 3.8.1, preserves causation and parent IDs, and hashes normalized records. It excludes raw payloads to avoid exposing sensitive data and prevents payload claims from impersonating the recorded source.

The source ledger is verified before projection. Invalid event chains fail closed. Repeated reads and process restarts yield the same projection without new migrations, runtime calls, telemetry exports, or state mutations. This stage ingests events already durably recorded in the Mission ledger; it does not accept arbitrary external events or claim complete coverage of external subsystem streams.

Runtime control version: `stage3.8.2-cross-subsystem-event-normalization-ingestion`; server version: `APTSMissionOrchestrator/3.8.2`; migration level remains 53.
