# NVD Synchronization Patch

## Perubahan utama

1. **Full sync tidak lagi dibatasi lima halaman.** Sinkronisasi membaca `totalResults` dan melanjutkan pagination sampai seluruh data selesai.
2. **Ukuran halaman default dinaikkan menjadi 2.000**, yaitu batas maksimum yang digunakan oleh implementasi ini untuk NVD CVE API 2.0.
3. **Checkpoint full sync** disimpan sebagai `nvd_full_sync_start_index` pada tabel `app_settings` setelah setiap halaman berhasil di-commit.
4. **Incremental sync dibagi menjadi window maksimal 120 hari** dan melakukan pagination lengkap pada setiap window.
5. **Checkpoint incremental** (`nvd_incremental_checkpoint`) baru dimajukan setelah seluruh halaman dalam window berhasil diproses.
6. Query audit incremental sekarang memfilter `sync_type='INCREMENTAL'`, sehingga tidak mengambil checkpoint dari full sync atau sumber lain.
7. HTTP client memiliki retry untuk status 429 dan 5xx, exponential backoff, dukungan `Retry-After`, timeout, dan request delay.
8. API key yang sebelumnya tertanam di README dan `.env` telah dikosongkan pada paket distribusi. Isi kembali secara lokal dan jangan commit `.env`.

## Perilaku resume

- Jika full sync berhenti setelah suatu halaman berhasil, proses berikutnya melanjutkan dari halaman sesudahnya.
- Jika incremental sync berhenti di tengah window, proses berikutnya mengulang window tersebut dari halaman pertama. Upsert berdasarkan CVE ID membuat pengulangan ini aman.
- Setelah full sync selesai seluruhnya, checkpoint full sync dihapus. Full sync berikutnya akan memulai mirror ulang dari indeks nol.

## Konfigurasi baru

```env
NVD_PAGE_SIZE=2000
NVD_TIMEOUT_SECONDS=90
NVD_REQUEST_DELAY_SECONDS=0.6
NVD_MAX_RETRIES=5
NVD_BACKOFF_BASE_SECONDS=2
NVD_INCREMENTAL_WINDOW_DAYS=120
NVD_INCREMENTAL_INITIAL_START=2024-01-01T00:00:00+00:00
```

Tanpa API key, client menerapkan delay minimum enam detik per request. Dengan API key, nilai `NVD_REQUEST_DELAY_SECONDS` digunakan.
