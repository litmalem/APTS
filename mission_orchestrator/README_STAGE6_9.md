# Stage 6.9 — Closed-Loop CTI ↔ Pentest Integration

Baseline: `Mission(20261004-012953).zip`, termasuk completion fence Stage 6.8.
Control Execution aktif: `stage6.9-closed-loop-cti-pentest-integration`.
Execution migration **9**, CTI feedback migration **1**, Mission **53**, Pentest **16**.

Implementasi menutup jalur CTI → PIP → Pentest → VEP → knowledge CTI → adaptation
Mission → snapshot dan kandidat replanning. Feedback baru dibangun dari VEP,
laporan post-action Stage 6.8, serta retained artifact bytes yang terverifikasi.
Setiap knowledge revision menyimpan hubungan sumber tersebut dan predecessor
hash. Consumer Mission mengikat revision exact ke episode `EXTERNAL_SIGNAL /
CTI_CHANGE` pada kontrak adaptasi yang sudah ada.

## Deliverable dan kepemilikan

| Deliverable roadmap | Implementasi |
|---|---|
| CTI feedback contract | Kontrak canonical 6.9 dengan predecessor SHA-256 exact 6.8, intake schema, assessment, graph annotation, dan source lineage |
| Knowledge update pipeline | Feedback append-only pada Execution; revision chain CAS pada database CTI feedback terpisah; replay, restart, quota, audit offline |
| Closed-loop mission feedback | Consumer read-only CTI pada Mission; exact Mission/plan CAS, PIP dan scope checks; durable adaptation episode dan Mission event; context diteruskan ke snapshot/kandidat |

Execution menulis `execution_cti_feedback` miliknya sendiri. Knowledge pipeline
menulis `data/cti_feedback_repository.db` melalui owner CTI khusus; pembacaan
feedback Execution memakai SQLite `mode=ro` dan `query_only`. Mission hanya
membaca knowledge, lalu menulis episode/event melalui repository Mission.
Sumber Mission dan Pentest pada Execution tetap read-only.

Database ini merupakan ekstensi knowledge feedback CTI. Integrasi tidak menulis
database core VulnDesk yang tidak disertakan pada baseline. Health menyatakan
`cti_feedback_external_vulndesk_writes=false`. Export knowledge menyediakan
lineage untuk integrasi berikutnya tanpa mengklaim bahwa VulnDesk sudah berubah.

## Arti assessment

Lima adapter baseline hanya menyediakan TCP connect, TCP banner, atau HTTP HEAD.
Bukti tersebut mendukung observasi primitive, belum verdict vulnerability.
Karena itu evaluator aktif menghasilkan `INCONCLUSIVE`, mempertahankan prior
confidence hypothesis dan estimated impact, serta menyatakan validated risk
score sebagai `null`. Kegagalan koneksi tidak menolak hypothesis. Keberhasilan
adapter tidak mengonfirmasi vulnerability atau impact.

Observation quality diturunkan terpisah sebagai `VERIFIED_OBSERVATION` atau
`INCOMPLETE_OR_UNCERTAIN`. Knowledge baru bertipe `VALIDATION_OBSERVATION`.
Attack graph mendapat annotation `VALIDATION_STILL_REQUIRED` dengan referensi
feedback/evidence; conditional edges dan attack path sumber tetap dipertahankan.
Vocabulary kontrak mencakup CONFIRMED/REJECTED untuk evaluator berbukti di masa
depan; caller tidak dapat memasukkan verdict tersebut pada implementasi ini.

Laporan cleanup blocked tetap boleh direkam sebagai negative/uncertain evidence,
dengan `review_required=true` dan blocking reasons asli. Feedback tidak menutup
execution, task atau mission dan tidak membuktikan state target maupun issuer
credential revocation. VEP 6.7 dan laporan 6.8 tetap immutable.

## Revision dan replanning

Satu attempt memiliki paling banyak satu feedback. `knowledge_id` diturunkan
dari subject exact: mission, task/Pentest, PIP, target, dan hypothesis. Attempt
berikutnya untuk subject sama dapat menghasilkan revision berikutnya. Import
memerlukan `expected_revision` dan `expected_head_sha256`; stale head ditolak
409. Replay identik mengembalikan record lama, termasuk setelah head berkembang;
perubahan intake pada feedback yang sudah diimport ditolak.

