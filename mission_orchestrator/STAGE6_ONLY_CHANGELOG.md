# Perubahan WPT: Stage 6 saja

- Hapus fungsi pemindaian target langsung dari layanan WPT dan hapus mode standalone dari UI.
- `execution_mode=STANDALONE` ditolak; API allowlist lama menjawab `410 Gone`. Record lama tetap ada sebagai data historis.
- Job baru wajib mengikat Mission ID dan Task ID (`ptask-*`) serta membawa idempotency key saat dikirim.
- Dispatch mengirim strict WPT intake ke Mission dengan bearer token. Status `AWAITING_STAGE6` secara eksplisit berarti Mission menerima intake, bukan bahwa target I/O atau scan sudah terjadi.
- Mission package yang disertakan masih menetapkan capability WPT `REGISTERED_NOT_EXECUTABLE`; eksekusi scan tetap fail-closed sampai fixed Stage 6 adapter/worker tersedia.
- Hasil hanya tersimpan melalui callback terautentikasi yang mensyaratkan execution ID dan manifest evidence `SEALED`.

Verifikasi lokal: 18 tes WPT lulus; Python compile dan JavaScript syntax check lulus.
