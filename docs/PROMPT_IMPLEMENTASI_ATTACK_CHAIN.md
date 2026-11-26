# Prompt Implementasi — Attack-Chain Enrichment (untuk Claude Code)

Tempel isi blok di bawah ke Claude Code saat berada di repo `D:\APTS`. Spesifikasi lengkap ada di
`docs/ATTACK_CHAIN_CPE_CVE_CWE_CAPEC_ATTACK_DESIGN.md`.

---

```
# TUGAS: Implementasi Attack-Chain Enrichment (CPE→CVE→CWE→CAPEC→ATT&CK) ke Stage 5.4/5.5

## Acuan WAJIB (baca dulu, jangan mulai sebelum ini)
1. `docs/ATTACK_CHAIN_CPE_CVE_CWE_CAPEC_ATTACK_DESIGN.md` — spesifikasi otoritatif. Ikuti persis
   §3 (perubahan per file), §5 (kontrak data `attack_chain`), §6 (version-bump), §7 (test), §8 (urutan).
2. `CLAUDE.md` — INVARIANT KERAS. Bila ada langkah yang menuntut pelanggaran invariant, HENTIKAN
   dan laporkan; jangan "akali agar test lewat".

## Prinsip eksekusi
- **Aditif.** Jangan ubah jalur read-only Stage 6, oracle, korelasi CVE Stage 5.4, maupun STRIPS planner.
  `attack_chain` = field OPSIONAL baru; tanpa data CTI perilaku lama harus byte-identik.
- **TDD per tahap.** Untuk tiap tahap: tulis kode → tulis test (tiru pola `STAGE_X_Y_ACCEPTANCE`/`verify_*`
  di `mission_orchestrator/tests/`) → `pytest` test terkait HIJAU → baru lanjut. Jangan lompat tahap.
- **Deterministik.** Tanpa `eval`/`exec`, tanpa randomness runtime, tanpa waktu-nyata di hash
  (pakai `graph_snapshot_id` + versi katalog). Segel dengan `boundary_contract.sha256_hex` + domain.
- **Projection-only.** Tak ada I/O jaringan baru di agent Stage 5.x (adapter loopback-only ke VulnDesk,
  `auto_fetch=false`). Chain tak pernah menyentuh scope/RoE/otorisasi.
- Setelah tiap tahap: commit aditif terpisah dengan pesan jelas (jangan satu commit raksasa).

## Urutan implementasi (ikuti §8 dokumen; test # merujuk §7)
1. Modul baru `pentest_subsystem/cti_attack_chain.py`: `fetch_attack_chain(cve=/cwe_ids=)` (loopback,
   pola `_post` seperti `cti_hypothesis_adapter`) + `normalize_attack_chain(raw, entry=)` dengan
   pemangkasan fan-out deterministik + segel `ATTACK_CHAIN_HASH_DOMAIN`. → test #1.
2. (Opsional) endpoint konsolidasi `/api/pentest/attack-chain` di VulnDesk `pentest_enrichment_api_service.py`
   yang bungkus `AttackMappingService.map_vulnerability()` + `graph_snapshot_id`. Kalau dilewati, adapter
   panggil `/api/pentest/cve-cwes` lalu `/api/pentest/map-attack`.
3. `vulnerability_hypothesis._normalize_knowledge_item`: tambah `"attack_chain"` ke `allowed` (BUKAN
   `required`) + normalizer `_normalize_attack_chain` (enum `mapping_level`; `technique_id` ^T\d{4}(\.\d{3})?$;
   `is_causal` harus False); masukkan ke `result` SEBELUM `knowledge_sha256`. → test #4.
4. `cti_hypothesis_adapter._knowledge_item` (≈214): tempel `attack_chain` entry="CPE" hanya bila resolve
   sukses (gagal → tanpa field, fail-open). Tambah `build_weakness_knowledge_items(...)` entry="CWE" dari
   `knowledge_packs/`. → test #2, #3.
5. `attack_path_planning.py`: bawa `attack_chain` ke provenance jalur + ringkasan non-kausal
   `path["attack_techniques"]`. JANGAN ubah `symbolic_planner.compile_problem()/plan()`. → test #5
   (regresi: paths/cost/edges identik baseline; chain TIDAK muncul di preconditions/effects).
6. `learning_dataset.py`: perluas `_path_features(pr, linked)` hitung `chain_mapping_strength` (rumus §3.6b)
   dari `attack_chain` hipotesis `linked`; bump `DATASET_SCHEMA_VERSION`. Pastikan `ensure_label_dataset_store`
   + migrasi dijalankan (tabel `pentest_label_dataset` belum ada di DB live).
7. `attack_path_ranking.py` → RANKER v2: `RANKER_FEATURES_V2` (+`chain_mapping_strength`);
   `FIXED_FORMULA_WEIGHTS` beri chain=0.0 agar `prior_model()` TETAP `0.8/0.2` byte-identik; arahkan
   `ranking_features/score/fit/verify_model` ke V2; bump `RANKER_SCHEMA_VERSION/MODEL/EVAL` ke _V2;
   tambah param `chain_mapping_strength` di `planning_score_block` + baca di `candidate_path_features`.
   → test #6, #7, #9, #10.
8. Bump versi/migrasi + REGENERASI fixtures + gate `STAGE_5_4_*` & `STAGE_5_5_*` (§6 checklist). → test #11.
9. Jalankan test suite terkait + `verify_ae_run`/`verify_*`; semua HIJAU.

CATATAN: JANGAN melatih/mempromosikan model ranker v2 sungguhan sekarang — belum ada data `ATTACK_PATH`
berlabel (0 record; `pentest_attack_path_planning_runs=0`). Implementasikan hanya MACHINERY-nya dan uji
gate LOMO-NDCG dengan FIXTURE sintetik (test #8). Promosi nyata (`build_promoted_model`) dijalankan nanti
setelah terkumpul ≥20 path ber-chain dari ≥2 misi — tulis ini sebagai TODO, jangan eksekusi.

## Definition of Done (lapor di akhir)
- Semua test §7 hijau; `verify_*` hijau; jalur Stage 6 read-only tak tersentuh.
- `git diff` aditif; `prior_model()` v2 == perilaku `0.8/0.2` lama (buktikan di test #6).
- Tak ada field chain di STRIPS; tak ada I/O jaringan baru di agent Stage 5.x; tak ada randomness runtime.
- Perubahan hash berhenti di Stage 5.4→5.5 (bila merembet ke 5.6+/6.x: STOP & lapor — §6).
- Ringkas: file yang diubah/ditambah, konstanta yang di-bump, test baru, dan daftar TODO yang ditunda.

## JANGAN
- Menjadikan technique/CAPEC/CWE sebuah effect/precondition planner (klaim reachability — dilarang).
- Query CTI live saat serve untuk `chain_mapping_strength` (hanya dari `attack_chain` ter-snapshot di path).
- Mengisi `chain_mapping_strength=0.0` diam-diam untuk record label; longgarkan `MAX_NDCG_REGRESSION`;
  melatih ranker saat inference; menambah I/O jaringan ke agent Stage 5.x; memakai `eval`/`exec`.
- Melonggarkan RoE/governance dari kode "agar test lewat".
```

---

## Cara pakai
- Jalankan bertahap. Untuk membatasi satu sesi, potong di **tahap 5** (semua provenance + planner, tanpa
  ranker), lalu lanjutkan **ranker v2** (tahap 6–7) di sesi berikutnya.
- **Tahap 8 (training/promosi nyata) ditunda** sampai ada data `ATTACK_PATH` berlabel (saat ini 0). Yang
  diimplementasikan sekarang hanya machinery + test fixture sintetik.
- Jika sebuah tahap bertabrakan dengan INVARIANT di `CLAUDE.md`, Claude Code diminta **berhenti dan
  melapor**, bukan memaksakan.
