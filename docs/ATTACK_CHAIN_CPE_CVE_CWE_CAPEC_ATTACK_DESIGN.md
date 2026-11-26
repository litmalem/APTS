# Attack-Chain Enrichment — CPE → CVE → CWE → CAPEC → ATT&CK (Stage 5.4 → 5.5)

Spesifikasi siap-implementasi untuk **menyalurkan rantai pengetahuan BRON**
(CPE→CVE→CWE→CAPEC→ATT&CK, plus dua *shortcut edge*) dari CTI Subsystem (VulnDesk)
ke **knowledge_item Stage 5.4** dan **Attack-Path Planning Stage 5.5** pada Pentest Subsystem.
Dibuat dari pembacaan kode `mission_orchestrator/pentest_subsystem/`, `Vulndesk/cti_services/`,
dan `Vulndeskcti_structure.sql` per 2026-11-26.

> **Status gap terverifikasi.** Rantai ini **sudah 90% terbangun di VulnDesk** (tabel + service +
> endpoint), tetapi **putus di `cti_hypothesis_adapter._knowledge_item()`**, yang hanya membangun
> knowledge_item **sampai CVE** (`knowledge_type="CVE"`, `vulnerability_id=<CVE>`). Ekor
> **CWE→CAPEC→ATT&CK** yang sudah dihitung VulnDesk (`/api/pentest/cve-cwes`, `/api/pentest/map-attack`,
> `AttackMappingService.map_vulnerability`) **tidak ikut** masuk ke hipotesis, sehingga Attack-Path
> Planner Stage 5.5 tidak pernah melihatnya. Modul ini menambahkan **blok provenance `attack_chain`**
> yang aditif — jalur pengayaan KEDUA, tidak mengganti korelasi CVE yang ada.

---

## 0. Prinsip (selaras CLAUDE.md — WAJIB)

- **Aditif.** Tidak mengubah jalur read-only Stage 6, oracle, maupun korelasi CVE Stage 5.4 yang ada.
  `attack_chain` adalah **field opsional baru** pada knowledge_item; tanpa data CTI, perilaku lama utuh.
- **Provenance, bukan edge kausal.** `attack_chain` **TIDAK pernah** menjadi `precondition`/`effect`
  pada `planning_model` symbolic planner. Mapping taksonomi **bukan bukti reachability**
  (invariant planner `CANDIDATE_PATHS_ARE_PLANNING_HYPOTHESES_NOT_PROOF_OF_REACHABILITY`).
  ATT&CK **tetap deskriptif** — konsisten dengan `enrichment.py` (`is_causal_dependency: False`).
- **Deterministik & tersegel (Inv. 1 & 2).** Setiap edge berasal dari *lookup kamus ter-snapshot*,
  bukan inferensi stokastik. Blok disegel `boundary_contract.sha256_hex` + domain hash baru.
  Fan-out dipangkas dengan aturan **murni deterministik** (urut lalu top-k by `mapping_level`).
- **Version-bump eksplisit (Inv. 2).** Menambah field ke knowledge_item meng-cascade
  `knowledge_sha256` → output Stage 5.4 → `output_sha256` yang diikat Stage 5.5. Wajib bump
  SCHEMA_VERSION + migration level + regenerasi acceptance gate (lihat §7).
- **Projection-only & governance tak dipelajari (Inv. 3 & 4).** Rantai hanya menyetir
  *prioritas/skor/hipotesis*. **Tidak pernah** menyentuh scope/RoE/otorisasi, tidak menambah I/O
  jaringan ke agent Stage 5.x (adapter tetap loopback-only ke VulnDesk, seperti sekarang).
- **Tanpa `eval`/`exec`.** Normalisasi & pemangkasan murni fungsi data.

---

## 1. Status rantai saat ini (bukti kode)

