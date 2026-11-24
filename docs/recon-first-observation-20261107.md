# WPT verified evidence accepted by Recon — 7 November 2026

Implemented a separate `apts-wpt-recon-initial-request-v1` contract for the first real observation. Its durable event has null parent/action references. Existing iterative handoffs retain their original contract.

The Recon receiver reads the authoritative intake, sealed Stage 6 result and queued event, compares their identities and content, and validates the immutable Pentest task binding, target scope and orchestration. It imports the actual sanitized WPT observation and evidence manifest reference. Replay uses the same immutable request and run, including recovery after a lost acknowledgement.

After a durable Recon acknowledgement, the worker posts a service-authenticated WPT receipt. WPT checks intake, mission, task, execution and evidence manifest bindings against the completed job. Matching receipts replay without changes; conflicting receipts fail. Failed receipt synchronization is retried from the delivered outbox during subsequent sweeps.

Also repaired the inherited v9 Recon run table found under v16 repository metadata. The transactional repair retains the newer metadata and adds the existing v10 iteration schema. Server-owned task target metadata is projected to the strict two-field Recon target identity without relaxing observation input validation.

## Verified operational result

- Mission: `mission-gmo-f3008c8b-034f-4a1d-9853-8089003467f4`
- Intake: `wptreq-auto-65832c55866fa55f657cfb02300858f7bd2b9efc`
- WPT job: `wpt-cb4c3a8cc005716d2bae469dba2a6682`
- Recon run: `reconrun-69e1e45984e24a6b461507a61a0090c54c88cb6d986aa71c`
- Source result SHA-256: `834e1ef6a193008c91438bd1659b82031242343ad88e1f856d1a45fb8f97b716`
- Outbox: `DELIVERED`; parent and action are SQL NULL.
- Recon API: `COMPLETED`, target `http://127.0.0.1:80//dvwa/`, source `WPT_STAGE6_RESULT`.
- WPT API: `COMPLETED`, Recon receipt `DELIVERED`, delivery ID equals the Recon run ID.
- Autonomous worker replay: `replayed: true`, `wpt_receipt_status: DELIVERED`, total Recon run count remains one.
- Mission, Pentest and WPT health endpoints returned HTTP 200 after restart.

Existing evidence was re-read and verified against the authoritative Stage 6 ledger. This recovery did not dispatch a new target scan. Backups of WPT intake, Pentest and WPT job databases were captured under `D:/APTS/backups/recon-first-observation-20261107` before the handoff changes.

## Historical screenshot limitation

During implementation the active Mission/Pentest repositories no longer contained screenshot missions `06c45464…` and `370bb9b4…`; their older WPT evidence remained. They were not restored, fabricated or rebound to the current mission. The operational acceptance above concerns the current mission with complete authoritative bindings.

## Validation

Focused tests cover first observation, lost acknowledgement after Recon commit, idempotent replay, altered event rejection, authenticated WPT receipt binding/replay, newer repository schema preservation, metadata-bearing task targets, worker receipt retry, legacy cross-module handoff, Recon runs/iterations and Stage 6 recovery.

Final regression run: **60 passed**. The actual `observationForTarget` function from the Recon UI was evaluated against the live API response and selected this run as **Telah diobservasi**. WPT still returned `DELIVERED` after the final Mission restart; all three service health endpoints returned HTTP 200.
