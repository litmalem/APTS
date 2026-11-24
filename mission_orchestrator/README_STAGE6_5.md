# Stage 6.5 — Execution Runtime Control

Stage 6.5 menambahkan lifecycle eksekusi asinkron yang tersimpan, heartbeat dari supervisor, cancellation, emergency kill, retry terbatas, dan attempt identity di atas gateway serta fixed adapter Stage 6.4.

Jika acceptance Windows gagal pada `test_retry_rejects_completed_or_possible_io[TIMEOUT]`, gunakan perbaikan tes pada paket ini. Timeout 0,3 detik pada tes lama dapat habis sebelum I/O saat startup worker lambat. Tes terbaru menyinkronkan fase target I/O/DNS dengan deadline fixture; kebijakan runtime tetap sama. Untuk instalasi 6.5 yang sudah aktif, cukup timpa berkas tes Stage 6.5 dan runner regresi. Langkah lengkap ada pada `HOTFIX_STAGE6_5_TIMEOUT_RETRY.md`.

Control: `stage6.5-execution-runtime-control`  
Execution migration: **5**. Mission **53** dan Pentest **16** tetap read-only.  
Predecessor: kontrak Stage 6.4 dengan SHA-256 persis.  
Tahap berikutnya: **6.6 — Artifact & Evidence Capture**.

## Aktivasi Windows

1. Hentikan proses Execution Stage 6.4 di port 8791 dan backup Execution DB setelah proses berhenti.
2. Ekstrak isi ZIP patch langsung ke `D:\mission_orchestrator`.
3. Mission 8780, Pentest 8790, dan GSS 8770 memakai layanan yang sudah terpasang. GSS harus menyediakan execution attestation Stage 6.4. Tidak perlu mengimpor ulang dump SQL.
4. Jalankan runtime dalam PowerShell pertama:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\START_STAGE6_5_EXECUTION.ps1
```

5. Jalankan gate dalam PowerShell kedua:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE6_5_ACCEPTANCE.ps1
```

Gate menjalankan native sandbox, 70 focused tests, 530 continuity tests, dan seluruh 2539 canonical tests. Full regression memakai batch pytest terisolasi dan mencocokkan setiap JUnit testcase dengan inventory canonical. `-RegressionWorkers 1` membatasi gate ke satu proses pytest pada satu waktu; default 4.

CLI: `python run\execution_runtime.py`. Parameter database, GSS, dan credential lease mengikuti runner Stage 6.4. Runner PowerShell juga menerima `-ExecutionDb`, `-MissionDb`, `-PentestDb`, `-GovernanceUrl`, dan `-CredentialLeasesFile`.

Upgrade atomik mendukung Execution DB v1–v4. Satu OS lock mencegah dua runtime Stage 6.5 memakai DB yang sama. Symlink di-resolve dan DB hard-link ditolak. Runner historis menolak membuka DB v5; trigger v5 juga menolak claim RESERVED baru tanpa runtime attempt. Rollback memakai backup setelah runtime dihentikan, bukan penurunan angka migration.

## Lifecycle dan attempt

| State | Makna dan penerus |
|---|---|
| `AUTHORIZED` | Fresh GSS, scope/RoE dan quota lulus; claim adapter, identitas attempt, dan event awal disimpan dalam satu transaksi |
| `DISPATCHED` | Owner lokal mengambil attempt tersebut untuk fixed worker |
| `RUNNING` | Native sandbox siap; broker menjalankan DNS, boundary revalidation, dan primitive yang terdaftar |
| `SUCCEEDED` | Primitive selesai dan resource telah ditutup |
| `FAILED` | Primitive atau gate runtime gagal; metadata kegagalan disimpan |
| `TIMEOUT` | Deadline yang dibatasi source, GSS, authorization, atau runtime terlampaui |
| `CANCELLED` | Instruksi cancel untuk attempt yang persis telah diproses dan resource ditutup |
| `ABORTED` | Kill, revocation/source change, kehilangan supervision, shutdown, atau orphan recovery |

Penghentian dapat terjadi sejak AUTHORIZED atau DISPATCHED, sebelum RUNNING. Kelima state terminal final: heartbeat atau hasil terlambat tidak boleh mengubahnya. Identitas `xattempt-*` deterministik terhadap invocation yang immutable, dengan ordinal 1–3 per execution. Event `xevent-*` membawa sequence, state sebelum/sesudah, parent hash, attempt hash, actor, timestamp UTC, dan data kontrol. Read API memverifikasi index, hash chain, claim, authorization, result, serta predecessor retry dalam satu snapshot SQLite.

