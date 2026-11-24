# Stage 6.3 — Controlled Execution Gateway

Stage 6.3 menambahkan **gateway admission terpusat** untuk ExecutionRequest Stage 6.1. Setiap submission baru memperoleh revalidation eksternal Stage 6.2, memeriksa constraint GSS, lalu menyimpan admission dan reservasi budget secara atomik. Specialist tetap hanya menghasilkan proposal dan tidak memperoleh raw target/tool access.

Control: `stage6.3-controlled-execution-gateway`  
Predecessor: `stage6.2-authoritative-execution-authorization`, terikat hash kontrak persis.  
Next: **6.4 — Authorized Tool Adapters & Sandboxing**.

Gateway ini mengimplementasikan boundary admission Tahap 6.3. Tidak ada adapter produksi yang terdaftar. Receipt `ADMITTED_AWAITING_ADAPTER` bukan bearer permit dan tidak dapat digunakan untuk menjalankan target. `execution_authorized`, `usable_for_dispatch`, dispatch/tool/target/result/evidence flags selalu false pada response gateway. Adapter Tahap 6.4 wajib melakukan fresh revalidation lagi pada boundary side effect dan menerapkan seluruh constraint runtime.

## Alur dan otoritas

1. Caller mengirim `submission_id`, idempotency key, execution ID dan hash envelope tersimpan. Caller tidak dapat memasukkan PolicyDecision/ALLOW, authorization ID lama, target, parameter, command, adapter, endpoint GSS atau budget.
2. Gateway memverifikasi request immutable serta konteks Mission/Pentest terkini melalui source verifier Stage 6.2. Mission wajib RUNNING/nonterminal; semua scope, RoE, risk, target, technique dan source lineage tetap berlaku.
3. Server membangkitkan identitas revalidation dan nonce baru. Client Stage 6.2 meminta PolicyDecision authoritative ke endpoint GSS terkonfigurasi. Delapan check, binding request/envelope/context, policy version, expiry, revocation, emergency stop dan human approval tetap wajib. Tidak ada local/default ALLOW.
4. Semua `PolicyDecision.constraints` dibaca. Constraint yang tidak dikenal atau berbentuk salah memblokir admission; empty allowlist menolak semua. Constraint diterapkan sebagai pembatas tambahan dan tidak dapat melonggarkan batas sumber.
5. Setelah memperoleh write lock Execution DB, gateway membaca ulang sumber, membandingkan current context, menjalankan local checks dan memeriksa validity/expiry. Budget dan duplikasi dihitung dari audit yang diverifikasi, dalam transaksi yang sama dengan commit receipt.
6. Admission yang diterima mereservasi satu unit action pada Mission, Pentest dan local task. Satu execution hanya dapat memperoleh satu admission. Authorization hanya dapat diikat ke satu submission.
7. Receipt immutable menyimpan chain gateway → authorization → evaluation → request → source binding, termasuk hash, actor, status, reason codes, policy constraint, budget sebelum admission dan timestamp.

Konteks source berbeda database dan tidak dikunci atomik dengan Execution DB. Recheck mempersempit race pada admission, tetapi receipt tidak menjamin tidak ada perubahan/revocation setelah commit. Tidak ada side effect target pada tahap ini; fresh GSS dan source revalidation sebelum target dispatch pada 6.4 tetap wajib.

## Central policy

| Constraint GSS | Enforcement admission |
|---|---|
| `max_actions` | Integer >= 0; ceiling konservatif pada total admission Mission, dikombinasikan dengan batas sumber |
| `allowed_action_classes`, `prohibited_action_classes` | Action exact dari request; larangan menang |
| `allowed_techniques`, `prohibited_techniques` | Technique exact; empty allowed list menolak semua |
| `allowed_targets`, `excluded_targets` | Daftar exact `{target_type,target_value}`, tanpa target override atau wildcard |
| `risk_threshold`, `impact_limit` | Impact request tidak boleh melebihi pembatas tambahan |
| `allowed_time_window` | `{start_at,end_at}`, timezone eksplisit; end exclusive |
| `requires_human_approval` | Boolean eksplisit; approval harus verified oleh GSS |
| `credential_usage_allowed`, `persistence_allowed`, `destructive_actions_allowed` | Boolean eksplisit; false membatasi action terkait |
| Field lainnya, termasuk timeout/rate/sandbox/credential/resource controls | `BLOCKED_CONSTRAINTS`; dukungan enforcement harus ditambahkan pada tahap adapter |

Constraint runtime Mission/Pentest/task yang sudah ada, termasuk max duration, resource budget, data handling dan maximum concurrency, dipertahankan dalam sealed `authorization_record.evaluation.current_context`. Gateway tidak mengklaim telah menjalankan kontrol runtime tersebut. Tahap 6.4 wajib menerapkannya sebelum tool/target I/O.

Budget admission bersifat **reservasi lifetime konservatif**, bukan jumlah action target yang telah berjalan. Tidak ada release/reset otomatis, TTL refund atau runtime completion di 6.3. Deny/review/blocked receipt tidak memakan budget. Identitas key baru tidak dapat mengulang admission untuk execution yang sama; retry/attempt lifecycle dan release terkontrol mengikuti Tahap 6.5. Budget tidak menyatakan penggunaan dari sistem eksternal di luar gateway ini; batas lintas subsistem tetap tanggung jawab GSS.

| Status receipt | Makna |
|---|---|
| `ADMITTED_AWAITING_ADAPTER` | Admission diterima dan budget direservasi; target dispatch menunggu 6.4 |
| `DENIED` | Hard deny, failed authoritative check, revocation atau emergency stop |
| `REVIEW_REQUIRED` | Review/pending approval; tidak ada admission |
| `BLOCKED_CONSTRAINTS` | Restriction, constraint unsupported atau malformed |
| `BLOCKED_BUDGET` | Salah satu ceiling admission Mission/Pentest/task habis |
| `BLOCKED_DUPLICATE` | Execution sudah memiliki admission sebelumnya |