Intake Mission baru harus menunjuk latest knowledge revision, exact hash,
current Mission version/state, dan active plan version. Target harus berada
dalam current canonical scope dan PIP harus cocok. Mission terminal tidak
dibuka kembali. Replay episode yang sudah diterima tetap idempotent setelah
perubahan state/head, tanpa membuat episode baru.

Consumer membuat episode adaptasi dan event Mission; lifecycle state dan active
plan tetap sampai gate yang sesuai dijalankan. Urutannya mengikuti Stage 3.7:
trigger classification → eligibility dengan fresh external Governance → replan
snapshot → kandidat → controlled commit. `DENY`/`REVIEW` tidak dilewati.
Snapshot mengikat exact CTI knowledge hash. Kandidat dan successor candidate
mempertahankan requirement validasi, review/blocking reasons, serta source hash.
Metadata dari endpoint adaptasi generic diverifikasi kembali dari trusted CTI
source sebelum dapat menjadi context snapshot. Tidak ada automatic plan commit,
redispatch, target I/O, atau panggilan GSS pada pembuatan feedback/knowledge/intake
CTI sendiri. Governance baru digunakan pada gate replanning yang sudah ada.

## API

| Method | Route | Fungsi |
|---|---|---|
| GET | `/api/execution/closed-loop-cti-pentest-contract` | Kontrak canonical 6.9; alias `/api/contracts/closed-loop-cti-pentest` |
| POST | `/api/execution/cti-feedback` | Membangun feedback dari exact persisted VEP/post-action |
| GET | `/api/execution/cti-feedback?execution_id=<id>&limit=100` | Daftar scoped feedback |
| GET | `/api/execution/cti-feedback/<id>?attempt_id=<id>` | Record exact attempt; suffix `/verify` dan `/export` tersedia |
| POST | `/api/cti/knowledge-updates` | Import source feedback melalui read-only reader dan revision CAS |
| GET | `/api/cti/knowledge?mission_id=<id>&limit=100` | Daftar latest knowledge pada exact mission |
| GET | `/api/cti/knowledge/<id>?mission_id=<id>&revision=<n>` | Revision record; ordinal opsional, default latest |
| GET | `/api/cti/knowledge/<id>/export?mission_id=<id>&revision=<n>` | Chain self-contained sampai revision yang diminta |
| GET | `/api/missions/<id>/cti-pentest-feedback-contract` | Intake contract Mission |
| POST | `/api/missions/<id>/cti-pentest-feedback` | Guarded knowledge handoff ke episode adaptasi Mission |

Record baru mengembalikan 201; replay identik 200. Invalid/duplicate JSON atau
query, caller verdict/evidence/authority overrides: 400. Scope tidak ditemukan:
404. Source integrity, CAS dan binding conflict: 409. Storage unavailable: 503.
Upload feedback/knowledge dan direct mutation bypass ditolak 409. List limit
1–100. Knowledge chain dibatasi 1000 revisions dan 16 MiB export; feedback
dibatasi 64 KiB. Bind Execution hanya loopback. Export memakai no-store,
nosniff, dan `X-CTI-SHA256`.

Contoh memakai VEP dan post-action yang **sudah tersedia**, setelah source/hash
dibaca dari API pemiliknya:

```powershell
$base = 'http://127.0.0.1:8791'
$attemptId = 'xattempt-ISI_DARI_RUNTIME'
$vepId = 'xvep-ISI_DARI_STAGE6_7'
$postActionId = 'xcleanup-ISI_DARI_STAGE6_8'
$vep = Invoke-RestMethod "$base/api/execution/veps/$vepId`?attempt_id=$attemptId"
$post = Invoke-RestMethod "$base/api/execution/post-actions/$postActionId`?attempt_id=$attemptId"
$feedbackBody = @{
    schema_version = 'apts-cti-pentest-feedback-intake-v1'
    attempt_id = $attemptId
    vep_id = $vepId
    vep_sha256 = $vep.vep_sha256
    post_action_id = $postActionId
    post_action_sha256 = $post.report_sha256
} | ConvertTo-Json
$feedback = Invoke-RestMethod -Method Post -Uri "$base/api/execution/cti-feedback" -ContentType 'application/json' -Body $feedbackBody

