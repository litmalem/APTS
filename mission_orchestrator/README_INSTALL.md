# Pemasangan patch Pentest UI Phase 1

Ekstrak ZIP ini. Hentikan/restart layanan Pentest saat pemasangan, lalu jalankan dari folder yang berisi Install-PentestUI.ps1:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\Install-PentestUI.ps1 -ProjectRoot D:\mission_orchestrator
cd D:\mission_orchestrator
.\START_PENTEST_UI_PHASE1.ps1
```

Jika menggunakan APTS Control Center, gunakan tombol start/restart Pentest di sana sebagai pengganti launcher terakhir.

Buka http://127.0.0.1:8790/pentest/

Installer memeriksa baseline mission_orchestrator(10).zip sebelum mengubah file, menyimpan backup file existing, lalu menyalin patch. Jika versi lokal berbeda, installer berhenti sebelum menulis; lakukan merge perubahan yang relevan. Database dan konfigurasi tidak disertakan atau ditimpa.

Panduan fitur, format input, batas integrasi, dan hasil tes berada di payload/README_PENTEST_UI_PHASE1.md.
