# Rencana Implementasi Bertahap — Generalisasi Stage 7 (BAC sebagai Logika Pentest Umum)

**Tanggal:** 2026-11-21 · **Subsistem:** `mission_orchestrator/pentest_subsystem`
**Pemicu:** analisa mission `mission-gmo-3adb7cf5-d0d2-40cb-aae3-1d6030691bea`
**Sifat perubahan:** aditif (sidecar), backward-compatible, 77 test lama tetap hijau.

> **Keputusan final (2026-11-21):**
> 1. Knowledge-pack Juice **dipertahankan sebagai data** (bukan dibuang) → katalog lama di-*derive* darinya.
> 2. **Mission baru ber-scope CAE**, bukan re-scope `gmo-3adb7cf5` (scope ter-seal imutabel).
> 3. Enumerasi Fase 5: **"surface import" terotorisasi untuk MVP**, perkuat recon aktif setelahnya.
>
> **Status eksekusi:** Fase 0–5 ✅ · **Fase 6 ✅ SELESAI** (regresi 18/18 suite ~117 test + containment 15/15
> termasuk P14/P15 generik; README diperbarui). **SELURUH ROADMAP SELESAI.**
> **BUKTI LIVE (127.0.0.1:3000):** surface-import→sintesis→planner→gateway men-solve `easterEggLevelOne`
> (forced-browse) & `basketAccess` (idor-read) — keduanya **EXPLOITED/CONFIRMED oleh oracle bukti, tanpa
> challenge key**, dan **scoreboard cross-validation agreed=True**.

---

## 0. Ringkasan masalah (hasil pemeriksaan)

Dua gap terpisah ditemukan:

**Gap A — Stage 7 adalah *solver* OWASP Juice Shop, bukan logika pentest umum.**
- `exploit_primitive_library.py`: katalog hardcoded di-key `challenge_key`; endpoint, body, dan
  `success_predicate` literal Juice (`challenge.X.solved==true`, produk `O-Saft`, URL `/solve/...?key=tRy_H4rd3r...`).
- Deteksi sukses = scoreboard Juice. `ChallengeOracle` nge-diff `GET /api/Challenges`; di
  `active_exploitation_execution.py` `outcome="EXPLOITED"` **hanya** bila `challenge_key` muncul di scoreboard.
  Primitive tanpa challenge_key maksimal `ACTUATED` — tak pernah dinyatakan tereksploitasi.
- Entry point di mana-mana `primitives_for_challenge(challenge_key)`. `cae_service_runner` menolak
  apa pun di luar daftar Juice (`UNKNOWN_CHALLENGES`).

**Gap B — Stage 7 terputus dari pipeline mission.**
- Mission menghasilkan hipotesis (CTI/CVE, mis. Angular). Gateway mengkonsumsi `challenge_key` statis.
  Hipotesis mission tak pernah sampai ke gateway. Tak ada generator hipotesis BAC dari enumerasi.
- Mission `gmo-3adb7cf5` sendiri: scope `WPT_FINGERPRINT_AUTONOMOUS_V1`, `execution_authorized=false`,
  GET-only, 12 request, `endpoint_discoveries=0` → secara struktur tak bisa eksploitasi.

**Prinsip target:** sukses ditentukan dari **bukti respons nyata** (differential/authorization oracle),
primitive adalah **template berparameter target**, peta Juice dipindah jadi **knowledge-pack (data)**,
dan hipotesis BAC lahir dari **enumerasi** lalu mengalir ke gateway di bawah **RoE mission**.

---

## 1. Invarian yang WAJIB dijaga (guardrail)

1. 77 test Stage 7 lama tetap hijau tanpa diubah (challenge-key path dipertahankan sebagai knowledge-pack).
2. Semua pagar RoE Stage 7 tetap: loopback-only, master-switch, kelas aksi, approval single-use,
   blast-radius, kill-switch, auto-rollback, integrity-seal (`UTF8_SORTED_JSON_V1`), deterministic replay.
3. 13 probe containment (APTS-AL-028) tetap lulus; tak ada pelonggaran RoE.
4. Tak ada I/O jaringan di layer deklaratif; aktuasi hanya lewat transport yang di-inject.

---

## Fase 0 — Baseline & titik kontrak (0.5 hari)

