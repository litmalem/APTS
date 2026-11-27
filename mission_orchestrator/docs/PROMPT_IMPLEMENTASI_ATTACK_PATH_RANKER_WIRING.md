# PROMPT IMPLEMENTASI — Wiring Runtime Ranker Fase 2 (Stage 5.5 Attack-Path Learning-to-Rank)

> Dokumen eksekusi untuk Claude Code. Jalankan dari root repo `D:\APTS\mission_orchestrator`.
> Tujuan: menutup **satu-satunya gap** yang menghalangi Fase 2 "Learning Sejati (B)" aktif —
> yaitu menyambungkan ranker terlatih ke jalur runtime Stage 5.5. Seluruh pipeline lain
> (dataset berlabel, fitur `chain_mapping_strength`, `fit`, gate LOMO NDCG, injeksi fail-closed)
> **sudah ada dan teruji unit test**; dokumen ini hanya menambah *wiring*, bukan mengubah algoritma.

---

## 0. Konteks & temuan (jangan diubah, ini premis)

Hasil audit kode (`pentest_subsystem/`):

1. **BRON Knowledge Graph sudah terpakai** di Attack-Path Planning: konstruksi path dari
   `bron_graph_service.enrichment()` + traversal (`attack_path_planning.build_candidate_attack_paths`,
   baris 424–452), binding ke aksi symbolic planner (`symbolic_planner.compile_graph_action`), dan
   fitur `chain_mapping_strength` masuk ruang fitur ranker **v2** (`attack_path_ranking.RANKER_FEATURES_V2`).
2. **Ranker Fase 2 lengkap tetapi belum di-wire ke runtime.** Bukti:
   - `AttackPathPlanningAgentRepository._attack_path_ranker_model` default `None`
     (`attack_path_planning.py:1040`); jika `None`, `planning_score_block` jatuh ke formula tetap
     `0.8*conf + 0.2*impact` dan **bobot `chain_mapping_strength` efektif 0**.
   - `set_attack_path_ranker_model` dan `build_promoted_model` **hanya dipanggil di `tests/`**,
     tidak ada kode produksi/bootstrap yang memanggilnya.
   - Tidak ada artefak model tersimpan di disk; `initialize()` tidak memuat model apa pun.
3. **Dataset pelatihan sudah benar.** `learning_dataset.build_records()` menghasilkan record
   `KIND_ATTACK_PATH` bergrade (0/1/2) dari run Stage 6 terverifikasi, dan `_path_features`
   **sudah mengemisi `chain_mapping_strength`** (`learning_dataset.py:90`). Jadi fitur rantai
   benar-benar terlatihkan — tidak perlu migrasi re-derive.
4. **Fase 1 (Stage 5.4 `set_calibration_model`) juga belum ter-wire** dengan pola identik.
   Di luar scope dokumen ini (lihat §7 sebagai follow-up opsional).

Kesimpulan: yang kurang hanyalah **collect → promote → persist → load → inject**, dijalankan
**offline** (training) + **saat startup** (load/inject).

---

## 1. Invariants yang WAJIB dijaga (fail bila dilanggar)

- **Offline-trained.** Training TIDAK boleh berada di jalur request/HTTP. Jalur request hanya
  MEMBACA model yang sudah ter-promote lalu meng-inject-nya. (Arah "Learning Sejati B".)
- **Fail-closed / fail-open startup.** Model tidak ada, korup, atau gagal verifikasi →
  `_attack_path_ranker_model` tetap `None` → formula tetap `0.8/0.2` **byte-identik** dengan
  perilaku pra-wiring. Startup TIDAK boleh gagal karena urusan ranker.
- **Deterministik & sealed.** Model di-seal (`weights_sha256`). Sebelum inject WAJIB lewat
  `attack_path_ranking.model_is_usable(model)` (status `TRAINED` + verifikasi integritas).
- **Projection-only.** Hanya mengubah URUTAN prioritas validasi; tidak menambah actuation,
  tidak mengubah scope/RoE/authorization, tidak membuat finding/execution request.
- **Governance tidak dipelajari.** Ranking tetap `VALIDATION_PRIORITY_HEURISTIC`, bukan
  probabilitas sukses eksploit.
