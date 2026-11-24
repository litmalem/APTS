# Perbaikan CTI enrichment → Enumeration, 9 November 2026

## Penyebab yang diverifikasi

1. Worker `mission_cti_enumeration_delivery` sudah dipanggil dalam recovery sweep Mission, tetapi flag `APTS_AUTONOMOUS_CTI_ENUMERATION_DELIVERY` belum diaktifkan di Control Center.
2. Builder context membandingkan seluruh objek target. CTI membawa `target_type` dan `target_value`, sedangkan task juga membawa `environment` dan `metadata`. Ketiga enrichment yang tersedia ditolak dengan `CTI target differs from task scope target`, meskipun tipe dan nilai target identik.
3. Proses Pentest belum menerima shared token CTI. Ini juga menghalangi pengambilan context melalui UI manual.

## Implementasi

- Aktifkan flag delivery dalam konfigurasi Mission. Control Center memasok default aktif untuk Mission, dengan nilai eksplisit `0` tetap dihormati.
- Turunkan URL loopback CTI dari port Vulndesk dan pasok shared token ke Mission dan Pentest saat peluncuran. Token tidak disalin ke konfigurasi baru; konflik konfigurasi ditolak.
- Bandingkan identitas target secara persis berdasarkan `target_type` dan `target_value`. Perbedaan tipe/nilai tetap ditolak. Pemeriksaan SEALED evidence, authenticated WPT handoff, hash predecessor, scope GSS, dan status mission tetap berlaku.
- Catat alasan kandidat yang tertunda. Kegagalan transport CTI atau konflik satu kandidat tidak menghalangi kandidat berikutnya.
- UI menjelaskan intake otomatis dan memperbarui daftar run setiap 30 detik saat tab terlihat. Form manual tetap tersedia.

## Verifikasi

- 46 pengujian CTI context, autonomous delivery, dan Enumeration Agent lulus, termasuk kontrak HTTP, target berbeda, replay, serta isolasi kandidat gagal.
- Suite Control Center: 20 lulus; 3 failure dan 1 error juga direproduksi pada kode HEAD sebelum perubahan. Tiga assertion lama mengharapkan 9 modul meskipun Stage 6 runtime sudah menjadi modul ke-10. Satu test proses sintetis memakai port Vulndesk aktif sehingga start mengembalikan `pid=None`. Test wiring CTI baru lulus.
- Mission dan Pentest dimuat ulang melalui kontrol proses lokal. Keduanya sehat dan tetap dikenali Control Center.
- Worker otomatis menghasilkan 3 run COMPLETED: WebGoat (1 observasi), DVWA (3 observasi), dan kurikulum.del.ac.id (3 observasi).
- API UI context mengembalikan `status=ok` untuk ketiganya. Replay delivery mengembalikan `replayed` dan jumlah run tetap 3.
- Semua request hasil enrichment membawa `enumeration_proposals=[]`; delivery ini tidak melakukan I/O target atau menerbitkan otorisasi eksekusi.

## Operasional

Mission worker melakukan recovery sweep setiap 30 detik. Enrichment tervalidasi untuk mission RUNNING diproses tanpa paste Recon ID atau JSON. Konfigurasi launcher baru digunakan saat Control Center berikutnya dijalankan. Layanan Mission/Pentest yang aktif sudah menggunakan perbaikan ini.
