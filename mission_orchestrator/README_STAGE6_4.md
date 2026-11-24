# Stage 6.4 — Authorized Tool Adapters & Sandboxing

Stage 6.4 membuka eksekusi primitive yang terdaftar di server setelah revalidation eksternal, reservasi atomik, dan pembuktian kesiapan sandbox. Specialist tetap hanya menghasilkan proposal. Command, target, adapter, payload, policy decision, credential, dan quota tidak dapat dimasukkan lewat intake adapter.

Control: `stage6.4-authorized-tool-adapters-sandboxing`  
Predecessor: kontrak Stage 6.3 dengan SHA-256 persis; kontrak dan kode Stage 3–6.3 dipertahankan.  
Execution migration: **4**. Mission **53**, Pentest **16**, keduanya read-only.  
Tahap berikutnya: **6.5 — Execution Runtime Control**.

## Adapter yang tersedia

| Keluarga | Adapter | Capability / technique | Operasi |
|---|---|---|---|
| Scanner | `scanner.tcp-connect.v1` | `reconnaissance` / `TCP_CONNECT_SCAN` | Satu koneksi TCP |
| Network Tool | `network.tcp-banner.v1` | `enumeration` / `TCP_BANNER_READ` | Satu pembacaan banner TCP terbatas |
| Web Testing | `web.http-head.v1` | `validation` / `HTTP_HEADER_INSPECTION` | HEAD HTTP/HTTPS |
| Exploit Validation | `validation.version-configuration.v1` | `exploitation` / `SAFE_VERSION_CONFIGURATION_CONFIRMATION` | HEAD untuk observasi metadata; tidak menyatakan exploitability |
| Evidence Collector | `evidence.http-metadata.v1` | `validation` / `HTTP_RESPONSE_METADATA` | Metadata respons dan digest |

Selection menggunakan kombinasi capability, action class, technique, dan target type yang persis. Action impact maksimum adapter adalah LOW. Tidak ada dynamic plugin loading, arbitrary binary, shell, payload exploitation, atau credential dumping.

Intake Stage 6.1 saat ini berasal dari proposal Stage 5.6 dan membawa capability `exploitation`; karena itu trajectory produksi yang sudah tersedia memakai adapter konfirmasi versi/konfigurasi. Empat adapter lain sudah memiliki implementasi dan pengujian I/O, tetapi tidak mengubah intake/source lineage Stage 6.1 untuk mengarang proposal specialist baru. Proposal dengan teknik lain gagal closed.

Target URL membawa port/path yang persis dan hanya mendukung HTTP/HTTPS. Target IP/HOST/DOMAIN memakai port default registry, saat ini 80. Runtime tidak menarik port baru dari caller atau menganggap port observasi upstream sebagai izin tambahan.

## Jalur eksekusi

1. `POST /api/execution/gateway/tool-invocations` hanya menerima referensi ExecutionRequest immutable dan hash envelope.
2. Server membaca ulang Mission/Pentest, memverifikasi lineage, dan meminta revalidation GSS baru melalui gate Stage 6.2.
3. Dalam transaksi Execution DB, server memeriksa constraint, budget, duplicate, rate, concurrency, credential consumption, dan duration. Claim disimpan sebelum worker atau target digunakan.
4. Fixed worker dijalankan dalam direktori sementara dengan environment minimal dan kuota OS. Parent menunggu readiness sebelum mengakses target.
5. Gateway memvalidasi target, seluruh jawaban DNS, dan scope IP; satu alamat dipin tanpa resolve ulang saat connect.
6. Tepat sebelum connect, server meminta GSS baru lagi, membaca ulang source, memeriksa expiry, mengevaluasi policy, dan memeriksa IP yang dipin terhadap scope terkini. Policy runtime yang berubah memblokir execution.
7. Broker membuka satu endpoint yang disetujui. Worker hanya menerima bytes observasi terbatas melalui stdin untuk parsing; worker tidak mengakses target.
8. Worker/socket ditutup sebelum result append-only dipersist. Result diikat ke claim, dua authorization records, execution/task/pentest/mission, adapter registry, dan target pin.

Stage 6.3 receipts tetap dapat dibaca. Receipt lama hanya dapat menyumbang reservasi budget yang sudah ada; receipt bukan authorization untuk menjalankan target. Admission baru Stage 6.4 memakai jalur adapter. Trigger migration 4 menutup INSERT gateway Stage 6.3 agar proses lama tidak menambah reservasi yang mengabaikan budget baru.

## Kontrol yang diterapkan