Native worker PID/backend dicatat pada event RUNNING. Result adapter dan event terminal dipersist dalam transaksi yang sama sesudah worker/socket ditutup. Concurrency slot dapat dipakai lagi setelah terminal yang tervalidasi; action/network/rate/credential budget tetap mengonsumsi reservasi secara konservatif.

`SUCCEEDED` adalah hasil primitive adapter. Observasi tetap membawa `validation_verdict: UNDETERMINED`, `expected_evidence_confirmed: false`, dan `vulnerability_confirmed: false`. Stage 6.5 belum mengubah Pentest ActionResult, menyelesaikan task/Mission, membuat evidence repository, atau membangun VEP.

## Heartbeat, authority, dan penghentian

Supervisor memeriksa durable stop intent setiap 50 ms, menerbitkan heartbeat setiap 0,5 detik selama RUNNING, dan meminta revalidation GSS berkala setiap 0,5 detik. Heartbeat mengikat identity owner dan authorization tersimpan; ia menyatakan liveness supervisor, bukan kemajuan atau keberhasilan target.

Watchdog terpisah menghentikan resource ketika supervision tidak diperbarui selama 2 detik atau deadline habis. Pemeriksaan source mendeteksi perubahan Mission/Pentest/task; revalidation baru mendeteksi policy/revocation/emergency stop. GSS yang gagal atau tidak kembali dalam 2 detik selama RUNNING memicu ABORTED. Default timeout primitive tetap 5 detik dan seluruh batas Stage 6.4 hanya dapat diperketat.

Cancellation menargetkan satu attempt dengan hash record immutable. Emergency kill menargetkan satu Mission, menghentikan seluruh attempt lokal yang aktif, dan menyimpan latch yang memblokir admission berikutnya untuk Mission itu. Tidak ada reset otomatis atau endpoint reset latch pada tahap ini. Cancel setelah terminal menghasilkan receipt `TERMINAL_NOOP` tanpa mengubah event head. Replay command mengembalikan receipt yang sama.

Runtime menutup broker socket, menghentikan fixed worker, lalu mengonfirmasi terminal. DNS dan query GSS yang sedang menunggu dapat ditinggalkan melalui helper daemon; helper hanya dapat menyelesaikan source/authority lookup, dan tidak memiliki dispatch target. Hasilnya tidak dipakai setelah stop. Watchdog/control polling memiliki interval yang dibatasi; waktu respons nyata juga bergantung pada scheduling OS. Penghentian tidak menarik kembali request yang telah diterima target.

Control API bind hanya loopback. `requested_by` merupakan identitas audit dari operator lokal; remote authentication belum ditambahkan. Caller tidak dapat memberikan state, heartbeat, result, command, executable, adapter, target, quota, atau keputusan ALLOW.

## Retry dan recovery

Retry harus diminta secara eksplisit melalui endpoint retry, merujuk attempt terakhir dan exact terminal head SHA-256. Batas server: 3 attempts per execution. Hanya FAILED/TIMEOUT dengan result tersimpan, resource tertutup, dan `target_network_io_performed: false` yang memenuhi syarat hasil. Gate baru tetap memeriksa GSS, source, rate, duration, lease, concurrency, dan lifetime budget. Kelayakan hasil tidak menjamin admission.

Setiap retry mendapat invocation dan authorization baru serta mengonsumsi budget baru. SUCCEEDED, CANCELLED, ABORTED, timeout/kegagalan setelah kemungkinan I/O, dan hasil yang ambigu tidak dapat diulang. Tidak ada automatic retry, refund, redelivery, atau exactly-once target claim.

Saat restart, OS lock harus berhasil diambil sebelum recovery. Attempt Stage 6.5 nonterminal dari owner sebelumnya ditutup sebagai ABORTED dengan `RECOVERY_ORPHAN_NO_REDISPATCH` dan `target_io_uncertain: true`. Runtime tidak mengarang hasil adapter atau menyambung target kembali. Budget tetap dikonsumsi; attempt tersebut tidak retryable.

