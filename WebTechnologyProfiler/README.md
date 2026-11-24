# Web Technology Profiler

Prototipe layanan/UI terpisah untuk meminta **Web Technology Fingerprinting** dan **bounded web-surface enumeration**, memantau job, dan mencatat delivery status ke Reconnaissance Agent serta Enumeration Agent.

## Temuan kritis dari paket APTS 15 Oktober 2026

Paket Mission sudah memiliki alur Recon → Action Request → Governance/Stage 6 → sealed evidence → Recon iteration. Stage 6 saat ini mempunyai fixed immutable registry dengan adapter `web.http-head.v1` (`HTTP_HEADER_INSPECTION`) dan `network.tcp-banner.v1`, namun belum mempunyai action tuple khusus `web_technology_fingerprinting` atau `web_surface_enumeration`. Registry juga tidak memiliki API untuk memasang adapter dinamis. Maka aplikasi ini **fail-closed**: tombol Dispatch tidak menjalankan scan bila adapter baru belum didaftarkan pada Mission Stage 6. Mode APTS UI tidak pernah membuat request langsung ke target. Mode Mandiri menjalankan probe terbatas setelah konfirmasi operator ke loopback atau ke host remote yang persis tercantum di allowlist WTP; mode ini tidak menerbitkan bukti Stage 6.

Aplikasi ini merupakan deployment terpisah yang mencakup UI, job ledger, integrasi API, dan pure profile engine (`adapters/profile_engine.py`). Untuk mengaktifkan target I/O sungguhan, tambahkan adapter tetap pada Mission Stage 6 dan kontrak Action Request/Governance yang mengikat mission, task, target, mode, teknik, request budget, expiry, dan evidence. Lihat `APTS_INTEGRATION.md`.

## Fitur UI

- Execution context APTS governed atau Mandiri. Mode Mandiri tidak meminta Mission ID/Task ID; target remote perlu allowlist exact-host dan konfirmasi operator. Admin dapat menambah atau menghapus entri melalui panel **Target Remote**; konfigurasi `WTP_REMOTE_ALLOWLIST` tetap didukung sebagai entri environment hanya-baca. Default allowlist kosong, sehingga target remote nonaktif sampai admin mengaturnya.
- Job ledger mencatat konteks eksekusi, mission/task (kosong untuk mode lokal), target, execution ID, dan hasil terstruktur. Fragment SPA seperti `/#/` dibuang karena tidak dikirim dalam HTTP request.
- Status delivery terpisah untuk Recon dan Enumeration; hanya berubah ke `DELIVERED` melalui callback APTS terautentikasi dengan `delivery_id`.
- Menampilkan kondisi dispatch capability Stage 6.
- UI polling 5 detik dan detail job. Detail job memiliki **Ringkasan target** untuk konteks awal pentest: stack dan bukti teknologi, URL akhir/redirect, title/status, aset framework, nama cookie, favicon hash, TLS, dan header keamanan terpilih. Nilai “tidak terlihat” hanya berlaku pada respons yang diprobe; panel bukan pemindai kerentanan.
- Fingerprinting v2 memberi metrik cakupan respons, jumlah header, jumlah signature cocok, indeks kekuatan bukti 0–100, keluarga bukti pendukung, dan versi hanya saat tertulis eksplisit pada metadata. Signature juga mengenali pola aset Yii Framework dan cookie sesi `PHPSESSID`; hasil melabeli Nginx sebagai web server/reverse proxy, bukan framework aplikasi. Informasi TLS `UNAVAILABLE` menjelaskan bahwa metadata tidak tertangkap dan bukan kegagalan validasi sertifikat.

## Metode fingerprinting terukur

Fingerprinting menjalankan dua GET tetap: halaman root (maksimum 256 KiB) dan `/favicon.ico` (maksimum 64 KiB). Redirect dibatasi maksimal dua hop per probe, hanya pada origin yang sama dan di bawah prefix target; tidak ada fuzzing, payload, atau perubahan state. Mesin normalisasi mencocokkan header HTTP (`Server`, `X-Powered-By`, `X-Generator`, header framework), nama cookie saja, metadata dan judul HTML, atribut, pola skrip/aset/runtime CMS/framework, serta pola URL redirect seperti `;jsessionid`. Nilai session ID pada URL di-redact sebelum disimpan. Body favicon tidak disimpan; SHA-256 hanya dibuat untuk konten berjenis gambar, sehingga halaman HTML fallback atau halaman login tidak keliru dianggap favicon.

