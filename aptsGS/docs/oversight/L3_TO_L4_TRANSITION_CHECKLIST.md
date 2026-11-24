# APTS — L3 → L4 Transition Readiness Checklist (HO/AL)

Fase 4. Gate audit untuk kenaikan dari **L3** ke **L4 (Autonomous)** pada model
Graduated Autonomy OWASP (dokumen §6). Checklist ini **bukan** otorisasi — ia
mengumpulkan bukti; keputusan menaikkan ke L4 tetap keputusan **manusia**
(Incident Commander / otoritas kebijakan), yang direkam lewat
`authorization_level.reauthorize_level(authorized_level=4, …)`.

Status terkonsolidasi dihitung oleh `oversight_attestation.l3_to_l4_readiness()`:
`ready=True` hanya jika **semua** kriteria `met`.

## Prasyarat (§6)

| Kriteria | ID (`l3_to_l4_readiness`) | Bukti yang diperlukan | Status |
| --- | --- | --- | --- |
| ≥ 500 jam operasi L3 | `L3-HOURS` | Akumulasi jam operasi pada level L3 (`l3_operating_hours`) dari log keputusan | ☐ |
| Adversarial / containment testing | `ADVERSARIAL-SAFETY` | Harness Fase 2 `tests/containment` melaporkan `contained=True`; evidence record hash-bound terlampir | ☐ |
| Review independen | `INDEPENDENT-REVIEW` | `build_periodic_review_attestation()` lulus (`review_passed=True`), reviewer ≠ operator | ☐ |
| Monitoring 24/7 aktif | `MONITORING-24-7` | `monitoring_alerts()` tanpa `MONITORING_STALE`; heartbeat kontinu | ☐ |
| Incident response teruji | `INCIDENT-RESPONSE` | Minimal satu tabletop lulus (template terisi) + runbook ter-review | ☐ |

## Verifikasi bukti

Semua bukti harus **hash-bound & tamper-evident**:
- Keputusan governance: `verify_scope_roe_decision` / `verify_level_authorization_decision`.
- Review berkala: `verify_periodic_review_attestation`.
- Readiness: `verify_l3_to_l4_readiness`.

## Keputusan

- [ ] Semua kriteria `met` dan readiness attestation `ready=True` (verifikasi hash lulus).
- [ ] Otoritas manusia menyetujui transisi; direkam via `reauthorize_level(authorized_level=4)` dengan `valid_until` (default tahunan).
- [ ] Jalur downgrade & emergency-stop diuji berlaku **juga** di L4 (level lebih tinggi ≠ menghapus rem).

**Catatan jujur.** Hingga semua di atas benar-benar dioperasikan (bukan sekadar
diinstrumentasi), status HO L4 tetap `gap`/`partial` sesuai dokumen acuan. Modul &
runbook ini menyediakan *instrumentasi dan prosedur*; **operasi berkelanjutannya**
yang membuat L4 layak.
