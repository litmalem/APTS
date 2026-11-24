# Database governance SQLite ? 6 November 2026

aptsGSS sekarang menggunakan `D:/APTS/aptsGS/data/governance.sqlite3`. Backend MySQL masih didukung untuk pemulihan. Database modul APTS lain tidak dialihkan.

## Hasil migrasi

Sumber adalah snapshot konsisten **database MySQL aktif**, bukan dump SQL lama yang mungkin berisi keadaan berbeda. Seluruh 16 tabel dan 145 record disalin dengan ID, indeks, foreign key, nilai desimal, dan urutan AUTO_INCREMENT yang dipertahankan. Checksum isi setiap tabel cocok sebelum cutover. Sebanyak 28 record audit beserta rantai hash lolos verifikasi.

SQLite memakai WAL, foreign_keys=ON, synchronous=FULL, busy_timeout 30 detik, dan transaksi BEGIN IMMEDIATE. Koneksi nested memakai transaksi yang sama. Audit read-head dan append serta pembuatan scope berada dalam transaksi agar proses bersamaan tidak membuat cabang audit atau penulisan scope parsial.

DDL MySQL dikonversi menjadi schema SQLite termasuk CHECK untuk ENUM/boolean/unsigned/panjang string, indeks unik, foreign key, dan trigger updated_at. Angka DECIMAL(6,2) disimpan sebagai teks presisi dan dibaca sebagai Decimal berskala dua digit; query analitik manual harus melakukan CAST jika memerlukan pengurutan numerik pada kolom tersebut. Query aplikasi yang digunakan sudah diuji pada SQLite.

Identity key yang dimigrasikan telah diperiksa ASCII dan memakai NOCASE. Migrator menolak identity/unique/FK key non-ASCII yang memerlukan pemetaan kolasi khusus, serta tipe, trigger sumber atau unique prefix index yang belum didukung. Ini bukan penerjemah umum seluruh dialek MySQL.

Nilai timestamp historis dipertahankan persis untuk menjaga isi dan provenance. Sesi MySQL sumber memakai jam lokal UTC+7, sementara timestamp SQL baru pada SQLite menggunakan UTC. Pada cutover tidak ada event outbox PENDING/FAILED yang membutuhkan penyesuaian jadwal historis. Retry outbox baru diuji terhadap jam UTC.

## Konfigurasi aktif

`.env` menetapkan `GOV_DB_DRIVER=sqlite` dan `GOV_SQLITE_PATH=D:/APTS/aptsGS/data/governance.sqlite3`. File database wajib sudah ada; backend tidak membuat database kosong atau beralih ke MySQL secara diam-diam jika SQLite tidak tersedia. Login cepat lokal dan registry principal tetap terpisah dari database serta tetap aktif.

`GET http://127.0.0.1:8770/health` menampilkan `database_backend: sqlite`, `database: ok`, dan worker outbox berjalan. Login, session, overview, scope, keputusan, audit, policy, approval, emergency history dan runtime status diuji HTTP 200 melalui web. SQLite integrity_check menghasilkan ok dan foreign_key_check tidak menemukan pelanggaran.

## Backup dan pemulihan

Folder `.runtime/sqlite-migration-20261106/` menyimpan:

- `final-mysql-snapshot.json`: data serta metadata sumber sebelum cutover.
- `final-report.json`: row count/checksum tiap tabel, audit head, pemeriksaan integritas dan hasil HTTP.
- `env-before-sqlite.bak`: konfigurasi sebelum migrasi.

MySQL sumber tidak dihapus atau ditimpa. Untuk rollback, hentikan backend GSS terlebih dahulu dan simpan backup SQLite dengan SQLite backup API. Jika sudah ada perubahan setelah cutover, perubahan tersebut perlu direkonsiliasi terlebih dahulu; mengganti driver saja akan kembali ke keadaan MySQL saat cutover. Atur `GOV_DB_DRIVER=mysql` atau pulihkan konfigurasi sebelumnya, lalu jalankan backend dan periksa health serta login. Web dapat dimuat ulang bila sesi sudah berakhir.

Control Center backup/reset kini memilih backend sesuai konfigurasi; pengujiannya menggunakan database sementara. Tidak ada reset database operasional yang dilakukan selama migrasi.

## Kode dan pengujian

- `app/db.py`: backend ganda dan penyesuaian query repository tetap, termasuk backoff outbox dan semantics UPDATE MySQL.
- `scripts/migrate_governance_sqlite.py`: snapshot MySQL konsisten, file target baru, pencocokan seluruh data dan audit, lalu publikasi file setelah verifikasi.
- `sql/03_governance_sqlite_schema.sql` dan `sql/04_seed_default_policies_sqlite.sql`: struktur dan seed untuk database SQLite baru, tanpa data operasional pengguna.
- `tests/test_sqlite_governance.py`: acceptance nyata yang memakai kembali kasus approval/konsol, termasuk empat approval serentak dengan tepat satu pemenang, rollback, emergency stop, audit paralel, backup/reset, dan larangan membuka koneksi MySQL saat backend SQLite aktif.

175 pengujian regresi lulus sebelum cutover; satu fixture konsol lama yang sudah diketahui tidak kompatibel tetap dikecualikan. Setelah cutover, 26 acceptance SQLite/login cepat lulus. Pengujian tidak melakukan target scan atau mengubah database MySQL operasional.