Skor berbasis aturan deterministik per produk: bobot indikator terkuat + 12 untuk setiap indikator unik tambahan + 8 untuk setiap keluarga bukti tambahan, maksimum 100. Pita low/medium/high adalah interpretasi skor, bukan probabilitas statistik. Versi dicatat hanya jika muncul eksplisit pada metadata. Bukti berisi ID sinyal, sumber, nilai singkat, dan bobot.

Waktu scan disimpan dalam UTC pada job dan hasil: waktu mulai, selesai, total durasi, serta waktu mulai/terima dan latensi setiap request. `scan_metrics` juga membedakan request direncanakan, respons diterima, tingkat respons, error, header, HTML, jumlah fingerprint dan favicon hash. Status scan `COMPLETED`, `PARTIAL`, atau `NO_RESPONSE`; standalone tanpa respons menjadi job `FAILED`. Body HTML, nilai cookie, token, dan materi autentikasi tidak disimpan. Tidak adanya signature pada halaman yang diperiksa bukan bukti teknologi tidak digunakan.

Untuk target HTTPS, WTP mencatat protokol TLS dan cipher yang dinegosiasikan serta subject, issuer, SAN, masa berlaku, dan SHA-256 sertifikat dari handshake pada koneksi HTTP yang sama. TLS tidak divalidasi dalam mode mandiri (status selalu `NOT_VALIDATED`), sehingga data ini adalah observasi fingerprinting, bukan bukti bahwa sertifikat dipercaya. Untuk HTTP, hasil menandai `NOT_APPLICABLE_HTTP`; tidak ada sertifikat maupun TLS yang dapat diambil. Adapter Stage 6 harus meneruskan metadata yang sama dari koneksi target yang diotorisasi, tanpa handshake tambahan di luar broker.

## Penanganan redirect dan kegagalan WebGoat

Mode mandiri mengikuti paling banyak dua redirect hanya jika origin (skema, host, dan port) sama dan path tetap berada di bawah prefix target. Jadi target `http://localhost:8080/WebGoat` dapat mengikuti redirect ke `/WebGoat/login`, tetapi tidak ke host lain atau path di luar `/WebGoat`. Redirect di luar scope dicatat sebagai HTTP 3xx yang diblokir; koneksi gagal/timeout dibedakan dan diberi diagnosis. Remote scan hanya diizinkan untuk host exact-match pada allowlist WTP (hostname/IP, opsional port, atau URL HTTP(S)); wildcard tidak didukung. UI menyimpan entri yang dikelola operator ke tabel `remote_allowlist` pada SQLite WTP; entri environment tetap terlihat tetapi tidak bisa dihapus dari UI. Operasi admin hanya dapat diakses dari loopback atau dengan `WTP_CLIENT_TOKEN` saat akses dari komputer lain. Request dibatasi pada probe pasif HTTP GET/HEAD dari profile engine, tanpa autentikasi atau fuzzing. Set allowlist kosong secara default. Jika target menghasilkan `NO_RESPONSE`, pastikan target dapat dicapai dari host/network namespace tempat WTP berjalan.


Scan WebGoat terbaru pada arsip menghasilkan HTTP 200 untuk halaman login setelah satu redirect; probe favicon menerima 302 kembali ke halaman login dengan `;jsessionid`. Ini menunjukkan WTP tersambung dengan baik, tetapi aplikasi meminta halaman login dan favicon tidak tersedia untuk sesi tersebut. WTP menandai favicon `REDIRECTED`, tidak membuat hash dari respons itu, dan memakai pola URL session tracking sebagai indikator `Java Servlet` tingkat sedang; ini tidak cukup untuk menyimpulkan produk WebGoat atau versinya secara pasti. Dua record WebGoat sebelumnya tetap tersedia dan mencatat `0/2` respons saat port belum memberi respons.

