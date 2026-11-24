# Vulndesk Web App v1.1

Antarmuka web untuk instalasi Vulndesk yang sudah ada. Frontend yang sama dipakai dalam pratinjau berisi data contoh dan dalam aplikasi lokal dengan data aktual.

## Menjalankan di Windows

1. Pasang paket perubahan pada instalasi Vulndesk. Lokasi default Web App adalah `D:\Vulndesk\Vulndesk_Web`; direktori Web terpisah juga dapat digunakan jika file runtime pada `D:\Vulndesk` ikut diperbarui. Lihat `README_API_EXTERNAL.md` di akar Vulndesk.
2. Gunakan Python 3.10 atau lebih baru. Buka PowerShell di folder hasil ekstraksi:

   ```powershell
   python -m pip install -r requirements-web.txt
   python server.py --vulndesk-root D:\Vulndesk
   ```

3. Buka **http://127.0.0.1:8801**. Server terikat ke komputer lokal.
4. Setelah dependensi terpasang, `START_WEB.bat` dapat dipakai untuk menjalankan konfigurasi default. Hentikan dengan Ctrl+C.

Untuk melihat antarmuka tanpa database:

```powershell
python server.py --demo
```

Mode contoh memakai ID `CVE-DEMO-*`, entri sintetis, dan status SIMULASI. CRUD sumber API, import, penghapusan, serta perubahan enabled pada mode ini hanya berlaku selama sesi halaman. Tidak ada akuisisi sumber atau proses API yang dijalankan oleh tombol simulasi.

## Konfigurasi lokal

Ubah `config.json`, lalu restart Web App:

| Parameter | Default | Kegunaan |
| --- | --- | --- |
| `vulndesk_root` | `D:/Vulndesk` | Lokasi source dan `.env` Vulndesk yang sudah ada |
| `vulndesk_python` | string kosong | Python untuk menjalankan API asli; kosong menggunakan Python Web App |
| `web_port` | `8801` | Port antarmuka web |
| `service_ports.cti` | `8765` | Pentest Enrichment API / CTI |
| `service_ports.gss` | `8770` | aptsGS |
| `service_ports.mission` | `8780` | Mission Orchestrator |
| `service_ports.pentest` | `8790` | Pentest Subsystem |

Contoh interpreter instalasi asli: `D:/Vulndesk/.venv/Scripts/python.exe`. Python tersebut harus memiliki dependensi dari instalasi Vulndesk asli agar tombol **Start API** dapat bekerja. Web App tidak memasang atau mengubah dependensi proyek asli secara otomatis.

Kredensial dibaca oleh server dari `.env` Vulndesk: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, atau `DATABASE_URL` MariaDB/MySQL. Variabel environment yang sudah diatur memiliki prioritas, mengikuti perilaku konfigurasi asli. Kredensial tidak dimasukkan ke frontend atau paket ini.

Gunakan database dengan skema dari versi Vulndesk yang diberikan. Paket ini tidak membuat tabel, menjalankan migrasi, atau mengisi registry secara otomatis. Akun database memerlukan SELECT untuk penelusuran. Pengelolaan API memerlukan SELECT, INSERT, UPDATE, DELETE pada `cti_source_registry` dan SELECT pada `cti_source_state`. UPDATE registry komponen dan operasi dataset memerlukan hak tulis pada tabel terkait. API bawaan dapat didaftarkan melalui form setelah konfigurasi diperiksa.

## Halaman dan fungsi

