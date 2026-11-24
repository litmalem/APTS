# APTS GOV-PLANE — Tabletop Exercise Template (HO L4)

Fase 4 / AL-HO. Template latihan meja (tabletop) untuk memvalidasi
[Incident Response Runbook](INCIDENT_RESPONSE_RUNBOOK.md) secara berkala. Latihan
tabletop berkala adalah salah satu syarat **Human Oversight L4** (dokumen §6).

Cadence yang disarankan: **tiap kuartal** + setelah perubahan besar pada gate keamanan.

## Metadata latihan

| Field | Isi |
| --- | --- |
| Exercise ID | `tabletop-YYYYQn` |
| Tanggal | |
| Fasilitator | |
| Peserta (peran) | On-call Oversight / Incident Commander / Independent Reviewer / Pengamat |
| Skenario dipakai | (pilih di bawah) |

## Skenario (pilih ≥1 per latihan)

1. **Emergency-stop (SEV-1).** Alert `EMERGENCY_STOP_ACTIVE` saat dispatch Stage 6 berjalan. Harapan: semua target action ter-preempt (GOV-S06), dispatch DENY, bukti `emergency_stop=True`.
2. **Audit tamper (SEV-1).** `AUDIT_INTEGRITY_FAILURE` — satu record audit gagal verifikasi hash-chain. Harapan: containment, preservasi bukti, review pasca-insiden.
3. **Monitoring blind (SEV-2).** `MONITORING_STALE` — heartbeat hilang 20 menit. Harapan: perlakukan sebagai insiden (fail-closed), bukan diabaikan.
4. **Containment breach (SEV-1).** Harness Fase 2 melaporkan `contained=False` pada satu probe. Harapan: hentikan, akar masalah, perbaikan jadi test case.
5. **Autonomy downgrade (SEV-3).** `AUTONOMY_DOWNGRADE` terpicu `DEGRADE`. Harapan: operasi lanjut di level lebih rendah; naik kembali butuh `reauthorize_level()` + approver.

## Injeksi & langkah (isi saat latihan)

| T+ | Injeksi fasilitator | Tindakan peserta | Artefak/gate yang disentuh |
| --- | --- | --- | --- |
| 00:00 | Alert awal | | `monitoring_alerts()` |
| 00:05 | Eskalasi | Containment (emergency-stop / downgrade) | GOV-S06 / `downgrade_on_incident` |
| 00:15 | Permintaan recovery | Keputusan IC + re-otorisasi | `reauthorize_level()` |
| 00:30 | Penutup | Rencana review pasca-insiden | `build_periodic_review_attestation()` |

## Evaluasi (checklist pass/fail)

- [ ] Containment dilakukan fail-closed sebelum diagnosis.
- [ ] Bukti dipreservasi (tak ada mutasi record hash-bound).
- [ ] Recovery/naik-level hanya lewat jalur re-otorisasi manusia.
- [ ] Review pasca-insiden ditandatangani reviewer **independen** (bukan IC).
- [ ] SLA severity terkait terpenuhi.

## Temuan & tindak lanjut

| # | Temuan | Severity | Pemilik | Tenggat |
| --- | --- | --- | --- | --- |
| | | | | |

## Bukti kesiapan

Latihan yang lulus → set `incident_response_tested=True` pada evidence
`l3_to_l4_readiness()`. Simpan lembar ini (terisi) sebagai artefak audit; tautkan ID-nya
di tiket readiness L3→L4.