- **Tanpa egress baru.** Training & load membaca store lokal (sqlite repo / sidecar), bukan jaringan.
- **Jangan sentuh** `attack_path_ranking.py`, `cti_attack_chain.py`, `bron_graph_*`,
  `learning_dataset.py`, atau hash/seal domain mana pun. Ruang fitur v2 sudah benar.
- **Human-in-the-loop.** Promosi model yang mengaktifkan ranker baru butuh langkah eksplisit
  (`--install`), bukan otomatis saat training.

---

## 2. Arsitektur yang dibuat

```
Stage 6 runs (tersimpan di repo)                      [sudah ada]
          │  verify_execution_run()
          ▼
learning_dataset.build_records() ── KIND_ATTACK_PATH  [sudah ada]
          │
          ▼
attack_path_ranking.evaluate_ranking() → {evaluation, model}   [sudah ada: LOMO NDCG gate]
          │  promotable == True ?
          ▼
AttackPathRankerStore.save(model, evaluation)         [BARU — persistensi + audit]
          │
   (startup / reload)
          ▼
install_persisted_ranker(service) → model_is_usable? → service.set_attack_path_ranker_model()
          │                                                            [BARU — bootstrap]
          ▼
build_candidate_attack_paths(ranker_model=...) → planning_score.formula == LEARNED_FORMULA
```

**Keputusan persistensi (default = sidecar, rendah risiko):**
Simpan model aktif sebagai **file JSON ter-seal** di samping sqlite repo:
`<sqlite_path>.attack_path_ranker.json`. Alasan: tidak perlu bump migrasi skema
(migration level repo saat ini `= 12`), blast-radius kecil, tetap ride direktori & retensi
yang sama. Opsi B (tabel sqlite + migration 13) didokumentasikan di §6 sebagai upgrade,
JANGAN dikerjakan kecuali diminta.

---

## 3. File yang dibuat / diubah

### 3.1 BARU — `pentest_subsystem/attack_path_ranker_store.py`
Persistensi + audit untuk satu model ranker aktif.

Spesifikasi:
- `class AttackPathRankerStore` dengan konstruktor `__init__(self, sqlite_path: str | Path)` →
  menurunkan `self.path = Path(str(sqlite_path) + ".attack_path_ranker.json")`.
- `save(self, model: Mapping, evaluation: Mapping) -> None`:
  - Tolak bila `not attack_path_ranking.model_is_usable(model)` → `raise AttackPathRankerStoreError`.
  - Tolak bila `not attack_path_ranking.verify_evaluation(evaluation)` atau
    `evaluation["promotable"] is not True`.
  - Tulis atomik (`*.tmp` lalu `os.replace`) sebuah envelope:
    `{"schema_version": "apts-stage5.5-ranker-store-v1", "model": model, "evaluation": evaluation,
      "envelope_sha256": sha256_hex({...})}` (gunakan `boundary_contract.sha256_hex`,
    domain string khusus mis. `"APTS_STAGE5_5_RANKER_STORE_V1"`). Tanpa wall-clock di dalam hash.
- `load(self) -> dict | None`:
  - `None` bila file tak ada / JSON rusak / `envelope_sha256` tak cocok / model gagal
    `model_is_usable`. **Tidak pernah raise** (fail-closed; dipakai di startup).
  - Jika valid → kembalikan `{"model": ..., "evaluation": ...}`.
- `clear(self) -> None`: hapus file bila ada (abaikan jika deletion belum diizinkan — lihat
  catatan device, cukup `try/except`).
- `class AttackPathRankerStoreError(ValueError)`.

### 3.2 BARU — `pentest_subsystem/attack_path_ranker_training.py`
Orkestrasi training **murni & offline**.

- `collect_attack_path_records(repository, *, max_runs: int | None = None) -> tuple[list[dict], dict]`:
  - Iterasi Stage 6 execution run yang tersimpan di `repository`. Untuk tiap run: jalankan
    verifikasi integritas run yang sudah ada (pakai fungsi `verify_execution_run` / verifier
    yang dipakai modul exploitation; JANGAN membuat verifier baru), lewati run yang gagal.
    Ambil `hypotheses` dan `assets` terkait run tsb, panggil
    `learning_dataset.build_records(execution_run, hypotheses, assets=...)`.
  - Kumpulkan hanya `record["entity_kind"] == learning_dataset.KIND_ATTACK_PATH`, dedup by
    `record_id`. Kembalikan `(records_terurut, counters_gabungan)`.
  - Deterministik: urutkan run & record secara stabil (by id).