**Tujuan:** kunci baseline sebelum menyentuh kode.
- Jalankan seluruh regresi Stage 7 + containment, simpan ringkasan hijau sebagai baseline.
- Dokumentasikan 3 titik kontrak yang akan di-extend (bukan diubah):
  `ActiveExploitationGateway.run_chain` (semantik outcome), `exploit_primitive_library` (katalog),
  `cae_service_runner.evaluate_cae_request` (validasi input).

**Selesai bila:** baseline hijau terekam; daftar test yang menegaskan perilaku Juice teridentifikasi
(`test_stage7_2`, `test_stage7_4`, `test_stage7_11`).

---

## Fase 1 — Oracle sukses generik (decouple dari scoreboard) (1–1.5 hari)

**Tujuan:** sukses eksploit dapat dideteksi tanpa scoreboard Juice.

**Perubahan (aditif):**
- Modul baru `cae_success_oracle.py`: evaluator `success_predicate` terhadap konteks
  `{response, status_code, session(self.userId/email/basketId), request}`.
  - Grammar aman & kecil (bukan `eval`): dukung `status==`, `&&`, `!=`, `==`, path `body.data.X`,
    pembanding `self.*`, `contains('...')`, `!= null`.
  - Verdict: `CONFIRMED` / `REFUTED` / `INDETERMINATE`.
- `active_exploitation_execution.py`: tambah parameter `success_oracle=None`. Logika outcome jadi
  **berlapis**:
  1. jika primitive punya `challenge_key` **dan** `oracle_fetcher` challenge tersedia → pakai scoreboard
     (jalur lama, test lama hijau);
  2. selain itu → pakai `success_oracle.evaluate(primitive, ctx)` → `EXPLOITED` saat `CONFIRMED`.
  Default `oracle_fetcher` boleh `None` untuk mission non-Juice.

**Test baru:** `test_stage7_1x_success_oracle.py` — IDOR read (owner≠self → CONFIRMED), mutation gagal
(403 → REFUTED), predikat tanpa challenge_key menghasilkan EXPLOITED tanpa scoreboard.

**Selesai bila:** gateway bisa memutus EXPLOITED pada target yang tak punya scoreboard; test lama hijau.
**Risiko:** parser predikat; mitigasi — grammar terbatas + fail-closed ke INDETERMINATE (bukan EXPLOITED).

---

## Fase 2 — Primitive jadi template berparameter + knowledge-pack Juice (1.5 hari)

**Tujuan:** pisahkan *mesin* primitive dari *pengetahuan* target.

**Perubahan:**
- `exploit_primitive_library.py`: perkenalkan **primitive-template generik** tak ber-challenge:
  `idor-read`, `idor-write`, `forced-browse`, `missing-func-level-ac`, `param-tamper`, `ssrf-generic`,
  masing-masing dengan `endpoint_template`/`http_method`/`action_class`/`success_predicate` berparameter
  (`{endpoint}`, `{id_param}`, `{route}`) — **tanpa** `challenge_key`.
- Pindahkan entri Juice saat ini ke `knowledge_packs/owasp_juice_shop.py` (atau JSON) sebagai **data**:
  peta `challenge_key → (template_id, params, prepare)`. Katalog lama tetap di-expose
  (`PRIMITIVES`, `primitives_for_challenge`, `BROKEN_ACCESS_CONTROL_CHALLENGES`) dengan di-*derive* dari
  knowledge-pack → test `test_stage7_2` tetap hijau.
- `make_hypothesis_record` diperluas menerima primitive-template + params runtime.

**Test baru:** `test_stage7_2x_generic_templates.py` — template membentuk plan STRIPS (auth→idor) tanpa
challenge_key; knowledge-pack Juice merender ulang katalog lama secara identik (hash cocok).

**Selesai bila:** katalog lama = turunan knowledge-pack; template generik lulus symbolic_planner.
**Risiko:** hash katalog berubah → kunci urutan/serialisasi agar canonical hash identik.

---

## Fase 3 — Generator hipotesis BAC dari enumerasi (2 hari)

**Tujuan:** sistem *menemukan* kandidat BAC, bukan diberi tahu.

