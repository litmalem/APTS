# Stage 6.2 — Authoritative Execution Authorization

Stage 6.2 mengimplementasikan execution authorization gate sesuai roadmap. Gate membaca request Stage 6.1 yang immutable, memeriksa konteks Mission/Pentest terkini, lalu meminta keputusan **ALLOW / DENY / REVIEW** dari **aptsGSS**. Gateway dan tool adapter merupakan tahap berikutnya.

Control: `stage6.2-authoritative-execution-authorization`  
Predecessor: `stage6.1-canonical-execution-request-contract`  
Next: **6.3 — Controlled Execution Gateway**

## Otoritas dan alur

1. Klien mengirim identitas revalidation, execution ID, dan hash envelope yang telah tersimpan. Klien tidak dapat memasukkan PolicyDecision, target, parameter, endpoint Governance, approval, atau hasil pemeriksaan.
2. Gate membaca Mission state, scope head, governance binding head dan artefak canonical dalam satu transaksi SQLite read-only. Mission harus `RUNNING`, nonterminal, dengan scope/binding yang masih konsisten.
3. Proposal Stage 5.6 dan seluruh lineage-nya dibaca ulang melalui verifier Stage 6.1 dalam transaksi Pentest read-only. Envelope harus tetap identik; orchestration harus `ACTIVE` atau `COMPLETED`.
4. Gate menerapkan scope/exclusion, network range, RoE/action, time window, risk/impact, dan technique dari **current Mission**, **bound Pentest boundary**, serta **local task**. Kegagalan lokal menghasilkan HTTP 409 tanpa menghubungi GSS dan tanpa membuat PolicyDecision lokal.
5. Evaluation mengikat execution request, envelope, sumber, current context, actor, timestamp dan nonce baru. Request dikirim ke endpoint aptsGSS yang dikonfigurasi operator.
6. GSS harus memberikan bukti fresh revalidation atas delapan pemeriksaan. Gate memeriksa korelasi, policy downgrade, waktu berlaku, freshness, revocation, emergency stop dan human approval.
7. Setelah respons, konteks Mission/Pentest dibaca ulang dan dibandingkan. Perubahan state/version, scope/binding, proposal atau orchestration membatalkan authorization. Expiry diperiksa kembali sebelum persist.
8. Keputusan dan evaluasinya disimpan sebagai artefak `eauth-*` append-only, terpisah dari request. Gate tidak memodifikasi database sumber.

## Pemeriksaan dan keputusan

| Pemeriksaan | Kontrak |
|---|---|
| SCOPE | Scope misi terkini dan batas Pentest/task harus mengizinkan action |
| ROE | Action, waktu, larangan dan persyaratan approval tidak boleh dilonggarkan |
| POLICY | aptsGSS mengevaluasi policy aktif; policy version tidak boleh mundur dari referensi request |
| RISK | Estimasi impact dibatasi lokal; GSS memeriksa risk dan batas dinamis authoritative |
| EXPIRY | Explicit timezone; `valid_from <= now < valid_until`; freshness proof terikat evaluation baru |
| REVOCATION | GSS memeriksa current revocation/emergency stop dan mengembalikan flag eksplisit |
| TARGET | Target persis di dalam request/envelope/hash; allowlist, exclusions dan CIDR diverifikasi |
| TECHNIQUE | Technique persis terikat evaluation, diperiksa terhadap batas lokal dan policy GSS |

Hard deny selalu menang: `DENY`, satu `FAIL`, revoked atau emergency stop menghasilkan **DENY**. Jika tidak ada deny, `REVIEW`, satu check `REVIEW`, pending human approval, atau review requirement tanpa verified approval menghasilkan **REVIEW**. **ALLOW** hanya berlaku bila seluruh pemeriksaan PASS dan tidak ada blocker.

TTL lokal maksimum **120 detik**, dipotong lebih awal jika GSS expiry lebih pendek. Toleransi clock skew pada `checked_at` adalah **5 detik**; validity expiry tidak mendapat toleransi. PolicyDecision ID historis dari request atau ID yang pernah tersimpan untuk attempt lain ditolak.

Keputusan adalah snapshot pada saat evaluasi. Ia tidak menjamin tidak ada revocation setelah evaluasi. Stage 6.3 wajib melakukan fresh revalidation pada boundary side effect dan menerapkan seluruh `PolicyDecision.constraints`; Stage 6.2 tidak mengkonsumsi permit atau menjalankan target.

## Kontrak aptsGSS yang diperlukan

**Source aptsGSS tidak tersedia di arsip Mission ini.** Paket mengimplementasikan client dan gate, serta menerbitkan kontrak berikut untuk integrasi aptsGSS. Tidak ada fake/default ALLOW pada produksi.

