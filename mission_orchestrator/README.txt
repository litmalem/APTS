PERBAIKAN MISSION WEB / BUKA WEB

Penyebab: /health Mission berhasil, tetapi /api/dashboard/summary dan /ui/ HTTP 404.
Sumber terbaru tidak mendaftarkan kembali rute dan read-model console.

Pemasangan Windows:
1. Hentikan Mission melalui Control Center, lalu tutup proses Control Center.
2. Ekstrak ZIP ini ke folder sementara.
3. Buka PowerShell pada folder hasil ekstraksi, jalankan:
   .\Install-MissionWebLinkFix.ps1
   Bila folder proyek berbeda:
   .\Install-MissionWebLinkFix.ps1 -MissionRoot D:\mission_orchestrator -ControlCenterRoot D:\APTS_Control_Center
4. Jalankan kembali D:\APTS_Control_Center\START_UI.bat, lalu nyalakan Mission.
5. Muat ulang Control Center (Ctrl+F5). Mission Web harus WEB AKTIF; klik Buka Web.
   URL langsung: http://127.0.0.1:8780/ui/ (port default).

Installer memeriksa SHA-256 paket dan mencadangkan file lama ke backups/mission-web-link-<waktu>.
Paket hanya berisi kode, aset console, dan tes; tidak berisi database atau config.json.

Verifikasi yang dilakukan:
- 27 unittest Control Center: lulus.
- 2 tes HTTP Mission memakai layanan asli dan database sementara: lulus.
- /ui/, /ui/app.js, /ui/app.css, dashboard, daftar mission, perhatian operator: HTTP 200.
- Pembacaan console tidak mengubah hash database.
- Percobaan path traversal dan parameter limit tidak valid ditolak.
- Pemasangan PowerShell/Windows belum dijalankan di lingkungan pengujian Linux.

Tes setelah pemasangan:
cd D:\mission_orchestrator
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_mission_web_link_http.py -v
