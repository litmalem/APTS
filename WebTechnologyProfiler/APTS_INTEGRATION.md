# Kontrak integrasi APTS yang diperlukan

## A. Sumber APTS yang diperiksa

- Recon collector bridge pada Mission mengizinkan `reconnaissance / TARGET_RECON / TCP_CONNECT_SCAN` dan melakukan preflight current-scope/RoE, Stage 6.1 request, gateway submission, runtime attempt, result verification, sealed evidence, lalu Recon iteration.
- Tool registry Mission adalah fixed server-owned registry. Adapter saat ini antara lain `scanner.tcp-connect.v1`, `network.tcp-banner.v1`, dan `web.http-head.v1`. Caller tidak dapat mendaftarkan plugin melalui API.
- Governance memegang authorization dan scope; adapter bukan authority. Gateway dan Stage 6 runtime memegang admission, sandbox, evidence, dan lifecycle.

## B. Capability tuple yang perlu didaftarkan (usulan)

| Profile | Capability ID | Action class | Technique | Impact | Requests |
|---|---|---|---|---|---:|
| Fingerprinting | `web_technology_fingerprinting` | `TARGET_RECON` | `WEB_TECHNOLOGY_FINGERPRINT` | `LOW` | max 6 (dua GET tetap untuk root dan favicon) |
| Enumeration | `web_surface_enumeration` | `TARGET_RECON` | `BOUNDED_WEB_SURFACE_ENUMERATION` | `LOW` | max 12 |

Capability harus terdaftar sebagai fixed adapter di server Mission, bukan sebagai executable path yang dipilih oleh UI/agent. Terapkan target allowlist, URL normalization, DNS/IP target pinning melalui target broker, redirects disabled, max response bytes, timeout, one-worker concurrency, request budget, idempotency, cancellation, dan evidence sealing.

Enumeration awal dibatasi pada probe metadata dan kandidat surface berisiko rendah. No directory brute-force, form submission, credential guessing, exploit validation, state-changing method, atau follow redirect keluar scope. Setiap profil perlu kontrak action sendiri; izin fingerprinting tidak otomatis mengizinkan Enumeration.

## C. Alur yang perlu dihubungkan

1. Reconnaissance/Enumeration Agent atau UI mandiri mengajukan job beserta `mission_id`, `task_id`, `target`, `mode`, expected evidence, dan idempotency key.
2. Untuk target non-loopback, Pentest workflow membuat/menautkan task/action proposal yang durable dan job harus memiliki mission serta active scope/RoE. Mode mandiri WTP dapat memindai loopback atau target remote yang persis tercantum dalam `WTP_REMOTE_ALLOWLIST` dan dikonfirmasi operator; mode ini tidak membuat mission/task, tidak dispatch ke agent, dan tidak menghasilkan evidence Stage 6. Untuk pekerjaan yang memerlukan evidence governed, gunakan alur APTS.
3. Stage 6 membuat canonical Execution Request. Governance mengevaluasi authorization dan operator approval sesuai policy; gateway menerima hanya setelah fresh authorization/revalidation.
4. Adapter tetap Stage 6 menjalankan request lewat sandbox + target broker, menormalisasi evidence, menyegel hasil, dan mengembalikan execution/result IDs.
5. Recon Agent / Enumeration Agent mengonsumsi result sebagai observation melalui event atau endpoint iteration resmi. Delivery acknowledgement mencakup agent, job/action/result ID, evidence hash, delivery ID, timestamp, consumer status.
6. UI hanya menampilkan status setelah menerima durable response/ack. `DELIVERED` tidak diatur dari browser.


## D. Stage 6 → WPT job dan hasil

WPT menerima status eksekusi melalui callback server-ke-server yang memakai `X-APTS-Client-Token` yang sama dengan inbox Mission. Callback job:

`POST /api/stage6/intakes/{intake_id}/job`

```json
{
  "schema_version": "apts-wpt-stage6-job-v1",
  "mission_id": "mission-gmo-…",
  "task_id": "ptask-…",
  "target": "https://target.example",
  "profile": "fingerprinting",
  "execution_id": "stage6-exec-…",
  "status": "AWAITING_APPROVAL",
  "authorization_id": null
}
```

