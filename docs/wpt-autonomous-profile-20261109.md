# Fingerprinting WPT otonom — 9 November 2026

## Penyebab

Mission baru `mission-gmo-f3ef7325-c13a-4a46-b9b6-d97b505b1433` memiliki scope GSS versi 1 dengan `action_constraints=[]`. Form scope memakai profil NONE secara default, sehingga tiap Mission baru dapat mengulang kebuntuan yang sebelumnya dipulihkan secara manual. Worker menolak pembentukan binding tanpa izin TARGET_RECON eksplisit; status WPT “Menunggu izin Recon” mencerminkan kondisi ini.

## Perbaikan aktif

Konsol Governance kini memakai pilihan AUTO. Untuk scope baru tanpa aturan tindakan, dengan semua target yang diizinkan berupa URL LAB, server memilih profil `WPT_FINGERPRINT_AUTONOMOUS_V1`. Profil menerbitkan izin Recon, web_technology_fingerprinting, dan AUTHORIZE_TARGET_EXECUTION khusus WEB_TECHNOLOGY_FINGERPRINT, LOW, maksimal enam GET. Delegasi dibatasi ke PENTEST:pentest.recon. Stage 6 tetap meminta keputusan Governance segar.

Scope dengan aturan operator tidak diberi grant default. Revisi mewarisi profil dari metadata predecessor yang tersimpan; NONE eksplisit dihormati. DENY/REVIEW/approval tidak diubah menjadi ALLOW. Profil ini tidak menambahkan validasi kerentanan, eksploitasi, atau akses CTI. API machine/internal tetap mempertahankan perilakunya.

Scope Mission yang tertahan direvisi melalui API konsol terautentikasi menjadi `scope-c250f7b4-d02a-4c69-8ea3-077a1dd45c2d`, versi 2. Target tetap `http://127.0.0.1:80//dvwa/`, LAB. Backup dan payload tersedia di `D:/APTS/backups/wpt-autonomous-profile-20261109`. Governance dan WPT sudah dimulai ulang. Mission mencapai RUNNING; task, orchestration, dan job WPT terbentuk otomatis.

## Hasil runtime awal

Attempt `xattempt-13b6ffe772a056bc28f709da12a7c79c` menjalankan target I/O tetapi berhenti ABORTED dengan `RUNTIME_GOVERNANCE_REVALIDATION_STALE`. WPT memproyeksikannya sebagai FAILED. Tidak ada fingerprint atau pengiriman Recon sukses yang diklaim.

Pemeriksaan kode menemukan timeout probe Governance dihitung dari waktu sebelum pembacaan konteks sumber. Perbaikan mengukur timeout dari saat probe diluncurkan, tanpa mengubah batas delapan detik atau pemeriksaan otorisasi. Dua tes deterministik memastikan pembacaan sumber tidak menghabiskan waktu probe dan probe yang benar-benar terlambat tetap dihentikan. Temuan ini belum dibuktikan sebagai satu-satunya penyebab kegagalan live.

Pada pemeriksaan awal, perbaikan runtime belum dimuat karena automatic approval review terkena batas penggunaan. Hambatan ini telah teratasi pada pekerjaan lanjutan. Attempt lama yang sudah melakukan I/O tetap disimpan sebagai riwayat.

## Penyelesaian terverifikasi

Stage 6 Runtime telah dimulai ulang dan memuat perbaikan timeout. Validasi melalui Human Layer dan API konsol resmi membuat satu Mission pengukuran baru, `mission-gmo-b4811cc9-7c67-4b38-b4e4-e3faff07f53c`, pada URL LAB yang sama. Pembuatan scope dengan aturan kosong dan tanpa pilihan profil menghasilkan profil WPT otomatis dari server, sehingga jalur default AUTO teruji secara live.

Validasi juga menemukan proyeksi scope tanpa expiry menghasilkan `end_at=null` dalam jendela waktu yang mensyaratkan timestamp. Proyeksi kini memakai `allowed_time_window=null` saat GSS tidak menetapkan expiry; validitas sumber tetap diperiksa dan batas durasi Mission tetap berlaku. Mission telah dimulai ulang untuk memuat perbaikan ini.

Worker otonom meneruskan PIP, planning, handoff Pentest, orchestration, otorisasi Stage 6, fingerprinting, penyegelan evidence, dan pengiriman hasil ke Recon. Hasil akhir:

- Runtime `SUCCEEDED`, satu attempt `xattempt-dbee279eaf65f3a369855809f8a07d87`.
- WPT `COMPLETED`, job `wpt-c5ac891459cd4a01bdc8d3052e2bb2aa`.
- Evidence `SEALED`; hasil tersimpan dengan seal terverifikasi.
- Recon `DELIVERED`, satu run `reconrun-6c691d55061c9807b26d521ac00fb5c11bbb83e0a6a26981` berstatus `COMPLETED`.
- Dua GET dari kuota enam menerima dua respons. Header menunjukkan Apache/2.4.58 dan PHP/8.0.30; favicon tertangkap.
- Koleksi `PARTIAL` karena redirect login tidak diikuti dalam batas path scope. Ini tidak menghalangi keberhasilan fingerprinting metadata dan bukan klaim seluruh aplikasi terobservasi.

Tidak dilakukan scan tambahan setelah keberhasilan ini. Tidak ada bypass retry atau perubahan catatan kegagalan historis. Manifest pengukuran: `wpt-autonomous-live-validation-20261109.json`.

## Validasi

- 47 tes profil/konsol Governance lulus dengan HTTP loopback.
- 11 tes lokal terkait runtime timeout, prequeue, routing, dan retirement lulus.
- 14 tes murni profil diulang setelah pemeriksaan akhir dan lulus; ini bagian dari pengujian Governance, bukan 14 tes tambahan yang berbeda.
- JavaScript syntax dan Python compile lulus.
- Pekerjaan lanjutan: 33 tes scope, timeout, prequeue dan routing lulus. Pemeriksaan Python compile juga lulus.
- Tes tambahan runtime/completion/evidence: 20 lulus dan enam gagal pada konstruksi VEP dengan `invalid VEP execution/evidence lineage`. Satu kegagalan representatif direproduksi pada proses tes terisolasi menggunakan implementasi timeout baseline, sehingga kegagalan itu bukan akibat perubahan origin timeout. Enam kegagalan VEP tambahan ini belum diperbaiki; suite penuh tidak dinyatakan hijau. Penyimpanan evidence dan hasil WPT serta pengiriman Recon live di atas tetap terverifikasi berhasil.

Bukti tersaring: `wpt-autonomous-profile-verified-20261109.json`.
