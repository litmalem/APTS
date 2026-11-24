# CTI Services Merge - Installation Notes

Paket ini adalah hasil merge source asli dengan modul CTI service. Virtual environment (`.venv`) tidak disertakan agar paket ringan dan portable.

## Urutan instalasi database

1. Jalankan `sql_update_cti_services/01_pentest_new_tables.sql` pada database Pentest (`cti_pentest`).
2. Jalankan `sql_update_cti_services/02_vulndesk_new_tables.sql` pada database VulnDesk (`vulndesk`).
3. Jalankan `sql_update_cti_services/03_vulndesk_seed_attack_mappings.sql` pada database VulnDesk.

## Pentest

Fitur baru:
- folder `cti_services/`
- folder `cti_ui/`
- tombol `CTI Services` pada panel input aplikasi utama
- runner standalone: `python run/run_pentest_service_manager.py`

Setelah scan selesai, buka `CTI Services`, pilih Job Scan, lalu jalankan `Generate Local Candidates` atau `Run VulnDesk Enrichment`.

## VulnDesk

Fitur baru:
- folder `cti_services/`
- folder `cti_ui/`
- tab `CTI Services` pada aplikasi utama
- runner standalone service manager: `python run/run_vulndesk_service_manager.py`
- runner API: `python run/run_vulndesk_api.py --host 127.0.0.1 --port 8765`

Jalankan API VulnDesk sebelum Pentest melakukan enrichment. Endpoint default: `http://127.0.0.1:8765`.

## Dependensi tambahan

Pastikan dependensi berikut terpasang pada environment masing-masing aplikasi:

```bash
pip install -r requirements.txt
```

Dependensi tambahan utama: `packaging`, `requests`, `pymysql`, `PySide6`.

## Catatan keamanan dan interpretasi

Hasil ATT&CK, malware, dan actor context adalah threat context/relevance, bukan bukti atribusi serangan. Untuk atribusi actor/malware diperlukan telemetry seperti log server, WAF/IDS/EDR alert, IOC match, malware sample, atau incident report.