| Hop | Sudah ada di VulnDesk | Sudah sampai hipotesis Stage 5.4? |
|---|---|---|
| Asset → CPE | `cti_cpe_resolution_claims`, `asset_profiling_cpe_resolution_service`, `nvd_cpe_dictionary` | ✅ via `cti_hypothesis_adapter._enumeration_cpes()` |
| CPE → CVE | `cpe_matches`, `cpe_cve_matching_service`, endpoint `/api/pentest/resolve-cpe` | ✅ via `resolve_cpe_candidates()` / `resolve_technology_cves()` |
| CVE → CWE | `vulnerability_cwes`, `cwe_catalog`, endpoint **`/api/pentest/cve-cwes`** | ❌ **belum ditarik** |
| CWE → CAPEC | `capec_cwe_mappings`, `capec_patterns` | ❌ **belum ditarik** |
| CAPEC → ATT&CK | `capec_attack_mappings`, `attack_patterns` | ❌ **belum ditarik** |
| CVE → ATT&CK (shortcut) | `vuln_attack_mappings`, `cti_attack_mappings` | ❌ **belum ditarik** |
| Asset → ATT&CK (shortcut) | `AttackMappingService._map_by_endpoint_heuristic/_map_by_keywords` | ❌ **belum ditarik** |
| Graf utuh + snapshot | `cti_attack_graph_snapshots`, `cti_attack_paths` | ❌ |

**Orkestrator mapping CTI sudah lengkap:** `Vulndesk/cti_services/attack_mapping_service.py::map_vulnerability()`
menelusuri `_map_by_cve → _weakness_candidates → (_map_by_capec, _map_by_cwe) → _map_by_vuln_type →
_map_by_keywords → _map_by_endpoint_heuristic`, lalu `_rank_and_dedupe([_verify_mapping(...)])`.
Endpoint penyedia: `pentest_enrichment_api_service` → `/api/pentest/cve-cwes`, `/api/pentest/map-attack`,
`/api/pentest/match-cpe`, `/api/pentest/resolve-cpe`.

**Titik putus:** `pentest_subsystem/cti_hypothesis_adapter.py::_knowledge_item()` (sekarang berhenti di CVE)
dan `pentest_subsystem/enrichment.py` (sudah punya client `map-attack`, tetapi hasil ATT&CK hanya dipakai
sebagai **anotasi penjelasan**, bukan dibawa sebagai field knowledge yang terikat hash).

---

## 2. Target desain

Satu blok provenance baru, `attack_chain`, ditempelkan pada tiap knowledge_item Stage 5.4,
ikut mengalir ke output hipotesis → provenance jalur Stage 5.5 → UI. Dipakai sebagai:

1. **Provenance terikat-hash** (jejak keputusan lintas taksonomi untuk pertahanan disertasi).
2. **Fitur ber-skor pada ranker terlatih v2** (Fase 2): `chain_mapping_strength` masuk vektor fitur
   learning-to-rank, lewat version-bump v1→v2, dengan fail-safe fixed-formula `0.8/0.2` dan gate LOMO-NDCG.
3. **Anotasi ATT&CK deskriptif** untuk tampilan (tactic matrix order), **non-kausal**.

### 2.1 Masuk-dari-CWE untuk target tanpa CVE (WAJIB untuk Juice Shop / DVWA)

Juice Shop & DVWA adalah aplikasi *sengaja rentan* — vuln-nya **tidak ber-CVE**. Maka jalur
`Asset→CPE→CVE` kosong untuk justru vuln yang diuji (BAC). Rantai **harus bisa dimasuki dari CWE**:

- `knowledge_type="WEAKNESS_PATTERN"` (sudah ada di `VULNERABILITY_HYPOTHESIS_KNOWLEDGE_TYPES`)
  dengan `attack_chain.entry="CWE"`, di-seed dari `knowledge_packs/owasp_juice_shop.py`
  (sudah memuat CWE+CAPEC) lalu dilengkapi ekor CAPEC→ATT&CK via `/api/pentest/map-attack`.
- Untuk BAC, ekor ATT&CK sengaja dibiarkan kasar (mis. `T1190`, `T1078`); `mapping_level`
  merefleksikan keterbatasan ini. **Jangan** memaksa ATT&CK jadi pembeda jalur.

---

## 3. Perubahan per file (anchor nyata)

### 3.1 VulnDesk (CTI) — kebanyakan sudah ada; hanya konsolidasi

Tidak ada logika mapping baru. Jika perlu satu panggilan ringkas, tambahkan **endpoint konsolidasi
opsional** `POST /api/pentest/attack-chain` di `cti_services/pentest_enrichment_api_service.py` yang
membungkus `AttackMappingService.map_vulnerability()` + resolusi CWE, dan mengembalikan **beserta
`graph_snapshot_id`** dari `cti_attack_graph_snapshots` (+ versi NVD/CWE/CAPEC/ATT&CK). Kalau tidak,
adapter cukup memanggil `/api/pentest/cve-cwes` lalu `/api/pentest/map-attack` (dua round-trip,
loopback). **Larangan:** `auto_fetch=false` tetap (tanpa I/O eksternal NVD saat runtime).

