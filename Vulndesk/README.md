# VulnDesk (Single Folder Edition Plus)

Aplikasi desktop Windows/Linux berbasis **Python + PySide6 + MariaDB** untuk mengambil dan menampilkan data vulnerability dari **NVD API 2.0**.

## Fitur utama
- Full sync dan incremental sync dari NVD
- Penyimpanan lokal ke MariaDB
- Tabel vulnerability dengan panel detail
- Severity berwarna
- Filter keyword, severity, score, year, CWE, dan Has CPE
- Sorting dengan klik header kolom
- Pagination lokal
- Export CSV untuk halaman aktif
- Progress bar dan status sinkronisasi
- File build `.exe` via PyInstaller
- Tab **Tweet Topics** untuk upload `tweet_topics.csv` dan `topics_master.csv`
- Tampilan tabel tweet, topic master, dan tanggal upload
- Filter tweet berdasarkan topic dan tanggal upload

## Konfigurasi `.env`
Gunakan file `.env` seperti ini:

```env
APP_TITLE=VulnDesk - Vulnerability Viewer
NVD_API_URL=https://services.nvd.nist.gov/rest/json/cves/2.0
NVD_API_KEY=<your-nvd-api-key>
NVD_PAGE_SIZE=2000
NVD_TIMEOUT_SECONDS=90
NVD_REQUEST_DELAY_SECONDS=0.6
NVD_MAX_RETRIES=5
NVD_BACKOFF_BASE_SECONDS=2
NVD_INCREMENTAL_WINDOW_DAYS=120
NVD_INCREMENTAL_INITIAL_START=2024-01-01T00:00:00+00:00
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=vulndesk
DB_USER=root
DB_PASSWORD=
```

## Instalasi
```bash
pip install -r requirements.txt
```

## Siapkan database
```sql
CREATE DATABASE vulndesk CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

## Jalankan aplikasi
```bash
python main.py
```

## Build Windows `.exe`
```bat
build_exe.bat
```

## Catatan
- Untuk sinkronisasi besar, lakukan full sync bertahap.
- Pastikan MariaDB aktif dan kredensial `.env` benar.
- NVD dapat membatasi request; API key membantu menjaga akses lebih stabil.

## Fitur dataset Tweet Topics
- Buka tab **Tweet Topics**.
- Gunakan **Upload tweet_topics.csv** untuk mengimpor dataset tweet-topic.
- Gunakan **Upload topics_master.csv** untuk mengimpor master topic.
- Gunakan filter **Topic** dan **Upload date** untuk memfilter tabel tweet.
- Bagian bawah menampilkan daftar topic master beserta tanggal upload.


## Dataset CSV upload storage

Versi ini menyimpan file CSV yang di-upload ke folder fisik aplikasi:

- `data/uploads/tweet_topics/`
- `data/uploads/topics_master/`

Metadata file juga disimpan di tabel `dataset_uploads` melalui kolom:

- `stored_file_path`
- `file_size_bytes`

Jika tabel `dataset_uploads` sudah dibuat dari versi sebelumnya, aplikasi akan mencoba menambahkan dua kolom tersebut secara otomatis saat startup.


## Update dataset Twitter
- Filter `Tanggal Upload Twitter` diperbesar agar nilai tanggal terlihat penuh.
- Ditambahkan tombol `Delete tweet_topics` dan `Delete topics_master`.
- Jika filter tanggal dipilih, penghapusan hanya berlaku untuk dataset pada tanggal tersebut.
- Jika filter tanggal = `ALL`, seluruh dataset untuk tipe tersebut akan dihapus.

## Update branding dan tema
- Tema aplikasi diubah dari dark ke light/non-dark melalui stylesheet global di `main_window.py`.
- Ditambahkan header branding di bagian atas aplikasi berisi teks **SCRG Lab ITB** dan **Institut Teknologi Bandung**.
- Aplikasi sekarang mencoba memuat logo dari folder `assets/` dengan nama file `itb_logo.png`, `itb_logo.jpg`, `itb_logo.jpeg`, atau `itb_logo.svg`.
- Jika file logo belum tersedia, aplikasi akan menampilkan emblem fallback lokal agar layout tetap rapi.

## NVD synchronization performance settings

The NVD CVE synchronization path uses chunked bulk database operations and skips records whose local `modified_at` is equal to or newer than the source record.

```env
NVD_PAGE_SIZE=2000
NVD_REQUEST_DELAY_SECONDS=0.6
NVD_DB_BATCH_SIZE=250
NVD_SKIP_UNCHANGED=true
```

Use **Full Sync** for initial population or rebuilding. Use **Incremental Sync** for routine updates. Full Sync still reads the complete NVD collection, but unchanged CVEs are no longer rewritten.

## NVD packet-safe raw JSON storage

NVD source documents are stored as gzip-compressed 128 KiB chunks in
`vulnerability_raw_json_chunks`. This prevents MariaDB error 1153 for unusually
large CVEs while preserving the Raw JSON tab. See
`PATCH_NOTES_NVD_PACKET_SAFE_V3.md`.
