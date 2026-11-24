# Stage 6.4 — Authorized Tool Adapters & Sandboxing

Patch ini menambahkan lima fixed adapters, centralized tool-invocation gateway,
append-only execution claim/result, Execution migration 4, native resource sandbox,
bounded target broker, dan credential lease server yang single-use.

Target I/O memerlukan dua revalidation GSS fresh; check kedua dilakukan tepat
sebelum connect dan memeriksa lagi source, expiry, policy, lease, dan IP pin.
Caller tidak dapat menyisipkan command, parameter target, ALLOW, atau credential.
Reservasi atomic menegakkan concurrency, rate, action/network budget dan lifetime
duration. Crash/replay tidak melakukan dispatch ulang. Target responses hanya
menjadi metadata/digest; keberhasilan primitive tidak membuktikan vulnerability.

Source historis Mission/Pentest/Execution Stage 3–6.3 tidak diubah. API/kontrak
historis dan audit tetap tersedia. Migration 4 menutup INSERT admission gateway
lama untuk mencegah proses Stage 6.3 melewati budget adapter. Runner Stage 6.4
menggunakan port Execution 8791. Mission 53 dan Pentest 16 tetap read-only.

aptsGSS harus menerima patch pasangannya: baseline GSS yang disediakan belum
menghasilkan execution attestation yang sudah diwajibkan oleh Stage 6.2.
Patch GSS menghasilkan check authoritative sebelum decision hash; tidak
memerlukan schema SQL baru dan tidak mengubah request generic CTI/Stage 2.

Hasil build: 2469 tes Mission (64 kelompok proses), 58 tes GSS, native Linux
sandbox, dan tiga cross-plane boundary scenarios PASS. PowerShell, Windows Job
Object, production MySQL, dan live user mission belum dieksekusi oleh build.
Ikuti README_STAGE6_4.md dan gate host STAGE6_4_ACCEPTANCE.ps1.