### 3.2 `pentest_subsystem/cti_attack_chain.py` — MODUL BARU (client + normalisasi)

Memuat pengetahuan domain rantai; **murni data, tanpa target I/O**.

- `fetch_attack_chain(*, cve=None, cwe_ids=(), opener=None) -> dict | None`
  memanggil endpoint VulnDesk (loopback, pola `_post` seperti `cti_hypothesis_adapter`),
  mengembalikan struktur mentah links + snapshot id.
- `normalize_attack_chain(raw, *, entry) -> dict` → menghasilkan blok `attack_chain` final (§6),
  dengan **pemangkasan fan-out deterministik**:
  `MAPPING_WEIGHT = {"authoritative":3, "related":2, "partial":1, "heuristic":0}`; untuk tiap
  level taksonomi urutkan `(-weight, id)` lalu ambil `TOPK_PER_LEVEL` (default 8). Rekam
  `fanout_pruned` (jumlah dibuang). Segel dengan `sha256_hex` + `domain=ATTACK_CHAIN_HASH_DOMAIN`.
- **Tanpa randomness, tanpa waktu-nyata di hash** (gunakan hanya `graph_snapshot_id` + versi katalog).

### 3.3 `pentest_subsystem/cti_hypothesis_adapter.py` — sambungkan ekor rantai

- Di `_knowledge_item(cve, cand, *, match, subject)` (≈baris 214): setelah objek knowledge disusun,
  panggil `cti_attack_chain.fetch_attack_chain(cve=cve)` → `normalize_attack_chain(..., entry="CPE")`
  dan tempelkan `result["attack_chain"] = <blok>` **hanya bila resolve sukses** (jika gagal/ kosong →
  **tidak** menambah field; fail-open ke perilaku lama, bukan mengarang mapping).
- Tambah jalur **masuk-dari-CWE**: fungsi baru `build_weakness_knowledge_items(enumeration_run,
  weakness_seeds, *, opener=None)` yang membuat knowledge_item `WEAKNESS_PATTERN` dengan
  `attack_chain.entry="CWE"` (dipakai untuk Juice Shop/DVWA; sumber seed = `knowledge_packs/`).

### 3.4 `pentest_subsystem/vulnerability_hypothesis.py` — perbesar kontrak knowledge_item

- `_normalize_knowledge_item()` (≈baris 286): tambahkan `"attack_chain"` ke set `allowed`
  (JANGAN ke `required`). Bila ada, validasi via normalizer baru `_normalize_attack_chain(value)`
  (struktur §6; tolak field tak dikenal; `mapping_level` ∈ enum; `technique_id` cocok `^T\d{4}(\.\d{3})?$`;
  `is_causal` harus `False`). Masukkan hasil ke `result` **sebelum** `knowledge_sha256` dihitung
  (jadi ikut tersegel).
- Pastikan field diteruskan di proyeksi hipotesis inti (blok `core[...]`, ≈baris 606–631, tempat
  `knowledge` & `planning_model` disalin): tambahkan `core["knowledge"]["attack_chain"]` bila ada.
  **Jangan** menyentuh `planning_model`.

### 3.5 `pentest_subsystem/attack_path_planning.py` — bawa ke provenance jalur

- Node/step jalur sudah mengikat knowledge hipotesis (invariant
  `PATH_PROVENANCE_BINDS_HYPOTHESIS_KNOWLEDGE_EVIDENCE`). Pastikan `attack_chain` ikut terbawa di
  provenance output (bukan di `effects`). Tambahkan ringkasan non-kausal
  `path["attack_techniques"]` (gabungan unik technique dari langkah) **berlabel deskriptif**.
- `symbolic_planner.compile_problem()`/`plan()` **tidak diubah** (chain tidak masuk STRIPS).

### 3.6 `pentest_subsystem/attack_path_ranking.py` — promosikan `chain_mapping_strength` ke ranker terlatih (Fase 2)