- `train_promoted_ranker(records, **fit_kwargs) -> dict`:
  - `result = attack_path_ranking.evaluate_ranking(records, **fit_kwargs)`.
  - Kembalikan `{"evaluation": result["evaluation"], "model": result["model"]}`
    (model `None` bila gate menolak).
- Tidak menyentuh jaringan, tidak menulis file (penulisan dilakukan CLI/caller).

### 3.3 BARU — `pentest_subsystem/train_attack_path_ranker.py` (CLI offline)
Pola meniru `train_attack_policy.py`.

- argparse:
  - `--repo PATH` (sqlite repo Stage 5.5) **atau** `--dataset PATH` (JSON list record hasil
    `export_dataset`) — salah satu wajib.
  - `--out PATH` (opsional): tulis audit `{evaluation, model}` sebagai JSON.
  - `--install` (flag): bila di-set DAN `evaluation["promotable"]`, panggil
    `AttackPathRankerStore(repo_path).save(model, evaluation)` untuk mengaktifkan.
  - `--episodes`/fit kwargs opsional diteruskan ke `evaluate_ranking`.
- Alur: bangun repository dari `--repo` (atau baca dataset), `collect`/muat records →
  `train_promoted_ranker` → cetak ringkasan `evaluation` (sample_count, mission_count,
  lomo.ndcg_at_k, fixed_formula_baseline.ndcg_at_k, promotable, not_promotable_reasons) sebagai
  JSON ke stdout. Bila `--install` tetapi tidak `promotable` → cetak alasan, **exit code 2**,
  tidak menyimpan. Tanpa `--install` → hanya laporan (dry-run), tidak mengubah store.

### 3.4 EDIT — `pentest_subsystem/attack_path_planning.py`
Tambah kemampuan reload (tanpa mengubah default `None`, tanpa migrasi):

- Pada `AttackPathPlanningAgentRepository`:
  - Tambah method `reload_attack_path_ranker_model(self) -> bool`:
    ```
    store = AttackPathRankerStore(self.sqlite_path)
    loaded = store.load()
    if loaded is None:
        self._attack_path_ranker_model = None
        return False
    self.set_attack_path_ranker_model(loaded["model"])  # re-verify via model_is_usable
    return True
    ```
    Bungkus dalam `try/except` yang mengembalikan `False` + set `None` bila apa pun gagal
    (fail-closed). Import `AttackPathRankerStore` secara lokal di dalam method untuk
    menghindari import siklik.
- Pada `AttackPathPlanningAgentService`:
  - Tambah `reload_attack_path_ranker_model(self) -> bool` yang mendelegasikan ke
    `self.repository.reload_attack_path_ranker_model()`.
- **JANGAN** mengubah `__init__` default, `build_candidate_attack_paths`, atau
  `set_attack_path_ranker_model` yang sudah ada.

### 3.5 EDIT — `pentest_subsystem/api_service.py`
Pasang bootstrap tepat setelah service dibuat (baris ~1956: `service = AttackPathPlanningAgentService()`):

```python
service = AttackPathPlanningAgentService()
# Fase 2 (Stage 5.5 learning-to-rank) — muat ranker ter-promote dari store lokal, fail-closed.
try:
    if service.reload_attack_path_ranker_model():
        logger.info("Stage 5.5 attack-path ranker (Fase 2) loaded from store")
    else:
        logger.info("Stage 5.5 attack-path ranker absent/invalid; using fixed 0.8/0.2 formula")
except Exception:  # noqa: BLE001 — startup must never fail on ranker wiring
    logger.exception("attack-path ranker load failed; falling back to fixed formula")
```

Gunakan logger yang sudah ada di modul (sesuaikan nama). Tidak boleh ada `raise` yang
menggagalkan startup di blok ini.

### 3.6 BARU — `tests/test_stage5_5_ranker_runtime_wiring.py`
Lihat §4.

---

## 4. Acceptance tests (wajib lulus)

1. **Regresi fail-safe.** Service baru tanpa store → jalankan Stage 5.5 →
   `output["candidate_paths"][*]["planning_score"]["formula"] == attack_path_ranking.SYMBOLIC_FORMULA`,
   dan output byte-identik (hash sama) dengan build pra-wiring untuk input yang sama.
