# Pemulihan WPT ke server internal — 9 November 2026

Operator memilih server internal `172.21.2.2` dan secara eksplisit mengizinkan IP itu dalam scope.

## Perbaikan scope dan task

Scope GSS Mission `mission-gmo-57851fd3-1f64-436f-b713-0b49e839bcc2` direvisi via API konsol terautentikasi dari versi 1 ke versi 2 (`scope-ce9bc706-9ae0-4266-9501-548fdd4b1e20`). Target URL tetap `https://kurikulum.del.ac.id:443`, dengan satu IP tambahan tepat `172.21.2.2`. Aturan aksi tetap bounded WPT: LOW, maksimal enam GET, read-only, tanpa perubahan state. DNS sistem dan pemeriksaan TLS tidak diubah.

Scope diproyeksikan ke Mission dan binding Governance diperbarui. Task lama immutable dipertahankan; lifecycle ditutup ABORTED dengan alasan SCOPE_SUPERSEDED. Operator membuat task pemulihan `pentest-task-wpt-kurikulum-internal-20261109` melalui API task resmi. PIP consumer diturunkan dari artifact CTI asli setelah verifikasi hash, quality gate dan deklarasi target; batas scope consumer diikat ke scope baru, tanpa mengklaim observasi target baru. Referensi otorisasi berasal dari keputusan GSS ALLOW baru. Orchestration lokal aktif.

## Bug antrean yang diperbaiki

`_unobserved_recon_targets` membandingkan semua deklarasi Recon dengan set scope yang hanya memuat URL. Kehadiran deklarasi IP yang sah membuat seluruh scope ditolak. Pembanding kini memeriksa semua jenis target yang dideklarasikan. Pemilihan WPT tetap memfilter URL sesudah verifikasi hash, provenance, status dan scope. IP yang tidak dideklarasikan tetap ditolak. Tes regresi mencakup scope campuran serta penolakan IP yang tidak diizinkan.

## Hasil eksekusi aktual dan batas

Job baru `wpt-4e6a99b29d7bbf9f15a73ddbeb92ad6d`, execution `exec-44f379e336b26997f6e59d423cec9fcd`, attempt `xattempt-e1db853a9ccf5b4290c618e88d60b8e8`.

Governance ALLOW dan seluruh execution checks PASS. Ketiga lapisan scope berisi URL dan IP internal tepat. Runtime berhasil mem-pin `kurikulum.del.ac.id` ke `172.21.2.2:443`; penolakan RESOLVED_ADDRESS_OUTSIDE_SCOPE sudah teratasi.

Status akhir runtime ABORTED / WPT FAILED: `RUNTIME_GOVERNANCE_REVALIDATION_STALE`. Pemeriksaan ulang Governance melewati batas delapan detik; penyebab keterlambatan di dalam jalur revalidasi belum dipastikan. Hasil adapter mencatat `target_network_io_performed=true`, yang berarti I/O dicoba, bukan bukti koneksi atau respons berhasil. Tidak ada hasil HTTP/TLS/fingerprint, sealed observation atau pengiriman Recon yang diklaim. Resource ditutup; runtime menyatakan explicit retry tidak memenuhi syarat. Tidak ada retry atau penambahan budget setelah percobaan ini. Pemulihan fingerprint belum selesai.

Mission worker kembali berjalan. Riwayat job lama tetap FAILED sesuai bukti historis. Pesan UI kini menjelaskan penolakan DNS/scope serta penghentian revalidasi Governance.

## Validasi

21 tes Mission terkait lulus (preparation, prequeue, initial observation, scope projection). JavaScript syntax lulus. Satu tes callback semula gagal akibat pembatasan socket sandbox; tes yang sama dan suite terkait lulus saat diberi akses fixture loopback. Suite penuh tidak dijalankan.

Backup SQLite sebelum revisi dan payload API tersedia di `D:/APTS/backups/wpt-kurikulum-internal-20261109`. Bukti tersaring: `wpt-kurikulum-internal-verified-20261109.json`. Script pemulihan sekali jalan ada di `.mission-recovery`; jangan dijalankan ulang, karena identitas task dan request telah disimpan immutable.
