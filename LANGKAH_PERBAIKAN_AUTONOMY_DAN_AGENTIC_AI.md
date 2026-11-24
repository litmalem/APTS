# Langkah-Langkah Perbaikan Level Autonomy & Kriteria Agentic AI — APTS Pentest Subsystem

Acuan: `APTS Pentest Subsystem — Traceability Autonomy & Agentic AI.md` (19 Nov 2026, @litmalem)
Lingkup kode: `mission_orchestrator/pentest_subsystem/` + lapisan platform `aptsGS/` (GSS / GOV-PLANE).

---

## 0. Prinsip panduan (jangan dilanggar)

Dokumen acuan menegaskan bahwa posisi **L2–L3 / bounded autonomy itu disengaja** (defense-in-depth): reasoner dipisah dari execution authority, dan Stage 6 adalah satu-satunya execution authority. Maka:

- **Perbaikan tidak boleh menaikkan intensitas, memperluas scope, atau memindahkan eksekusi ke layer agentic.** Semua langkah di bawah bersifat *menutup gap verifikasi/oversight/penamaan*, bukan "melepas rem".
- Kriteria agentic #1 (otonomi penuh) dan #6 (tool-use langsung) **tetap ditahan**. Yang diperbaiki adalah **auditabilitas, containment verification, dan formalisasi oversight** — bukan menghilangkan batasannya.
- Setiap langkah berakhir pada **test case / artefak yang bisa diverifikasi**, mengikuti pola traceability dokumen (`met` / `partial` / `gap`).

Keputusan arah lebih dulu: **apakah target tetap "AUTONOMOUS_BOUNDED" (L2–L3) atau menuju L4?**
- Jika **tetap bounded** → kerjakan **Fase 1 + Fase 2** saja (luruskan istilah, tutup containment probe, verifikasi platform). Ini membuat status subsistem *clean* tanpa mengubah postur keamanan.
- Jika **menuju L4** → lanjut ke **Fase 3 + Fase 4** (re-authorization/downgrade + HO L4 formal). Sebagian besar ini *procedural*, bukan hanya kode.

---

## Bagian A — Perbaikan Level Autonomy

### Fase 1 — Luruskan istilah & hilangkan tabrakan skala (Rekomendasi #1)

**Masalah.** `AUTONOMY_LEVEL` (skala L0–L3, gating proposal per-kapabilitas) di `orchestration/deliberation.py:33` tertukar dengan model L1–L4 OWASP platform. Ini menimbulkan salah-baca status autonomy.

**Langkah:**

1. **Rename simbol kode** `AUTONOMY_LEVEL` → `PROPOSAL_GATING_LEVEL` dan `_GOVERNANCE_PENALTY` → `_PROPOSAL_GATING_PENALTY` di `orchestration/deliberation.py` (baris 33, 41, 146, 152, 222 + `__all__`).
2. **Tambahkan docstring semantik** di atas konstanta: "L0 advice → L1 auto-proposal → L2 proposal butuh policy-approval → L3 human-approval; BUKAN L1–L4 Graduated Autonomy platform."
3. **Sediakan alias deprecated** sementara (`AUTONOMY_LEVEL = PROPOSAL_GATING_LEVEL` dengan `DeprecationWarning`) agar konsumen hilir tidak putus; jadwalkan penghapusan.
4. **Grep & update konsumen**: cari semua referensi `AUTONOMY_LEVEL` di repo (`deliberation.py`, test, dan importer), ganti ke nama baru.
5. **Dokumentasikan** peta istilah di README subsistem: tabel "L0–L3 (gating proposal) vs L1–L4 (mode platform)".

**Definition of done:** tidak ada lagi `AUTONOMY_LEVEL` tanpa qualifier; test lama hijau; ada 1 test yang menegaskan nama baru + alias.
**Status target:** penamaan `gap` → `met`.

---

### Fase 2 — Tutup gate AL-028: Containment verification probe (Rekomendasi #2) ⟵ prioritas tertinggi

**Masalah.** Nol harness probe containment; platform eksplisit *"untrusted-code containment is not claimed"* (`PATCH_MANIFEST_STAGE6_4_GSS.json:154`). Ini satu-satunya gate `gap` yang **murni in-code** dan bisa ditutup tanpa proses manual.

**Langkah (bangun harness probe DI LUAR runtime agent, batas aman localhost lab):**

