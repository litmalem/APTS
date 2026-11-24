# VulnDesk NVD Official CPE Dictionary Patch

Patch ini menambahkan local mirror **NVD Official CPE Dictionary** ke VulnDesk dan membuat service pencocokan CPE resmi untuk aplikasi Pentest.

## Komponen baru

- `nvd_cpe_api.py` — client untuk NVD Product/CPE API 2.0 (`/rest/json/cpes/2.0`).
- `cpe_dictionary_mapper.py` — parser CPE 2.3 URI dan mapper response NVD ke field database.
- `cpe_dictionary_repositories.py` — repository query/search/upsert CPE dictionary.
- `cpe_dictionary_services.py` — service sinkronisasi dan matching technology fingerprint → official CPE.
- `cpe_dictionary_sync_worker.py` — worker Qt untuk sinkronisasi dari UI.
- `cpe_dictionary_ui.py` — halaman UI baru **CPE Dictionary**.
- `sql_update_cti_services/05_nvd_cpe_dictionary.sql` — tabel `nvd_cpe_dictionary` dan seed service registry.

## Alur baru Pentest → VulnDesk

1. Pentest menjalankan fingerprinting dan menyimpan teknologi target.
2. Tombol **Run VulnDesk Enrichment** membangun payload scan job, termasuk daftar teknologi.
3. VulnDesk menerima payload `/api/pentest/enrich-scan`.
4. `VulnerabilityContextService` memanggil `CpeDictionaryService.match_technologies()`.
5. VulnDesk mencocokkan teknologi target ke `nvd_cpe_dictionary`. Jika belum ada match yang layak, service dapat mengambil satu page terbatas dari NVD CPE API sesuai keyword teknologi.
6. Official CPE candidate digabung dengan CPE candidate lama dari Pentest.
7. `CpeCveMatchingService` melakukan mapping CPE → CVE melalui tabel `cpe_matches`.
8. Response mengembalikan `official_cpe_candidates`, `cpe_candidates`, dan `vulnerability_candidates`.

## Langkah instalasi DB

Jalankan pada database VulnDesk:

```sql
SOURCE sql_update_cti_services/05_nvd_cpe_dictionary.sql;
```

Atau buka file SQL tersebut di client MariaDB/MySQL dan execute.

## Penggunaan UI

Buka tab **CPE Dictionary** di VulnDesk.

- **Search**: mencari data lokal CPE berdasarkan vendor/product/version/title/CPE URI.
- **Sync Keyword**: mengambil CPE dari NVD berdasarkan `keywordSearch`, misalnya `apache http_server`.
- **Sync Match String**: mengambil CPE dari NVD berdasarkan `cpeMatchString`, misalnya `cpe:2.3:a:apache:http_server:*`.
- **Sync First Page(s)**: mengambil halaman awal dictionary untuk bootstrap terbatas.

## Endpoint service baru

- `POST /api/pentest/match-cpe`
- `POST /api/pentest/enrich-scan` sekarang otomatis melakukan official CPE lookup dari teknologi scan.
