# Perubahan Stage 6.10

- Kontrak final berisi 16 fase trajectory, 14 gate, hash predecessor 6.9 dan domain closure Mission/Pentest, serta pernyataan authority yang eksplisit.
- Runtime `APTSAcceptanceService`, handler loopback 6.10, CLI, endpoint kontrak read-only, dan penolakan caller PASS/evidence upload.
- Fingerprint lokasi sumber dalam health Mission, Pentest, dan Execution untuk mendeteksi konfigurasi yang membaca database berbeda. Pemeriksaan juga mencocokkan driver Mission dan URL Governance.
- Harness eksternal mengunci corpus tiga komponen, mengompilasi sumber, menjalankan probe native, memeriksa JUnit/exit code, snapshot sumber, dan audit connected trajectory. Bukti lama tidak ditimpa.
- Skenario native menghubungkan objective Mission, PIP asli VulnDesk, planned task, keenam specialist, kode GSS asli, controlled execution, VEP, knowledge feedback, governed replan commit, restart/replay, dan rekonstruksi forensic menggunakan fixture terisolasi.
- Verifier offline mengikat empat export: PIP CTI, PIP Pentest, knowledge/VEP, serta forensic bundle Mission. Tes negatif mencakup tampering, manifest/coverage palsu, skip, source drift, foreign identity, serta kill/abort.
- Perbaikan `mission_orchestrator/replan_validation.py` mempertahankan `cti_feedback_requirements` dalam evaluasi deterministic reproduction. Pemeriksaan trusted snapshot dan semua rejection untuk requirement yang diubah tetap berlaku.
- Skrip PowerShell untuk start dan acceptance, dependensi backend tambahan, serta panduan instalasi.

Tidak ada migration atau store runtime baru. Sumber GSS/VulnDesk dan SQL dump tetap memakai baseline yang disediakan. Semua target I/O pengujian hanya menuju server loopback terisolasi; deployment preflight bersifat read-only. PASS build Linux tidak menyatakan acceptance Windows atau eksekusi misi pengguna.
