# Stage 6.8 — Cleanup, Rollback & Post-Action Verification

Baseline: `Mission(20261003-222408).zip`, Stage 6.7.
Control aktif: `stage6.8-cleanup-rollback-post-action-verification`.
Execution migration **8**. Mission **53** dan Pentest **16** tetap read-only.
Kontrak Stage 6.1–6.7 tetap utuh; predecessor 6.7 diikat oleh exact SHA-256.

Stage ini membersihkan resource sementara yang dibuat runtime, melakukan
kompensasi lokal bila cleanup awal belum selesai, mencabut akses lease credential
secara persisten, lalu membangun laporan verifikasi dan penutupan **exact attempt**.
Penutupan berlaku untuk resource eksekusi lokal. State target dan pencabutan token
di penerbit credential belum dapat dibuktikan oleh adapter yang tersedia.

## Workflow

| Fase | Implementasi dan batas bukti |
|---|---|
| Verify effect | Meninjau hasil primitive, capture completeness, dan uncertainty dari VEP terverifikasi; bukan verdict vulnerability |
| Cleanup temporary artifacts | Menutup worker, pipe dan socket, menghentikan reader, melepaskan Windows Job Object, dan menghapus direktori sandbox yang dimiliki runtime |
| Revoke temporary credentials | Menyimpan revocation lease dengan scope execution di database Execution; acquire berikutnya ditolak termasuk setelah restart |
| Restore required state | Kompensasi terbatas terhadap objek worker/socket yang benar-benar dibuat runtime; baseline lokal tanpa resource sementara aktif |
| Verify cleanup | Memeriksa process exit, closed pipe/socket, stopped reader, released Job handle, dan absennya direktori sandbox |
| Close execution | Menghasilkan laporan `CLOSED_LOCAL_RESOURCES` hanya bila seluruh persyaratan lokal terbukti; lainnya `BLOCKED_REQUIRES_REVIEW` |

Observasi primitive terjadi selama execution. Cleanup fisik dilakukan otomatis
saat terminasi, sebelum runtime menulis terminal event. Receipt resource dan
revocation lokal disimpan dalam satu transaksi. Laporan enam fase dibangun
secara eksplisit setelah VEP tersedia; laporan tersebut meninjau bukti yang
telah tersimpan dan tidak melakukan target I/O tambahan atau memanggil GSS.

Objek sandbox dan socket dicatat dari constructor runtime. Caller tidak dapat
mengirim path, command, executable, PID, daftar file, receipt, atau verdict cleanup.
Kompensasi melakukan satu putaran tambahan terhadap objek yang sama bila cleanup
awal belum terbukti, lalu memeriksa hasilnya. Tidak ada pencarian PID atau
penghapusan folder global berdasarkan prefix. Windows `CloseHandle` harus
berhasil sebelum Job Object dilaporkan telah dilepaskan.

Evidence SQLite, manifest Stage 6.6, dan VEP immutable Stage 6.7 dipertahankan.
`cleanup_verified=false` dalam VEP 6.7 tetap tidak diubah. Bukti cleanup terdapat
di laporan 6.8 yang mengikat hash VEP, envelope, capture, terminal head, receipt,
dan revocation. Health `vep_cleanup_verification_enabled=true` menyatakan bahwa
verifikasi terkait VEP tersedia melalui laporan terpisah tersebut.

## Credential, recovery, dan rollback

Lease yang dikonfigurasi dicabut secara lokal saat terminasi, termasuk saat
pemulihan orphan. Revocation bersifat append-only dan terikat ke exact execution;
reset konfigurasi lease tidak menghapus deny yang sudah tersimpan. Secret
environment variable tidak ditulis ke receipt/laporan dan tidak diubah oleh cleanup.

Revocation lokal tidak mencabut bearer token di server penerbitnya. Jika lease
pernah di-acquire, penutupan diblokir dengan
`ISSUER_CREDENTIAL_REVOCATION_NOT_PROVEN`, termasuk jika credential belum dikirim
karena target tidak memakai TLS. Jika lease dikonfigurasi tetapi tidak pernah
di-acquire, revocation lokal dapat memenuhi fase credential tanpa klaim issuer
revocation. Pada crash tanpa durable result, acquisition dinyatakan **unknown**,
bukan false; laporan tetap diblokir.

