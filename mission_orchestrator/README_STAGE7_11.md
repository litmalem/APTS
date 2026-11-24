# Stage 7.11 — CAE di-wire ke Control Center (:8800 → :8790)

**Status:** implemented · additive · fail-closed · loopback-only
**Acceptance:** `python3 tests/test_stage7_11_cae_endpoint.py` → 8/8 PASS · regresi Stage 7 → 13/13 suite hijau

## Masalah yang diperbaiki
Sebelumnya lapisan CAE (Stage 7) hanya bisa dijalankan lewat `run_cae_live.py`. UI Control
Center `:8800` menjalankan pipeline dasar yang **tidak mengeksploitasi**, sehingga menekan
"pentest" dari `:8800` tak pernah men-solve tantangan BAC. Stage 7.11 menyambungkan CAE ke
service pentest sebagai endpoint opt-in.

## Yang ditambahkan (aditif)
- `pentest_subsystem/cae_service_runner.py` — core HTTP reusable (shared dengan host runner;
  tanpa Selenium) + gate fail-closed `evaluate_cae_request` + dispatch `handle_cae_execute` +
  `execute_bac_http` (injectable untuk test).
- `pentest_subsystem/runtime_autonomy_api.py` — route baru `POST /api/pentest/cae/execute`.
- `pentest_web/cae.html` + route di `web_ui.py` (`/pentest/cae/`), tertaut dari halaman Exploitation.

## Pagar (double-gate, fail-closed)
1. Master-switch server: env `APTS_CAE_ROE_MASTER` ∈ {1, ARM, ARMED, TRUE, ON}.
2. Token per-request: body `{"arm": "ARM-CAE"}`.
3. Target wajib loopback (127.0.0.1/localhost/::1). SPA (Web3/Admin) ditolak → arahkan ke host runner.
Tanpa gate 1+2 terpenuhi, **tak ada** request menyentuh target (403 `FAIL_CLOSED`).

## Cara pakai dari :8800
```powershell
# 1) set master-switch SEBELUM start Control Center (env diwariskan ke subproses :8790)
$env:APTS_CAE_ROE_MASTER = "ARM"
# 2) jalankan Control Center seperti biasa (buka :8800)
#    pastikan OWASP Juice Shop up di http://127.0.0.1:3000 dan sudah di-reset
# 3) di UI: Pentest :8800  ->  Exploitation (stage 05)  ->  "⚡ Controlled Active Exploitation" ->  Jalankan CAE (RoE)
```
Endpoint langsung (tanpa UI):
```powershell
curl -s -X POST http://127.0.0.1:8790/api/pentest/cae/execute -H "Content-Type: application/json" -d '{"arm":"ARM-CAE"}'
```
Respons memuat `solved_before`/`solved_after`/`newly_solved`, rantai per-tantangan, dan seal integritas.
Jika master-switch mati → `{"status":"blocked","cae":"FAIL_CLOSED","reason":"CAE_ROE_MASTER_OFF"}`.

## Batas
- Endpoint menjalankan tantangan BAC via HTTP (7 default). SPA (web3Sandbox/adminSection) tetap
  lewat `run_cae_live.py --browser` di host (butuh Selenium).
- Master-switch sengaja via env (bukan tombol UI) agar arming adalah keputusan sadar operator.
