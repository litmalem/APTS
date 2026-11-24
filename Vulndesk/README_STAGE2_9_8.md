# Tahap 2.9.8 — End-to-End Acceptance

## Tujuan

Tahap 2.9.8 adalah **closure gate** untuk seluruh rangkaian Tahap 2.9.1–2.9.6. Tahap ini tidak menambah decision semantics baru dan tidak mengubah database schema. Ia membuktikan bahwa satu mission CTI yang benar-benar governed dapat berjalan end-to-end dan bahwa seluruh evidence plane dapat direkonstruksi serta diverifikasi melalui API yang sudah diimplementasikan.

Profil acceptance default adalah **governed, read-only CTI acquisition** menggunakan source `mitre-attack`, maksimum satu acquisition action, dan `target_actuation=false`.

## Yang diverifikasi

| Stage | Gate E2E |
|---|---|
| 2.9.1 | Canonical lineage `CANONICAL_V2`, event lifecycle, dan causal chain commit → revalidation → dispatch → terminal |
| 2.9.2 | Task Lineage Probe untuk governed task; PolicyDecision, AuthorizationRequest, ScopeContract, dan pre-dispatch revalidation harus terikat |
| 2.9.3 | Mission Lineage Reconstruction; task dan causal edge harus dapat direkonstruksi |
| 2.9.4 | Cross-subsystem correlation harus `CORRELATED`, coverage lengkap, tidak ada missing reference/field mismatch/external-event gap |
| 2.9.5 | Integrity probe `PASS`, `verification_complete=true`, violation=0, violated/unverifiable task=0 |
| 2.9.6 | CTI dan Governance deep diagnostics `READY`, mandatory fail=0, outbox pending=0/failed=0; mission diagnostics `HEALTHY` |
| 2.9.7 | GUI bersifat opsional; tidak menjadi blocking criterion |
| 2.9.8 | Satu fresh governed mission harus `COMPLETED`; read-only probes harus menghasilkan semantic fingerprint yang stabil |

## File

- `STAGE2_9_8_E2E_ACCEPTANCE.ps1` — acceptance runner utama.
- `STAGE2_9_8_ACCEPTANCE_CRITERIA.md` — kriteria PASS/FAIL dan interpretasi hasil.
- `stage2_9_8_manifest.json` — manifest patch/acceptance.

## Prasyarat

1. VulnDesk berjalan di `127.0.0.1:8765`.
2. aptsGSS / Governance & Safety Plane berjalan di `127.0.0.1:8770`.
3. Governance outbox sudah bersih: `pending=0`, `failed=0`.
4. VulnDesk dijalankan dalam mode normal, bukan test/negative gate.
5. Jalankan dari root repository VulnDesk (umumnya `D:\vulndesk`) agar regression gate dapat menemukan `tests\`.

## Cara instalasi

Salin tiga file patch ke `D:\vulndesk`:

```powershell
Copy-Item .\STAGE2_9_8_E2E_ACCEPTANCE.ps1 D:\vulndesk\ -Force
Copy-Item .\STAGE2_9_8_ACCEPTANCE_CRITERIA.md D:\vulndesk\ -Force
Copy-Item .\stage2_9_8_manifest.json D:\vulndesk\ -Force
```

Tidak ada migration SQL untuk 2.9.8.

## Menjalankan acceptance penuh

Buka **PowerShell baru**, lalu:

```powershell
cd D:\vulndesk
.\.venv\Scripts\activate

Set-ExecutionPolicy `
    -Scope Process `
    -ExecutionPolicy Bypass `
    -Force

.\STAGE2_9_8_E2E_ACCEPTANCE.ps1
```

Default runner akan:

1. compile orchestrator;
2. menjalankan focused regression 2.8.8 + 2.9.5 + 2.9.6;
3. menjalankan seluruh pytest suite VulnDesk;
4. memeriksa preflight health/diagnostics;
5. membuat fresh `mission-stage298-e2e-*` dan ScopeContract;
6. menjalankan governed CTI mission;
7. memeriksa mission/task lineage, governance correlation, integrity, diagnostics, dan outbox;
8. mengulang probe dan membandingkan semantic fingerprint untuk membuktikan read-only/idempotent projection;
9. menyimpan seluruh evidence ke `stage2_9_8_evidence\<mission_id>\`.

## API-only acceptance

Jika regression sudah dijalankan terpisah:

```powershell
.\STAGE2_9_8_E2E_ACCEPTANCE.ps1 -SkipRegression
```

Jika ingin menjalankan focused regression tetapi tidak seluruh suite:

```powershell
.\STAGE2_9_8_E2E_ACCEPTANCE.ps1 -SkipFullRegression
```

## Reuse mission yang sudah ada

Mode ini hanya memverifikasi evidence plane; runner tidak membuat ScopeContract/mission baru:

```powershell
.\STAGE2_9_8_E2E_ACCEPTANCE.ps1 `
    -MissionId "mission-stage295-governed-20260829-185446" `
    -ReuseExistingMission `
    -SkipRegression
```

Fresh mission tetap merupakan mode yang direkomendasikan untuk closure 2.9.8.

## Expected final output

Bagian akhir harus berbentuk:

```text
STATUS                 : PASS
MANDATORY_FAIL         : 0
[PASS] TAHAP 2.9.8 END-TO-END ACCEPTANCE CLOSED.
```

Evidence authoritative adalah file:

```text
stage2_9_8_evidence\<mission_id>\99_acceptance_summary.json
```

## Catatan versi

Runner default mengunci baseline saat ini:

```text
architecture_version = 2026-08-harmonized
control_version      = hybrid-event-driven-2.17-health-diagnostics
```

Apabila Anda memang melakukan version bump secara sengaja setelah patch ini, jalankan dengan:

```powershell
.\STAGE2_9_8_E2E_ACCEPTANCE.ps1 `
    -ExpectedControlVersion "<control-version-baru>"
```

Jangan override versi hanya untuk membuat test hijau; override harus mencerminkan runtime version yang benar-benar sudah diverifikasi.

## Interpretasi closure

Jika runner PASS, maka **Tahap 2.9.8 CLOSED/PASS** dan rangkaian observability/governance closure Tahap 2.9 dapat dianggap selesai. Kegagalan satu mandatory check berarti Tahap 2.9.8 belum ditutup; gunakan file evidence dengan nomor tahap yang gagal untuk menentukan titik regresi.