Attempt sebelum Stage 6.8 tidak mempunyai receipt native dan tidak dibackfill.
Orphan recovery mempertahankan `target_io_uncertain=true` dan tidak redispatch.
Receipt yang sudah tersimpan sebelum crash dapat tetap dibaca, tetapi bila
result belum durable, laporan mencatat `PRETERMINAL_RESULT_NOT_DURABLE` dan
memblokir penutupan. Direktori orphan yang kepemilikannya tidak terbukti tidak
dihapus secara otomatis. Laporan blocked bersifat immutable; tidak tersedia
caller override atau upload attestation untuk menjadikannya closed.

Lima adapter saat ini hanya menggunakan TCP connect, TCP banner, atau HTTP HEAD.
Rollback yang tersedia memulihkan baseline resource **lokal**, bukan state target.
Tidak ada adapter mutasi target, baseline target before/after, atau protokol
issuer revocation. Laporan selalu menyatakan `target_state_verified=false` dan
`target_rollback_performed=false`. Sukses adapter tetap tidak mengonfirmasi
vulnerability maupun impact. Tahap ini juga tidak menutup task/mission upstream.

Rollback instalasi menggunakan backup database setelah runtime dihentikan.
Metadata migration tidak boleh diturunkan secara manual; runner 6.7 menolak
database migration 8. Ini terpisah dari kompensasi resource saat execution.

Hotfix 1 menutup race antara supervisor revalidation dan completion. Admission
helper ditutup saat action selesai; source/lock yang tertunda memeriksa lifecycle
sebelum query GSS. Completion menunggu helper yang sudah masuk maksimum dua
detik, dibatasi wall deadline, sebelum menyimpan terminal. Timeout quiescence
menghasilkan `ABORTED`; wall deadline tetap `TIMEOUT`. Cancellation tetap segera
menutup resource lokal, dengan respons panggilan control-plane yang sudah
dikirim dibuang. Query audit/VEP tidak membuat revalidation baru.

## API

| Method | Route | Keterangan |
|---|---|---|
| GET | `/api/execution/cleanup-rollback-post-action-verification-contract` | Canonical contract 6.8 |
| GET | `/api/execution/cleanup/attempts/<attempt-id>` | Enrollment, receipt availability, dan laporan yang sudah tersedia |
| POST | `/api/execution/post-actions` | Membangun laporan dari exact scoped VEP yang sudah tersedia |
| GET | `/api/execution/post-actions?execution_id=<id>&limit=100` | Daftar laporan terverifikasi, limit 1–100 |
| GET | `/api/execution/post-actions/<post-action-id>?attempt_id=<id>` | Laporan exact attempt |
| GET | `/api/execution/post-actions/<post-action-id>/verify?attempt_id=<id>` | Audit internal lineage dan closure state |
| GET | `/api/execution/post-actions/<post-action-id>/export?attempt_id=<id>` | Self-contained export, termasuk VEP dan retained artifact bytes |

API Stage 6.1–6.7 tetap tersedia. JSON/query keys duplikat, authority overrides,
paths/commands, serta upload cleanup/rollback/revocation ditolak. Bind hanya
loopback. Laporan baru mengembalikan HTTP 201, replay HTTP 200, termasuk laporan
blocked. HTTP success berarti penyimpanan/verification berhasil; periksa
`status`, `execution_closed`, dan `blocking_reasons` untuk hasil cleanup.
Invalid intake 400, scope tidak ditemukan 404, integrity/binding invalid 409,
dan storage unavailable 503. Read/export memakai `Cache-Control: no-store`;
export menyertakan `nosniff` dan `X-Post-Action-SHA256`.

