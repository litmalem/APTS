# Perbaikan WPT dan fingerprinting otonom — 9 November 2026

Mission `mission-gmo-31538bcf-92cc-46be-8a94-a9179c496f4a`, target `http://localhost:8080/WebGoat`.

## Perubahan

- Broker mengizinkan loopback untuk hostname tepat `localhost` hanya jika URL dinyatakan sebagai LAB pada setiap lapisan scope. Hostname lain, DNS tujuan non-loopback untuk localhost, exclusion, network range, origin dan path tetap diperiksa.
- Loop pembentukan tiga recovery intake dihapus. Retry otomatis hanya untuk daftar kegagalan transient, dengan bukti runtime bahwa tidak ada I/O, resource sudah ditutup, dan batas tiga attempt. Retry memakai execution/intake/job yang sama dengan binding predecessor dan head hash serta otorisasi GSS baru. Penolakan scope tidak diulang otomatis.
- Callback membawa nomor dan ID attempt. Pesan attempt lama diabaikan; retry terotorisasi memperbarui job yang sama.
- Runtime menghitung reservasi network nol untuk attempt gagal yang terbukti tidak melakukan I/O dan sudah ditutup. Riwayat immutable tetap dipertahankan.
- Retirement intake recovery menyimpan bukti append-only, memverifikasi rantai runtime, melepas reservasi, dan menolak otorisasi ulang. Tiga recovery historis dipetakan ke job utama pada proyeksi WPT. Daftar default menampilkan job utama; `/api/jobs?include_history=1` dan endpoint job individual tetap menyediakan riwayat.

## Hasil operasional

Backup konsisten lima database dibuat sebelum pemulihan di `D:/APTS/backups/wpt-repair-20261109`. Tiga recovery dipensiunkan berdasarkan bukti tanpa I/O; 14 dari 20 reservasi dilepas. Job utama mempertahankan budget enam request.

Job `wpt-3033cd635b816320f1ab17dc1dd6512a` berhasil pada attempt 2: runtime SUCCEEDED, WPT COMPLETED, evidence SEALED, Recon DELIVERED. Recon run `reconrun-afd44751a2c5120284200413f265ac9b4049bcd61af447b4` berstatus COMPLETED. Pemulihan dilakukan melalui endpoint retry resmi dan pemeriksaan Governance, tanpa mengubah scope tersimpan.

Tiga respons HTTP diterima dari tiga request. Halaman aplikasi mengikuti satu redirect ke `/WebGoat/login` dan memberi indikator Java Servlet dari nama cookie JSESSIONID (evidence strength 55/100, bukan probabilitas). Koleksi tetap PARTIAL karena redirect favicon diblokir. Keberhasilan proses tidak menyatakan semua metadata atau semua probe lengkap. Tidak ada pemindaian ulang setelah hasil sukses.

## Validasi dan batas

- Regresi terkait: 120 passed, 7 deselected.
- WPT: 31 passed, termasuk pembaruan attempt pada satu job dan penolakan pesan lama.
- Retirement setelah pemeriksaan integritas akhir: 2 passed.
- Ledger runtime dan penolakan ketiga intake retired dibaca ulang; satu hasil dan satu Recon run terkonfirmasi.
- Suite luas juga dijalankan: tujuh kegagalan direproduksi terpisah dan belum diperbaiki dalam pekerjaan ini: satu readiness orchestration, satu watchdog heartbeat, empat ekspektasi migrasi versi 5 terhadap implementasi versi 9, dan satu fixture legacy adapter yang membuka repository runtime lebih baru. Suite keseluruhan belum hijau.

Bukti tersaring tersedia dalam `wpt-repair-verified-20261109.json`. Script pemulihan sekali jalan ada di `.mission-recovery/repair_wpt_20261109.py`; script menolak menimpa backup dan tidak untuk dijalankan ulang.
