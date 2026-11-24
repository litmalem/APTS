# Stage 6.7 — VEP Construction & Integrity

Baseline: `Mission(20261003-133323).zip`, Stage 6.6. Control aktif:
`stage6.7-vep-construction-integrity`. Execution migration **7**;
Mission **53** dan Pentest **16** tetap read-only. Kontrak Stage 6.1–6.6
dipertahankan, dan kontrak Stage 6.6 menjadi exact SHA-bound predecessor.

VEP = **Validation/Evidence Package**. Paket ini merangkum sumber Pentest,
hasil fixed adapter, evidence yang sudah tersimpan, serta batas bukti aktual.
Konstruksi VEP tidak melakukan target I/O, memanggil GSS, mengulang execution,
atau mengubah Mission/Pentest. Fresh external GSS tetap wajib untuk execution
melalui gateway/runtime yang sudah tersedia.

## Isi canonical VEP

| Bagian | Sumber dan makna |
|---|---|
| Identity | mission, pentest, task, execution, invocation, attempt, dan package-local finding ID |
| Finding | `UNCONFIRMED_CANDIDATE`; bukan row FINDING baru pada Pentest |
| Hypothesis | Statement, status, reference dan hash lineage HYPOTHESIS tersimpan |
| Validation method | Exact validation task, action, parameters, adapter dan operation |
| Execution references | Envelope, claim, attempt, terminal event, result hashes, dan retry predecessor |
| Observed result | Runtime state, adapter status, observasi terstruktur, capture status dan uncertainty |
| Evidence | Manifest Stage 6.6 beserta seluruh descriptor dan coverage |
| Affected asset | Target dari exact canonical execution request |
| Impact | Estimasi proposal; observed security impact belum dinilai |
| Confidence | Confidence hypothesis sumber; confidence vulnerability tervalidasi bernilai null |
| Provenance | Hash snapshot sumber, proposal, path, authorization historis dan kontrak |
| Timestamps | Authorized, native running, sealing dan construction timestamps |
| Integrity hashes | SHA-256 per bagian, domain hash paket, dan hash exact retained artifact bytes |

`finding_id` deterministik dari scope, target dan hypothesis; retry atas kandidat
yang sama dapat menggunakan finding ID yang sama. `vep_id` terikat ke exact
attempt, manifest evidence, snapshot sumber dan kontrak 6.7. Setiap attempt
terminal memiliki paling banyak satu VEP immutable. Replay mengembalikan
paket pertama yang sama, termasuk construction timestamp.

Package menyertakan snapshot sumber task/binding, exploitation request/output,
evidence bundle, attack-path output/bundle, hypothesis, action proposal dan
evidence basis. Sumber dibaca dalam transaksi SQLite `mode=ro` dan `query_only`.
Snapshot execution menyertakan envelope, session, attempt, claim, runtime events,
adapter result, stop commands dan heartbeat authorizations yang direferensikan.
Hubungan antar-record dan kesesuaian target/task/mission diperiksa kembali.

## Batas bukti dan integritas

Fixed adapters yang tersedia menghasilkan observasi koneksi/respons dan
metadata. `SUCCEEDED` berarti primitive adapter berhasil; status tersebut
tidak menjadi verdict vulnerability. `vulnerability_confirmed=false`,
`impact_confirmed=false`, dan validated vulnerability confidence tetap null.
Tidak ada CVSS, tingkat privilege, resource compromise, atau business impact
yang diinferensikan dari sukses koneksi.

`PARTIAL` dan `RECOVERED_PARTIAL` dipertahankan lengkap dengan gap, ukuran,
digest, capture completeness dan target I/O uncertainty. Screenshots tetap
`NOT_SUPPORTED_BY_CURRENT_FIXED_ADAPTERS`; target before/after state tetap
`NOT_MEASURED`. Tidak ada data sintetis yang mengisi gap.
Attempt aktif atau history lama tanpa capture Stage 6.6 tidak dapat dibuatkan VEP.

SHA-256 dan canonical JSON membuktikan konsistensi record, byte, serta lineage
di dalam boundary runtime. Paket tidak ditandatangani oleh pihak independen.
Audit offline tidak membuktikan independent authenticity atau memulihkan raw
target bytes yang sudah direduksi menjadi metadata/digest pada Stage 6.6.
Schema JSON memeriksa struktur interchange; pemeriksaan hubungan, semantics,
timestamp dan nilai turunan dilakukan oleh `verify_vep`/`verify_vep_export`.

Construction timestamp tidak boleh mendahului sealing. Tidak ada caller-supplied
summary, finding ID, verdict, confidence, path, command, result atau evidence upload.
Penyimpanan menggunakan transaksi `BEGIN IMMEDIATE`, foreign keys, unique attempt,
dan SQL guards untuk append-only, terminal lineage dan byte quota. Kegagalan
penyimpanan VEP membatalkan transaksi VEP; execution tidak dijalankan ulang.

Batas: 1 MiB snapshot Pentest, 2 MiB VEP, 4.096 runtime events, dan 3 MiB export.
Capture quotas Stage 6.6 tetap berlaku. Export hanya menyertakan retained JSON
blobs yang telah diverifikasi, tanpa file paths dan tanpa raw target body,
cookie, credential bytes atau raw stderr.

