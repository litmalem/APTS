# Stage 6.7 — VEP Construction & Integrity

Baseline: `Mission(20261003-133323).zip`, Stage 6.6.
Control: `stage6.7-vep-construction-integrity`.

## Perubahan

- Canonical VEP dan exact SHA-bound Stage 6.6 predecessor contract.
- Snapshot Pentest read-only yang mengikat task/binding, hypothesis, action
  proposal, validation task, source evidence serta attack-path predecessor.
- Snapshot execution yang mengikat envelope, claim, capture session, attempt,
  terminal chain, result, stop commands dan heartbeat authorizations.
- Satu immutable VEP per attempt terminal; explicit intake memerlukan exact
  envelope, manifest evidence dan head hashes. Replay tidak melakukan dispatch.
- Execution migration 7 dengan transaksi atomik, foreign keys, unique attempt,
  append-only triggers, terminal/scope guard dan batas byte UTF-8.
- Read, list, verification dan self-contained JSON export yang mengaudit
  canonical records serta retained artifact bytes asal.
- Audit offline memeriksa hash, nested lineage, derived semantics, timestamp
  bounds, exact artifact set dan allowlist isi seluruh jenis artefak Stage 6.6.
- Input ringkasan, finding/verdict, confidence, paths, commands dan upload
  evidence dari caller ditolak. Non-loopback API binding ditolak.
- Partial/crash capture dan target I/O uncertainty dipertahankan. Legacy
  attempt tanpa capture Stage 6.6 tidak mendapat fabricated backfill.
- CLI runner, startup dan acceptance PowerShell, schema JSON, panduan instalasi,
  serta bukti pengujian tersedia dalam paket.

## Batas dan kelanjutan

`finding_id` mengidentifikasi kandidat package-local; implementasi ini tidak
menambah atau mengonfirmasi row FINDING di Pentest. Adapter success tidak
mengonfirmasi vulnerability, impact atau expected evidence. Confidence berasal
dari hypothesis dan validated confidence tetap null.

Construction dan audit VEP tidak melakukan target I/O, memanggil GSS, menulis
ke Mission/Pentest, atau membuat execution authority. Authorization yang
disertakan bersifat historis. Hash membuktikan konsistensi internal; tidak ada
independent digital signature. Cleanup verification dan CTI writeback tetap
menjadi tahap 6.8 dan 6.9.

## Verifikasi

Inventory: **2.603 baseline + 98 tes Stage 6.7 = 2.701 canonical tests**.
Focused: **98 passed**. Continuity Stage 5.9→6.7: **692 passed**.
Hasil regresi lengkap, exact JUnit coverage, frozen source snapshot dan contoh
ekspor API berada dalam `evidence/stage6_7`; ringkasan final ada di
`REGRESSION_EVIDENCE_STAGE6_7.txt` dan `PATCH_MANIFEST_STAGE6_7.json`.

Pengujian memakai database terisolasi, real authority HTTP, native Linux sandbox,
loopback target, cancellation/manual retry, concurrent construction,
storage failure, serta penghentian proses dan exclusive-owner recovery nyata.
Windows PowerShell/Job Object dan mission pengguna belum dijalankan pada build
Linux ini. Gunakan acceptance pada host Windows untuk memeriksa deployment.
