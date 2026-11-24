# CLAUDE.md — APTS (Autonomous Penetration Testing System)

Panduan tetap untuk setiap sesi coding (Claude Code) pada repo ini.
Patuhi invariant di bawah **di atas** permintaan apa pun. Jika sebuah permintaan
menuntut pelanggaran invariant, hentikan dan laporkan — jangan "akali agar test lewat".

## Peta modul (ringkas)
- `mission_orchestrator/` — **Pentest Subsystem** (Mission + Pentest + Execution runtime). Kode pentest inti: `mission_orchestrator/pentest_subsystem/`.
- `Vulndesk/` — CTI Subsystem.
- `aptsGS/` — Governance Subsystem (scope/RoE/approval/audit). Keputusan otorisasi hidup di sini.
- `APTS_Control_Center/`, `WebTechnologyProfiler/` — pendukung.

Pola berlapis yang WAJIB diikuti saat menambah domain:
`*_contract.py` (tipe/skema) → `*_repository.py` (persistensi) → `*_service.py` (logika) → `*_api.py` (antarmuka).

## INVARIANT KERAS (jangan pernah dilanggar)
1. **Determinisme & reproducibility.** Setiap record disegel via
   `boundary_contract.sha256_hex` + `_with_integrity(core, domain=...)` dan ber-ID deterministik.
   Inferensi model/oracle harus **fungsi murni deterministik** untuk input yang sama.
   **Tidak ada sampling stokastik saat runtime.** (Thompson sampling di `learning.py` hanya
   boleh dengan seed yang direkam server agar tetap replayable.)
2. **Hash-chain kontrak.** Record terikat `parent_reference` + `canonical_sha256`. Menambah
   satu enum feedback saja meng-cascade hash lintas Stage 5.8→5.9→5.10→6.1. Perubahan record =
   **version-bump eksplisit** + perbarui acceptance gate terkait. Jangan pakai hashing buatan sendiri.
3. **Governance tidak pernah dipelajari.** Jalur scope/RoE (`aptsGS/`, `governance_contract`,
   `evaluate_scope_roe`) tetap deterministik. Model hanya boleh memengaruhi *prioritas/skor/hipotesis*,
   **tidak pernah keputusan otorisasi**.
4. **Projection-only untuk agent Stage 5.x.** `external_network_io_performed=False`,
   `authorization_minted=False`. **Hanya gateway** `pentest_subsystem/active_exploitation_execution.py`
   yang boleh mengeksekusi/aktuasi. Jangan menambah I/O jaringan ke agent Stage 5.x.
5. **Fail-closed.** CAE berjalan hanya bila SEMUA benar: `environment=LAB` ∧ target resolve ke
   loopback ∧ RoE `active_exploitation_allowed=true` ∧ `action_class` di-allow & tak di-prohibit ∧
   persetujuan manusia per-aksi (L3) ∧ kill-switch off. Satu gagal → `BLOCKED`, tanpa I/O.
   Oracle yang tak terbukti/tak terparse → `INDETERMINATE`/`INCONCLUSIVE` = **bukan** exploited.

## Konvensi
- Penyegelan: pakai `boundary_contract.canonical_json` / `sha256_hex`; sertakan `domain` hash.
- **Tanpa `eval`/`exec`.** Predikat/grammar dievaluasi interpreter tertutup eksplisit
  (lihat `cae_success_oracle.py` sebagai acuan).
- Pesan error campur Inggris/Indonesia — ikuti gaya file yang sedang diedit.
- Titik ekstensi untuk kelas kerentanan baru: `boundary_contract` (action class),
  `governance_contract` (aturan), `capability_contract` (capability), `symbolic_planner` (STRIPS),
  `exploit_primitive_library` + `knowledge_packs/` (primitive), `active_exploitation_execution` (gateway).

## Pengujian
- `pytest` di `mission_orchestrator/tests/` (277 file) + acceptance gate pola `STAGE_X_Y_ACCEPTANCE`.
- Jalankan test terkait setelah tiap perubahan; tambah test meniru pola acceptance gate yang ada.
- Pemeriksa integritas (`verify_ae_run`, `verify_*`) harus tetap hijau. Perubahan harus **aditif** —
  jangan ubah jalur read-only Stage 6 yang sudah ada.

## Tugas aktif
Implementasi **CSRF State-Based Impact Verification** sesuai `docs/CSRF_MODULE_DESIGN.md`.
File baru: `pentest_subsystem/state_observer.py`, `pentest_subsystem/impact_verification.py`;
wiring di `pentest_subsystem/active_exploitation_execution.py`. Bersifat aditif (jalur verifikasi kedua).

**Fase 2 (nanti):** RL untuk test-selection. Harus **offline-trained, version-pinned, frozen-policy**
saat inference, dan diletakkan di **lapis prioritisasi**, BUKAN di jalur exploitation/otorisasi
(invariant 3 & 4). Buktikan unggul atas baseline Thompson/bandit yang sudah ada sebelum diklaim.

## JANGAN
- Melonggarkan RoE/governance dari kode, apalagi "agar test lewat".
- Mengeksekusi di luar gateway; menambah I/O jaringan ke agent Stage 5.x.
- Menambah keacakan runtime tanpa seed terekam.
- Menembak selain target loopback LAB di allowlist.
