# APTS Control Center — WPT & kontrol layanan global

## Reset khusus CTI Enrichment

Perbaikan penolakan "cakupan tidak dikenal": ditemukan dua instance panel
berbagi port 8800, sehingga backend lama menerima pilihan baru dari JavaScript
yang dibaca langsung dari disk. Startup Windows sekarang memakai port eksklusif;
instance kedua ditolak. Preview menyertakan versi kontrak reset dan UI menolak
backend lama. Endpoint `/api/reset/validate` memeriksa preview dan pilihan tanpa
menjalankan reset, sebelum UI mengirim permintaan penghapusan.

Validasi langsung: satu listener panel pada port 8800; pilihan 7 cakupan / 924
baris termasuk CTI Enrichment diterima oleh endpoint validasi; status tetap idle.
13 tes reset lulus, termasuk alur HTTP validasi/eksekusi dengan worker tiruan dan
penolakan instance kedua pada port yang sama. Tidak ada reset database aktual
yang dijalankan saat perbaikan ini.

Reset data menyediakan pilihan **Vulndesk · CTI Enrichment** untuk menghapus
evidence dan hasil enrichment yang tampil pada halaman CTI Enrichment. Cakupannya
hanya tabel `cti_wpt_verified_evidence`, termasuk JSON hasil teknologi, kandidat CPE,
dan status pipeline. Preview menunjukkan jumlah baris aktual dan rincian tabel.
Pilihan **Vulndesk · data operasional CTI lainnya** terpisah sehingga jumlah data
tidak dihitung dua kali. Semua pilihan tetap kosong secara default.

Pilih CTI Enrichment saja untuk mempertahankan data CTI lain, katalog referensi,
data Mission/WPT, dan file dataset. Backup dan konfirmasi reset yang sudah ada
tetap wajib. Menambahkan pilihan ini tidak menjalankan penghapusan data.

Validasi: `python -m unittest -v test_reset_enrichment` (11 tes dengan database
sintetis), pemeriksaan sintaks Python/JavaScript, serta pemeriksaan pemilihan scope
di JavaScript. Preview database aktual mengidentifikasi dua baris enrichment;
tidak ada penghapusan pada database aktual selama pemasangan fitur.

## Perbaikan kontrol Hentikan (9 November 2026)

Panel sebelumnya menyimpan objek proses hanya dalam memori. Layanan yang tetap
hidup setelah panel dibuka ulang, atau dimulai melalui terminal lain, kehilangan
kontrol Hentikan. Mission dan Mission Web menggunakan satu proses.

Perbaikan kedua menggunakan API Windows langsung (`GetExtendedTcpTable`,
`OpenProcess`, dan pembacaan identitas proses), menggantikan inventaris CIM yang
mengembalikan identitas listener tidak lengkap. Tabel khusus listener digunakan
langsung tanpa menyaring ulang field state yang dapat tidak terisi. Launcher
relatif juga dikenali melalui direktori kerja proses sebenarnya, bukan direktori
kerja panel.

Tombol Hentikan tersedia untuk proses panel maupun proses APTS terverifikasi.
PID, waktu pembuatan, command line, executable, direktori kerja dan pemilik port
diperiksa lagi sebelum penghentian; handle yang sama ditahan sampai proses
berhenti. Proses yang tidak dapat diverifikasi tetap ditolak dengan pesan error.

OFF semua memproses setiap proses bersama satu kali dalam urutan dependensi
terbalik. Listener aktif yang tidak bisa dihentikan dihitung sebagai kegagalan,
bukan dilewati diam-diam. Audit port terakhir melaporkan layanan yang masih aktif,
termasuk yang dijalankan ulang supervisor. Tombol global tetap OFF jika ada
layanan aktif walaupun prosesnya belum bisa dikontrol.

Tes khusus: `python -m unittest -v test_process_recovery test_process_lifecycle`.
Validasi: 21 tes lulus, termasuk proses eksternal dengan launcher relatif yang
dihentikan melalui endpoint HTTP Control Center, dan sintaks Python/JavaScript.
Verifikasi langsung 9 November 2026: backend baru dimuat pada port 8800;
`POST /api/action` dengan module=all dan action=stop menghasilkan 3 berhasil,
0 gagal, remaining kosong. Vulndesk (PID 24948), Vulndesk Web (PID 31496), dan
Mission/Mission Web (PID 25564) berhenti; port 8765, 8801, 8780 tidak memiliki
listener lagi dan status panel menunjukkan 0/10 layanan aktif.

