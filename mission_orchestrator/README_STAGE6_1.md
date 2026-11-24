# Stage 6.1 — Canonical Execution Request Contract

Stage 6.1 menambahkan **ExecutionRequest schema** dan **canonical action envelope** sesuai roadmap. Implementasi tetap berada pada satu root `D:\mission_orchestrator`, dengan kode baru pada `execution_subsystem\`.

Control: `stage6.1-canonical-execution-request-contract`  
Predecessor: `stage5.10-agentic-pentest-acceptance-regression-gate`  
Tahap berikutnya: **6.2 — Authoritative Execution Authorization**

## Proses dan data

Layanan membaca proposal Stage 5.6 yang sudah tersimpan dalam database Pentest. Satu transaksi baca mengikat task artifact/binding, run specialist, predecessor attack path, identitas/ownership subtask, keputusan eligibility, action-proposal lineage, hypothesis parent, dan seluruh evidence basis. Klien hanya mengirim identitas proposal serta hash-nya; klien tidak menentukan target, agent, action, parameter, bukti, atau otorisasi.

`ExecutionRequest` berisi seluruh sepuluh field roadmap:

| Field | Sumber dan makna |
|---|---|
| `execution_id` | Identitas deterministik dari mission, upstream task, pentest, dan idempotency key; prefix `exec-` |
| `mission_id` | Root lineage Global Mission Orchestrator |
| `task_id` | `upstream_task_id` milik Global Mission Orchestrator; bukan local Pentest task ID |
| `pentest_id` | Root Pentest lokal yang tersimpan |
| `proposing_agent` | Agent, role, orchestration, dan subtask dari assignment yang tersimpan |
| `action` | Action class, capability, dan technique proposal |
| `target` | Target persis dari proposal/attack path |
| `parameters` | Validation task ID, expected evidence, dan estimated impact; data deskriptif, tanpa command/payload |
| `evidence_basis` | Referensi evidence yang sudah ada beserta SHA-256 masing-masing |
| `authorization_requirement` | Referensi policy, human-review requirement, dan delapan pemeriksaan Stage 6.2 |

Schema core terdapat pada `execution_subsystem\schemas\execution_request_v1.schema.json`. Request disegel dengan metadata SHA-256 dan dimasukkan dalam envelope. Schema envelope lengkap terdapat pada `execution_subsystem\schemas\canonical_action_envelope_v1.schema.json`.

Envelope mengikat request, intake, source hashes, scope/RoE/constraints, policy reference, Stage 5 closure contract, status, dan semantics. Verifier Python juga memeriksa hubungan antar-field, hash, identitas deterministik, serta duplikasi evidence yang tidak dapat seluruhnya dinyatakan lewat JSON Schema. SHA-256 merupakan pemeriksaan integritas konten; otorisasi dan autentikasi tetap merupakan tanggung jawab kontrol berikutnya.

## Layanan dan penyimpanan

| Komponen | Port default | Control |
|---|---|---|
| Global Mission Orchestrator | `8780` | Stage 3.9.10 |
| Pentest Subsystem | `8790` | Stage 5.10 |
| Execution Subsystem | `8791` | Stage 6.1 |

Pentest migration tetap **16**. Stage 6.1 memiliki migration **1** sendiri pada `execution_migrations\` dan database `data\execution_subsystem.db`. Tidak ada perubahan pada migration, service, handler, contract, atau test historis Stage 3–5.

Proposal source menggunakan SQLite `mode=ro` dan `query_only`; layanan tidak menginisialisasi atau memigrasikan database Pentest. Database execution harus berbeda dari database Pentest, termasuk jika kedua path merupakan symlink atau hardlink ke file yang sama. Initializer execution juga menolak database yang berisi tabel repository lain, sehingga konfigurasi path tidak dapat menambahkan tabel execution ke database Global Mission atau aplikasi lain.

Konfigurasi opsional:

- `APTS_PENTEST_DB`: sumber proposal; default `data\pentest_subsystem.db`.
- `APTS_EXECUTION_DB`: request store; default `data\execution_subsystem.db`.
- CLI `--pentest-db` dan `--execution-db` mengesampingkan default masing-masing.

Store bersifat append-only. UPDATE/DELETE ditolak oleh trigger. Intake identik mengembalikan record lama; penggunaan request ID atau idempotency key untuk konten berbeda ditolak dengan HTTP 409. Identitas request yang berbeda dapat mengusulkan aksi yang sama; pencegahan eksekusi ganda/attempt identity menjadi tugas gateway/runtime berikutnya.

Replay idempotent mengembalikan envelope historis tanpa mengotorisasi ulang dan tanpa membaca ulang sumber yang mungkin telah berubah. Setiap request tetap memerlukan revalidation terbaru pada Stage 6.2 sebelum bisa dieksekusi.

## Boundary Stage 6.1

Semua request memiliki status **`AWAITING_AUTHORIZATION`**. Request yang berasal dari `AWAITING_HUMAN_REVIEW` mempertahankan `human_review_required=true`; proposal `BLOCKED_BY_SCOPE_ROE` ditolak.

`authorization_requirement` mewajibkan SCOPE, ROE, POLICY, RISK, EXPIRY, REVOCATION, TARGET, dan TECHNIQUE. Stage 6.1 menyimpan kebutuhan ini; pemeriksaan otorisasi terbaru dan keputusan ALLOW/DENY/REVIEW diimplementasikan pada Stage 6.2. Eligibility Stage 4.8 dan policy reference lama tidak menjadi izin execution baru.

Stage 6.1 tidak menjalankan tool, menyentuh target, membuat ActionResult, atau menghasilkan bukti target baru. Specialist tetap tidak mempunyai direct raw target access. Endpoint dispatch, authorizations, results, dan tool-invocations mengembalikan HTTP 409. API ini merupakan local control plane; jalankan pada loopback default.

## Menjalankan di Windows

Pertahankan layanan Global Mission Orchestrator dan Pentest Subsystem yang sudah aktif. Dari jendela PowerShell baru:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\START_STAGE6_1_EXECUTION.ps1
```