**Perubahan:**
- Modul baru `bac_hypothesis_synthesis.py`: dari `enumeration.endpoint_discoveries` +
  `enumerated_assets` + `service_observations`, sintesis hipotesis:
  - path ber-ID numerik/opaque (`/rest/basket/{id}`, `/api/.../{id}`) → IDOR read/write (CWE-639);
  - route/area privileged (admin, internal) → forced-browse / missing function-level AC (CWE-284);
  - endpoint state-changing tanpa anti-CSRF → CSRF (CWE-352); URL-fetch param → SSRF (CWE-918).
  - Output: record hipotesis standar (CWE/CAPEC/ATT&CK + `planning_model` + ref ke primitive-template),
    **tanpa** challenge_key, lengkap dengan `confidence` & `evidence_refs`.
- Integrasi ke `vulnerability_hypothesis` sebagai sumber hipotesis tambahan (opt-in via scope technique),
  sehingga mission menghasilkan hipotesis BAC saat enumerasi mengungkap surface.

**Test baru:** `test_bac_hypothesis_synthesis.py` — fixture enumerasi Juice (surface /rest,/api) →
menghasilkan hipotesis IDOR/forced-browse yang benar; surface kosong → nol hipotesis (tak ada false positive).

**Selesai bila:** dari enumerasi surface, pipeline memproduksi hipotesis BAC generik yang plan-legal.
**Risiko:** butuh enumerasi yang benar-benar menemukan endpoint (lihat Fase 5) — generator diuji dengan
fixture dulu, independen dari recon nyata.

---

## Fase 4 — Jembatan hipotesis→primitive→gateway + profil scope CAE (1.5 hari)

**Tujuan:** hipotesis BAC mission dieksekusi gateway di bawah RoE mission.

**Perubahan:**
- `cae_service_runner.py`: tambah mode `execute_bac_generic(target, hypotheses)` yang menggerakkan
  gateway dari **hipotesis** (bukan `challenges`). `evaluate_cae_request` menerima input berbasis
  hipotesis/surface; hapus penolakan keras `UNKNOWN_CHALLENGES` untuk mode generik (challenge-mode lama
  tetap ada untuk kompat).
- Resolver parameter runtime generik (ganti PREPARE Juice-spesifik): "prepare probe" read-only untuk
  menurunkan id/korelasi (mis. ambil id objek milik orang lain) — digeneralisasi, Juice-prepare jadi
  salah satu knowledge-pack.
- Tambah **scope profile** `WPT_BAC_CONTROLLED_V1` (atau serupa) dengan `execution_authorized=true`,
  kelas aksi `ACTIVE_EXPLOITATION`(+MUTATION bergantung approval), loopback allowlist — agar mission
  boleh eksekusi di lab. Didefinisikan di layer governance/scope, bukan hardcode di gateway.

**Test baru:** `test_cae_bridge_generic.py` — hipotesis BAC generik (fake transport+oracle generik) →
gateway EXPLOITED/REFUTED, RoE enforced, run ter-seal.

**Selesai bila:** gateway solve BAC dari hipotesis tanpa menyebut challenge_key; RoE & seal utuh.

---

## Fase 5 — Mission E2E: Juice BAC lewat pipeline (bukan daftar challenge) (2 hari)

**Tujuan:** buktikan end-to-end dengan mission nyata.

**Perubahan/langkah:**
- Perkuat enumerasi agar menemukan surface `/rest`,`/api` Juice di loopback (bounded, RoE-gated) —
  prasyarat Fase 3 bekerja di dunia nyata. (Jika di luar lingkup, sediakan "surface import" terotorisasi.)
- Buat mission lab baru bermandat `WPT_BAC_CONTROLLED_V1` → recon → enumerasi surface →
  sintesis hipotesis BAC (Fase 3) → attack-path (symbolic_planner) → CAE gateway (Fase 1/2/4) →
  impact assessment.
- **Validasi silang:** untuk instance Juice, scoreboard dipakai sebagai *corroborator opsional* (bukan
  mekanisme) guna memastikan oracle generik setuju dengan ground-truth Juice.

