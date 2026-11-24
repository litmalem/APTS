# Stage 6.6 — Artifact & Evidence Capture

Implementasi ini menggunakan baseline `Mission(20261003-122229).zip` pada Stage 6.5.
Control aktif: `stage6.6-artifact-evidence-capture`.
Execution migration: **6**. Mission migration **53** dan Pentest migration **16** tetap read-only.
Kontrak Stage 6.5 tetap identik dan menjadi predecessor SHA-bound.

## Capture dan penyimpanan

Gateway tetap menjalankan lima fixed adapters melalui fresh external GSS dan sandbox native.
Collector mengambil data yang memang sudah dihasilkan adapter; collector tidak melakukan target I/O tambahan.
SQLite milik Execution menyimpan payload JSON sebagai BLOB, descriptor artefak, dan manifest evidence.
Tidak ada API upload evidence, input path, executable, shell, atau caller-supplied result.

| Jenis | Data yang disimpan |
|---|---|
| TOOL_IDENTITY | Adapter, capability, operation, registry hash, fixed worker source hash, versi Python |
| ACTION_PARAMETERS | Tindakan dan target yang terikat request, parameter terstruktur, hash parameter lengkap, controls, lease ID tanpa credential bytes |
| BEFORE_STATE | State runtime AUTHORIZED, authorization ID, hash current context; bukan pengukuran state target |
| STDOUT | Pesan metadata fixed worker yang lolos allowlist, digest byte stdout yang tertangkap, ukuran, flag kelengkapan |
| STDERR | Digest dan ukuran stderr aktual, exit code; teks mentah tidak disimpan |
| NETWORK_OBSERVATION | Peer IP, status koneksi, ukuran dan digest respons, batas byte dan kelengkapan observasi |
| TARGET_RESPONSE | HTTP status bila tersedia, ukuran dan hash byte respons; nilai header, banner, cookie, token, dan body tidak disalin |
| RESULT | Status dan observasi hasil adapter yang terstruktur, hash hasil, semantics |
| AFTER_STATE | State terminal runtime, hash terminal event, ketidakpastian target I/O, tanpa klaim pengukuran state target |

Screenshots belum dihasilkan oleh fixed adapters yang tersedia. Coverage mencatat
`NOT_SUPPORTED_BY_CURRENT_FIXED_ADAPTERS`. Target before/after state tercatat `NOT_MEASURED`.
Keduanya tidak diisi dengan data sintetis. VEP, konfirmasi vulnerability, cleanup, dan CTI feedback
menjadi pekerjaan Stage 6.7–6.9, bukan kesimpulan dari capture ini.

Setiap descriptor terikat ke `attempt_id`, `invocation_id`, `execution_id`, `task_id`,
`pentest_id`, `pentest_task_id`, dan `mission_id`, serta session hash.
Manifest juga terikat ke exact claim, envelope, hasil adapter, dan terminal event hash.
Timestamp mencakup enrollment, capture tiap artefak, native RUNNING, dan sealing.

`captured_sha256` menghitung byte yang tertangkap sebelum normalisasi/redaksi;
`content_sha256` menghitung payload BLOB yang benar-benar disimpan.
Untuk stdout yang melebihi batas baca, digest hanya mencakup prefix yang tertangkap dan
`capture_complete=false`. Hash tidak memberikan authorization dan tidak memulihkan byte yang dibuang.
Hash membuktikan konsistensi data dan lineage dalam boundary runtime, bukan tanda tangan pihak ketiga.

Batas: 128 KiB per artefak, 512 KiB total per attempt, maksimum sembilan jenis artefak.
Network/output quotas Stage 6.4 tetap berlaku. Table, blob, dan manifest append-only;
SQL triggers menolak perubahan, penghapusan, quota berlebih, dan penambahan setelah manifest disegel.

## Atomicity, failure, dan recovery