Pembacaan VEP memeriksa immutable snapshot, canonical hashes, event chain,
manifest serta byte artefak asal dari database Execution. Snapshot Pentest
yang sudah tersimpan memungkinkan read/replay setelah sumber upstream tidak
tersedia. Konstruksi pertama memerlukan snapshot sumber yang valid, tetapi
tidak mensyaratkan Mission masih RUNNING atau authorization masih berlaku.
`authorization_current=false` selalu berlaku pada konstruksi dan pembacaan VEP.

## API

| Method | Route | Keterangan |
|---|---|---|
| GET | `/api/execution/vep-construction-integrity-contract` | Exact canonical contract |
| POST | `/api/execution/veps` | Konstruksi dari exact terminal references |
| GET | `/api/execution/veps?execution_id=<id>&limit=100` | Daftar VEP terverifikasi |
| GET | `/api/execution/veps/<vep-id>?attempt_id=<attempt-id>` | Exact scoped VEP |
| GET | `/api/execution/veps/<vep-id>/verify?attempt_id=<attempt-id>` | Audit record dan artifact bytes |
| GET | `/api/execution/veps/<vep-id>/export?attempt_id=<attempt-id>` | Self-contained JSON export |

List membutuhkan satu exact execution ID, dengan limit 1–100. Read, verify,
dan export membutuhkan exact attempt ID. Duplicate query/JSON keys dan source,
path atau authority overrides ditolak. POST upload/verify/export ditolak 409.
Construction baru mengembalikan 201; replay mengembalikan 200. Invalid intake
400, identitas tidak ditemukan 404, binding/lineage invalid 409, dan sumber atau
storage tidak tersedia 503. Semua read/exports memakai `Cache-Control: no-store`;
export menambahkan `nosniff` dan `X-VEP-SHA256`.

API request, authorization, runtime, capture dan artifact Stage 6.1–6.6
tetap tersedia pada runtime baru. Aktifkan runner **execution_vep.py**, bukan
runner predecessor yang akan menolak migration 7.

Contoh membuat VEP dari attempt terminal yang sudah ada:

```powershell
$base = 'http://127.0.0.1:8791'
$attemptId = 'xattempt-ISI_DARI_RUNTIME'
$runtime = Invoke-RestMethod "$base/api/execution/runtime/attempts/$attemptId"
$capture = Invoke-RestMethod "$base/api/execution/evidence/attempts/$attemptId"
$body = @{
    schema_version = 'apts-execution-vep-construction-v1'
    attempt_id = $attemptId
    envelope_sha256 = $runtime.record.runtime_intake.envelope_sha256
    evidence_sha256 = $capture.manifest_sha256
    expected_head_sha256 = $runtime.head_sha256
} | ConvertTo-Json -Depth 10
$vep = Invoke-RestMethod -Method Post -Uri "$base/api/execution/veps" -ContentType 'application/json' -Body $body
$vep | Select-Object status, created, vep_id, finding_id, vep_sha256
Invoke-RestMethod "$base/api/execution/veps/$($vep.vep_id)/verify?attempt_id=$attemptId"
Invoke-WebRequest "$base/api/execution/veps/$($vep.vep_id)/export?attempt_id=$attemptId" -UseBasicParsing -OutFile '.\vep_export.json'
python run\stage6_7_audit.py --export-file .\vep_export.json
```

Perintah tersebut membangun metadata VEP saja. Attempt baru tetap dibuat
melalui runtime dengan fresh external GSS seperti Stage 6.5/6.6.

## Instalasi dan acceptance

Lihat `INSTALL_STAGE6_7.txt`. Hentikan Execution lama, backup database,
ekstrak arsip hasil, lalu jalankan `START_STAGE6_7_EXECUTION.ps1` dan
`STAGE6_7_ACCEPTANCE.ps1` pada PowerShell terpisah. Tidak perlu impor SQL dump
ke Mission/Pentest/GSS. Acceptance tidak membuat VEP atau menjalankan target
mission pengguna; pengujian menggunakan database terisolasi dan target loopback.

Opsional `-LiveAttemptId <id> -LiveVepId <id>` melakukan audit read-only atas
VEP yang sudah ada, termasuk ekspor dan audit offline retained bytes.
Audit itu tidak membuat VEP baru.

Regression runner menyimpan per-group log/XML, exact per-test coverage,
inventory dan frozen source hashes dalam `evidence/stage6_7`. Build lokal
menguji Linux `SECCOMP_RLIMIT`, real authority HTTP, loopback target, stop/retry,
penghentian proses nyata dan recovery. Windows PowerShell/Job Object serta
mission pengguna tidak dijalankan dalam build Linux; acceptance pada host
Windows memverifikasi runtime aktual.

Tahap berikutnya: **6.8 — Cleanup, Rollback & Post-Action Verification**.

## Hasil build final

| Pemeriksaan | Hasil |
|---|---|
| Stage 6.7 focused | 98 passed |
| Stage 5.9–6.7 continuity | 692 passed |
| Full canonical regression | 2.701 passed; 0 failed/error/skipped |
| Exact JUnit coverage | PASS |
| Frozen source snapshot | UNCHANGED |
| Offline API export | VERIFIED; 9 artifacts |