**Selesai bila:** sebuah mission (bukan `run_cae_live.py`) men-solve ≥1 BAC (mis. basketAccess/forced-browse)
murni dari hipotesis hasil enumerasi; oracle generik & scoreboard sepakat.
**Catatan:** mission `gmo-3adb7cf5` yang ada tak dipakai (read-only, no execution); dibuat mission baru
ber-scope CAE. Opsi: re-scope tak disarankan (melanggar imutabilitas scope ter-seal).

---

## Fase 6 — Regresi, containment, dokumentasi (0.5–1 hari)

- Jalankan ulang 12 suite / 77 test Stage 7 + 13 probe containment → semua hijau.
- Tambah probe containment untuk jalur generik (oracle tak boleh EXPLOITED saat INDETERMINATE;
  non-loopback tetap diblok di mode generik).
- Perbarui `README_STAGE7_VALIDATION.md`: pisahkan "engine umum" vs "knowledge-pack Juice"; perjelas
  bahwa solve = bukti oracle, scoreboard = corroborator lab.

---

## Urutan & ketergantungan

```
Fase 0 → Fase 1 → Fase 2 → Fase 3 → Fase 4 → Fase 5 → Fase 6
                     ╰──(Fase 3 & 4 bisa paralel setelah 1–2 selesai)
```

**Estimasi total:** ~9–10 hari kerja. **MVP "BAC umum terbukti"** tercapai di akhir Fase 4
(engine+oracle+bridge generik dengan fake transport); Fase 5 adalah bukti dunia-nyata.

## Keputusan (final 2026-11-21)

1. **Knowledge-pack Juice dipertahankan** sebagai data untuk validasi lab. ✅
2. **Mission baru ber-scope CAE** (scope ter-seal imutabel; `gmo-3adb7cf5` tetap sebagai bukti recon). ✅
3. **Surface-import terotorisasi untuk MVP**, recon aktif diperkuat sesudahnya (pekerjaan Stage 5 terpisah). ✅

## Artefak Fase 1 (sudah diimplementasi)

- `pentest_subsystem/cae_success_oracle.py` — oracle predikat tertutup (no `eval`), fail-closed ke
  INDETERMINATE; verdict CONFIRMED/REFUTED/INDETERMINATE dari bukti respons.
- `pentest_subsystem/active_exploitation_execution.py` — param `success_oracle`; outcome berlapis
  (scoreboard → oracle generik → fallback status). Jalur lama tak berubah (default `success_oracle=None`).
- `tests/test_stage7_1x_success_oracle.py` — 9 test (7 unit oracle + 2 integrasi gateway tanpa scoreboard).

## Artefak Fase 2 (sudah diimplementasi)

- `pentest_subsystem/bac_primitive_templates.py` — 8 template BAC target-agnostic (idor-read/write,
  forced-browse, missing-function-level-ac, param-tamper, ssrf, csrf, privileged-delete) dengan
  `instantiate(...)` → primitive tanpa challenge_key + success predicate terstruktur (dinilai oracle 7.1x).
- `pentest_subsystem/knowledge_packs/owasp_juice_shop.py` — katalog Juice (14 primitive) kini **data**
  dalam pack; `PRIMITIVE_TEMPLATE_MAP` memetakan tiap primitive ke template generiknya.
- `pentest_subsystem/exploit_primitive_library.py` — `_CATALOG` di-*derive* dari pack; expose
  `instantiate_template` + `TEMPLATE_IDS`. Jalur lama (`primitives_for_challenge`, BAC coverage) utuh.
- `tests/test_stage7_2x_generic_templates.py` — 7 test (template plan-legal, template→planner→gateway
  EXPLOITED tanpa scoreboard, library derived-from-pack, konformans tiap primitive Juice ke templatenya).

## Artefak Fase 3 (sudah diimplementasi)

- `pentest_subsystem/bac_hypothesis_synthesis.py` — sintesis hipotesis BAC dari `endpoint_discoveries`
  enumerasi: path ber-ID → IDOR read/write (path di-templatize `{id}`), route/area privileged →
  forced-browse / missing-function-level-ac, param URL-fetch → SSRF, state-change akun tanpa token → CSRF.
  Output record standar (CWE/CAPEC/ATT&CK + planning_model + template, **tanpa challenge_key**) siap
  `symbolic_planner.compile_problem`. Surface kosong/benign → nol (fail-closed, tanpa false positive).