Claim RESERVED Stage 6.4 yang tidak memiliki result tidak memiliki lifecycle/control identity Stage 6.5. Claim historis itu dipertahankan dan dikarantina: tidak didispatch, tidak otomatis ditutup/refund, dan tetap mengonsumsi slot. Jumlahnya tersedia sebagai `legacy_quarantined_invocations` pada health. Hal ini mencegah retry terhadap I/O lama yang tidak dapat dibuktikan.

## API

| Method | Endpoint | Fungsi |
|---|---|---|
| GET | `/health` | Migration 5, owner, active attempts, failures, recovery/quarantine count |
| GET | `/api/execution/execution-runtime-contract` | Canonical contract Stage 6.5 |
| POST | `/api/execution/runtime/attempts` | Fresh admission dan start asinkron; HTTP 202 ketika dibuat |
| GET | `/api/execution/runtime/attempts/{xattempt-id}` | Audit lifecycle, event chain, claim, dan result |
| GET | `/api/execution/runtime/attempts?execution_id=exec-...&limit=100` | Daftar attempts untuk satu execution |
| POST | `/api/execution/runtime/retries` | Admission baru dengan exact predecessor terminal |
| POST | `/api/execution/runtime/cancellations` | Cancel satu attempt dengan hash immutable |
| POST | `/api/execution/runtime/emergency-kills` | Kill seluruh attempt aktif satu Mission dan latch durable |
| POST | `/api/execution/gateway/tool-invocations` | Intake lama Stage 6.4 diarahkan ke lifecycle yang sama; response menjadi HTTP 202 dengan attempt |
| GET | API request/authorization/gateway/adapter predecessor | Audit historis tetap tersedia |
| POST | `/api/execution/runtime/heartbeats`, `/results`, `/transitions` | 409; producer hanya server |

GET dan idempotency replay tidak melakukan target I/O atau revalidation. Top-level `execution_authorized` dan `usable_for_dispatch` pada audit selalu false; authorization historis bukan izin baru. Fakta I/O invocation ada pada `invocation.result.semantics` bila result tersedia.

### Memulai satu ExecutionRequest yang memang hendak dieksekusi

```powershell
$base = 'http://127.0.0.1:8791'
$requests = Invoke-RestMethod "$base/api/execution/requests?limit=100"
$req = $requests.requests | Select-Object -First 1
if (-not $req) { throw 'Buat ExecutionRequest dari proposal Stage 5.6 dahulu.' }
$suffix = [guid]::NewGuid().ToString('N')
$start = @{
    schema_version = 'apts-execution-runtime-start-v1'
    invocation_request_id = "toolreq-$suffix"
    idempotency_key = "idem-runtime-$suffix"
    execution_id = $req.execution_id
    envelope_sha256 = $req.envelope.integrity.canonical_sha256
    requested_by = 'operator-local'
}
$accepted = Invoke-RestMethod -Method Post -Uri "$base/api/execution/runtime/attempts" `
    -ContentType 'application/json' -Body ($start | ConvertTo-Json -Depth 20)
$attemptId = $accepted.attempt_id
$live = Invoke-RestMethod "$base/api/execution/runtime/attempts/$attemptId"
$live.state
# Verifikasi read-only untuk attempt yang sudah ada:
.\STAGE6_5_ACCEPTANCE.ps1 -LiveAttemptId $attemptId
```

HTTP 202 mengonfirmasi admission, bukan primitive sukses. Baca state/result untuk hasil akhir.

### Cancel atau emergency kill

```powershell
$suffix = [guid]::NewGuid().ToString('N')
$cancel = @{
    schema_version = 'apts-execution-runtime-cancel-v1'
    command_request_id = "rtcmd-$suffix"
    idempotency_key = "idem-cancel-$suffix"
    requested_by = 'operator-local'
    reason = 'Operator requested stop'
    attempt_id = $attemptId
    attempt_sha256 = $accepted.record.integrity.canonical_sha256
}
Invoke-RestMethod -Method Post -Uri "$base/api/execution/runtime/cancellations" `
    -ContentType 'application/json' -Body ($cancel | ConvertTo-Json -Depth 20)
# Tunggu/baca state terminal; receipt belum merupakan konfirmasi penutupan resource.
Invoke-RestMethod "$base/api/execution/runtime/attempts/$attemptId"

# Emergency kill menggunakan Mission yang persis dari attempt, dengan latch durable.
$suffix = [guid]::NewGuid().ToString('N')
$kill = @{
    schema_version = 'apts-execution-runtime-kill-v1'
    command_request_id = "rtcmd-$suffix"
    idempotency_key = "idem-kill-$suffix"
    requested_by = 'operator-local'
    reason = 'Emergency stop'
    mission_id = $accepted.record.mission_id
}
Invoke-RestMethod -Method Post -Uri "$base/api/execution/runtime/emergency-kills" `
    -ContentType 'application/json' -Body ($kill | ConvertTo-Json -Depth 20)
