# APTS GOV-PLANE — Incident Response Runbook (HO L4)

Fase 4 / AL-HO. Prosedur respons insiden untuk subsistem pentest + GSS. Runbook ini
adalah syarat **Human Oversight L4** (dokumen §6): respons insiden *teruji*, bukan
hanya approval per-aksi. Pasangkannya dengan monitoring 24/7 (`app/oversight_attestation.monitoring_alerts`)
dan jalur downgrade level (`app/authorization_level.downgrade_on_incident`).

## 1. Klasifikasi insiden

| Kelas | Pemicu (sinyal) | Contoh |
| --- | --- | --- |
| **SEV-1 Kritis** | `EMERGENCY_STOP_ACTIVE`, `AUDIT_INTEGRITY_FAILURE`, containment breach | Emergency-stop aktif; record audit gagal verifikasi hash; probe containment (Fase 2) melaporkan breach |
| **SEV-2 Tinggi** | `MONITORING_STALE`, `INELIGIBLE_SPIKE` tak terduga | Tidak ada heartbeat monitoring dalam interval; lonjakan penolakan keputusan |
| **SEV-3 Sedang** | `AUTONOMY_DOWNGRADE`, anomali RoE | Downgrade level otomatis terpicu; pelanggaran RoE tunggal terkandung |

## 2. Alur respons (semua SEV)

1. **Deteksi.** Alert dari `monitoring_alerts()` (24/7) atau laporan manual. Catat `alert.code`, severity, waktu.
2. **Contain (fail-closed dulu).**
   - SEV-1: picu **emergency stop** GSS (GOV-S06) — `emergency_stop_preempts_all_target_actions` memaksa DENY semua dispatch. Verifikasi via `execution_revalidation` (`emergency_stop=True`).
   - SEV-2/3: picu **downgrade level** — `downgrade_on_incident(grant, signal=…, to_level=…)`. Ceiling turun; `requires_reauthorization=True`.
3. **Preserve bukti.** Jangan hapus/мutasi record. Audit hash-chain (`audit_service`) + transition record (`authorization_level`) + evidence containment (`tests/containment`) adalah bukti forensik — hash-bound, rekonstruksi tanpa re-run.
4. **Eradicate & recover.** Perbaiki akar masalah. Naikkan kembali level **hanya** via `reauthorize_level()` dengan approver manusia (bukan otomatis).
5. **Review pasca-insiden.** Dalam ≤5 hari kerja: `build_periodic_review_attestation()` atas window insiden, ditandatangani reviewer independen. Lampirkan ke tiket.

## 3. Peran & eskalasi

- **On-call Oversight** — menerima alert, melakukan containment awal.
- **Incident Commander (manusia)** — memutuskan emergency-stop vs downgrade, otorisasi recovery.
- **Independent Reviewer (manusia)** — menandatangani review pasca-insiden (bukan orang yang sama dengan IC).
- **Execution authority** tetap **Stage 6 saja**; oversight tidak pernah mengeksekusi.

## 4. SLA (target L4)

| Severity | Deteksi→Contain | Review pasca-insiden |
| --- | --- | --- |
| SEV-1 | ≤ 5 menit (emergency stop dalam detik) | ≤ 2 hari kerja |
| SEV-2 | ≤ 15 menit | ≤ 5 hari kerja |
| SEV-3 | ≤ 1 jam | siklus review berkala berikutnya |

## 5. Bukti kesiapan (untuk gate L3→L4)

Setiap latihan/insiden nyata menghasilkan bukti yang di-feed ke
`l3_to_l4_readiness(evidence={... "incident_response_tested": True ...})`. Tanpa
bukti IR teruji, kriteria `INCIDENT-RESPONSE` tetap `unmet` dan readiness `ready=False`.