**Keputusan:** `chain_mapping_strength` **masuk vektor fitur ber-skor** ranker (bukan tie-break),
lewat **version-bump v1→v2**. Memenuhi syarat Fase 2 CLAUDE.md: offline-trained, version-pinned,
frozen-policy saat inference, di lapis prioritisasi, **wajib lolos gate LOMO-NDCG** (terbukti ≥ baseline
formula tetap). Catatan: ranker ini memang jalur Fase 2 (header file sudah menyatakannya); menambah
fitur = version-bump eksplisit yang diizinkan Inv. 2, **bukan** pelanggaran Inv. 1.

**a. Perluas ruang fitur (v1 → v2).**
- `RANKER_FEATURES_V2 = ("hypothesis_confidence", "impact_factor", "evidence_ref_count_norm", "chain_mapping_strength")`.
- Bump: `RANKER_SCHEMA_VERSION` → `apts-stage5.5-attack-path-ranker-v2`; `RANKER_MODEL_HASH_DOMAIN`
  & `RANKER_EVAL_HASH_DOMAIN` → `..._V2`.
- `FIXED_FORMULA_WEIGHTS` v2 = `{hypothesis_confidence:0.8, impact_factor:0.2, evidence_ref_count_norm:0.0,
  chain_mapping_strength:0.0}`. **Properti fail-safe WAJIB dipertahankan:** `prior_model()` (untrained)
  mereproduksi `0.8*conf + 0.2*impact` **byte-identik** — sistem tak-terlatih == planner pra-learning;
  fitur chain hanya mengubah urutan setelah model `TRAINED` berbobot ≠0 lolos gate.
- `ranking_features()`, `score()`, `fit()`, `verify_model()` semua key ke tuple fitur → arahkan ke V2.
  `verify_model` tetap menuntut `features == RANKER_FEATURES_V2`; model v1 lama otomatis **tak-usable**
  di jalur serve → fallback aman ke fixed formula. (Pertahankan `verify_model` v1 hanya untuk *replay*
  `planning_score` lama yang sudah mengembed featurenya sendiri.)

**b. Definisi fitur deterministik (anti train/serve skew).**
`chain_mapping_strength ∈ [0,1]` = fungsi murni dari blok `attack_chain` ter-snapshot:
```
LEVEL_W = {authoritative:1.0, related:0.66, partial:0.33, heuristic:0.1}
s = max(LEVEL_W[link.mapping_level] untuk link pada jalur terkuat yang mencapai ATT&CK)
chain_mapping_strength = round( s * (1.0 if reached_attack else 0.5)
                                  * (0.7 if tail_truncated else 1.0), 6 )
# attack_chain tidak ada -> 0.0  (path tanpa chain tak terpengaruh; kompat mundur penuh)
```
Nilai **hanya dibaca dari `attack_chain` yang sudah tersegel pada path** (mengandung `graph_snapshot_id`),
**tidak** query ulang VulnDesk saat serve — jaga replay + Inv. 4 (no-I/O Stage 5.x). Fungsi identik dipakai
dua sisi: serve `candidate_path_features(path)` (tambah baca `path[...]["attack_chain"]`) dan train
`record_features(features_block)` (baca dari dataset, lihat §3.6c).

**c. Pipa label Fase 0 (`learning_dataset.py`) — PRASYARAT training. [KEPUTUSAN: capture-forward]**
Pemeriksaan DB live `mission_orchestrator/data/pentest_subsystem.db` (2026-11-26, WAL-applied):
`pentest_label_dataset` **belum ada** (0 record label apa pun); `pentest_attack_path_planning_runs=0`;
`pentest_vulnerability_hypothesis_runs=23` COMPLETED (2660 hipotesis, anchor `vulnerability_id`/CVE/
`asset_id`/`supporting_evidence_refs` lengkap; `knowledge_type` semua `CVE`; `planning_model` absen).
→ **Tidak ada data `ATTACK_PATH` historis untuk di-backfill.** Maka pakai **opsi (ii) capture-forward**:
- Wiring `chain_mapping_strength` ke `_path_features(pr, linked)` / `build_records()` **sebelum** grading
  Stage 6 pertama, dihitung dari `attack_chain` pada hipotesis `linked` (anchor sudah tersedia di run)
  terhadap snapshot ter-pin → setiap label `ATTACK_PATH` lahir ber-fitur, **tanpa migrasi re-derive**.
  Bump `DATASET_SCHEMA_VERSION`.
