# VulnDesk CWE Uraian Patch

Patch ini menambahkan uraian CWE pada detail vulnerability.

## File yang berubah

1. `detail_panel.py`
   - Tab CWE berubah dari 3 kolom menjadi 4 kolom: `CWE ID`, `Name`, `Description`, `URL`.
   - Kolom description dibuat stretch dan row otomatis menyesuaikan tinggi teks.

2. `repositories.py`
   - Detail CVE sekarang memperkaya CWE dengan nama, URL MITRE CWE, dan uraian.
   - Jika database memiliki kolom `cwe_catalog.description_text`, uraian dibaca dari database.
   - Jika belum ada, aplikasi memakai fallback katalog lokal pada `cwe_catalog_utils.py`.

3. `cti_services/cpe_cve_matching_service.py`
   - Response enrichment sekarang membawa `cwe_description` dan `cwe_url` untuk candidate vulnerability.
   - Query CWE dibuat kompatibel dengan kolom baru `description_text` bila sudah ada.

4. `cwe_catalog_utils.py`
   - Katalog lokal ringan untuk CWE umum pada web security dan CTI mapping.
   - Menghasilkan URL resmi CWE otomatis: `https://cwe.mitre.org/data/definitions/<id>.html`.

5. `sql_update_cti_services/04_cwe_catalog_descriptions.sql`
   - Migration untuk menambahkan `cwe_catalog.description_text`.
   - Seed/update nama, URL, dan uraian CWE umum.

6. `vulndesk_db_structure_cwe_uraian.sql`
   - Versi struktur database lengkap dengan tambahan kolom `description_text` pada `cwe_catalog`.

## Cara pakai

1. Backup database.
2. Jalankan migration:

```sql
SOURCE sql_update_cti_services/04_cwe_catalog_descriptions.sql;
```

Atau buka file SQL tersebut di SQLyog/phpMyAdmin lalu execute.

3. Replace file Python lama dengan file di patch ini.
4. Restart VulnDesk desktop/API service.

Catatan: kode tetap bisa berjalan tanpa migration karena ada fallback katalog lokal, tetapi database sebaiknya tetap diupdate agar uraian tersimpan permanen di `cwe_catalog`.
