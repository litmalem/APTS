# Stage 6.6 — Artifact & Evidence Capture

- Tambahkan evidence collector server-owned yang menggunakan keluaran broker/worker existing.
- Execution migration 6: capture sessions, JSON BLOB artifact repository, dan manifest evidence.
- Simpan hash byte captured dan hash payload stored, timestamps, tool source identity, parameters,
  runtime before/after state, stdout/stderr metadata, network observation, dan target response metadata.
- Ikat artifacts dan manifest ke exact attempt/execution/task/pentest/mission, claim, envelope,
  adapter result, dan terminal event. Manifest dan hasil terminal committed atomik.
- Tambahkan quotas, append-only SQL triggers, verifikasi blob/index/lineage, penolakan caller upload,
  query override, dan artifact read tanpa exact attempt ID.
- Recovery menyegel partial evidence dari data durable dan menyatakan missing output tanpa redispatch.
  History Stage 6.5 tidak memperoleh fabricated capture.
- Tambahkan 64 focused tests, startup/acceptance PowerShell, exact canonical regression runner,
  dan auditor yang memverifikasi payload bytes hasil read API.
- Kontrak predecessor Stage 6.1–6.5, governance protocol, dan skema Mission/Pentest dipertahankan.
- Screenshot/target state measurement belum tersedia pada fixed adapters; coverage menyatakan hal ini.
  Evidence capture belum membangun VEP atau mengonfirmasi vulnerability.
