# Stage 6.4 — Execution Revalidation Compatibility

Patch ini menambahkan attestation `apts-gss-execution-revalidation-v1` ke jalur authorization yang dipanggil Execution Subsystem Stage 6.2–6.4. Request generic CTI dan revalidation Stage 2 tetap memakai perilaku historis.

Request execution harus membawa sealed evaluation Stage 6.2, request Stage 6.1, nonce, hash, Mission/Pentest context, scope reference, dan evidence correlation yang konsisten. `subject_component=EXECUTION_SUBSYSTEM`, action `AUTHORIZE_TARGET_EXECUTION`, purpose, action class, target, actor, dan evidence harus terikat persis. Input invalid ditolak sebelum authorization/decision dipersist.

GSS menghitung sendiri delapan check: SCOPE, ROE, POLICY, RISK, EXPIRY, REVOCATION, TARGET, TECHNIQUE. `local_checks` dari caller tidak menjadi authority. Pemeriksaan menggunakan current stored scope/policy/action constraint/emergency state, referenced decision revocation/hash, serta pembatas tambahan Mission/Pentest/task. Risk memakai environment scope dan operasi/credential requirement; flags risk/approval dari caller tidak dapat memberikan izin.

`allowed_techniques` pada action constraint GSS wajib merupakan daftar yang eksplisit dan berisi technique request. Empty/missing allowlist menolak target execution. Stored scope harus memiliki mission/version/hash/policy identity yang sama dengan binding terkini. Referenced historical decision harus ditemukan, memiliki mission/hash yang cocok, dan tidak revoked; expired historical decision tidak dengan sendirinya menggantikan fresh authorization.

Hard deny/check FAIL/emergency/revocation mendahului approval. Human approval hanya berasal dari server approval path. Attestation dimasukkan sebelum `decision_hash` dihitung dan disimpan pada audit/outbox authoritative. Tidak ada perubahan schema SQL yang diperlukan; kolom decision/audit/outbox yang sudah ada tetap digunakan. Audit/outbox membawa proof lengkap; GET decision generik bukan permit adapter reusable.

Health menambahkan `execution_revalidation_schema_version` dan daftar mandatory checks. Execution client lama yang tidak membutuhkan attestation tetap berfungsi untuk request generic; request execution yang tidak memenuhi protocol tetap gagal closed.

Overlay patch ke root proyek aptsGSS yang berisi `app/main.py`, lalu restart runner yang biasa digunakan. Tidak perlu mengimpor ulang AptsGSS.sql. Jalankan:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE6_4_GSS_ACCEPTANCE.ps1
```

Regression: **58 tes** (26 baseline + 32 baru). Tests memakai repository terisolasi, bukan database production. Cross-plane source compatibility proof di paket Mission menggunakan kode GSS ini melalui HTTP loopback untuk ALLOW, revocation, dan emergency-stop-at-boundary; production MySQL dan live user mission belum diklaim terverifikasi. PowerShell harness belum dijalankan dalam Linux build.