```

### Retry kegagalan sebelum target I/O

```powershell
$last = Invoke-RestMethod "$base/api/execution/runtime/attempts/$attemptId"
if (-not $last.retry_eligible_by_result) { throw 'Hasil attempt tidak memenuhi policy retry.' }
$suffix = [guid]::NewGuid().ToString('N')
$retry = @{
    schema_version = 'apts-execution-runtime-retry-v1'
    invocation_request_id = "toolreq-$suffix"
    idempotency_key = "idem-retry-$suffix"
    execution_id = $last.record.execution_id
    envelope_sha256 = $last.record.runtime_intake.envelope_sha256
    requested_by = 'operator-local'
    retry_of_attempt_id = $last.attempt_id
    expected_head_sha256 = $last.head_sha256
}
Invoke-RestMethod -Method Post -Uri "$base/api/execution/runtime/retries" `
    -ContentType 'application/json' -Body ($retry | ConvertTo-Json -Depth 20)
```

## Bukti dan batas validasi

Inventory: **2539 = 2469 baseline + 70 Stage 6.5**. Focused: **70 PASS**. Continuity Stage 5.9–6.5: **530 PASS**. Detail full regression, exact per-test coverage, dan snapshot source terdapat pada `evidence/stage6_5/regression_summary.json`, JUnit, serta `REGRESSION_EVIDENCE_STAGE6_5.txt`.

Proof awal menggunakan schema/store Mission dan Pentest nyata dalam fixture terisolasi, real Governance HTTP transport dengan test authority, native Linux seccomp/rlimits, target loopback, dan proses runtime yang benar-benar dihentikan untuk menguji crash recovery. Tidak ada otorisasi atau target action terhadap Mission pengguna selama build. Windows/PowerShell dan Windows Job Object harus diverifikasi dengan acceptance di host Windows.

Verifikasi sumber GSS telah dilengkapi memakai unggahan `aptsGS(4).zip`: **58 tes GSS PASS**, **22 skenario lintas layanan PASS**, dan **70 tes runtime PASS ulang**. Proof tambahan memakai route FastAPI, `GovernanceService`, risk/policy checks, audit, dan outbox GSS yang sebenarnya melalui HTTP loopback. Repository GSS serta clock memakai fixture terisolasi; worker native dan socket target benar-benar dijalankan. Admission DENY/REVIEW, revalidation sebelum connect, pencabutan izin saat RUNNING, emergency stop GSS, cancellation, kill latch lokal, retry sebelum I/O, dan HTTP failure diperiksa. Decision hash serta attestation audit/outbox juga diverifikasi.

Seluruh 78 berkas non-cache GSS tetap identik dengan unggahan; snapshot core Mission berisi 375 berkas dan cocok dengan source pada full regression 2539 yang disertakan. Layanan runtime maupun GSS tidak memerlukan perubahan tambahan. Hotfix berikutnya mengubah dua tes timeout dan pelaporan runner; full regression diverifikasi ulang terhadap snapshot terbaru. Bukti dan batas cakupan terdapat pada `evidence/stage6_5/gss_compatibility_summary.json`, `gss_source_snapshot.json`, `retry_timeout_fix_summary.json`, serta log/JUnit pendamping. Suite tambahan ini terpisah dari inventory canonical 2539. Production MySQL dan pengiriman outbox ke VulnDesk aktif belum dijalankan; acceptance Windows memakai tes yang diperbaiki tetap diperlukan.

Untuk mengulang proof sumber dari root Mission, gunakan environment Python yang menyediakan dependensi backend GSS dan set lokasi source GSS yang sudah diekstrak:

```powershell
$env:APTS_STAGE6_5_GSS_SOURCE = 'D:\aptsGSS'
python -m pytest evidence\stage6_5\gss_runtime_source_proof.py -q
```

ZIP VulnDesk serta dump SQL yang tersedia diperiksa sebagai konteks boundary; patch ini mengubah Mission/Execution. GSS aktif tetap harus lulus protocol preflight dan revalidation runtime pada acceptance host.