1. **Buat paket uji terpisah** `tests/containment/` (di luar path runtime agent) — jangan diimpor oleh runtime.
2. **Probe write-escape:** agent/Stage-6 sandbox diminta menulis file **di luar path yang diizinkan** → harness memverifikasi operasi **ditolak/gagal** (fail-closed).
3. **Probe network-egress:** picu resolusi DNS / koneksi **di luar allowlist** → harus diblok; verifikasi tidak ada egress keluar loopback lab.
4. **Probe tool-call off-schema:** kirim permintaan tool-call yang **melanggar skema kapabilitas** → harus ditolak oleh `capability_contract` / gate deterministik GSS (GOV-S04).
5. **Probe prompt-injection containment:** suntik instruksi berbahaya via artefak/belief yang diproyeksikan → verifikasi beliefs tetap *server-owned* (tidak mematuhi instruksi caller), menutup sebagian **MR** (Manipulation Resistance) sekaligus.
6. **Catat hasil sebagai artefak audit** (hash-bound, sejalan `deliberation.py:197`) agar probe ini sendiri auditable & replayable.
7. **Jadikan CI gate**: probe wajib lulus; bila lulus, **ubah klaim manifest** dari *"not claimed"* menjadi *"containment verified by external harness"* dengan tautan bukti.

**Definition of done:** 4 kelas probe hijau + artefak bukti + manifest diperbarui.
**Status target:** AL-028 `gap` → `met`; MR `partial` → `met` (untuk aspek probe eksternal).
**Catatan keamanan:** semua probe dibatasi ke **loopback/localhost lab**, read-only kecuali untuk uji write-escape yang menargetkan path sandbox, fail-closed.

