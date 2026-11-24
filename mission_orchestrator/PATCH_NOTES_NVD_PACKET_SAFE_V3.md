# VulnDesk NVD Sync Packet-Safe V3

## Penyebab error 1153

`CVE-2021-3942` membawa dokumen NVD `raw_json` sekitar 1.34 MB. Pada server yang
memiliki `max_allowed_packet` sekitar 1 MB, satu baris tersebut tetap gagal
meskipun batch dibelah sampai hanya satu CVE.

## Perubahan utama

1. Raw JSON NVD tidak lagi dikirim bersama INSERT parent `vulnerabilities`.
2. JSON dikompresi dengan gzip, kemudian dibagi menjadi potongan maksimum 128 KiB.
3. Potongan disimpan di tabel `vulnerability_raw_json_chunks`.
4. Tab **Raw JSON** menggabungkan dan mendekompresi potongan secara transparan.
5. Data lama pada kolom `vulnerabilities.raw_json` tetap dapat dibaca.
6. Semua INSERT parent/child memakai batas jumlah baris dan estimasi byte maksimum
   512 KiB per statement.
7. Setiap batch memakai session dan transaksi baru.
8. Batch yang gagal dibelah adaptif; retry hanya dilakukan untuk kegagalan
   database sementara seperti deadlock atau lost connection.
9. Checkpoint halaman hanya bergerak jika semua CVE pada halaman berhasil.
10. Error lengkap ditulis ke `vulndesk_sync.log`.

## Konfigurasi baru

```env
NVD_DB_BATCH_SIZE=100
NVD_DB_PARENT_WRITE_BATCH_SIZE=100
NVD_DB_CHILD_WRITE_BATCH_SIZE=500
NVD_DB_MAX_STATEMENT_BYTES=524288
NVD_DB_TRANSIENT_RETRIES=2
NVD_DB_RETRY_BASE_SECONDS=1
NVD_RAW_JSON_STORAGE=compressed_chunks
NVD_RAW_JSON_CHUNK_BYTES=131072
```

Nilai `compressed_chunks` direkomendasikan. Pilihan lain:

- `plain`: kompatibilitas lama, tetapi dapat kembali terkena error 1153.
- `none`: tidak menyimpan source JSON, paling cepat dan paling hemat database.

## Database migration

Tidak diperlukan SQL manual. Saat aplikasi dijalankan, SQLAlchemy membuat tabel:

```text
vulnerability_raw_json_chunks
```

Tabel lama tidak dihapus dan raw JSON lama tetap terbaca.

## Melanjutkan full sync

Jalankan kembali **Full Sync**. Checkpoint yang gagal tidak dimajukan, sehingga
sinkronisasi melanjutkan kembali dari halaman `startIndex=200000`. CVE yang sudah
berhasil disimpan pada percobaan sebelumnya akan dilewati berdasarkan
`modified_at`.

## Pengujian

- Compile seluruh source: berhasil.
- Insert, skip unchanged, update changed: berhasil.
- Raw JSON pseudo-random 1.45 MB: berhasil dikompresi, dipotong, disimpan, dan
  direkonstruksi identik.
- Automated tests: 2 passed.
