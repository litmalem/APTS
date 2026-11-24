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
2. WPT hanya mengajukan job yang memiliki Mission ID dan Task ID melalui intake terautentikasi. Target/izin tetap diperiksa terhadap task aktif, Mission scope, RoE, dan budget di Mission. Tidak ada jalur pemindaian mandiri.
3. **Belum diimplementasikan pada paket ini:** intake harus menjadi canonical Execution Request; Governance menilai otorisasi dan approval; gateway/runtime memanggil adapter Stage 6 tetap setelah revalidation.
4. **Belum diimplementasikan:** adapter menjalankan profil melalui sandbox + target broker, menormalisasi evidence, menyegel hasil, dan mengembalikan execution/result IDs.
5. **Belum diimplementasikan:** Recon/Enumeration menerima observation melalui endpoint iteration resmi dengan durable acknowledgement yang mengikat action/result ID dan evidence hash.
6. UI hanya menampilkan status setelah menerima durable response/ack. `DELIVERED` tidak diatur dari browser.

## D. Callback contract yang digunakan UI service

`POST /api/jobs/{job_id}/deliveries/{reconnaissance|enumeration}`

```json
{"delivery_id":"<durable event or iteration ID>"}
```

Header: `X-APTS-Client-Token`. Status hasil mencakup `NOT_SENT` atau `DELIVERED`; failure/retry dapat diperluas menjadi `FAILED`, `RETRYING`, atau `ACKNOWLEDGED`. Gunakan outbox + idempotent consumer di APTS untuk menjamin retry tidak menggandakan iterasi agent.

## E. Acceptance gate sebelum target I/O

- Governance unavailable/deny/review/expired/revoked → tidak ada target I/O.
- Scope mismatch atau URL redirect ke luar scope → tidak ada follow-up request.
- Capability/profile/parameter tidak cocok dengan action fingerprint → reject.
- Replay idempotency → hasil historis dikembalikan; tidak melakukan scan ulang.
- Stage 6 evidence tidak SEALED/hash invalid → tidak diteruskan ke agent.
- Recon delivery dan Enumeration delivery tercatat independen, dengan acknowledgement yang sesuai.
- Hasil profiler hanya observation/technology claims/surface candidates; tidak menetapkan CVE atau vulnerability validated.

## F. Stage 6 saja (status paket ini)

WPT tidak menjalankan pemindaian langsung dan tidak memiliki mode standalone. `POST /api/jobs` hanya membuat proposal; `POST /api/jobs/{job_id}/dispatch` mengirim strict intake ke Mission (`POST /api/wpt/intakes`) menggunakan bearer token, idempotency key, Mission ID, Task ID, URL target, dan profil. Mission memvalidasi scope/RoE/task/budget dari sumber otoritatifnya.

Pada paket Mission yang diperiksa, kedua profil WPT masih `REGISTERED_NOT_EXECUTABLE`. Intake Mission menghasilkan `ACCEPTED_PENDING_STAGE6` dan tidak melakukan dispatch atau target I/O. WPT menampilkan status `AWAITING_STAGE6`; status ini bukan bukti bahwa pemindaian telah berjalan. Backend WPT akan menerima hasil hanya melalui callback terautentikasi dengan execution ID dan sealed evidence. Aktivasi pemindaian menunggu implementasi fixed Stage 6 adapter/worker yang memakai profile engine di sandbox, target broker, request/byte/time budgets, no-redirect policy, dan sealed evidence.

Konfigurasi `APTS_WTP_DISPATCH_URL` menunjuk ke base URL Mission dan `APTS_WTP_DISPATCH_TOKEN` harus sama dengan `MISSION_WPT_INTAKE_TOKEN` (minimum 32 karakter). `WTP_REMOTE_ALLOWLIST` dan API allowlist standalone tidak lagi digunakan; target hanya ditentukan melalui Mission/task scope.