2. **Jalur terlatih.** Siapkan dataset bergrade yang membuat `build_promoted_model` menghasilkan
   model (≥ `MIN_TRAIN_SAMPLES`=20, ≥2 mission, lolos NDCG). `store.save(model, evaluation)` →
   `service.reload_attack_path_ranker_model()` True → jalankan Stage 5.5 →
   `planning_score.formula == LEARNED_FORMULA`, `planning_score.model.features` memuat
   `chain_mapping_strength`, dan `verify_attack_path_planning_output(output)` True.
3. **Store korup/tampered.** Rusak `envelope_sha256` atau bobot model → `store.load()` None →
   reload False → formula tetap `SYMBOLIC_FORMULA`, tidak ada exception.
4. **Gate menolak.** Dataset single-grade/terlalu kecil → `train_promoted_ranker` model None →
   CLI `--install` exit code 2, store tidak berubah.
5. **Determinisme.** `train_promoted_ranker` dua kali atas records identik → `weights_sha256` sama.
6. **Bootstrap tidak menggagalkan startup.** Simulasikan `reload` melempar (monkeypatch store
   load raise) → konstruksi app/service tetap sukses, ranker `None`.

Gunakan fixture/util yang sudah ada di `tests/test_stage5_5_attack_path_ranking.py`
(mis. pembuat records bergrade) agar tidak menduplikasi data sintetis.

---

## 5. Perintah verifikasi (jalankan setelah implementasi)

```bash
# dari D:\APTS\mission_orchestrator
python -m pytest tests/test_stage5_5_ranker_runtime_wiring.py -q
python -m pytest tests/test_stage5_5_attack_path_ranking.py -q      # regresi ranker
python -m pytest tests/ -k "attack_path or ranker or bron" -q       # regresi area terkait

# dry-run laporan promosi dari repo nyata (tidak mengubah apa pun)
python -m pentest_subsystem.train_attack_path_ranker --repo <path_sqlite_stage5_5>

# aktifkan bila promotable (human-in-the-loop)
python -m pentest_subsystem.train_attack_path_ranker --repo <path_sqlite_stage5_5> --install
```

Bukti keberhasilan empiris: pada output live Stage 5.5 setelah `--install`,
`planning_score.formula` berubah dari `0.8*HYPOTHESIS_CONFIDENCE + 0.2*LOWER_VALIDATION_IMPACT_FACTOR`
menjadi `LEARNED_LINEAR_VALIDATION_PRIORITY_RANKER_V2`, dan `planning_score.model.model_sha256`
cocok dengan `weights_sha256` di store.

---

## 6. Opsi B (upgrade, JANGAN dikerjakan kecuali diminta)

Persistensi di sqlite repo: bump `ATTACK_PATH_PLANNING_AGENT_REPOSITORY_MIGRATION_LEVEL`
`12 → 13`, tambah tabel `attack_path_ranker_model(repository_id, model_json, evaluation_json,
envelope_sha256)` di jalur migrasi `initialize()`, muat di akhir `initialize()`. Keuntungan:
ikut transaksi/retensi/lifecycle repo. Risiko: menyentuh jalur migrasi — butuh uji
backward-compat level 12 dan penolakan level >13 (pola penolakan sudah ada di `initialize()`).

---

## 7. Follow-up opsional — simetri Fase 1 (Stage 5.4)

`vulnerability_hypothesis.set_calibration_model` punya pola in-memory identik dan juga belum
ter-wire runtime. Setelah Fase 2 lolos, pola store+bootstrap yang sama dapat diterapkan
(`CalibrationStore` + `reload_calibration_model` + hook di `api_service`), memakai
`vulnerability_hypothesis_calibration.build_promoted_model`. Catat sebagai item terpisah; JANGAN
digabung ke PR ini agar diff tetap fokus.

---

## 8. Definition of Done

- [ ] 3 file baru + 2 edit sesuai §3, tanpa menyentuh algoritma ranker/graph/dataset.
- [ ] Semua acceptance test §4 lulus; regresi §5 hijau.
- [ ] Tanpa store → perilaku byte-identik dengan pra-wiring (formula tetap).
- [ ] Dengan model ter-promote → `LEARNED_FORMULA` aktif & `verify_attack_path_planning_output` True.
- [ ] Startup tidak pernah gagal akibat ranker; semua jalur gagal → fallback formula tetap.
- [ ] Training tetap offline (CLI), aktivasi eksplisit via `--install`.