Endpoint mencocokkan mission, task, URL canonical, dan profile dengan intake tersimpan. Satu intake dipetakan ke satu `job_id` deterministik; retry dengan binding dan execution ID yang sama memperbarui job yang sama, sementara binding atau execution ID berbeda menghasilkan `409`. Status yang diterima: `AWAITING_APPROVAL`, `AUTHORIZED`, `AWAITING_STAGE6`, `DISPATCHED`, `RUNNING`, `BLOCKED`, `BLOCKED_CONFIGURATION`, `FAILED`, dan `CANCELLED`. Callback status saja tidak melakukan target I/O.

Hasil dikirim ke endpoint job yang sama:

`POST /api/jobs/{job_id}/result`

```json
{
  "status": "COMPLETED",
  "execution_id": "stage6-exec-…",
  "result": {
    "mission_id": "mission-gmo-…",
    "task_id": "ptask-…",
    "target": "https://target.example",
    "evidence": {
      "capture_status": "SEALED",
      "manifest_sha256": "<64 hex chars>",
      "evidence_ref": "sealed://…"
    }
  },
  "result_sha256": "<sha256 canonical JSON result>"
}
```

`result_sha256` adalah SHA-256 atas `result` sebagai UTF-8 JSON dengan key terurut, separator compact `,` dan `:`, dan `ensure_ascii=false`. WPT memeriksa hash tersebut, kecocokan execution ID, mission/task/target wajib, status evidence `SEALED`, hash manifest, serta referensi evidence sebelum menyimpan hasil. Hasil tersimpan bersama hash dan evidence reference; status intake dan job berubah ke status terminal hanya setelah callback hasil valid. Callback hasil tidak menerima body respons, cookie, token, atau kredensial mentah.

## E. Callback contract yang digunakan UI service

`POST /api/jobs/{job_id}/deliveries/{reconnaissance|enumeration}`

```json
{"delivery_id":"<durable event or iteration ID>"}
```

Header: `X-APTS-Client-Token`. Status hasil mencakup `NOT_SENT` atau `DELIVERED`; failure/retry dapat diperluas menjadi `FAILED`, `RETRYING`, atau `ACKNOWLEDGED`. Gunakan outbox + idempotent consumer di APTS untuk menjamin retry tidak menggandakan iterasi agent.

## F. Acceptance gate sebelum target I/O

- Governance unavailable/deny/review/expired/revoked → tidak ada target I/O.
- Scope mismatch atau URL redirect ke luar scope → tidak ada follow-up request.
- Capability/profile/parameter tidak cocok dengan action fingerprint → reject.
- Replay idempotency → hasil historis dikembalikan; tidak melakukan scan ulang.
- Stage 6 evidence tidak SEALED/hash invalid → tidak diteruskan ke agent.
- Recon delivery dan Enumeration delivery tercatat independen, dengan acknowledgement yang sesuai.
- Hasil profiler hanya observation/technology claims/surface candidates; tidak menetapkan CVE atau vulnerability validated.

## G. Mode Mandiri WTP (loopback atau remote allowlist)

Mode ini menghilangkan keharusan mengisi Mission ID/Task ID. Pengguna harus mengonfirmasi kewenangan untuk setiap scan. Loopback diizinkan; target remote hanya diterima bila authority target exact-match dengan `WTP_REMOTE_ALLOWLIST`, yang kosong secara default. Entri dapat berupa hostname/IP (semua port) atau hostname/IP:port; wildcard tidak didukung. Fingerprinting memakai dua GET tetap (`/` dan `/favicon.ico`), dengan batas 256 KiB HTML dan 64 KiB favicon; enumeration memakai daftar tetap paling banyak 5 GET/HEAD request. Timeout 3 detik per request. Fragment URL seperti `/#/` dihapus sebelum request. Maksimal dua redirect hanya di origin dan prefix path yang sama; proxy dinonaktifkan dan kredensial URL ditolak. Hasil memiliki timestamp UTC dan konteks `LOCAL_STANDALONE_LOOPBACK` atau `LOCAL_STANDALONE_REMOTE_ALLOWLIST`, disimpan di ledger WTP, dan tidak ditandai sebagai Governed/Stage 6 evidence atau dianggap terkirim ke Recon/Enumeration.

Atur allowlist pada environment sebelum menjalankan WTP, misalnya `WTP_REMOTE_ALLOWLIST=lab.example.test,192.0.2.10:8443`. Bind UI/API WTP sendiri tetap harus dilindungi secara terpisah; `WTP_REMOTE_ALLOWLIST` hanya mengatur target outbound standalone.