- **Inisialisasi store dulu:** migrasi `pentest_migrations/023_learning_label_dataset.sql` (+ kolom/skema
  baru) belum teraplikasi di DB live (tabel hilang) — panggil `ensure_label_dataset_store` sebelum ingest.
- **Re-derive (opsi i) tidak diperlukan sekarang**, tetap mungkin kelak: 23 run hipotesis hash-pinned &
  ber-anchor CVE bisa diputar ulang untuk membootstrap data latih dari run yang sudah digrade.
- **JANGAN** mengisi `0.0` diam-diam untuk record tanpa chain — itu bias label; path tanpa `attack_chain`
  memang bernilai `0.0` secara sah (§3.6b), beda dari record yang fiturnya hilang karena belum di-wiring.
- Catatan korpus: 88 CVE yang ada (2007–2013) = advisory produk/pustaka hasil enumerasi, **bukan** vuln
  BAC. Untuk target BAC, fitur chain yang bermakna datang dari **entry CWE** (§2.1), bukan CVE.

**d. Gate promosi (sudah ada, kini bermakna).**
`evaluate_ranking()` melatih model v2 penuh, LOMO per-misi, bandingkan held-out NDCG@5 vs baseline
**formula tetap `0.8/0.2`** (`prior_model` v2, chain-weight 0). `promotable` hanya bila
`lomo.ndcg ≥ baseline.ndcg − MAX_NDCG_REGRESSION (1e-9)`. Ini **tepat** memenuhi "buktikan unggul atas
baseline" (CLAUDE.md §Fase 2). **Jangan longgarkan** `MAX_NDCG_REGRESSION`. Simpan record `evaluation`
ber-hash sebagai bukti promosi (audit/disertasi); `build_promoted_model()` mengembalikan `None` bila gagal.

**e. Serve & frozen-policy.**
`planning_score_block(...)` (≈baris 339) tambah parameter `chain_mapping_strength: float` (dihitung
pemanggil di `attack_path_planning.py` dari `attack_chain` path). `model_is_usable` → skor learned v2 +
blok model hash-bound (sudah mengembed `features` + `feature_order` → replayable). Tidak usable →
**fixed formula byte-identik** (chain diabaikan). Model dibaca dari artefak **version-pinned**, tak pernah
dilatih saat inference.

### 3.7 UI `pentest_web/planning.*` + `web_ui.py` (opsional, tampilan)

- Render chip rantai `CPE→CVE→CWE→CAPEC→ATT&CK` + tactic (matrix order) per kandidat jalur,
  diberi label **"descriptive / non-causal"** agar tak disalahartikan sebagai bukti reachability.

---

## 4. Determinisme, snapshot & anti-fan-out

- **Snapshot-pinned.** Setiap blok merekam `graph_snapshot_id` + `nvd/cwe/capec/attack_version`.
  Dua run atas snapshot sama → blok byte-identik → `canonical_sha256` sama (replayable).
- **Fan-out pruning deterministik** (§3.2): urut `(-weight, id)`, top-k, rekam `fanout_pruned`.
  Tanpa ini, satu CVE bisa meledak jadi puluhan teknik dan mendominasi `ATTACK_PATH_PLANNING_MAX_PATHS`.
- **Coverage holes jujur.** CWE-noinfo/Other, CWE tanpa CAPEC, CAPEC tanpa ATT&CK → set `tail_truncated=true`
  dan **jatuh ke shortcut** (`vuln_attack_mappings` CVE→ATT&CK; heuristik asset→ATT&CK) dengan
  `mapping_level` yang lebih rendah. Shortcut **tidak pernah** menaikkan confidence hipotesis.

---

## 5. Kontrak data `attack_chain` (§6 referensi untuk normalizer)