Endpoint tetap `POST /api/governance/authorization/evaluate`, dengan response envelope `{"status":"completed","policy_decision":{...}}`. Evaluation lengkap dikirim pada `context.execution_authorization_evaluation`. Bentuk PolicyDecision yang telah digunakan Mission Orchestrator dipertahankan, dengan field tambahan wajib `execution_revalidation` ber-schema **`apts-gss-execution-revalidation-v1`**.

GSS harus benar-benar membaca scope, RoE, policy, risk, expiry, revocation/emergency stop, target dan technique authoritative terkini. GSS tidak boleh sekadar menyalin hasil local check, menetapkan PASS konstan, atau menggunakan eligibility/reference lama sebagai izin. Resource budgets, stop signals, concurrency, rate limits dan restrictions dinamis yang tidak dapat dibuktikan dari request deskriptif harus diputuskan GSS. Human approval hanya dinyatakan verified setelah approval sah yang terikat action/request, policy dan scope.

Attestation mengembalikan:

```text
schema_version = apts-gss-execution-revalidation-v1
evaluation_sha256 = evaluation.integrity.canonical_sha256
nonce = evaluation.nonce
execution_id = evaluation.execution_request.execution_id
request_sha256 = evaluation.execution_request.integrity.canonical_sha256
envelope_sha256 = evaluation.envelope_sha256
context_sha256 = SHA256(canonical UTF8_SORTED_JSON_V1 evaluation.current_context)
checked_at = waktu pemeriksaan terkini, timezone eksplisit
checks = {SCOPE, ROE, POLICY, RISK, EXPIRY, REVOCATION, TARGET, TECHNIQUE}
         masing-masing tepat PASS / FAIL / REVIEW
revoked = boolean eksplisit
emergency_stop = boolean eksplisit
human_approval_verified = boolean eksplisit
```

`decision_id`, `request_id`, `mission_id`, `decision`, `decision_hash`, `scope_contract_id`, `scope_version`, `policy_set_id`, `policy_version`, `valid_from`, `valid_until`, `requires_human_approval`, `constraints`, dan `reason_codes` wajib tersedia pada PolicyDecision. Scope ID/version dan policy set harus sesuai current Mission binding. `decision_hash` adalah digest opaque authoritative dari GSS; hashing lokal tidak mengautentikasi GSS. Trust berasal dari endpoint yang dikonfigurasi operator dan kanalnya.

File schema terdapat pada `execution_subsystem/schemas/gss_execution_revalidation_v1.schema.json`. Kontrak lengkap juga tersedia melalui API contract. Respons GSS lama tanpa attestation, timeout, error HTTP, redirect, malformed/duplicate JSON, incomplete checks, correlation mismatch, expiry atau invalid freshness menghasilkan **HTTP 503** dengan `execution_authorized=false`. Tidak ada fallback ke ALLOW sebelumnya.

Client menerima HTTP hanya untuk loopback. Endpoint remote harus HTTPS dengan validasi sertifikat bawaan. Redirect dan environment proxy dinonaktifkan; response dibatasi 1 MiB dan timeout default 5 detik (maksimum 30). Control API ini mengikuti boundary loopback lokal baseline; aplikasi remote memerlukan authentication/access controls pada deployment boundary yang dipercaya.

## Penyimpanan dan replay

| Komponen | Control/migration |
|---|---|
| Global Mission Orchestrator, port 8780 | Stage 3.9.10; migration **53** |
| Pentest, port 8790 | Stage 5.10; migration **16** |
| Execution, port 8791 | Stage 6.2; migration **2** |

Migration execution 1 → 2 dijalankan atomically. Semua request/envelope Stage 6.1 dipertahankan. Table baru `execution_authorizations` memiliki foreign key ke `execution_requests`, unique revalidation/idempotency/PolicyDecision identities, dan trigger yang melarang UPDATE/DELETE. Foreign database, incomplete metadata atau future migration ditolak tanpa downgrade. Path/symlink/hardlink untuk ketiga database wajib berbeda.

Replay dengan intake identik mengembalikan record historis dan `created=false`, **`authorization_current=false`**, **`execution_authorized=false`**, tanpa query GSS. GET/list juga audit-only. Nilai `record.execution_authorized_at_evaluation` merekam fakta historis. Untuk current authorization, kirim **revalidation ID dan idempotency key baru**. Tidak ada mutable status yang dapat menghidupkan kembali cached ALLOW.

Concurrent duplicate request dalam satu service menghasilkan satu query dan satu record. Unique constraints menjaga satu record saat ada competing process; duplicate external evaluations tidak dianggap sebagai exactly-once execution, karena eksekusi belum tersedia pada tahap ini.

## Aktivasi Windows

