# WPT kurikulum berhasil — 9 November 2026

Target `https://kurikulum.del.ac.id:443`, tujuan internal yang disetujui operator `172.21.2.2`.

## Penyebab kegagalan terbaru

Job `wpt-6201d2da8ed77275d986c3bece643c66` berasal dari Mission baru `mission-gmo-887dae4f-1611-4b07-8ee7-7f184b7379be`. Scope GSS versi 1 pada Mission ini hanya berisi URL; izin IP internal yang diterapkan sebelumnya milik Mission berbeda. Karena DNS lokal mengembalikan alamat RFC1918, broker kembali menolak dengan `RESOLVED_ADDRESS_OUTSIDE_SCOPE`. Otorisasi pada Mission lama tidak otomatis berlaku pada Mission baru.

## Perbaikan

Dengan persetujuan IP internal yang sudah diberikan dalam chat, scope Mission baru direvisi melalui API Governance menjadi versi 2 (`scope-6553576a-6e12-4a27-af10-297ea0600bf5`), menambahkan hanya IP `172.21.2.2`. Aturan aksi tetap enam GET, LOW, read-only dan tanpa perubahan state. Scope Mission dan binding Governance disinkronkan.

Task lama ditutup ABORTED dengan journal SCOPE_SUPERSEDED. Task pemulihan immutable `pentest-task-wpt-kurikulum-internal-20261109b` dibuat melalui API Pentest dengan PIP CTI asli yang telah diverifikasi serta keputusan GSS ALLOW baru. Scope URL+IP tepat diteruskan ke task dan boundary Pentest. Mission worker kemudian menjalankan WPT melalui Stage 6 normal. Tidak ada perubahan DNS sistem, pelemahan validasi TLS, atau retry terhadap attempt lama yang sudah melakukan I/O.

## Hasil terverifikasi

- Job: `wpt-d30854c7129a1b17b634f17c6a49b04e`.
- Runtime: SUCCEEDED; WPT: COMPLETED; collection: COMPLETED.
- Execution: `exec-c9e53640bc68c2d3d0c13bfc32f230c5`.
- Attempt: `xattempt-3f3977b7cec54a0a5d95612a522afed9`.
- Peer IP: `172.21.2.2`; empat respons dari empat request dalam budget enam.
- Halaman akhir HTTP 200: `/auth/login`, judul `ITDel Kurikulum - Login`; dua redirect, tidak ada redirect diblokir.
- Indikator teknologi: Laravel (nama cookie XSRF-TOKEN), PHP/8.4.27 (header), nginx (header). Laravel merupakan indikasi berbasis satu marker, bukan kepastian produk/versi.
- Evidence SEALED: `stage6-evidence://xevidence-26a328e7157e1c59f690b0b123008f36`.
- Recon DELIVERED: `reconrun-a83a6fc7b458d128c284e10890efd26ea616c664cc45f348`.

Revalidasi Governance pada runtime aktif berhasil berulang selama scan. Pengukuran kontrol terpisah tanpa target I/O menghasilkan ALLOW dalam 0.093 detik (evaluasi GSS 0.023 detik). Kegagalan historis RUNTIME_GOVERNANCE_REVALIDATION_STALE tidak terulang pada percobaan ini; akar keterlambatan historis belum dibuktikan dan tidak diklaim sebagai bug yang telah diperbaiki.

Metadata TLS tidak tertangkap (UNAVAILABLE); ini bukan hasil uji kepercayaan sertifikat. Favicon memberi HTTP 200 tetapi tidak menghasilkan hash/signature. Riwayat job yang gagal tetap dipertahankan sebagai riwayat, bukan diubah menjadi sukses.

## Validasi dan artefak

Lima tes timeout-origin dan prequeue scope lulus. Tidak ada perubahan kode runtime pada pekerjaan lanjutan ini dan suite penuh tidak dijalankan. Backup database sebelum revisi, source scope, payload dan readback API berada di `D:/APTS/backups/wpt-kurikulum-internal-20261109b`. Bukti tersaring: `wpt-kurikulum-success-20261109.json`. Script sekali jalan bersufiks `20261109b.py` di `.mission-recovery` tidak boleh dijalankan ulang.

Untuk Mission berikutnya, scope juga harus mencantumkan URL ini dan IP `172.21.2.2` sebelum task Pentest dibentuk; izin tetap terikat pada masing-masing Mission.