| Halaman | Fungsi |
| --- | --- |
| Ringkasan | Jumlah katalog, distribusi severity, CVE terbaru, health empat modul |
| Vulnerabilities | Pencarian, severity, rentang CVSS, tahun, CWE, keberadaan CPE, pagination, ekspor halaman CSV, detail CVE |
| MITRE ATT&CK | Teknik, malware, dan threat actors; pencarian dan detail |
| CWE Catalog | Pencarian, klasifikasi, likelihood, dan detail raw data |
| CPE Dictionary | Vendor, produk, versi, URI, serta detail |
| Tweet Topics | Tweet topics dan topics master; import CSV serta hapus per jenis/tanggal |
| API Eksternal | Lihat endpoint, konfigurasi dan kesehatan sumber; tambah, ubah, hapus API; pencarian, filter, pagination, dan pilihan API bawaan |
| CTI Components | Registry, enabled flag, health API, konfigurasi port, start/stop API milik Web App, diagnostik |
| Mission Monitor | Status misi, event trace, diagnostics, lineage, integrity |

CSV tweet topics menerima kolom `Tweet` dan `Topic`, termasuk alias `TWEETS`, `TOPICS`, `text` dari desktop. Topics master menerima `Topic`/`Topics`. CSV harus UTF-8, maksimum 5 MB dan 100.000 baris. Import memakai tabel dan penyimpanan dataset yang sama dengan desktop. Penghapusan meminta jenis, tanggal unggah UTC, dan konfirmasi, serta memeriksa bahwa file berada di folder unggahan yang dikonfigurasi. Ekspor CSV hanya mengekspor halaman yang terlihat.

## Integrasi runtime

Semua koneksi modul berasal dari server lokal ke `127.0.0.1` pada port yang dikonfigurasi. Frontend tidak mencoba mengakses komputer lokal dari pratinjau yang dihosting.

- CTI: GET `/health`, `/api/cti/diagnostics?deep=true`, status/diagnostics/lineage/integrity misi, serta event misi. Status misi dibaca dari objek `mission`, sehingga wrapper HTTP `completed` tidak dianggap sebagai selesainya eksekusi misi.
- GSS, Mission Orchestrator, Pentest: pemeriksaan GET `/health`. Health yang berhasil tidak membuktikan bahwa seluruh integrasi lintas modul sudah berjalan.
- **Misi akuisisi CTI** meneruskan mission ID baru, scope contract ID, satu sumber yang aktif serta memiliki adapter, dan batas satu tindakan ke `/api/cti/missions/start`. Dropdown dibaca dari registry, termasuk Source ID baru. Keputusan authorization tetap dievaluasi backend CTI/aptsGS. Akun pengguna harus menyediakan scope yang valid. Web App tidak menerima keputusan ALLOW dari browser.
- Connector mendukung format NVD CVE 2.0, NVD CPE 2.0, MITRE ATT&CK/TAXII 2.1, dan MITRE CWE REST. Akuisisi CWE dibatasi satu CWE ID per tindakan. Endpoint, autentikasi, timeout, parameter halaman, dan collection berasal dari registry serta diterapkan pada instance client terkait. Source ID baru dapat memakai adapter yang sesuai dengan format respons API tersebut.
- API berformat lain dapat disimpan sebagai **Registry saja**. Sumber tersebut ditampilkan untuk pengelolaan konfigurasi dan tidak masuk kandidat akuisisi sampai adapter tersedia.
- Proposal baru terikat pada konfigurasi sumber. Connector memeriksa registry kembali sebelum menjalankan sinkronisasi; sumber yang dihapus, dinonaktifkan, atau berubah sejak proposal tidak diteruskan ke client HTTP.
- **Start API** menjalankan launcher asli `run/run_vulndesk_api.py` menggunakan interpreter yang dikonfigurasi. **Stop API** hanya menghentikan child process milik server ini. Proses yang dimulai oleh desktop atau control center dibiarkan berjalan.
- Tampilan ini memantau Pentest Subsystem. Pengiriman PIP otomatis ke pentest tidak ditambahkan dalam paket UI ini.

`Enabled` adalah konfigurasi registry, bukan bukti bahwa agent aktif. `REACHABLE` berarti endpoint merespons tanpa menyatakan readiness; `READY` hanya ditampilkan jika health menyatakan readiness. Koneksi gagal tetap terlihat sebagai OFFLINE atau pesan error. Database yang tidak tersedia menampilkan tanda `—`, bukan jumlah data contoh.