# Genesis untuk subject tanpa knowledge. Revision lanjutan harus memakai
# revision dan knowledge_sha256 dari GET latest sebagai expected head.
$knowledgeBody = @{
    schema_version = 'apts-cti-knowledge-update-intake-v1'
    feedback_id = $feedback.feedback_id
    feedback_sha256 = $feedback.feedback_sha256
    attempt_id = $attemptId
    expected_revision = 0
    expected_head_sha256 = $null
} | ConvertTo-Json
$knowledge = Invoke-RestMethod -Method Post -Uri "$base/api/cti/knowledge-updates" -ContentType 'application/json' -Body $knowledgeBody
$knowledge.knowledge.assessment

$missionBase = 'http://127.0.0.1:8780'
$missionId = $knowledge.knowledge.subject.mission_id
$version = Invoke-RestMethod "$missionBase/api/missions/$missionId/version-vector"
$state = Invoke-RestMethod "$missionBase/api/missions/$missionId/state"
$active = Invoke-RestMethod "$missionBase/api/missions/$missionId/plan-versions/active"
$handoff = @{
    schema_version = 'apts-mission-cti-pentest-feedback-intake-v1'
    knowledge_id = $knowledge.knowledge_id
    revision_id = $knowledge.revision_id
    revision = $knowledge.revision
    knowledge_sha256 = $knowledge.knowledge_sha256
    expected_version_sha256 = $version.version_sha256
    expected_state_version = $state.mission_state.state_version
    expected_active_plan_version_record_id = $active.plan_version_record_id
    expected_active_plan_version = $active.plan_version
    expected_active_plan_sha256 = $active.canonical_sha256
} | ConvertTo-Json
$episode = Invoke-RestMethod -Method Post -Uri "$missionBase/api/missions/$missionId/cti-pentest-feedback" -ContentType 'application/json' -Body $handoff
$episode | Select-Object adaptation_episode_id, cti_feedback_status, next_required_gate
```

HTTP success di atas berarti record/intake diterima. Periksa assessment,
review_required dan blocking reasons sebelum mengklasifikasikan trigger atau
melanjutkan gate replanning. Bila state berubah di antara GET dan POST, CAS
menolak intake; baca ulang state dan periksa perubahan sebelum membentuk request.

## Audit dan deployment

Ikuti `INSTALL_STAGE6_9.txt`. Startup default menambahkan Execution migration 9
dan CTI migration 1, lalu Mission direstart dengan source consumer 6.9. Tidak
ada migration Mission/Pentest baru. Kedua proses harus memakai file CTI yang
sama: default `data/cti_feedback_repository.db`, atau `APTS_CTI_FEEDBACK_DB` /
parameter `-CtiFeedbackDb`. File CTI hanya diinisialisasi owner pipeline;
consumer Mission tidak membuat atau memperbaiki file yang hilang.

Export dapat diverifikasi pada mesin offline dengan source paket yang sama:

```powershell
Invoke-WebRequest "$base/api/cti/knowledge/$($knowledge.knowledge_id)/export?mission_id=$missionId" -UseBasicParsing -OutFile '.\knowledge_export.json'
python run\stage6_9_audit.py --export-file .\knowledge_export.json
```

Audit memeriksa reconstructed assessment, revision chain, VEP/post-action,
manifest/event chain dan retained bytes. Status `VERIFIED_INTERNAL_LINEAGE`
membuktikan konsistensi internal. Tidak ada independent digital signature atau
klaim ground truth target. Example export pada `evidence/stage6_9` berasal dari
pengujian terisolasi, bukan mission pengguna.

Build Linux menjalankan 72 focused tests dan regresi canonical 2865 tests,
termasuk jalur governance/replan lama. Seluruh target uji loopback dan database
terisolasi. Detail hasil final ada di `REGRESSION_EVIDENCE_STAGE6_9.txt` dan
`evidence/stage6_9/regression_summary.json`. Native backend yang diuji adalah
SECCOMP_RLIMIT. PowerShell/Windows Job Object dan mission pengguna belum
dijalankan di build Linux; jalankan `STAGE6_9_ACCEPTANCE.ps1` pada host deployment.

Next: **Stage 6.10 — Full APTS End-to-End Acceptance & Regression Gate**.