Admission menyimpan session dan tiga artefak awal dalam transaksi reservasi.
Keluaran broker dan worker dicatat selama runtime. Transaksi terminal menyimpan hasil,
terminal event, RESULT, AFTER_STATE, dan manifest secara atomik.
Kegagalan penyimpanan tidak boleh menghasilkan SUCCEEDED tanpa evidence: health menjadi degraded,
claim tetap consumed, dan execution tidak otomatis diulang.

Status capture:

- `CAPTURING`: artefak durable tersedia; manifest belum disegel.
- `CAPTURED`: semua data yang dihasilkan operation telah dicatat, dengan batas capability di coverage.
- `PARTIAL`: interruption atau kegagalan membuat sebagian observasi tidak lengkap/tidak tersedia.
- `RECOVERED_PARTIAL`: exclusive owner baru menutup orphan sebagai ABORTED; hanya artefak durable digunakan,
  output yang hilang dinyatakan eksplisit, target I/O tetap uncertain, tidak ada redispatch.
- `LEGACY_NOT_CAPTURED`: attempt sebelum Stage 6.6; tidak ada capture baru atau backfill target I/O.

Manual retry mengikuti policy Stage 6.5. Setiap attempt memiliki artefak dan manifest tersendiri.
Read dan verification mengaudit hash BLOB, index, session, scope identity, hasil, dan event chain.
Read tidak mengubah governance atau memulai execution.

## API read-only

| Method | Route |
|---|---|
| GET | `/api/execution/artifact-evidence-contract` |
| GET | `/api/execution/evidence?execution_id=<exec-id>&limit=100` |
| GET | `/api/execution/evidence/attempts/<attempt-id>` |
| GET | `/api/execution/evidence/attempts/<attempt-id>/verify` |
| GET | `/api/execution/artifacts/<artifact-id>?attempt_id=<attempt-id>` |
| GET | `/api/execution/artifacts/<artifact-id>/content?attempt_id=<attempt-id>` |

Artifact metadata response menyediakan `content_base64` dari payload yang telah diverifikasi.
Content response mengirim JSON bytes, `X-Artifact-SHA256`, no-store, dan nosniff.
Exact attempt ID wajib pada pembacaan artifact. Path/target/authority override dan duplicate query ditolak.
POST pada evidence/artifact routes ditolak 409. Runtime API Stage 6.5 tetap tersedia.

Contoh pemeriksaan attempt terminal yang dibuat setelah upgrade:

```powershell
$base = 'http://127.0.0.1:8791'
$attemptId = 'xattempt-ISI_DARI_RESPONSE_RUNTIME'
$capture = Invoke-RestMethod "$base/api/execution/evidence/attempts/$attemptId"
$capture | Select-Object status, sealed, artifact_count, manifest_sha256
Invoke-RestMethod "$base/api/execution/evidence/attempts/$attemptId/verify"
```

## Instalasi dan acceptance

Lihat `INSTALL_STAGE6_6.txt`. Aktifkan dengan `START_STAGE6_6_EXECUTION.ps1`,
lalu jalankan `STAGE6_6_ACCEPTANCE.ps1` pada PowerShell terpisah.
Opsional `-LiveAttemptId <id>` melakukan audit read-only event chain, manifest, dan seluruh blob bytes.
Audit tersebut membutuhkan attempt terminal; history Stage 6.5 dilaporkan sebagai legacy tanpa capture.

Inventory: 2.539 baseline + 64 tes Stage 6.6 = **2.603 tes canonical**.
Regression runner menyimpan per-group log/XML, exact per-test coverage, dan frozen source hashes.
Hasil build lokal berada dalam `evidence/stage6_6`.
Proof menggunakan repository terisolasi, authority HTTP, sandbox native Linux, loopback targets,
dan penghentian proses nyata. Windows PowerShell/Job Object dan live user mission belum dieksekusi
dalam build ini; acceptance pada host Windows memverifikasi deployment aktual.