```json
{
  "schema_version": "apts-stage5.4-attack-chain-provenance-v1",
  "entry": "CPE",
  "snapshot": {
    "source": "vulndesk",
    "graph_snapshot_id": "ctigs-<id>",
    "nvd_version": "<iso>", "cwe_version": "4.x",
    "capec_version": "3.x", "attack_version": "15.x"
  },
  "links": [
    {"from_type":"CPE","from_id":"cpe:2.3:a:vendor:product:ver:*","to_type":"CVE","to_id":"CVE-YYYY-NNNN","mapping_level":"authoritative","source_ref":"vulndesk://.../cpe_matches"},
    {"from_type":"CVE","to_type":"CWE","to_id":"CWE-639","mapping_level":"authoritative","source_ref":"vulndesk://.../cve-cwes"},
    {"from_type":"CWE","to_type":"CAPEC","to_id":"CAPEC-122","mapping_level":"related","source_ref":"vulndesk://.../capec_cwe_mappings"},
    {"from_type":"CAPEC","to_type":"ATTACK","to_id":"T1190","mapping_level":"partial","source_ref":"vulndesk://.../capec_attack_mappings"}
  ],
  "attack_techniques": [
    {"technique_id":"T1190","tactic":"Initial Access","mapping_level":"partial","is_causal":false}
  ],
  "completeness": {"reached_attack": true, "tail_truncated": false, "fanout_pruned": 7},
  "integrity": {"canonical_sha256":"<hex>"}
}
```

`mapping_level ∈ {authoritative, related, partial, heuristic}`. `is_causal` selalu `false`.
`entry ∈ {CPE, CWE}`.

---

## 6. Version-bump & hash-chain checklist (Inv. 2)

| Konstanta / artefak | Aksi |
|---|---|
| `VULNERABILITY_HYPOTHESIS_*_SCHEMA_VERSION` (knowledge/agent) | **bump** (field knowledge_item berubah) |
| `VULNERABILITY_HYPOTHESIS_AGENT_REPOSITORY_MIGRATION_LEVEL` | **+1** + migrasi aditif kolom/serialisasi |
| `ATTACK_CHAIN_SCHEMA_VERSION` / `ATTACK_CHAIN_HASH_DOMAIN` | **baru** di modul `cti_attack_chain.py` |
| `knowledge_sha256` → `output_sha256` Stage 5.4 | berubah by-design; **regenerasi fixtures** |
| Acceptance gate Stage 5.4 (`STAGE_5_4_*`) | perbarui expected hashes |
| Attack-Path Stage 5.5 (`output_sha256` predecessor diikat) | regenerasi fixtures + gate `STAGE_5_5_*` |
| `RANKER_FEATURES` / `RANKER_SCHEMA_VERSION` / `RANKER_MODEL_HASH_DOMAIN` / `RANKER_EVAL_HASH_DOMAIN` | **bump ke v2** (+`chain_mapping_strength`); prior v2 tetap = `0.8/0.2` |
| `learning_dataset` skema fitur `ATTACK_PATH` (Fase 0) | **bump + migrasi** (tambah `chain_mapping_strength`); strategi record lama = §3.6c |
| Model ranker v2 terlatih | artefak baru via `build_promoted_model` (hanya bila lolos gate LOMO-NDCG) |

> Perubahan hash **harus** berhenti di Stage 5.4→5.5. Jika menyentuh 5.6+/6.x, berarti ada
> kebocoran chain ke jalur kausal/eksekusi — **hentikan & tinjau** (melanggar §0).

---

## 7. Pengujian (pola acceptance-gate yang ada)

Di `mission_orchestrator/tests/` (tiru pola `STAGE_X_Y_ACCEPTANCE` + `verify_*`):

1. `test_cti_attack_chain_normalize.py` — determinisme: input mentah sama → blok byte-identik;
   `verify`/`canonical_sha256` cocok; fan-out pruning stabil & `fanout_pruned` benar.
2. `test_attack_chain_entry_cpe.py` — CVE knowledge_item mendapat `attack_chain.entry="CPE"`;
   resolve gagal → **tanpa** field (fail-open), perilaku lama utuh.
3. `test_attack_chain_entry_cwe_juiceshop.py` — seed WEAKNESS_PATTERN (CWE BAC) → ekor CAPEC→ATT&CK
   terisi; `tail_truncated` benar saat mapping kosong.
4. `test_hypothesis_knowledge_attack_chain_sealed.py` — `attack_chain` ikut `knowledge_sha256`;
   field tak dikenal / `is_causal=true` / `technique_id` invalid → **ValidationError**.
5. `test_planner_ignores_attack_chain.py` — **regresi invariant**: `attack_chain` TIDAK muncul di
   `preconditions/effects`; paths/cost/edges **identik** dengan baseline tanpa chain.
6. `test_ranker_v2_prior_equals_fixed_formula.py` — **fail-safe**: `prior_model()` v2 mereproduksi
   `0.8*conf + 0.2*impact` byte-identik; model tak-usable → `planning_score_block` = formula tetap.