| Kontrol | Enforcement |
|---|---|
| Sandbox | Fixed parser process; Linux seccomp + rlimits; Windows Job Object sebelum worker menerima input |
| Timeout | Deadline monotonic pada DNS, connect, TLS, send/read, parsing, dan exit; min dari batas sumber, GSS, authorization expiry, time window, dan lease expiry |
| Rate limit | Rolling window konservatif per Mission, dihitung dari reservasi durable; tidak ada sleep/retry otomatis |
| Target boundary | Target immutable; seluruh resolved IP harus diizinkan Mission/Pentest/task; excluded dan alamat unspecified/multicast/link-local ditolak; pin diperiksa lagi sebelum I/O |
| Credential lease | Hanya lease server yang diminta constraint GSS, diizinkan semua RoE, terikat mission/execution/target/adapter, belum revoked/expired, dan single-use; hanya dikirim lewat TLS |
| Resource quota | CPU/memory worker, batas output, total application request/response bytes per invocation, jumlah network request lifetime, concurrency dan action budget |
| Command allowlist | Hanya `TCP_CONNECT`, `TCP_BANNER`, `HTTP_HEAD` yang tersedia dalam registry; caller tidak dapat memberikan executable |
| Technique allowlist | Matching registry persis + restriction source dan GSS; empty GSS allowlist menolak semua |
| Source max duration | Membatasi waktu per invocation sekaligus lifetime Mission/Pentest/task sejak reservasi/admission pertama yang tercatat |
| Data handling | Tidak menyimpan raw headers/body/banner, Set-Cookie, token, environment, stdout/stderr arbitrer, atau credential secret |

Default: timeout 5 detik; CPU 2 detik; memory 128 MiB; output 16 KiB; application network bytes 16 KiB; 10 reservasi network/Mission; concurrency 1; rate 1 reservasi/detik. Semua restriction tambahan hanya memperketat default dan sumber. Field resource/data handling/stop condition yang tidak didukung diblokir dengan reason code, tidak diabaikan.

GSS runtime fields yang didukung: `timeout`, `max_duration`, `rate_limit:{requests,window_seconds}`, `maximum_concurrency`, `sandbox:"FIXED_WORKER_BROKER_V1"`, `credentials_lease:{lease_id,required:true}`, `resource_budget`, `command_allowlist`, `technique_allowlist`, dan `data_handling_policy`. Field admission Stage 6.3 tetap diperiksa. `resource_budget` mendukung `cpu_seconds`, `memory_mb`, `max_output_bytes`, `max_network_bytes`, dan `max_network_requests`. Data handling hanya mendukung `retain_sensitive_output`; output sensitif tetap tidak disimpan.

DNS hostname harus memiliki scope IP/CIDR yang eksplisit selain identitas hostname. Hostname tanpa izin alamat resolved tidak menghasilkan koneksi target. Proxy environment diabaikan dan redirect tidak diikuti. TLS memverifikasi sertifikat/hostname dengan trust store sistem.

## Batas sandbox dan bukti

Sandbox ini ditujukan untuk fixed worker yang ada dalam patch. Linux memblokir syscall file/network/process yang relevan setelah import stdlib; Windows Job Object menerapkan CPU, memory, active-process, dan kill-on-close. Windows backend tidak diklaim sebagai containment untuk kode Python/binary yang tidak dipercaya. Tidak tersedia API untuk menjalankan kode tersebut. Broker I/O merupakan bagian trusted gateway dengan kuota bytes dan target pin, bukan worker dengan raw network permission.

Metadata `SUCCEEDED` berarti primitive adapter selesai. `validation_verdict` tetap `UNDETERMINED`, `expected_evidence_confirmed=false`, dan `vulnerability_confirmed=false`. Header/version observasi saja tidak membuktikan kerentanan atau seluruh configuration state. Result ini belum menjadi Pentest ActionResult, evidence repository Stage 6.6, atau VEP Stage 6.7.

Claim `RESERVED` tanpa result setelah crash memakan budget dan slot concurrency. Replay/GET mengembalikan audit dan tidak menjalankan target lagi. Key baru untuk execution yang sudah RESERVED diblokir. Tidak ada automatic retry, refund, restart redispatch, atau klaim exactly-once target side effects. Recovery, heartbeat/cancellation/kill berjalan merupakan bagian Stage 6.5. Revocation global saat I/O sudah berlangsung belum merupakan runtime kill Stage 6.5; setiap connect tetap memerlukan fresh authoritative check.

Budget bersifat konservatif. Reservasi yang gagal setelah commit tetap mengonsumsi action/network/lease budget. Budget per Mission tidak menghitung penggunaan target dari sistem lain di luar gateway; enforcement lintas sistem berada pada GSS. Source DB dan GSS tidak dikunci dalam satu transaksi global dengan Execution DB.

## Aktivasi Windows

1. Ekstrak **Mission patch** ke `D:\mission_orchestrator`.
2. Ekstrak **aptsGSS patch** ke root proyek aptsGSS yang berisi `app\main.py`; restart GSS memakai runner proyek yang biasa digunakan. Tidak perlu mengimpor ulang SQL dump.
3. Hentikan proses Execution Stage 6.3 pada port 8791. Simpan backup Execution DB sebelum upgrade; runner historis menolak membuka database v4.
4. Mission 8780, Pentest 8790, dan GSS 8770 tetap menggunakan layanan masing-masing. Jalankan Execution baru:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\START_STAGE6_4_EXECUTION.ps1
```

Dari PowerShell lain:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE6_4_ACCEPTANCE.ps1
```

