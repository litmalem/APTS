# VulnDesk Patch: MITRE CWE API Upload + CWE Search

Patch ini menambahkan integrasi MITRE CWE REST API ke aplikasi VulnDesk.

Root API default:

```text
https://cwe-api.mitre.org/api/v1
```

## Fitur baru

1. **Tab baru: CWE Catalog**
   - Search CWE berdasarkan CWE ID, nama, description, dan extended description.
   - Detail CWE menampilkan: ID, name, abstraction, structure, status, likelihood of exploit, URL resmi, API version, synced timestamp, description, extended description, related weaknesses JSON, dan alternate terms JSON.

2. **Upload/sinkronisasi data CWE dari MITRE CWE REST API**
   - `Fetch CWE ID`: mengambil satu CWE berdasarkan isi field Search, misalnya `CWE-79`.
   - `Sync Known CWE`: memperkaya CWE yang sudah ada pada database karena ditemukan dari NVD CVE mapping. Mode ini paling aman dan cepat untuk workflow VulnDesk.
   - `Sync View 1000`: mencoba mengambil data dari endpoint view MITRE CWE. Jika API view tidak mengembalikan daftar CWE lengkap, gunakan `Sync Range`.
   - `Sync Range`: mengambil CWE berdasarkan rentang angka, misalnya 1 sampai 1500.

3. **Integrasi dengan detail CVE**
   - Tab CWE pada panel detail CVE sekarang menampilkan `Description`, `Likelihood`, dan `Status`, selain ID, Name, dan URL.

4. **Auto migration ringan pada startup**
   - `db.py` menambahkan kolom yang belum ada pada `cwe_catalog` saat `init_database()` dijalankan.

## File baru

```text
cwe_api.py
cwe_mapper.py
cwe_repositories.py
cwe_services.py
cwe_sync_worker.py
cwe_ui.py
sql_update_cti_services/04_cwe_api_catalog_search.sql
vulndesk_db_structure_cwe_api_search.sql
README_CWE_API_SEARCH_PATCH.md
```

## File yang diubah

```text
config.py
db.py
orm_models.py
repositories.py
detail_panel.py
main_window.py
main.py
```

## SQL migration

Jalankan SQL berikut pada database `vulndesk`:

```bash
mysql -u root -p vulndesk < sql_update_cti_services/04_cwe_api_catalog_search.sql
```

Patch juga memiliki auto migration di `db.py`, tetapi menjalankan SQL migration tetap disarankan agar struktur DB eksplisit dan mudah diaudit.

## Konfigurasi `.env` opsional

```env
CWE_API_ROOT=https://cwe-api.mitre.org/api/v1
CWE_TIMEOUT_SECONDS=60
CWE_DEFAULT_VIEW_ID=1000
CWE_DEFAULT_RANGE_START=1
CWE_DEFAULT_RANGE_END=1500
```

## Urutan penggunaan yang disarankan

1. Jalankan migration SQL.
2. Replace file aplikasi dengan file dari patch.
3. Restart VulnDesk.
4. Buka tab **CWE Catalog**.
5. Tekan **Sync Known CWE** terlebih dahulu.
6. Gunakan field Search untuk mencari `CWE-79`, `SQL Injection`, `hard-coded key`, dan kata kunci lain.
7. Jika ingin mengisi katalog lebih luas, gunakan **Sync Range** bertahap, misalnya 1-300, 301-600, dan seterusnya.

## Catatan implementasi

- NVD tetap menjadi sumber utama CVE, CVSS, CPE, dan mapping awal CVE → CWE.
- MITRE CWE REST API digunakan untuk memperkaya `cwe_catalog` dengan uraian CWE.
- Jika API view tidak mengembalikan daftar CWE lengkap pada deployment tertentu, gunakan `Sync Range` atau `Sync Known CWE`.