- `tests/test_stage7_3x_bac_synthesis.py` — 7 test (6 kelas BAC tersintesis benar, templatisasi id,
  nol false-positive, plan-legal, run tersintesis lolos planner, terima list endpoint telanjang).

## Artefak Fase 4 (sudah diimplementasi) — MVP BAC umum

- `pentest_subsystem/active_exploitation_execution.py` — param `primitive_registry` (aditif): gateway
  kini bisa mengeksekusi primitive tersintesis yang tak ada di katalog library (fallback ke library).
- `pentest_subsystem/cae_service_runner.py` —
  `execute_bac_generic(target, hypotheses|enumeration_output)`: rekonstruksi primitive dari hipotesis →
  rantai (auth enabler opsional + eksploit) → gateway + oracle 7.1x, **tanpa scoreboard**; +
  `bac_controlled_scope_profile()` / `WPT_BAC_CONTROLLED_V1` (mandat scope `execution_authorized=true`,
  loopback-only) sebagai seam governance. Jalur challenge-mode lama (`execute_bac_http`) tak berubah.
- `tests/test_stage7_4x_bac_generic_bridge.py` — 5 test (forced-browse EXPLOITED dari enumerasi tanpa
  scoreboard, IDOR via rantai auth, profil scope meng-authorize eksekusi, RoE loopback tetap memblok
  target non-loopback, run ter-seal).

## Artefak Fase 5 (sudah diimplementasi) — terbukti LIVE

- `pentest_subsystem/session_broker.py` — tangkap `uid`→`userId` + `update_session_meta()` (enrichment).
- `pentest_subsystem/active_exploitation_execution.py` — param `identity_probe`: probe read-only
  (mis. `GET /rest/user/whoami`, JWT via cookie+header) menuliskan `userId` sesi → owner-check IDOR
  generik punya bukti. Data probe dari pack, bukan hardcode engine.
- `pentest_subsystem/knowledge_packs/owasp_juice_shop.py` — `BAC_SURFACE` (import surface terotorisasi,
  enumeration-shaped), `BAC_SURFACE_CHALLENGE_MAP` (korroborator), `SELF_IDENTITY_PROBE`,
  `bac_surface_enumeration()`, `READ_ACTIVE_SAFE`.
- `pentest_subsystem/cae_service_runner.py` — `cross_validate_with_scoreboard()` (oracle vs scoreboard,
  status absolut), `execute_bac_generic(..., identity_probe=...)`.
- `run_bac_generic_live.py` — host runner pipeline penuh (surface→sintesis→plan→gateway→korroborasi),
  default read-active-safe.
- `tests/test_stage7_5x_bac_mission_e2e.py` — 4 test E2E hermetik (sintesis+plan, EXPLOITED via oracle,
  oracle sepakat scoreboard, nol challenge_key). **Validasi live:** easterEgg + basketAccess
  EXPLOITED/CONFIRMED, agreed=True.

## Batas jujur yang tersisa (untuk Fase 6+)

- Generic IDOR butuh identity-probe untuk self-id; tanpa probe yang cocok → oracle INDETERMINATE
  (fail-closed, benar secara keamanan) bukan EXPLOITED.
- Enumerasi surface masih via import terotorisasi (keputusan #3); recon aktif penemuan surface = kerja
  Stage 5 terpisah.
- Mission intake belum dijahit ke `WPT_BAC_CONTROLLED_V1` (profil ada sebagai data; wiring ke state-machine
  mission = kerja intake terpisah, di luar roadmap Stage 7 ini).

## Artefak Fase 6 (sudah diimplementasi)

- `pentest_subsystem/cae_containment.py` — +2 probe generik: **CAE-P14** (oracle generik tanpa bukti tak
  boleh naik ke EXPLOITED — fail-closed) & **CAE-P15** (primitive generik ke target non-loopback → BLOCKED:AE-LOOPBACK).
- `tests/test_stage7_8_cae_containment.py` — katalog 13→15; semua lulus.
- `README_STAGE7_VALIDATION.md` — bagian "Engine BAC umum vs knowledge-pack"; solve = oracle bukti,
  scoreboard = corroborator.
- Regresi akhir: **18 suite / ~117 test hijau**, **containment 15/15**.