Jalankan `STAGE6_4_GSS_ACCEPTANCE.ps1` dari root proyek GSS untuk memeriksa 58 tes dan health protocol GSS. Script Mission acceptance menjalankan native sandbox probe pada host Windows sebelum menyatakan PASS. Linux memerlukan `libseccomp.so.2`; bila backend gagal, target execution diblokir.

CLI: `python run\execution_adapters.py`. Konfigurasi database/GSS mengikuti runner Stage 6.2–6.3: `--execution-db`, `--mission-db`, `--pentest-db`, `--governance-url`, `--governance-timeout`. API bind hanya loopback karena control plane lokal belum memiliki remote authentication.

## API dan submission nyata

| Method | Endpoint | Makna |
|---|---|---|
| GET | `/health` | Runtime 6.4, migration 4, registry/sandbox capability |
| GET | `/api/execution/tool-adapters-contract` | Canonical contract 6.4 |
| POST | `/api/execution/gateway/tool-invocations` | Reservasi, revalidation boundary, bounded primitive invocation |
| GET | `/api/execution/gateway/tool-invocations/{toolinv-id}` | Historical claim/result dengan integrity verification |
| GET | `/api/execution/gateway/tool-invocations?execution_id=exec-...&limit=100` | Historical list |
| GET / replay | Kontrak, request, authorization, gateway predecessor | Audit predecessor tetap tersedia |
| POST | `/api/execution/dispatches`, `/results`, `/tool-invocations` | 409; raw execution route tetap tertutup |

POST dapat membuat claim BLOCKED atau result FAILED/TIMEOUT/BLOCKED; HTTP 201 bukan bukti primitive berhasil. Periksa `record.status` dan `result.status`.

Contoh berikut melakukan primitive nyata setelah GSS mengizinkan request dan target memenuhi scope; gunakan hanya request yang memang hendak dieksekusi:

```powershell
$requests = Invoke-RestMethod 'http://127.0.0.1:8791/api/execution/requests?limit=100'
$req = $requests.requests | Select-Object -First 1
if (-not $req) { throw 'Buat ExecutionRequest dari proposal Stage 5.6 terlebih dahulu.' }
$suffix = [guid]::NewGuid().ToString('N')
$body = @{
    schema_version = 'apts-execution-adapter-intake-v1'
    invocation_request_id = "toolreq-$suffix"
    idempotency_key = "idem-tool-$suffix"
    execution_id = $req.execution_id
    envelope_sha256 = $req.envelope.integrity.canonical_sha256
    requested_by = 'operator-local'
} | ConvertTo-Json -Depth 10
$result = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8791/api/execution/gateway/tool-invocations' `
    -ContentType 'application/json' -Body $body
$result.record.status
$result.result.status
# Read-only verification of this stored invocation:
.\STAGE6_4_ACCEPTANCE.ps1 -LiveInvocationId $result.invocation_id
```

## Credential lease configuration

Optional `--credential-leases-file` adalah file JSON milik operator berisi daftar lease dengan field `lease_id`, `mission_id`, `execution_id`, `target`, `adapter_id`, `issued_at`, `expires_at`, `secret_environment`, dan boolean `revoked`. Environment secret harus bernama `APTS_CRED_...`; secret tidak berada dalam JSON, request, worker environment, atau audit. Scope lease harus persis. File dibaca ulang pada boundary agar revocation/expiry berlaku. GSS harus meminta lease tersebut serta `credential_usage_allowed:true`, dan seluruh RoE harus mengizinkan credential use. Lease dikonsumsi sekali secara durable. Patch tidak membuat credential riil atau mengubah akun target; pencabutan token eksternal merupakan cleanup Stage 6.8.

## Validasi

Canonical inventory: **2469 = baseline 2340 + 129 focused Stage 6.4**. Continuity Stage 5.9 → 6.4: **460** tes. GSS: **58 = baseline 26 + 32** tes attestation. Hasil dan cakupan run dicatat di `REGRESSION_EVIDENCE_STAGE6_4.txt` dan `evidence/stage6_4`.

Source final lulus seluruh 2469 tes dalam 64 kelompok proses pytest terisolasi, dengan nol failure/error/skip; bukan satu invocation pytest tanpa jeda. JUnit gabungan memuat setiap testcase canonical sekali. Hash 362 berkas source snapshot tetap cocok. Overlay dari ZIP pada salinan bersih baseline juga lulus kompilasi, inventory 2469/58, sandbox native, 129 focused Mission, dan seluruh 58 tes GSS.

Cross-plane proof menggunakan kode GovernanceService yang diperbarui, real Governance HTTP client, real schema/stores Mission/Pentest, native worker, dan target loopback. Repository GSS pada proof ini merupakan isolated test double; production MySQL dan mission pengguna tidak diotorisasi oleh proses build. PowerShell/Windows Job Object belum dijalankan dalam Linux build; acceptance Windows merupakan gate host deployment.

Referensi implementasi native: [Python resource](https://docs.python.org/3/library/resource.html), [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects), dan [Job memory/CPU limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information). Sandbox tidak mengandalkan Python audit hook sebagai containment.
