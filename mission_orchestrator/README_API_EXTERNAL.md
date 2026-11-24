# Vulndesk_Web v1.1 — Pengelolaan API eksternal sumber CTI

Pembaruan berdasarkan `Vulndesk(20261006-015355).zip` dan skema `Vulndesk(20261006-015401).sql`. Menu **API Eksternal** menambahkan pengelolaan sumber CTI yang tersimpan pada database.

## Fungsi yang tersedia

| Fungsi | Perilaku |
| --- | --- |
| Lihat API | Daftar nama, Source ID, endpoint, adapter, status aktif, referensi autentikasi, dan kesehatan akuisisi; detail konfigurasi serta parameter |
| Tambah API | Form sumber baru dengan endpoint HTTPS, format data, autentikasi, dan parameter adapter; Source ID duplikat ditolak |
| Ubah API | Ubah nama, endpoint, adapter, referensi environment, timeout, batas halaman, collection/CWE ID, SLA, criticality, dan status aktif |
| Hapus API | Konfirmasi Source ID dan penghapusan dari registry; data CTI serta riwayat yang sudah tersimpan tetap tersedia |
| Cari / filter | Pencarian nama, Source ID, endpoint, deskripsi; filter status aktif dan adapter; pagination |
| API bawaan | Pilihan NVD CVE, NVD CPE, MITRE ATT&CK, dan MITRE CWE untuk didaftarkan melalui form |

API yang menggunakan format NVD CVE 2.0, NVD CPE 2.0, TAXII 2.1 ATT&CK, atau MITRE CWE REST dapat memakai adapter yang tersedia. Endpoint yang sekadar menghasilkan JSON dengan struktur berbeda tidak otomatis kompatibel. Pilih **Registry saja** untuk mencatat API tersebut; pemrosesan datanya memerlukan adapter tambahan. Label ini terlihat pada daftar dan form.

## Memasang paket perubahan di Windows

1. Ekstrak `Vulndesk_Web_API_External_Patch.zip` ke folder sementara, misalnya `D:\Temp\Vulndesk_API_Update`.
2. Hentikan **Vulndesk_Web** dan **Vulndesk CTI API** melalui APTS_Control_Center atau terminal masing-masing. Pastikan akuisisi tidak sedang berjalan saat mengganti source.
3. Jalankan PowerShell:

   ```powershell
   cd D:\Temp\Vulndesk_API_Update
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
   .\INSTALL_API_EXTERNAL.ps1 -VulndeskRoot D:\Vulndesk
   ```

   Installer memeriksa hash baseline untuk berkas yang akan diganti, membuat cadangan, dan memasang berkas perubahan. Berkas konfigurasi lokal seperti `config.json` dan `.env` tidak masuk paket perubahan. Berkas yang sudah sama dengan versi baru dapat dipasang ulang. Jika baseline berbeda, installer berhenti sebelum menulis agar perubahan lokal dapat diperiksa.

   Bila Web App berada di direktori terpisah:

   ```powershell
   .\INSTALL_API_EXTERNAL.ps1 -VulndeskRoot D:\Vulndesk -WebRoot D:\Vulndesk_Web
   ```

4. Jalankan kembali CTI API dan Vulndesk_Web dari APTS_Control_Center. Untuk Web App saja:

   ```powershell
   cd D:\Vulndesk\Vulndesk_Web
   python -m pip install -r requirements-web.txt
   python server.py --vulndesk-root D:\Vulndesk
   ```

5. Buka **http://127.0.0.1:8801/#sources**. Muat ulang halaman bila server sebelumnya masih terbuka di browser.

Paket lengkap yang diperbarui juga tersedia sebagai versi terbaru `Vulndesk(20261006-015355).zip`. Untuk instalasi yang sudah berjalan, gunakan paket perubahan agar konfigurasi lokal tetap terjaga.

## Menggunakan menu API Eksternal