## Pengujian dan batas verifikasi

Jalankan tes adapter yang tidak memerlukan database:

```powershell
python -m unittest discover -s tests -v
```

Pengujian memeriksa allowlist query, batas input, transaksi baca, host/origin/CSRF, route terbatas, normalisasi status misi, pembatasan proposal CTI, kepemilikan proses, serta CRUD API dengan fixture SQLite. Tes SQL menggunakan terjemahan placeholder dan tidak membuktikan locking MariaDB. Tes browser `tests/test_sources_ui.cjs` memakai Playwright dan server fixture terpisah; tidak mengakses database pengguna.

Paket dirancang berdasarkan source dan skema Vulndesk yang diberikan. Database MariaDB aktif dan runtime Windows pengguna tidak tersedia selama pembuatan, sehingga koneksi nyata dan keberhasilan mission authorization harus diperiksa pada instalasi lokal. Alur CRUD, filter, konflik versi, mode contoh, escaping HTML, dan tampilan seluler diverifikasi di Chromium. WebMCP pada browser pendukung belum diuji secara khusus.

## Struktur paket

```text
Vulndesk_Web/
  server.py             server HTTP lokal dan kontrol origin/sesi
  backend.py            bridge database dan API lokal
  source_manager.py     CRUD registry sumber eksternal
  config.json           lokasi instalasi dan port
  requirements-web.txt  dependensi baca database / environment
  START_WEB.bat          launcher Windows
  RUN_WEB.ps1           launcher PowerShell
  web/                  HTML, CSS, JavaScript
  tests/                tes adapter
```

Server hanya membuka aset frontend yang terdaftar. Koneksi database tetap di server. POST memerlukan token sesi dan origin lokal. Referensi kredensial sumber menggunakan nama environment, misalnya `env:NVD_API_KEY`; nilai API key tidak dikembalikan kepada frontend. Tidak ada proxy URL bebas, command shell dari browser, atau endpoint pentest target.

## Endpoint pengelolaan API

| Metode | Endpoint | Fungsi |
| --- | --- | --- |
| GET | `/api/sources` | Daftar, filter, pagination, statistik, dan pilihan API bawaan |
| GET | `/api/sources/{source_id}` | Detail konfigurasi, versi, dan kesehatan sumber |
| POST | `/api/sources/create` | Tambahkan konfigurasi sumber |
| POST | `/api/sources/update` | Ubah dengan `expected_revision` untuk mencegah penimpaan perubahan lain |
| POST | `/api/sources/delete` | Hapus konfigurasi dengan versi dan konfirmasi |

Penghapusan hanya menghapus baris registry. Data CVE/CPE/ATT&CK/CWE, audit, dan state sumber yang sudah tersimpan tetap tersedia. Pengaturan desktop tetap mengikuti Config / `.env`; halaman ini mengelola registry akuisisi CTI.

## CTI Enrichment: target dan status evidence

Halaman CTI Enrichment menampilkan URL target, ringkasan teknologi, dan kandidat CPE
dari `cti_wpt_verified_evidence`. Pencarian mencakup URL target, intake, mission,
dan task; Created mendukung urutan naik/turun dengan pengurutan ID sebagai pembeda.
URL ditampilkan sebagai teks dan tidak diakses oleh CTI maupun UI.

Hasil baru menyimpan target, teknologi asli dan hasil normalisasi, alasan pencocokan,
serta status setiap tahap pipeline di `result_json`; tidak diperlukan migrasi tabel.
Nama seperti `PHP/8.4.27` dinormalisasi menjadi PHP versi 8.4.27. Kandidat harus
memisahkan identitas produk dari kecocokan versi. Jika produk dikenali tetapi
versi target belum diketahui, kandidat ditandai `VERSION_UNKNOWN`. Jika versi
teramati tidak ada di dictionary, statusnya `VERSION_NOT_FOUND`. Kandidat produk
tidak menetapkan CPE/versi target; `reference_cpe23_uri` hanya merujuk entri
dictionary pendukung. `EXACT_VERSION_MATCH` memerlukan versi yang cocok dan tidak
memasangkan rilis stabil dengan update prerelease seperti rc1. Alias Laravel
Framework dibatasi vendor `laravel`. Skor CPE bukan probabilitas kerentanan.
Produk yang belum ditemukan ditandai `PRODUCT_NOT_FOUND` per teknologi di UI.

