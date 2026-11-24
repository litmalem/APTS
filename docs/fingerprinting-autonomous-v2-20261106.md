# Analisis dan perbaikan fingerprinting otonom ? 6 November 2026

## Hasil terverifikasi pada workspace saat ini

Dua job otonom yang sebelumnya kosong kini COMPLETED dan menyimpan hasil schema v4:

- wpt-01da3c0951ddc8311e660de2674a6f73
- wpt-beb2a1276546ecfba676871678661f64

Keduanya memperoleh dua respons HTTP, indikator Apache/2.4.58 (Win64) OpenSSL/3.1.3 PHP/8.0.30, PHP/8.0.30, serta PHP dari nama cookie. Nama cookie yang tersimpan adalah PHPSESSID dan security. Favicon berhasil diambil dan memiliki SHA-256. Indeks kekuatan bukti tertinggi 70/100, bukan probabilitas. Ketiga entri teknologi adalah indikator pendukung Apache/PHP, bukan tiga produk terpisah yang terverifikasi.

Hasil runtime SUCCEEDED dan evidence SEALED telah dibaca ulang melalui verifikasi ledger. Tidak ada kegagalan persistence runtime pada pemeriksaan akhir. Bukti tersaring tersedia di fingerprinting-autonomous-verified-20261106.json.

## Penyebab

1. Workspace ini masih berisi profil satu GET, batas respons 16 KiB, redirect DENY. Modul pengumpulan dua probe yang disebut dalam percakapan sebelumnya belum tersedia pada workspace ini.
2. Parser lama mengosongkan findings ketika menerima HTTP redirect. Header yang sebenarnya mengindikasikan Apache/PHP menjadi tidak berguna pada hasil tersebut.
3. Kontrak output dan callback lama tidak meneruskan metadata tersaring seperti nama cookie, judul, aset framework dan favicon.
4. Jalur WPT meminta receipt Stage 6.3, sedangkan layanan Stage 6.4 sudah menutup admission gateway lama. Runtime Stage 6.5 seharusnya melakukan admission melalui fresh GSS authorization dan reservasi durable.
5. Source data_handling_policy memuat execution_authorized:false. Ini marker bahwa sumber tidak menerbitkan izin; runtime lama menolaknya sebagai key tidak dikenal.
6. Capture ACTION_PARAMETERS hanya mengenali sumber Recon, Enumeration dan validation; source_wpt_intake_id menimbulkan StopIteration sebelum attempt berhasil dicatat.
7. Pembaca hasil menggunakan repository evidence Stage 6.6 terhadap database runtime versi 9. Handoff Recon juga menggunakan pembaca versi 10 terhadap database Pentest versi 16.
8. Replay status progress setelah COMPLETED ditolak, membuat sweep otonom terus melaporkan pending meskipun hasil sudah tersegel.

## Implementasi

- Dua probe GET tetap: halaman konteks aplikasi dan favicon.ico.
- Maksimal dua hop per probe, maksimum enam request total. Runtime memakai nilai terkecil dari batas sumber, capability dan reservasi intake immutable. Jumlah request dicadangkan sebelum I/O, bukan dihitung sebagai satu invocation saja.
- Semua koneksi tetap melalui broker, memakai host/IP/port/TLS yang dipin, rate limit dan deadline. Setiap koneksi memperoleh pemeriksaan GSS baru dan scope root yang masih berlaku. Subpath hanya diizinkan oleh profil bounded di bawah origin/prefix root yang sama. Exclusion path diperiksa pada setiap URL.
- Redirect lintas origin/prefix, loop, query redirect yang belum didukung dan path tidak didukung tidak diikuti. Cookie/kredensial tidak diteruskan ke target.
- Parser sandbox mengolah kumpulan respons dengan signature engine WPT. Header pada respons redirect tetap menjadi bukti. Hasil mencakup banner, cookie names, judul, URL akhir, path script tanpa query, dan hash favicon untuk image response.
- Kontrak v4 memakai daftar field/header yang ketat pada producer, Mission dan WPT. Body HTML, nilai cookie, query token dan header autentikasi tidak disimpan. HTTPS tetap menggunakan validasi TLS broker; metadata TLS lengkap belum diekspor oleh koleksi baru ini.
- Evidence mengikat byte count dan digest gabungan semua respons ke hasil worker. Raw response tidak dipersistenkan. source_wpt_intake_id sekarang dicatat pada action parameters.
- Admission khusus sumber WPT dijalankan oleh runtime Stage 6.5 dengan GSS dan claim durable, bukan endpoint legacy yang sudah ditutup. Persyaratan receipt untuk sumber Recon umum tetap dipertahankan.
- Identitas yang dikonsumsi tanpa runtime attempt dapat dilewati secara deterministik dan terbatas; runtime tetap menolak legacy RESERVED yang sudah dikonsumsi. Attempt yang sudah berjalan atau selesai tidak otomatis dipindai ulang.
- Pembaca hasil menggunakan source read-only yang sesuai runtime versi 9. Pemilihan repository Recon mengenali owner database versi 16 tanpa downgrade.
- Replay progress yang binding-nya sama diakui tanpa mengubah status terminal atau hash hasil. Binding execution/mission/task/target yang berbeda tetap ditolak.
- UI membedakan hasil belum tersedia dari nol temuan, dan menghitung rasio respons terhadap request aktual termasuk hop redirect.

## Batas hasil saat ini

Target tersimpan sebagai //dvwa, sementara Location menuju /dvwa/... . Prefix literal berbeda sehingga redirect tetap diblokir. Karena itu scan_metrics.scan_status adalah PARTIAL, meskipun status job COMPLETED berarti proses dan penyimpanan hasil telah selesai. Tidak ada pelebaran scope secara diam-diam. Satu job masih memiliki batas otorisasi dua request; job lain memiliki budget enam, tetapi tetap tidak boleh melampaui prefix.

Pada server uji dengan prefix konsisten dan budget cukup, proses berhasil menjalankan tiga request: root 302, halaman login 200, favicon 200. Judul, stack, cookie names, aset dan favicon tersimpan. Kesetaraan metadata penuh dengan mode mandiri, khususnya metadata TLS lengkap, belum diklaim.

Handoff lanjutan ke Recon memerlukan parent run/action yang valid. Saat diperiksa, kedua mission ini belum memiliki Recon run yang dapat dijadikan parent; hasil WPT tetap tersimpan dan tidak dibuatkan parent palsu.

## Validasi

53 pengujian fokus lulus, mencakup broker dan sandbox nyata, scoped redirect, budget satu/dua request, penolakan origin/prefix lain, exclusion dan pin alamat, metadata sensitif, callback HTTP WPT, replay status terminal, binding evidence, sumber WPT, admission runtime dan pemilihan repository Recon.

Pemeriksaan sintaks JavaScript dan assertion panel UI terhadap hasil DVWA aktual juga lulus. Ledger dua hasil runtime dibaca ulang sebagai SUCCEEDED dengan evidence SEALED. Layanan Mission, WPT dan runtime kembali merespons health HTTP 200.
