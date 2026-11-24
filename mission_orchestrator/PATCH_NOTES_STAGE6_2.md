# Stage 6.2 — Authoritative Execution Authorization

Implementasi execution authorization gate untuk request Stage 6.1. Request dan source historis dipertahankan; record authorization ditambahkan pada execution database migration 2.

- Current Mission/Pentest sources read-only, verified scope/binding heads, RUNNING mission and stable proposal context.
- Local scope/RoE/risk/target/technique gates; fresh aptsGSS PolicyDecision with exact evaluation/request/envelope/nonce/context binding.
- Eight explicit authoritative checks; deny/revocation/stop precedence; human review preserved; expiry, freshness, policy downgrade and stale decision protections.
- Append-only authorization audit, idempotent historical replay, restart integrity and no cached ALLOW fallback.
- New Stage 6.2 handler, CLI, starter, acceptance, JSON schemas and 111 focused tests.
- Gateway/raw tools/target/results remain outside Stage 6.2. Next stage: 6.3.

GSS source is outside this archive. Its required attestation extension is documented; unsupported responses fail closed. Live production GSS integration and Windows PowerShell acceptance are not claimed by the Linux build evidence.