Bridge ini menjalankan resolusi CPE saja. Korelasi CVE, ATT&CK, prioritas risiko,
dan PIP dilaporkan `NOT_RUN`; jumlah kerentanan nol tidak menentukan status tahap.
Evidence lama tanpa status/target ditampilkan sebagai data tidak tersedia.

Pemulihan data lama dapat dijalankan dari direktori Vulndesk:

```powershell
python run/reprocess_wpt_enrichment.py
python run/reprocess_wpt_enrichment.py --apply
python run/reprocess_wpt_enrichment.py --apply --force
python run/reprocess_wpt_enrichment.py --apply --force --sync-missing
```

Perintah pertama hanya memeriksa sumber. `--mission-root` dan `--wpt-db` dapat
menentukan lokasi sumber. Pemulihan memvalidasi seal intake/hasil/handoff dan
mencocokkan hash envelope asli sebelum memperbarui hasil turunan. Hasil sebelumnya
disimpan di `previous_enrichment`; digest evidence dan waktu pembuatan tetap sama.
`--force` menghitung ulang hasil revisi terkini setelah dictionary diperbarui.
`--sync-missing` memerlukan `--apply`, menggunakan HTTPS endpoint NVD resmi,
dan mengambil maksimum satu halaman (100 entri) per teknologi yang belum
terselesaikan sebelum menghitung ulang. Sinkronisasi ini terpisah dari ingress
evidence, tercatat pada sync audit, dan tidak mengakses URL target. Hasil PARTIAL
berarti dictionary belum lengkap; query dengan nol hasil juga tidak membuktikan
bahwa sebuah produk tidak pernah memiliki CPE resmi. Tombol Refresh UI hanya
membaca hasil tersimpan, tidak menjalankan sinkronisasi atau pemrosesan ulang.

## Adaptive CTI source monitoring

Vulndesk Web now starts an adaptive source-monitor thread by default in live mode. Apply
`sql_update_cti_harmonized/09_adaptive_source_monitoring.sql` to the Vulndesk database first.
The monitor uses source-specific lightweight probes:

- NVD CVE: `lastModStartDate` / `lastModEndDate` with one-result probe.
- NVD CPE: `lastModStartDate` / `lastModEndDate` with one-result probe.
- MITRE ATT&CK: TAXII `added_after` with a one-object probe.
- MITRE CWE: `/cwe/version` fingerprint.
- Custom HTTPS registry source: conditional HTTP metadata probe where supported.

No-change streaks exponentially increase the interval between probes up to the configured
maximum; a detected change returns the interval to the configured minimum. A small deterministic
jitter prevents all sources from polling simultaneously. `cti_source_state.change_signal` is
updated from the probe result so CTI-A02 can use real change evidence.

`auto_update` is opt-in per source. When enabled, a detected change starts the existing
`/api/cti/missions/start` flow and therefore still requires authoritative GSS approval. Configure
`auto_scope_contract_id` for the source, or set `CTI_AUTONOMOUS_SCOPE_CONTRACT_ID` globally.
The scheduler never invokes `SourceSyncConnector` directly.

Environment controls:

- `CTI_ADAPTIVE_SCHEDULER_ENABLED=true|false` (default `true`)
- `CTI_ADAPTIVE_SCHEDULER_TICK_SECONDS=15` (scheduler scan cadence; per-source due time still controls probes)
- `CTI_AUTONOMOUS_SCOPE_CONTRACT_ID=<scope-id>` (optional global scope fallback)