DENY mendahului REVIEW dan semua status lain. HTTP 201 berarti record baru tersimpan; periksa `gateway_admitted` dan `record.status`. HTTP sukses tidak memberi izin menjalankan target.

## Penyimpanan, concurrency dan recovery

Execution database upgrade **1/2 → 3** dijalankan atomik. Request/envelope dan authorization lama dipertahankan byte-for-byte. Table baru `execution_gateway_submissions` append-only dengan UNIQUE submission/idempotency/authorization identities, foreign keys, sequence audit dan partial unique index satu admission per execution. Future/foreign/incomplete repository ditolak tanpa downgrade. Mission migration **53** dan Pentest migration **16** tetap read-only; ketiga path/symlink/hardlink database wajib berbeda.

Replay dengan intake sama dan GET/list hanya mengembalikan audit: `created=false`, `gateway_admitted=false`, `authorization_current=false`, `execution_authorized=false`, `usable_for_dispatch=false`. Tidak ada query GSS atau reservasi ulang. Replay historis masih tersedia saat konteks mission kemudian berubah, karena ia tidak melakukan admission baru.

Concurrent duplicate dalam satu service menghasilkan satu evaluation dan receipt. Competing processes dapat mengirim beberapa query GSS, tetapi transaction/unique constraints mencegah admission ganda atau oversubscription budget. Tidak ada klaim exactly-once target execution. Crash setelah authorization sebelum commit meninggalkan authorization audit; retry uncommitted submission memperoleh nonce/revalidation baru, tanpa menggunakan cached ALLOW.

## Aktivasi Windows

Ekstrak patch ke `D:\mission_orchestrator`, hentikan proses Execution lama pada port 8791, lalu jalankan:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\START_STAGE6_3_EXECUTION.ps1
```

Dari jendela PowerShell lain:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE6_3_ACCEPTANCE.ps1
```

CLI baru `python run\execution_gateway.py --host 127.0.0.1 --port 8791` menerima konfigurasi `--execution-db`, `--pentest-db`, `--mission-db`, `--governance-url`, `--governance-timeout`, dan environment Stage 6.2 yang sama. Default port Execution 8791, Mission 8780, Pentest 8790, GSS 8770. Gateway control API hanya menerima loopback bind karena baseline belum memiliki remote authentication. Runner lama tetap sebagai baseline historis dan tidak dapat membuka database v3.

## API

| Method | Endpoint | Hasil |
|---|---|---|
| GET | `/health` | Runtime 6.3, migration 3, gateway/adapter boundary flags |
| GET | `/api/execution/execution-gateway-contract` | Canonical contract 6.3 |
| GET | `/api/contracts/controlled-execution-gateway` | Alias contract |
| POST | `/api/execution/gateway/submissions` | 201 receipt baru; 200 historical replay |
| GET | `/api/execution/gateway/submissions/{gateway_id}` | Audit-only receipt dengan binding dan budget verification |
| GET | `/api/execution/gateway/submissions?execution_id=exec-...&limit=100` | Audit list; limit 1–500 |
| POST/GET | `/api/execution/requests...`, `/api/execution/authorizations...` | Kontrak dan audit predecessor tetap tersedia |
| POST | `/api/execution/dispatches`, `/results`, `/tool-invocations` | HTTP 409; authorized adapter 6.4 diperlukan |

Contoh dengan request tersimpan nyata:

```powershell
$requests = Invoke-RestMethod 'http://127.0.0.1:8791/api/execution/requests?limit=100'
$req = $requests.requests | Select-Object -First 1
if (-not $req) { throw 'Buat ExecutionRequest Stage 6.1 dari proposal tersimpan terlebih dahulu.' }
$suffix = [guid]::NewGuid().ToString('N')
$body = @{
    schema_version = 'apts-execution-gateway-intake-v1'
    submission_id = "gwreq-$suffix"
    idempotency_key = "idem-gateway-$suffix"
    execution_id = $req.execution_id
    envelope_sha256 = $req.envelope.integrity.canonical_sha256
    requested_by = 'operator-local'
} | ConvertTo-Json -Depth 10
$gate = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8791/api/execution/gateway/submissions' `
    -ContentType 'application/json' -Body $body
$gate.gateway_id
$gate.gateway_admitted
$gate.record.status
# Verifikasi captured live receipt secara read-only:
.\STAGE6_3_ACCEPTANCE.ps1 -LiveGatewayId $gate.gateway_id
```

400: intake invalid/authority override. 404: request tidak ditemukan. 409: integrity, source restriction, expired snapshot atau idempotency conflict. 503: source/GSS/storage unavailable atau GSS protocol invalid. Duplicate JSON, transfer encoding, payload oversized dan query override gateway ditolak.

## Validasi dan batas bukti

Inventory **2340 tests** = baseline 2229 + **111 focused Stage 6.3**. Coverage mencakup fresh GSS, raw-path isolation, constraints, source/expiry recheck, atomic budget, competing processes, append-only/tamper checks, migration, restart dan crash retry. Full historical regression dan log disertakan dalam `evidence/stage6_3`.

Source aptsGSS dan runtime PowerShell tidak tersedia dalam build ini. Tidak ada klaim live production GSS compatibility atau Windows acceptance telah dijalankan. GSS wajib menyediakan protocol `apts-gss-execution-revalidation-v1` sesuai Stage 6.2; response lama gagal closed. Acceptance tanpa `-LiveGatewayId` membuktikan source/runtime/tests dan GSS health, tetapi belum captured live gateway admission.