Hash dan audit offline membuktikan konsistensi internal, hubungan record, nilai
turunan, serta retained bytes. Bukti ini tidak ditandatangani oleh pihak
independen dan tidak membuktikan ground truth state target. Schema JSON hanya
memeriksa struktur interchange; verifier Python memeriksa semantics dan lineage.

Contoh membuat laporan dari VEP yang sudah tersedia:

```powershell
$base = 'http://127.0.0.1:8791'
$attemptId = 'xattempt-ISI_DARI_RUNTIME'
$vepId = 'xvep-ISI_DARI_STAGE6_7'
$runtime = Invoke-RestMethod "$base/api/execution/runtime/attempts/$attemptId"
$vep = Invoke-RestMethod "$base/api/execution/veps/$vepId`?attempt_id=$attemptId"
$body = @{
    schema_version = 'apts-execution-post-action-intake-v1'
    attempt_id = $attemptId
    envelope_sha256 = $runtime.record.runtime_intake.envelope_sha256
    evidence_sha256 = $vep.vep.evidence.integrity.canonical_sha256
    expected_head_sha256 = $runtime.head_sha256
    vep_id = $vepId
    vep_sha256 = $vep.vep_sha256
} | ConvertTo-Json -Depth 10
$post = Invoke-RestMethod -Method Post -Uri "$base/api/execution/post-actions" -ContentType 'application/json' -Body $body
$post | Select-Object status, execution_closed, cleanup_verified, blocking_reasons
Invoke-WebRequest "$base/api/execution/post-actions/$($post.post_action_id)/export?attempt_id=$attemptId" -UseBasicParsing -OutFile '.\post_action_export.json'
python run\stage6_8_audit.py --export-file .\post_action_export.json
```

Untuk attempt lama, POST tersebut menghasilkan laporan blocked karena tidak ada
receipt Stage 6.8; tidak menjalankan ulang attempt. Execution baru tetap melewati
gateway, fixed adapter, native sandbox, dan fresh external GSS yang sama.

## Instalasi dan verifikasi

Ikuti `INSTALL_STAGE6_8.txt`. Jalankan `START_STAGE6_8_EXECUTION.ps1` dan
`STAGE6_8_ACCEPTANCE.ps1` pada dua console PowerShell terpisah. Acceptance default
tidak membuat laporan atau execution pada mission pengguna. Seluruh tes mutasi
menggunakan database terisolasi, fake/real loopback authority HTTP, dan target
loopback. Audit opsional laporan yang sudah ada:

```powershell
.\STAGE6_8_ACCEPTANCE.ps1 -LiveAttemptId 'xattempt-...' -LivePostActionId 'xcleanup-...'
```

Build Linux memeriksa `SECCOMP_RLIMIT`, penghentian owner process nyata, recovery,
resource compensation, credential deny setelah restart, retained-byte audits,
atomic storage failures, serta exact canonical JUnit coverage. Windows
PowerShell/Job Object dan mission pengguna tidak dijalankan dalam build Linux;
gunakan acceptance pada host Windows untuk memeriksa runtime aktual.

Hasil final tercantum di `REGRESSION_EVIDENCE_STAGE6_8.txt` dan
`evidence/stage6_8/regression_summary.json`.

| Pemeriksaan build final | Hasil |
|---|---|
| Stage 6.8 focused, termasuk completion races | 92 passed |
| Stage 5.9–6.8 continuity | 784 passed |
| Full canonical regression | 2.793 passed; 0 failed/error/skipped |
| Exact JUnit coverage | PASS |
| Frozen source snapshot | UNCHANGED |
| Offline post-action export | VERIFIED_INTERNAL_LINEAGE; 9 artifacts |

Log Windows sebelum Hotfix 1 menunjukkan native Job Object, 80 focused tests,
dan 772 continuity tests lulus, tetapi regresi penuh gagal pada satu race
Stage 6.7. Hotfix ini telah diuji pada Linux; acceptance Windows perlu dijalankan
ulang setelah source diganti dan proses Execution direstart.

Tahap berikutnya: **6.9 — Closed-Loop CTI ↔ Pentest Integration**.
