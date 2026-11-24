# APTS — Autonomous Penetration Testing System

Workspace ini berisi layanan CTI, Governance, Mission, Pentest, Execution, dan
Web Technology Profiler. Panel Control Center mengelola proses lokalnya.

## Modul utama

| Folder | Tanggung jawab | Port lokal melalui Control Center |
| --- | --- | --- |
| `APTS_Control_Center/` | Kontrol proses, health monitoring, dan log | 8800 |
| `vulndesk/` | CTI, data vulnerability, enrichment, desktop PySide6 | API 8765; Web 8801 |
| `aptsGS/` | Scope/RoE, kebijakan, approval, audit, emergency stop | API 8770; Web 8802 |
| `mission_orchestrator/` | Mission, Pentest Workspace, Execution Runtime | Mission/Web 8780; Pentest/Web 8790; Runtime 8792 |
| `WebTechnologyProfiler/` | Profil teknologi web, ledger job, integrasi Recon | 8791 |

Port di atas mengikuti `APTS_Control_Center/config.json`, bukan hasil pemeriksaan
layanan aktif. Mission Web berbagi proses dengan Mission; Pentest Web berbagi
proses dengan API Pentest.

## Menjalankan panel

Setelah dependency Python tiap layanan, konfigurasi lokal, dan database siap:

```powershell
Set-Location D:\APTS\APTS_Control_Center
.\START_UI.bat
```

Buka `http://127.0.0.1:8800`. Menyalakan layanan tidak sama dengan menjalankan
scan. Gunakan panel agar parameter runtime dan integrasi antarlayanan mengikuti
konfigurasi yang sama.

## Panduan struktur

- [Arsitektur dan sumber runtime](docs/ARSITEKTUR.md)
- [Aturan source, data, dan backup](docs/PENGELOLAAN_WORKSPACE.md)
- [Control Center](APTS_Control_Center/README.md)
- [Governance](aptsGS/README.md)
- [Mission](mission_orchestrator/README.md)
- [VulnDesk](vulndesk/README.md)
- [Web Technology Profiler](WebTechnologyProfiler/README.md)

Dependency dan migrasi dikelola per modul. Jangan memasang seluruh requirements
ke satu environment tanpa memeriksa kompatibilitasnya.
