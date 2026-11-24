# WPT menunggu task Pentest — 9 November 2026

Target LAB: `http://127.0.0.1:80//dvwa/`. Mission: `mission-gmo-17a8fa8a-c6d9-4da5-aad2-0fc73113239c`.

Penyebab awal: scope GSS versi 1 mempunyai `action_constraints=[]`. Routing sudah terpilih tetapi binding otomatis mensyaratkan ALLOW TARGET_RECON eksplisit, sehingga task Pentest belum materialized dan Mission tetap PLANNING. WPT hanya menampilkan pesan menunggu task tanpa alasan policy.

Dengan persetujuan eksplisit pengguna, scope direvisi melalui API konsol terautentikasi. Versi 3 mengizinkan Recon dan WEB_TECHNOLOGY_FINGERPRINT pada URL LAB yang sama, LOW, tanpa approval tambahan, maksimum enam GET dan tanpa perubahan state. Delegasi hanya PENTEST:pentest.recon. Task dan orchestration berhasil terbentuk; Mission RUNNING. Scope/izin aksi lain tidak diperluas.

Revisi antara yang belum memuat aksi AUTHORIZE_TARGET_EXECUTION menghasilkan penolakan sebelum runtime, tetapi tetap menahan reservasi intake. Metode `retire_unadmitted` kini memverifikasi claim dan authorization immutable, menolak reservation/runtime/result, serta menyimpan proof append-only sambil menahan lock admission. Enam reservasi intake ditolak dilepas sebelum intake scope baru dibuat. Percobaan menggunakan ulang envelope lama ditolak oleh pemeriksaan binding; pendekatan itu tidak dipertahankan dalam kode akhir.

WPT menerima kode alasan policy pada prequeue; UI menjelaskan izin Recon yang hilang, DENY, approval, dan RoE. Replay memperbarui alasan hanya sebelum promosi dan tidak menurunkan status job. Prequeue lama untuk pengukuran yang sudah berjalan disembunyikan dari daftar aktif; `/api/governed-intakes?include_history=1` mempertahankan akses riwayat. Job retired lama dipetakan ke intake pengganti pada proyeksi UI.

Hasil runtime aktual: `FAILED / WEB_PROFILE_NO_RESPONSE`, attempt `xattempt-63ec73a8fff55056a2c3669055b5caed`, execution `exec-99d837f27716c972aab6524db24cda3e`. Governance memberikan ALLOW dan seluruh execution checks PASS; target I/O dicoba. Tidak ada listener lokal port 80; Docker Desktop Linux engine juga tidak tersedia. Tidak ada hasil fingerprint sukses atau pengiriman Recon yang diklaim. Tidak dilakukan retry setelah kegagalan dengan I/O ini. Layanan DVWA perlu dihidupkan dan eksekusi berikutnya harus melalui pemeriksaan Governance/budget normal.

Validasi: 30 tes Mission terkait dan 23 tes WPT lulus; Python compile dan JavaScript syntax lulus. Fixture readiness lama diperbarui agar menyertakan orchestration ACTIVE yang memang diwajibkan implementasi. Suite penuh tidak dijalankan.

Backup dan payload revisi: `D:/APTS/backups/wpt-waiting-policy-20261109` dan `D:/APTS/backups/wpt-waiting-execution-policy-20261109`. Bukti tersaring: `wpt-waiting-policy-verified-20261109.json`.