> **Status implementasi (SELESAI — 19 Nov 2026).** Harness dibangun di
> `mission_orchestrator/tests/containment/` (di luar runtime agent):
> `containment_harness.py` (engine + evidence record hash-bound, bisa jalan
> standalone sebagai CI gate: `python -m tests.containment.containment_harness`,
> exit 0=contained) dan `test_containment_al028.py` (15 test hijau).
> 11 probe menutup ke-4 vektor dengan memukul `evaluate_scope_roe` (fail_closed):
> A1 off-allowlist / A2 denylist, B1 IP off network-range / B2 host tak-resolvable,
> C1/C2 off-schema (ditolak kontrak) / C3 capability-identity mismatch / C4
> prohibited action+technique, D1 metadata-injection tak menimpa boundary
> server-owned / D2 stop-signal; plus kontrol positif P0 (in-scope = ELIGIBLE tapi
> tetap non-eksekusi) agar suite tak "lulus karena menolak semua". Tiap keputusan
> juga di-assert membawa invariant non-eksekusi (`execution_started`,
> `tool_invocation_performed`, `external_network_io_performed`, `authorization_minted`
> = False).
>
> **Scope klaim (penting, jujur).** Harness ini memverifikasi **containment di
> lapisan keputusan governance** (fail-closed), **bukan** containment kode-untrusted
> level-OS di worker Stage 6. Karena itu klaim manifest
> `aptsGS/PATCH_MANIFEST_STAGE6_4_GSS.json:154` ("untrusted-code containment is not
> claimed") **sengaja TIDAK diubah** — klaim itu tentang lapisan berbeda dan masih
> benar. AL-028 yang tertutup di sini = *decision-boundary containment*; containment
> level-OS tetap `gap` terpisah bila nanti diperlukan.

---

### Fase 3 — AL-025: Re-authorization & jalur downgrade (Rekomendasi #4)

**Masalah.** TTL per-keputusan ada di GSS (`decision_ttl=300s`, `approval_ttl=900s`, `aptsGS/app/config.py:23`), tapi **re-authorization level tahunan** dan **jalur downgrade saat insiden** tidak ada.

**Langkah:**

1. **Model otorisasi berbatas waktu di level** (bukan hanya per-keputusan): tambah entitas `authorization_grant` dengan `valid_from`, `valid_until` (mis. tahunan), `authorized_level`, dan `approver` di GSS (`approval_auth.py` / `models.py`).
2. **Invariant revalidasi**: perluas `execution_revalidation.py` agar `EXPIRY` mencakup kadaluarsa grant level, bukan hanya keputusan/approval. Dispatch ditolak bila grant level kedaluwarsa.
3. **Jalur downgrade otomatis saat insiden**: pada sinyal `HALT`/`DEGRADE`/`ESCALATE`/`TERMINATE` (dari `replanning.py:14`) dan/atau emergency-stop GSS (GOV-S06), turunkan `authorized_level` secara otomatis dan paksa re-authorization manual untuk naik kembali.
4. **Audit transisi level**: setiap naik/turun level ditulis sebagai record hash-bound + alasan (lineage).
5. **Test**: grant kedaluwarsa → dispatch ditolak; insiden → auto-downgrade; naik level tanpa re-auth → ditolak.

**Definition of done:** siklus grant→expiry→re-auth + downgrade-on-incident tertutup test.
**Status target:** AL-025 `partial` → `met` (bila target L4) / `met-bounded` (bila tetap L2–L3, cukup downgrade + expiry tanpa siklus tahunan penuh).

> **Status implementasi (SELESAI sebagai kontrak murni — 19 Nov 2026).** Modul
> `aptsGS/app/authorization_level.py` (GOV-PLANE, hash-bound, tanpa I/O) + config
> `GOV_LEVEL_GRANT_TTL_SECONDS` (default 365 hari) di `aptsGS/app/config.py`, dengan
> test `aptsGS/tests/test_authorization_level_al025.py` (16 hijau). Yang dibangun:
> grant level berbatas-waktu L1–L4 (`build_authorization_level_grant`, valid_from..
> valid_until + approver + binding mission/scope); evaluasi fail-closed
> (`evaluate_level_authorization`: GRANT-INTEGRITY / GRANT-ACTIVE / GRANT-WINDOW /
> LEVEL-CEILING / EMERGENCY-STOP, grant hilang = ditolak); downgrade saat insiden
> (`downgrade_on_incident` untuk HALT/DEGRADE/ESCALATE/TERMINATE/EMERGENCY_STOP —
> monotonik turun, set `requires_reauthorization=True`); re-otorisasi manual
> (`reauthorize_level`, butuh approver manusia); dan **transition record** hash-bound
> (ISSUE/DOWNGRADE/REAUTHORIZE) sebagai lineage tamper-evident. Tiap keputusan
> membawa invariant non-eksekusi (Stage 6 tetap satu-satunya execution authority).
>
> **Wiring ke dispatch (A1 — SELESAI 19 Nov 2026).** Binding ke jalur dispatch GSS
> sudah dipasang, **opt-in & fail-closed**:
> - **Skema + repo** (`aptsGS/app/repositories.py`): `ensure_authorization_level_schema()`
>   (DDL portabel sqlite/mysql, `gov_authorization_level_grant` + `..._transition`),
>   `save_level_grant` (supersede ACTIVE lama), `get_active_level_grant`,
>   `save_level_transition`.
> - **Guard dispatch** (`aptsGS/app/governance_service.py` `_level_gate_denials`,
>   disisipkan setelah blok execution-checks): aktif **hanya** bila repo punya grant
>   store DAN request mendeklarasikan `autonomy_level_required` di context → `GateResult
>   DENY` dgn kode `LEVEL_AUTHORIZATION_FAILED:*`. Semua alur lama (tak deklarasi level)
>   tak tersentuh.
> - **Lifecycle service**: `issue_authorization_level_grant` / `downgrade_authorization_level`
>   / `reauthorize_authorization_level` (persist + audit + transition hash-bound).
> - **Tidak** menyentuh schema evaluation Stage-6 ter-seal. Test
>   `aptsGS/tests/test_authorization_level_dispatch_al025.py` (13 hijau: guard + sqlite
>   nyata); regresi dispatch `test_execution_revalidation_stage6_4` tetap **32 hijau**.
>
> Dengan A1, AL-025 `met` pada **lapisan kontrak + wiring dispatch**. Sisa `partial`
> menyempit ke **operasional**: penerbitan grant tahunan nyata + pemicu downgrade dari
> sinyal insiden hidup (bukan sekadar API tersedia).

---

## Bagian B — Perbaikan Human Oversight (HO) menuju L4

### Fase 4 — Formalkan oversight berkala L4 (Rekomendasi #3) — *procedural + hook kode*

**Masalah.** Kode masih approval per-aksi (`REVIEW_REQUIRED`, `governance_contract.py:331`); nol "24/7", "tabletop", "incident-response teruji" di subsistem. Ini **tidak bisa ditutup oleh kode saja** — butuh proses operasional. Kerjakan hanya bila target L4.

**Langkah (kode mendukung proses, bukan menggantikan):**

1. **Monitoring 24/7 hook**: ekspor metrik keputusan/arbitrasi/degradasi (dari `learning.py`, `adaptive_degradation.py`) ke kanal observability + alert threshold. Tautkan ke `audit_service.py` GSS.
2. **Siklus review berkala**: jadwalkan review independen atas log keputusan (mis. mingguan/bulanan); sediakan laporan ter-generate dari record hash-bound (`plan_explanation` + `impact_report`).
3. **Incident-response runbook teruji + tabletop**: dokumen prosedur + latihan periodik; simpan bukti pelaksanaan sebagai artefak (procedural).
4. **Prasyarat transisi L3→L4** (dokumen §6): kumpulkan bukti ≥500 jam operasi L3, adversarial safety testing (sambungkan ke harness Fase 2), review independen — sebagai gerbang audit, bukan flag kode.

**Definition of done:** runbook + bukti tabletop + dashboard monitoring + laporan review berkala tersedia dan tertaut ke record auditable.
**Status target:** HO `gap` → `met` (procedural), prasyarat L3→L4 terdokumentasi.

> **Status implementasi (SELESAI sebagai hook + prosedur — 19 Nov 2026).** Dua bagian:
>
> **Hook kode** — `aptsGS/app/oversight_attestation.py` (pure, hash-bound; test
> `aptsGS/tests/test_oversight_attestation_ho.py`, 14 hijau):
> `monitoring_alerts()` (24/7: `MONITORING_STALE` bila heartbeat hilang,
> `AUDIT_INTEGRITY_FAILURE`, `EMERGENCY_STOP_ACTIVE`, `INELIGIBLE_SPIKE`,
> `AUTONOMY_DOWNGRADE`); `build_periodic_review_attestation()` (review berkala
> human-signed, fail-closed bila ada record gagal integritas / reviewer kosong /
> alert kritis); `l3_to_l4_readiness()` (akumulator §6: ≥500h L3, containment Fase 2,
> review independen, monitoring aktif, IR teruji → `ready` hanya bila semua `met`).
> Ketiganya mengikat Fase 2 (bukti containment) & Fase 3 (downgrade) sebagai input.
>
> **Prosedur** — `aptsGS/docs/oversight/`: `INCIDENT_RESPONSE_RUNBOOK.md` (klasifikasi
> SEV, alur fail-closed, SLA, peran), `TABLETOP_EXERCISE_TEMPLATE.md` (skenario +
> checklist evaluasi, cadence kuartalan), `L3_TO_L4_TRANSITION_CHECKLIST.md` (gate
> audit prasyarat).
>
> **Batas jujur.** Ini *instrumentasi + prosedur*, bukan operasi. HO L4 jadi `met`
> hanya setelah 24/7 monitoring, review berkala, dan tabletop benar-benar dijalankan
> dengan bukti yang diatestasi fungsi-fungsi ini. Sampai itu, HO tetap `partial`
> (procedural) — instrumentasi siap, operasinya yang menentukan.
>
> **Pipeline monitoring operasional (A3 — SELESAI 19 Nov 2026).** `monitoring_alerts()`
> kini tersambung ke data nyata lewat satu snapshot hidup:
> - **Agregasi repo** (`repositories.py`): `monitoring_window(since=...)` menghitung
>   `total_decisions`/`ineligible` (dari `gov_policy_decisions`), `emergency_stops`
>   (`gov_emergency_actions` ACTIVATE), `downgrades` (`gov_authorization_level_transition`),
>   `integrity_failures` via `audit_chain_breaks()` (deteksi putus linkage hash-chain
>   `gov_audit_log`); timestamp diformat `YYYY-MM-DD HH:MM:SS` agar portabel sqlite/mysql.
> - **Heartbeat liveness**: tabel `gov_monitoring_heartbeat` + `read/touch` — gap antar
>   sampel memunculkan `MONITORING_STALE` (sinyal 24/7 nyata).
> - **Service** (`governance_service.py`): `monitoring_snapshot(window_seconds)` →
>   agregasi → hitung gap → `build_monitoring_snapshot()` ter-seal (`oversight_attestation.py`,
>   +`verify_monitoring_snapshot`) → catat heartbeat + audit record. Loop terjadwal yang
>   memanggil ini tiap interval = sinyal monitoring 24/7.
> - Test `aptsGS/tests/test_oversight_monitoring_a3.py` (8 hijau: wiring + sqlite agregasi);
>   regresi dispatch/AL-025 tetap hijau.
>
> Sisa operasional: menjadwalkan loop pemanggil + dashboard/paging (deployment), bukan kode.

---

### Fase 5 — Verifikasi lokasi gate platform (Rekomendasi #5) — kerjakan lebih awal

**Masalah.** Beberapa gate yang tampak `gap` di subsistem ternyata **ada di lapisan platform GSS** (kill-switch GOV-S06, deny-by-default GOV-S02, revalidasi-sebelum-dispatch). Perlu konfirmasi agar tidak salah tandai `gap` final.

**Langkah:**

1. **Audit silang katalog GSS**: petakan tiap requirement dokumen → komponen GSS nyata (`architecture.py`, `execution_revalidation.py`, `human_layer.py`). Hasil: tabel "gate × lokasi pemilik".
2. **Konfirmasi kill-switch end-to-end**: uji invariant `emergency_stop_preempts_all_target_actions` (`aptsGS/app/architecture.py:94`) benar memotong dispatch via `execution_revalidation.py` (test E2E).
3. **Tandai ulang status** di matriks traceability: pindahkan `partial`/`gap` yang tertutup platform menjadi `met (platform)` dengan bukti `file:line`.
4. **Pastikan Supply Chain Trust (TP)** benar milik platform lain (bukan subsistem) sebelum tetap `n/a`.

**Definition of done:** matriks traceability v2 dengan kolom "lokasi gate" terverifikasi; test E2E kill-switch hijau.

> **Status audit (SELESAI — 19 Nov 2026).** Katalog GOV + invariant dikonfirmasi di
> `aptsGS/app/architecture.py` (COMPONENTS GOV-S01..S06 & HUMAN-LAYER baris 7–85;
> INVARIANTS baris 87–100), dengan penegakan nyata ditautkan ke kode, bukan sekadar
> deklarasi.

#### Matriks traceability v2 — gate × lokasi pemilik (terverifikasi)

| Gate (dokumen) | Komponen GSS | Bukti penegakan `file:line` | Status v2 |
| --- | --- | --- | --- |
| Deny-by-default | GOV-S02/S04 | `policy_engine.py:82-84` (`effect or "DENY"`), `architecture.py:91` invariant `deny_by_default` | `met` (platform) |
| Scope/RoE aktif wajib | GOV-S01 | `policy_engine.py:69` (`NO_ACTIVE_SCOPE_CONTRACT`), `architecture.py:92` | `met` (platform) |
| Unknown action ditolak | GOV-S04 | `models.py:23` `ActionClass(str,Enum)` → parsing raise `ValueError`; `architecture.py:97` `unknown_action_classes_are_denied` | `met` (platform) |
| Hard-deny tak bisa di-bypass approval | GOV-S04 | `policy_engine.py:58-59`; `architecture.py:93` `human_approval_does_not_bypass_hard_denies` | `met` (platform) |
| Kill-switch / emergency stop (SC) | GOV-S06 | `policy_engine.py:55-56` (preempt DENY); `governance_service.py:646` `activate_emergency_stop` / `:680` `release_emergency_stop` (teraudit `EMERGENCY_STOP_ACTIVATED`); `execution_revalidation.py:161` | `met` (platform) |
| Revalidasi sebelum dispatch (SC/AL) | GOV-S04 | `execution_revalidation.py:15` CHECKS (SCOPE/ROE/POLICY/RISK/EXPIRY/REVOCATION/TARGET/TECHNIQUE) + `:161` FAIL/emergency→DENY; `architecture.py:96` invariant | `met` (platform) |
| Otorisasi berbatas waktu (AL-025) | GOV-S04 / (baru) authorization_level | TTL per-keputusan `config.py:23`; **grant level + downgrade** `app/authorization_level.py` (Fase 3) | `met` (kontrak); wiring dispatch `partial` |
| Oversight berkala (HO L4) | HUMAN-LAYER / (baru) oversight_attestation | per-aksi `human_layer.py`; **monitoring/review/readiness** `app/oversight_attestation.py` (Fase 4) | instrumentasi `met`; operasi `partial` |
| Containment (AL-028) | — | harness `tests/containment/` (Fase 2) = decision-boundary; OS-level `PATCH_MANIFEST_STAGE6_4_GSS.json:154` *not claimed* | decision-layer `met`; OS-layer `gap` |
| Supply Chain Trust (TP) | — | nol komponen supply-chain/model-trust/SBOM di `aptsGS/app/` | `n/a` (konfirmasi: milik lapisan lain) |

**Kesimpulan audit.** Mayoritas gate AL/SC yang tadinya tampak `gap` di subsistem
memang **tertutup di lapisan platform GSS** (deny-by-default, scope aktif, kill-switch,
revalidasi-sebelum-dispatch) — kini bertautan ke `file:line` nyata. Gap final menyempit
persis ke yang sudah ditangani Fase 2–4: AL-028 OS-layer (eksplisit tak diklaim),
wiring dispatch AL-025, dan **operasi** HO L4. `APTS_Control_Center` tetap lapisan
UI/orkestrasi, bukan pemilik gate.

---

## Bagian C — Kriteria Agentic AI (9 kriteria)

Dari dokumen: kuat di #2,3,4,5,8,9; *bounded* di #1 (otonomi), #6 (tool-use), #7 (learning). Perbaikan di sini **bukan** melepas bound, melainkan **memperkuat bukti & menutup verifikasi**:

| # | Kriteria | Status kini | Langkah perbaikan | Target |
| --- | --- | --- | --- | --- |
| 1 | Otonomi | `partial` (bounded, disengaja) | Dokumentasikan bound sebagai desain (bukan kekurangan); pastikan penamaan Fase 1 jelas | tetap bounded, label jelas |
| 6 | Tool-use | `partial` (dipisah ke Stage 6) | Verifikasi pemisahan via probe off-schema (Fase 2 #4); dokumentasikan kontrak usulan-vs-invokasi | tetap dipisah, terverifikasi |
| 7 | Pembelajaran | `met` (bounded) | Tambah test regresi: learning hanya *re-weight advisory*, tidak menaikkan intensitas/scope (`learning.py`, `reactive.py:6`) | pertahankan `met-bounded` |
| 2,3,4,5,8,9 | kognitif | `met` | Tidak diubah; hanya pastikan bukti tetap hash-bound & replayable | pertahankan `met` |

**Prinsip:** menaikkan #1/#6 ke "penuh" akan **melanggar SE/HO** — jangan dilakukan. Yang dikejar adalah **Level 5 Goal-Driven yang terverifikasi penuh**, bukan loncat ke otonomi tak-terbatas.

---

## Prioritas & urutan eksekusi

| Prioritas | Fase | Alasan | Sifat | Target status |
| --- | --- | --- | --- | --- |
| **P0** | Fase 5 (verifikasi platform) | Menghindari kerja mubazir; mungkin sebagian "gap" sudah tertutup | audit | matriks v2 |
| **P0** | Fase 1 (luruskan istilah) | Murah, menghapus salah-baca, tanpa risiko | kode | penamaan `met` |
| **P1** | Fase 2 (containment AL-028) | Satu-satunya `gap` in-code murni; menutup MR juga | kode + test | AL-028 `met` |
| **P2** | Fase 3 (AL-025 re-auth/downgrade) | Perlu hanya bila menuju L4 (downgrade-on-incident berguna walau tetap bounded) | kode | AL-025 `met` |
| **P3** | Fase 4 (HO L4) | Procedural berat; hanya bila target L4 | proses + hook | HO `met` |

**Rekomendasi pragmatis:** kerjakan **P0 + P1** lebih dulu. Setelah itu subsistem *bersih* pada posisi **L2–L3 yang disengaja** dengan penamaan benar dan containment terverifikasi — tanpa mengubah postur keamanan. Fase 3–4 hanya bila keputusan strategis menargetkan L4.

---

## Ringkasan gap → langkah

- **AL-028 containment** (`gap`, in-code) → **Fase 2** (harness probe eksternal, jadi test case).
- **AL-025 re-authorization level** (`partial`) → **Fase 3** (grant berbatas waktu + downgrade-on-incident).
- **HO L4 oversight berkala** (`gap`, procedural) → **Fase 4** (24/7 + review berkala + tabletop + incident-response).
- **Tabrakan istilah** → **Fase 1** (`PROPOSAL_GATING_LEVEL`).
- **Lokasi gate platform** → **Fase 5** (audit silang GSS, hindari salah tandai).

*Bukti `file:line` relatif terhadap `mission_orchestrator/pentest_subsystem/` dan `aptsGS/`.*