7. `test_ranker_v2_chain_feature_pure.py` — `chain_mapping_strength` murni & stabil dari `attack_chain`
   ter-snapshot; tanpa chain → `0.0`; **tak ada panggilan CTI** saat serve (replay-only).
8. `test_ranker_v2_lomo_gate.py` — `evaluate_ranking` menandai `promotable` hanya saat held-out NDCG ≥
   baseline `0.8/0.2`; regresi di bawah `MAX_NDCG_REGRESSION` → `not_promotable_reasons`.
9. `test_ranker_train_serve_no_skew.py` — `record_features` == `candidate_path_features` untuk path sama.
10. **Regresi invariant** (lanjutan #5): tanpa model terlatih, urutan kandidat identik baseline;
    `chain_mapping_strength` tak pernah muncul di STRIPS.
11. Perbarui gate `STAGE_5_4_*` & `STAGE_5_5_*` (hash baru). Pastikan `verify_ae_run`/`verify_*` hijau.

---

## 8. Urutan implementasi (Definition of Done)

1. `cti_attack_chain.py` (client + normalizer + hash domain) → test #1 hijau.
2. (Opsional) endpoint konsolidasi `/api/pentest/attack-chain` + `graph_snapshot_id`.
3. Perbesar kontrak `vulnerability_hypothesis._normalize_knowledge_item` + normalizer → test #4.
4. Sambungkan `cti_hypothesis_adapter._knowledge_item` (entry CPE) + `build_weakness_knowledge_items`
   (entry CWE) → test #2, #3.
5. Bawa provenance di `attack_path_planning` (non-kausal) → test #5 (regresi planner).
6. Perbesar skema fitur dataset Fase 0 (`learning_dataset`) + strategi record lama (§3.6c) → migrasi.
7. Ranker **v2**: `RANKER_FEATURES_V2` + fail-safe prior + `chain_mapping_strength` di `ranking_features`/
   `candidate_path_features`/`record_features`; wiring `planning_score_block` → test #6, #7, #9, #10.
8. Kumpulkan ≥20 path ber-chain (≥2 misi) → `evaluate_ranking`/`build_promoted_model`; promosikan **HANYA**
   bila lolos gate LOMO-NDCG → test #8. Simpan record `evaluation` ber-hash (bukti promosi).
9. Bump versi/migrasi + regenerasi fixtures + gate Stage 5.4/5.5 → test #11; `pytest` terkait hijau.
10. (Opsional) chip UI `planning.*` berlabel deskriptif + tampilkan `model_id` & `chain_mapping_strength`.

**DoD:** semua test di atas hijau; `verify_*` hijau; jalur Stage 6 read-only **tak tersentuh**;
`git diff` menunjukkan perubahan **aditif** (prior v2 == perilaku lama); ranker v2 dipromosikan **hanya**
lewat gate LOMO-NDCG (bila belum lolos → fixed formula); tak ada field chain di STRIPS; tak ada I/O
jaringan baru di agent Stage 5.x; tak ada randomness runtime (fit deterministik, tanpa sampling).

---

## 9. JANGAN (recap invariant untuk tugas ini)

- **Jangan** menjadikan technique/CAPEC/CWE sebuah `effect`/`precondition` planner (itu mengklaim
  reachability dari mapping — dilarang).
- **Jangan** memakai `attack_chain` untuk keputusan scope/RoE/otorisasi (Inv. 3 & 4).
- **Jangan** melatih/mengubah ranker saat inference (frozen-policy), melonggarkan gate LOMO-NDCG
  (`MAX_NDCG_REGRESSION`), atau mengisi `chain_mapping_strength=0.0` diam-diam untuk record label lama.
- **Jangan** memakai nilai `chain_mapping_strength` dari query CTI live saat serve — hanya dari
  `attack_chain` ter-snapshot pada path (demi replay + Inv. 4).
- **Jangan** memanggil NVD/eksternal saat runtime (`auto_fetch=false`; loopback-only ke VulnDesk).
- **Jangan** memasukkan waktu-nyata/randomness ke hash; pakai `graph_snapshot_id` + versi katalog.
- **Jangan** "akali agar test lewat" — bila mapping kosong, jujur `tail_truncated`, bukan mengarang.