Control Center yang sedang berjalan sudah dimulai ulang untuk memuat backend
baru. Muat ulang halaman browser agar token sesi dan JavaScript terbaru digunakan.
Suite paket lama di bawah belum menjadi gerbang regresi penuh: beberapa ekspektasi
masih menghitung sembilan modul sebelum penambahan Stage 6.5 Runtime. Bagian
pemasangan paket lama berikut disimpan sebagai dokumentasi distribusi sebelumnya.

Patch untuk APTS Control Center. Installer menambahkan konfigurasi WPT default jika belum ada, yaitu `D:\APTS\WebTechnologyProfiler` pada port `8791`; entri konfigurasi WPT yang sudah ada tetap dipertahankan.

## Pemasangan
1. Pastikan APTS_Pentest_UI_Phase1 sudah terpasang di D:\APTS\mission_orchestrator.
2. Selesaikan pekerjaan aktif dan hentikan layanan yang dikelola panel sebelum menutup Control Center.
3. Ekstrak ZIP patch ini, buka PowerShell di folder hasil ekstraksi, jalankan:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\Install-ControlCenterWebPentest.ps1 -ProjectRoot D:\APTS\APTS_Control_Center
cd D:\APTS\APTS_Control_Center
.\START_UI.bat
```

Sesuaikan ProjectRoot bila folder lokal berbeda. Installer memvalidasi checksum semua file sebelum menyalin dan membackup file lama ke backups. Jika file lokal berbeda dari baseline, installer berhenti agar perubahan lokal tidak tertimpa. Config, database, dan log tidak diganti.

## Penggunaan
Pada http://127.0.0.1:8800:
- Kartu **Web Technology Profiler (WPT)** menyediakan **ON · WPT**, **OFF · WPT**, **Buka Web**, monitor, dan log. ON menjalankan `app.py` memakai `WTP_HOST=127.0.0.1` dan `WTP_PORT=8791`.
- Tombol ringkasan **ON semua layanan / OFF semua layanan** memproses Vulndesk, Vulndesk Web, aptsGS, aptsGSS Web, Mission, Mission Web, Pentest, Web Pentest, dan WPT. Mission Web memakai proses Mission; Web Pentest berbagi proses dengan API Pentest, sehingga tidak dibuat proses ganda. Jika layanan sudah aktif di luar panel, ON mendeteksi health dan memantaunya tanpa mencoba membuat proses duplikat. OFF menghentikan proses panel dan proses APTS eksternal yang terverifikasi dalam urutan terbalik; layanan yang masih aktif dilaporkan sebagai kegagalan.
- Pada kartu **Web Pentest**, **ON · Web Pentest** menjalankan launcher Pentest existing. Tunggu **WEB AKTIF**, lalu tekan **Buka Web** atau buka `http://127.0.0.1:8790/pentest/`. **OFF · Web Pentest** menghentikan proses Pentest yang dimulai panel. Monitor dan Log tersedia.

Web Pentest dan Pentest Subsystem memakai satu proses/PID, port, konfigurasi dan log yang sama. ON berulang tidak membuat proses tambahan. OFF menghentikan API dan UI Pentest sekaligus; konfirmasi ditampilkan. Proses dari terminal lain dapat dihentikan jika identitas launcher dan pemilik port terverifikasi. Port/link mengikuti modules.pentest.port.

WEB AKTIF memerlukan halaman /pentest/ yang benar-benar tersedia. Jika API aktif tetapi UI belum dipasang, kartu Web Pentest tetap menampilkan error. Pasang paket Phase 1 dan restart Pentest. Tombol ON hanya menyalakan layanan; tidak memulai scan target.

## Validasi
Tes unittest mencakup synthetic HTTP subprocess start/stop untuk WPT, urutan start global, satu PID untuk API/UI, UI belum terpasang, browser URL dengan port khusus, proses eksternal, serta regresi modul existing. JavaScript lulus node --check. Pengujian dilakukan di Linux; installer PowerShell dan tampilan visual browser belum diuji di Windows.

```powershell
python -m unittest -v test_control_center test_gss_web test_mission_web test_pentest_web
```
