# Stage 6.5 — Perbaikan tes timeout dan retry

Full regression Windows melaporkan kegagalan `test_retry_rejects_completed_or_possible_io[TIMEOUT]`: retry tidak melempar `ExecutionSourceRejected`. Tes memakai timeout 0,3 detik sejak admission, sehingga deadline dapat habis saat native worker belum siap dan belum terjadi target I/O. Untuk kondisi yang terbukti tanpa I/O dan sudah menutup resource, manual retry memang memenuhi syarat hasil.

Kegagalan yang sama direproduksi dengan delay startup 0,45 detik. Probe ini juga menemukan asumsi readiness pada tes DNS timeout yang memakai deadline 0,25 detik.

Perbaikan mengubah dua tes pada `tests/test_stage6_5_execution_runtime_control.py`:

- Tes TIMEOUT setelah I/O menunggu request benar-benar diterima target loopback, lalu memajukan clock fixture ke deadline yang tersimpan. Tes memeriksa bukti I/O, penutupan resource, penolakan retry dengan reason yang tepat, dan jumlah attempt yang tetap satu.
- Tes DNS timeout menunggu native worker mencapai fase DNS yang sengaja diblokir, lalu memajukan clock fixture ke deadline. Tes memeriksa worker cleanup, bukti tanpa I/O, serta manual retry dengan identitas baru yang berhasil.

`run/stage6_5_regression.py` kini mencetak node pytest, traceback JUnit, dan lokasi log ketika kelompok gagal. Semua testcase tetap dijalankan sekali; runner tidak melakukan retry otomatis atau mengubah hasil gagal menjadi PASS.

Kode layanan runtime, aturan retry, batas deadline, kontrak SHA-256, migration 5, GSS, serta sumber Mission/Pentest tetap sama. Inventory canonical tetap **2539**, focused tetap **70**, dan continuity tetap **530**.

## Memasang pada Stage 6.5 yang sudah aktif

Dari ZIP terbaru, timpa hanya dua berkas berikut pada root `D:\mission_orchestrator`:

```text
tests\test_stage6_5_execution_runtime_control.py
run\stage6_5_regression.py
```

Perbaikan ini tidak memerlukan restart runtime atau perubahan database. Untuk mengulang probe startup secara lokal, salin juga `evidence\stage6_5\retry_timeout_startup_probe.py` dari ZIP.

Jalankan tes yang sebelumnya gagal, kemudian acceptance:

```powershell
cd D:\mission_orchestrator
python -m pytest -q "tests/test_stage6_5_execution_runtime_control.py::test_retry_rejects_completed_or_possible_io[TIMEOUT]"
.\STAGE6_5_ACCEPTANCE.ps1
```

Probe tambahan, opsional:

```powershell
python -m pytest -q "tests/test_stage6_5_execution_runtime_control.py::test_retry_rejects_completed_or_possible_io[TIMEOUT]" tests/test_stage6_5_execution_runtime_control.py::test_blocked_dns_deadline_reaps_native_worker_and_can_retry -p evidence.stage6_5.retry_timeout_startup_probe
python -m pytest -q evidence/stage6_5/retry_timeout_startup_probe.py
```

Probe terakhir memeriksa timeout saat startup tanpa I/O, kemudian retry manual yang memperoleh authorization baru dan melakukan satu request target loopback. Proof tambahan tidak masuk inventory canonical.

Hasil terkini terdapat pada `evidence/stage6_5/retry_timeout_fix_summary.json`. Log/XML `retry_timeout_before_fix` adalah negative control yang sengaja mempertahankan tes lama dan menunjukkan kegagalan sebelum perbaikan. Verification setelah perbaikan serta full canonical regression harus PASS. Acceptance Windows dengan source yang diperbaiki masih perlu dijalankan di host pengguna.