## Dasar metode

Metode multi-marker mengikuti OWASP WSTG: header HTTP, nama cookie, source HTML, path/file spesifik, dan beberapa indikator independen lebih andal dibanding satu banner saja. WTP menghilangkan nilai cookie dan membatasi path tetap agar data sensitif serta request berlebih tidak ikut terkumpul. Timestamp lokal disimpan terpisah dari header `Date` server: RFC 9110 mendefinisikan `Date` sebagai waktu asal pesan HTTP, bukan waktu pemindaian oleh WTP.

- OWASP WSTG, [Fingerprint Web Application Framework](https://wstg.owasp.org/stable/4-Web_Application_Security_Testing/01-Information_Gathering/08-Fingerprint_Web_Application_Framework/)
- OWASP WSTG, [Fingerprint Web Server](https://wstg.owasp.org/stable/4-Web_Application_Security_Testing/01-Information_Gathering/02-Fingerprint_Web_Server/)
- OWASP WSTG, [Testing for Weak Transport Layer Security](https://owasp.org/www-project-web-security-testing-guide/v42/4-Web_Application_Security_Testing/09-Testing_for_Weak_Cryptography/01-Testing_for_Weak_Transport_Layer_Security/)
- Python, [SSL module: peer certificate, negotiated version, and cipher](https://docs.python.org/3/library/ssl.html)
- IETF, [RFC 9110, Section 6.6.1 Date](https://www.rfc-editor.org/rfc/rfc9110.html#name-date)

## Menjalankan (Windows PowerShell)

```powershell
cd D:\WebTechnologyProfiler
$env:WTP_HOST = "127.0.0.1"
$env:WTP_PORT = "8791"
python .\app.py
```

Buka `http://127.0.0.1:8791`. Python 3.10+; hanya standard library.

## Inbox target Mission otomatis

Panel **Target Mission** menampilkan URL Recon yang diteruskan Mission secara idempoten. Sebelum task Pentest aktif, WPT menampilkan `AWAITING_PENTEST_TASK`; ini hanya prequeue untuk visibilitas dan tidak menjalankan target I/O. Setelah Mission mengonfirmasi task Pentest `RUNNING` dan satu orchestration aktif, row yang sama dipromosikan menjadi `AWAITING_STAGE6`. Pemindaian tetap memerlukan capability dan otorisasi Stage 6.

Atur `WTP_CLIENT_TOKEN` yang sama dengan `APTS_WPT_INBOX_TOKEN` pada Mission; gunakan rahasia acak minimal 32 karakter. Atur `APTS_WPT_INBOX_URL` di Mission ke base URL WPT (loopback HTTP atau HTTPS). WPT menolak POST inbox tanpa token layanan valid dan UI menyegarkan daftar setiap lima detik.

## Konfigurasi integrasi

Setelah endpoint dispatcher Stage 6 resmi terpasang:

```powershell
$env:APTS_WTP_DISPATCH_URL = "http://127.0.0.1:<port>"
$env:APTS_WTP_DISPATCH_TOKEN = "<shared secret dari konfigurasi lokal>"
$env:WTP_CLIENT_TOKEN = "<secret untuk callback APTS>"
```

Jangan mengekspos server ke jaringan publik. Bind default hanya ke loopback. Bind non-loopback ditolak kecuali `WTP_ALLOW_REMOTE=true`; gunakan hanya di belakang HTTPS, autentikasi, dan kontrol akses.

## Status

- UI, REST API, job persistence, lifecycle/status display, callback delivery, dispatcher fail-closed, profile response normalizer, dan standalone scanner terbatas ke loopback atau host remote allowlist: diimplementasikan.
- Integrasi **native** dengan Recon/Enumeration Stage 6 Mission untuk target non-loopback: belum aktif karena capability/route khusus belum ada pada paket sumber yang diberikan. Proyek ini tidak mengklaim status APTS terhubung sebelum acceptance test lintas sistem lulus.