Alternatif CLI:

```powershell
python run\execution_subsystem.py --host 127.0.0.1 --port 8791
```

Dari jendela PowerShell lain:

```powershell
cd D:\mission_orchestrator
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\STAGE6_1_ACCEPTANCE.ps1
```

Target akhir: **`STAGE 6.1 ACCEPTANCE: PASS`**. Harness memeriksa layanan nyata, exact canonical contract hash, predecessor binding, negative boundaries, kompilasi, inventory, focused tests, continuity, critical regression, dan full historical regression. Test pembentukan request memakai database terisolasi; harness tidak menambahkan request ke mission pengguna.

Inventory: **2118 tests** (baseline 2045 + 73 Stage 6.1).

## API

| Method | Endpoint | Hasil |
|---|---|---|
| GET | `/health` | Control, readiness sumber, migration, dan boundary flags |
| GET | `/api/execution/execution-request-contract` | Contract, definition, dan schema |
| GET | `/api/contracts/canonical-execution-request` | Alias contract |
| POST | `/api/execution/requests` | Membentuk dan menyimpan envelope; HTTP 201 baru, 200 replay |
| GET | `/api/execution/requests/{execution_id}` | Request/envelope tersimpan yang telah diverifikasi |
| GET | `/api/execution/requests` | List dengan filter `mission_id`, `task_id`, `pentest_id`, `limit` (1–500) |

Intake JSON hanya menerima:

```json
{
  "schema_version": "apts-execution-request-intake-v1",
  "request_id": "ereq-my-validation-001",
  "idempotency_key": "idem-my-validation-001",
  "exploitation_run_id": "xplrun-<ID-yang-tersimpan>",
  "exploit_action_proposal_id": "xplprop-<ID-yang-tersimpan>",
  "proposal_sha256": "<SHA-256-proposal-yang-tersimpan>"
}
```

Placeholder dalam contoh harus diganti dengan nilai asli. Proposal harus tersedia terlebih dahulu melalui workflow Stage 5; layanan tidak membuat proposal, evidence, atau target fiktif.

Untuk memilih proposal yang sudah ada:

```powershell
$runs = Invoke-RestMethod 'http://127.0.0.1:8790/api/pentest/exploitation-runs?limit=100'
$run = $runs.exploitation_runs | Where-Object {
    @($_.output.exploit_action_proposals | Where-Object {
        $_.proposal_status -in @('ELIGIBLE_FOR_EXTERNAL_AUTHORIZATION', 'AWAITING_HUMAN_REVIEW')
    }).Count -gt 0
} | Select-Object -First 1
if (-not $run) { throw 'Belum ada proposal Stage 5.6 yang dapat diproses.' }
$proposal = $run.output.exploit_action_proposals | Where-Object {
    $_.proposal_status -in @('ELIGIBLE_FOR_EXTERNAL_AUTHORIZATION', 'AWAITING_HUMAN_REVIEW')
} | Select-Object -First 1
$body = @{
    schema_version = 'apts-execution-request-intake-v1'
    request_id = 'ereq-my-validation-001'
    idempotency_key = 'idem-my-validation-001'
    exploitation_run_id = $run.exploitation_run_id
    exploit_action_proposal_id = $proposal.exploit_action_proposal_id
    proposal_sha256 = $proposal.integrity.canonical_sha256
} | ConvertTo-Json -Depth 10
$request = Invoke-RestMethod -Method Post `
    -Uri 'http://127.0.0.1:8791/api/execution/requests' `
    -ContentType 'application/json' -Body $body
$request.envelope.execution_request
```

HTTP 400 berarti intake invalid; 404 berarti referensi tidak ditemukan; 409 berarti konflik/integritas/proposal terblokir; 503 berarti sumber atau repository belum tersedia. Health 503 juga digunakan jika sumber belum berada pada migration 16.
