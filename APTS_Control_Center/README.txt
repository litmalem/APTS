PEMBERSIHAN DATA APTS
1. Matikan semua layanan APTS melalui Control Center, lalu tutup Control Center dan terminal worker yang masih berjalan. Biarkan MySQL aktif.
2. Ekstrak paket ke C:\Users\litma\Downloads\APTS_Reset_Data.
3. Jalankan PowerShell:
cd C:\Users\litma\Downloads\APTS_Reset_Data
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Reset-APTS-Data.ps1
4. Pastikan muncul SUCCESS, mulai ulang layanan, lalu Ctrl+F5.

Cakupan: seluruh data operasional Mission, Pentest, Execution dan feedback lokal Mission; seluruh kontrak Scope/RoE, permintaan otorisasi/persetujuan, keputusan/risk assessment, outbox dan audit governance; seluruh jobs/hasil/evidence/timing WPT yang membentuk Observability.
Audit governance dikosongkan seluruhnya agar tidak menyisakan rantai hash terpotong. Kebijakan, compliance, akun, emergency state, registry, metadata migrasi, allowlist WPT dan knowledge base Vulndesk dipertahankan.
Lokasi default: D:\APTS\mission_orchestrator, D:\APTS\aptsGS, D:\APTS\WebTechnologyProfiler. Parameter -MissionRoot, -GssRoot, -WtpRoot dapat menggantinya. Gunakan environment DB yang sama dengan launcher bila lokasi database dikustomisasi. Periksa lokasi yang dicetak pada laporan.

Backup otomatis: D:\APTS\mission_orchestrator\backups\reset-TIMESTAMP. Backup berisi data lama; penghapusan ini adalah reset aplikasi, bukan penghapusan forensik atau penghapusan arsip historis. Tidak ada perubahan kode aplikasi.
Jika gagal setelah penghapusan dimulai, jangan nyalakan layanan: kembalikan seluruh file SQLite dari backup ke lokasi asal (hapus sidecar -wal/-shm ketika layanan berhenti), dan impor governance-before.sql ke database governance yang sama. Reset beberapa database tidak atomik; laporan sukses hanya ditulis setelah semua pemeriksaan selesai.
Validasi di lingkungan pengembangan dilakukan terhadap salinan SQLite unggahan, termasuk trigger append-only dan foreign key. MySQL Windows belum dijalankan dari lingkungan ini. Skrip harus dijalankan di komputer instalasi; belum menghapus data pada D: Anda.
