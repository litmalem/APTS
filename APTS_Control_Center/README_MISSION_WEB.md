# APTS Control Center — Mission Web Integration

Mission Web Phase 1 ditambahkan sebagai kartu layanan terpisah pada APTS Control Center.

- Mission API: `http://127.0.0.1:8780`
- Mission Web: `http://127.0.0.1:8780/ui/`
- Probe: `GET /api/dashboard/summary`
- Mission dan Mission Web berbagi proses/PID/port dan `logs/mission.log`.
- **Mulai Mission** menjalankan `run/run_stage6_10_mission.py`.
- **Buka Web** membuka `/ui/`.
- **Hentikan Mission** menghentikan Mission API dan Mission Web sekaligus, hanya bila proses dimiliki panel.
- **Monitor** hanya memakai endpoint GET/read-only.

`mission_web` tidak menambah authority, database, atau backend baru.