1. Pilih **Tambah API**, atau **Daftarkan API** pada salah satu pilihan bawaan.
2. Isi nama dan Source ID. ID menjadi identitas pada riwayat sehingga tetap sama saat mengubah konfigurasi.
3. Pilih format adapter. Isi URL dasar HTTPS tanpa username, password, query, fragment, atau API key pada URL.
4. Pilih autentikasi. Referensi environment menerima bentuk `env:NVD_API_KEY`, `env:MY_CTI_API_KEY`, atau `env:MY_CTI_TOKEN`. Nilai rahasia diatur pada environment / `.env` server Vulndesk. Restart CTI API setelah nilai environment diubah. NVD dapat memakai akses anonim ketika API key belum tersedia.
5. Sesuaikan parameter yang muncul. NVD: batas halaman dan ukuran halaman; CPE: keyword / match string; ATT&CK: collection dan mode sinkronisasi; CWE: satu CWE ID seperti `CWE-79`.
6. Aktifkan sumber dan simpan. Pilih **Lihat** untuk detail, **Ubah** untuk perubahan berikutnya, atau ikon hapus untuk penghapusan.

Sumber aktif dengan adapter tersedia muncul pada dropdown **Misi akuisisi CTI**. Menyimpan konfigurasi API tidak membuat misi atau mengunduh data. Akuisisi tetap melalui orchestrator CTI dan evaluasi scope / kebijakan aptsGSS.

Proposal baru menyimpan binding konfigurasi sumber. Connector membaca registry kembali sebelum memanggil client: sumber yang telah dihapus, dinonaktifkan, atau berubah setelah proposal akan ditolak. Buat misi baru setelah mengubah konfigurasi sumber yang memiliki proposal tertunda.

## Penyimpanan dan kompatibilitas

- Menggunakan tabel `cti_source_registry` dan `cti_source_state` yang sudah terdapat pada skema unggahan. Tidak diperlukan migrasi SQL baru. Akun Web App memerlukan SELECT, INSERT, UPDATE, DELETE pada registry sumber, serta SELECT pada state sumber.
- Endpoint legacy seperti `config:NVD_CVE_API` dan credential reference `secret-ref:NVD_API_KEY` tetap dapat dibaca. Saat disimpan melalui form, endpoint menjadi URL eksplisit dan referensi kredensial dinormalisasi menjadi `env:…`.
- Field tambahan pada `config_json` lama tetap dipertahankan; parameter adapter yang tidak lagi berlaku dibersihkan ketika adapter berubah. Nilai API key dan konfigurasi tersembunyi tidak dikembalikan pada endpoint pengelolaan API.
- Setiap update/delete membawa versi sumber. Perubahan oleh operator lain menghasilkan pesan konflik sehingga tidak ditimpa.
- Penghapusan menghapus konfigurasi registry. Katalog CTI, audit, dan riwayat state sumber tetap disimpan. Sinkronisasi desktop tetap membaca `Config` / `.env`; UI ini mengelola jalur registry akuisisi CTI.
- Sumber kompatibel NVD menggunakan katalog dan checkpoint `SyncService` yang sudah ada. Penambahan Source ID tidak membuat penyimpanan atau checkpoint NVD terpisah.
- Paket ini mengubah Vulndesk dan Web App. Tidak ada perubahan source pada Mission, aptsGSS, atau APTS_Control_Center.

## Verifikasi

Pengujian yang dijalankan pada lingkungan pembangunan:

| Pemeriksaan | Hasil |
| --- | --- |
| Tes Python seluruh direktori `tests` dan `Vulndesk_Web/tests` | 178 passed; 31 subtests passed |
| Tes browser Chromium untuk UI API | 13 passed |
| Kompilasi Python dan pemeriksaan syntax JavaScript | Lulus |

Tes browser mencakup daftar/detail, tambah, ubah, hapus, validasi URL, ID duplikat, konflik versi, filter, pendaftaran CWE, dropdown misi, escaping HTML, mode contoh, serta tampilan seluler. Server pengujian memakai database SQLite sementara. Tes connector memakai layanan sumber sintetis dan tidak melakukan akuisisi eksternal.

MariaDB aktif, locking lintas proses pada MariaDB, runtime Windows Bapak, dan akuisisi API publik dengan scope aptsGSS aktual belum diuji di lingkungan pembangunan. Gambar pratinjau dalam paket memakai **DATA CONTOH**.

Untuk tes adapter tanpa database produksi:

```powershell
cd D:\Vulndesk\Vulndesk_Web
python -m unittest discover -s tests -v
```

Untuk tes browser, pasang Node.js dan Playwright pada folder pengujian:

```powershell
cd D:\Vulndesk\Vulndesk_Web
npm install --no-save playwright
npx playwright install chromium
node --test tests/test_sources_ui.cjs
```

Tes browser memulai server fixture terpisah pada port bebas; tidak menggunakan database Vulndesk yang aktif.