1. Ekstrak patch ke `D:\mission_orchestrator`.
2. Hentikan proses Execution Stage 6.1 yang memakai port 8791. Jalankan script Stage 6.2; layanan Mission, Pentest dan GSS tetap memakai port masing-masing.

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\START_STAGE6_2_EXECUTION.ps1
```

CLI baru:

```powershell
python run\execution_authorization.py --host 127.0.0.1 --port 8791
```

Runner/script Stage 6.1 dipertahankan sebagai baseline historis. Runner lama bukan entry point Stage 6.2 dan tidak dapat membuka database setelah upgrade v2.

Konfigurasi:

| Environment | Default |
|---|---|
| `APTS_EXECUTION_DB` | `data\execution_subsystem.db` |
| `APTS_PENTEST_DB` | `data\pentest_subsystem.db` |
| `APTS_EXECUTION_MISSION_DB` | `MISSION_SQLITE_PATH`, lalu `data\mission_orchestrator.db` |
| `APTS_EXECUTION_GOVERNANCE_URL` | `MISSION_GOVERNANCE_BASE_URL`, lalu `http://127.0.0.1:8770` |
| `APTS_EXECUTION_GOVERNANCE_TIMEOUT` | 5 detik |

CLI `--execution-db`, `--pentest-db`, `--mission-db`, `--governance-url`, `--governance-timeout` mengesampingkan default. Mission source pada versi ini menggunakan SQLite; tidak membuka atau memigrasikan database MySQL.

## API

| Method | Endpoint | Hasil |
|---|---|---|
| GET | `/health` | Runtime control, migrations dan capability/boundary flags; GSS diverifikasi setiap revalidation |
| GET | `/api/execution/execution-authorization-contract` | Contract dan protocol schemas |
| GET | `/api/contracts/authoritative-execution-authorization` | Alias contract |
| POST | `/api/execution/authorizations` | Fresh gate: 201 baru; 200 historical replay |
| GET | `/api/execution/authorizations/{authorization_id}` | Audit-only record |
| GET | `/api/execution/authorizations?execution_id=exec-...&limit=100` | Audit-only list, limit 1–500 |
| POST/GET | `/api/execution/requests...` | Intake/read request Stage 6.1 yang dipertahankan |

Intake authorization:

```json
{
  "schema_version": "apts-execution-authorization-intake-v1",
  "revalidation_id": "eauthreq-my-validation-001",
  "idempotency_key": "idem-auth-my-validation-001",
  "execution_id": "exec-<id-request-tersimpan>",
  "envelope_sha256": "<hash-envelope-tersimpan>",
  "requested_by": "operator-local"
}
```

Contoh PowerShell dengan identitas request nyata:

```powershell
$requests = Invoke-RestMethod 'http://127.0.0.1:8791/api/execution/requests?limit=100'
$req = $requests.requests | Select-Object -First 1
if (-not $req) { throw 'Buat ExecutionRequest Stage 6.1 dari proposal tersimpan terlebih dahulu.' }
$suffix = [guid]::NewGuid().ToString('N')
$body = @{
    schema_version = 'apts-execution-authorization-intake-v1'
    revalidation_id = "eauthreq-$suffix"
    idempotency_key = "idem-auth-$suffix"
    execution_id = $req.execution_id
    envelope_sha256 = $req.envelope.integrity.canonical_sha256
    requested_by = 'operator-local'
} | ConvertTo-Json -Depth 10
$auth = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8791/api/execution/authorizations' `
    -ContentType 'application/json' -Body $body
$auth.record.decision
$auth.authorization_id
```

404: execution request/reference tidak ditemukan. 400: intake invalid atau caller mencoba menentukan authority/action. 409: source/stored integrity, state/scope/RoE restriction atau idempotency conflict. 503: sumber/GSS unavailable atau respons tidak memenuhi protocol. ALLOW, DENY dan REVIEW yang valid semuanya menghasilkan record baru dengan HTTP 201; HTTP sukses tidak berarti action diizinkan.

## Acceptance dan batas validasi

```powershell
.\STAGE6_2_ACCEPTANCE.ps1
# Setelah revalidation nyata berhasil tersimpan:
.\STAGE6_2_ACCEPTANCE.ps1 -LiveAuthorizationId $auth.authorization_id
```

Inventory **2229 tests**: baseline 2118 + **111 Stage 6.2**. Harness memeriksa current runtime, upstream migrations, GSS health, exact contract hash, negative boundaries, compile, focused proof, continuity dan full regression. Tests memakai database terisolasi dan authority loopback khusus tests; tidak mengotorisasi mission pengguna.

Tanpa `-LiveAuthorizationId`, acceptance memvalidasi source/runtime dan reachability GSS, **belum membuktikan kompatibilitas live attestation GSS**. Dengan ID tersebut, harness memverifikasi captured live record secara read-only. Source GSS dan PowerShell runtime tidak tersedia pada build Linux ini; hasil pengujian lokal disajikan terpisah dalam `REGRESSION_EVIDENCE_STAGE6_2.txt`.
