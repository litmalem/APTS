# Rancangan detail: Strategi probing adaptif — degradasi otomatis (7 November 2026)

Dokumen ini merancang implementasi "strategi probing adaptif yang menyesuaikan
kondisi aplikasi" untuk APTS, dibatasi pada **degradasi otomatis level parameter
(tighten-only)**. Rancangan dibuat agar tidak melanggar invariant inti pentest
subsystem dan execution subsystem yang sudah ada.

## 1. Tujuan dan batas ruang lingkup

- **Tujuan:** ketika probing mengamati kondisi target yang buruk (rate limiting
  429, server overload 503, `Retry-After`, latensi tinggi, indikasi WAF),
  iterasi probing berikutnya otomatis **menurunkan intensitas**: window rate
  lebih panjang, budget request/byte lebih kecil, deadline lebih pendek.
- **Di dalam ruang lingkup:** penyesuaian parameter runtime yang hanya bisa
  *mengetatkan* (tighten-only). Tetap `rate_cost==1`, `active_concurrency==1`.
- **Di luar ruang lingkup (default):** menaikkan intensitas, menambah target,
  memakai teknik di luar allowlist. Semua ini **wajib** lewat revalidasi
  governance dan bukan bagian degradasi otomatis.
- **Ekstensi opsional (Bagian 9):** peralihan teknik aktif → pasif saat WAF
  terdeteksi. Masih degradasi, tapi menyentuh `technique_allowlist`.

## 2. Invariant yang dijaga

Rancangan ini mematuhi dan tidak boleh melanggar:

1. `DETERMINISTIC_NORMALIZATION_AND_AGGREGATION` — kebijakan degradasi adalah
   **fungsi murni** atas evidence yang sudah tersegel, bukan pembacaan real-time.
   Input sama → output (dan hash) sama → replayable.
2. Agen Stage 5 tidak mengeksekusi target; output tetap `action_proposal` yang
   dievaluasi `scope_roe` fail-closed.
3. Separation proposal ≠ authorization ≠ execution. Degradasi hanya menghasilkan
   proposal/parameter yang lebih lembut, tidak pernah mencetak otorisasi.
4. Fail-closed by `min()` intersection di `compile_runtime_policy`. Sumber baru
   apa pun hanya boleh menambah pengetatan, tidak pernah melonggarkan.
5. Perubahan scope/RoE → `ESCALATE_GOVERNANCE`. Degradasi tidak menyentuh scope.

## 3. Temuan kode yang menjadi fondasi

- `compile_runtime_policy()` — `mission_orchestrator/execution_subsystem/adapter_policy.py:36`.
  `limits` = interseksi fail-closed (`min` kuota, `max` window) dari constraint
  deklaratif; dihitung sekali di awal dari snapshot otorisasi, **belum** menerima
  input kondisi teramati.
- Penegakan nyata: reservasi (`adapter_repository.py:228`) untuk concurrency,
  rolling-window rate, agregat budget; in-run pacing + hard-stop byte/budget
  (`web_profile_collection.py:51`).
- Gate footprint minimum: `proposal_source.py:374` menolak kecuali
  `rate_cost==1`, `active_concurrency==1`, `impact∈{NONE,LOW}`.
- **Retry runtime memakai ExecutionRequest yang SAMA & immutable**
  (`runtime_repository.py:246`) dan hanya boleh bila attempt gagal **tanpa I/O
  target** (`retryable()`, `runtime_repository.py:239`;
  `RETRY_REQUIRES_PROVEN_NO_TARGET_IO_FAILURE`, baris 293).
- `stop_conditions` deklaratif saat ini **ditolak** runtime
  (`adapter_policy.py:62`). Degradasi di dokumen ini TIDAK memakai jalur stop
  deklaratif, sehingga tidak menabrak penolakan itu.

### Konsekuensi arsitektur

Karena menerima respons berarti I/O target sudah terjadi, attempt yang melihat
429/503/latensi menjadi **terminal dan tidak bisa di-retry**. Maka degradasi
untuk kondisi tersebut **tidak bisa** lewat retry runtime — ia harus menjadi
**iterasi baru di lapis proposal** (Jalur 2). Retry runtime hanya relevan untuk
kegagalan tanpa I/O (Jalur 1).

## 4. Arsitektur: dua jalur, empat komponen

```
                 attempt N (tersegel, evidence hash-bound)
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  A. Sensor kondisi (ekstraktor murni) │  → target_condition_signal
        └──────────────────────────────────────┘     (evidence baru, hash-bound)
                           │
             ┌─────────────┴──────────────┐
             ▼                            ▼
  Jalur 1: gagal TANPA I/O      Jalur 2: 429/503/latensi (I/O terjadi)
  (CONNECTION_FAILED/TIMEOUT)   → attempt terminal
             │                            │
             ▼                            ▼
  C. compile_runtime_policy     D. cross_agent_feedback
     + sumber pengetat             feedback_type=TARGET_CONDITION_DEGRADE
     (pacing attempt berikut)      → REPLAN_LOCAL → proposal lebih lembut
             │                            │
             ▼                            ▼
  retry request SAMA, GSS fresh   B. kebijakan deterministik (tighten-only)
  window rate lebih panjang       → proposal baru → governance → request baru
```

Komponen **B** (kebijakan deterministik) dipakai oleh kedua jalur sebagai sumber
kebenaran pemetaan "kondisi → delta pengetatan".

## 5. Komponen A — Skema sinyal kondisi

Modul baru, mis. `execution_subsystem/condition_signal.py`. Fungsi ekstraktor
**murni** yang membaca frame respons yang sudah tersegel (bukan I/O baru) dan
menghasilkan satu record hash-bound.

### 5.1 Skema `target_condition_signal_v1`

```
{
  "schema_version": "apts-target-condition-signal-v1",
  "signal_id": "tcond-<sha48>",            # deterministik dari evidence sumber
  "attempt_ref": "<attempt_id>",
  "execution_id": "<immutable ExecutionRequest id>",
  "source_evidence_sha256": "<hash frame/evidence tersegel>",
  "observed": {
    "status_classes": ["4xx", "5xx"],       # dari HTTP status line tiap frame
    "rate_limited": true,                    # ada 429
    "server_overload": true,                 # ada 503
    "retry_after_seconds": 30,               # dari header Retry-After (bila ada)
    "max_latency_ms": 8200,                  # latensi per hop tertinggi
    "waf_indicator": false,                  # signature header allowlist (opsional)
    "requests_performed": 2,
    "request_budget": 2
  },
  "semantics": {
    "derived_from_sealed_evidence": true,
    "new_target_io_performed": false,        # ekstraksi TIDAK melakukan I/O
    "is_decision": false,
    "is_authorization": false
  },
  "integrity": { ... SHA-256 UTF8_SORTED_JSON_V1 ... }
}
```

### 5.2 Aturan ekstraksi (tighten-only friendly)

- Hanya membaca metadata yang **sudah** ada di evidence v4: HTTP status line,
  header allowlist (`Retry-After`, signature WAF bila diaktifkan), hitungan
  request, dan latensi yang sudah tercatat per frame.
- Tidak menyimpan body, cookie value, query token, atau header autentikasi —
  konsisten dengan kontrak output v4.
- `signal_id` dan seluruh record **deterministik** dari `source_evidence_sha256`
  → dua ekstraksi atas evidence sama menghasilkan signal identik.
- `new_target_io_performed: false` adalah invariant modul ini: ekstraksi murni.

### 5.3 Titik sisip ekstraksi

Setelah attempt mencapai terminal dan evidence SEALED, pada pembaca hasil
(bukan di dalam `collect_profile`). Signal menjadi evidence anak dari evidence
attempt, hash-bound ke lineage Stage 4.9 seperti observation lain.

## 6. Komponen B — Fungsi kebijakan deterministik

Modul baru, mis. `pentest_subsystem/adaptive_degradation.py`. **Fungsi murni,
tanpa I/O, tanpa clock.**

### 6.1 Tanda tangan

```python
def derive_degradation_delta(
    *,
    signal: Mapping[str, Any],        # target_condition_signal_v1 tervalidasi
    current_limits: Mapping[str, Any] # subset limits saat ini (rujukan batas atas)
) -> dict[str, Any]:
    """Petakan kondisi teramati -> delta pengetatan. TIGHTEN-ONLY.

    Mengembalikan hanya field yang DITURUNKAN/diperketat. Tidak pernah
    mengembalikan nilai yang melonggarkan current_limits. Deterministik.
    """
```

### 6.2 Tabel pemetaan kondisi → delta (deterministik)

| Kondisi pada signal | Delta pengetatan yang dihasilkan |
|---|---|
| `rate_limited` (429) | `rate_window_seconds ×= 4` (perlambat); jika ada `retry_after_seconds`, `rate_window_seconds = max(window, retry_after_seconds)` |
| `server_overload` (503) | `max_network_requests = max(1, budget-1)`; `timeout_seconds ×= 0.5` |
| `max_latency_ms` > ambang (mis. 5000) | `timeout_seconds` dinaikkan HANYA sampai batas sumber (tidak melebihi), selain itu `rate_window_seconds ×= 2` |
| `status_classes` memuat `5xx` berulang (≥ N iterasi) | tandai `recommend_halt: true` (lihat 6.4) |
| `waf_indicator` (opsional) | `technique_downgrade: "PASSIVE"` (Bagian 9) |

Nilai faktor (4×, 2×, 0.5×) adalah konstanta modul yang bisa dikalibrasi; yang
penting **arah selalu mengetatkan**.

### 6.3 Properti tighten-only (wajib diuji)

Untuk setiap field `k` dalam hasil delta:
- Field kuota/konkurensi/budget: `delta[k] <= current_limits[k]`.
- Field window: `delta[k] >= current_limits[k]` (window lebih panjang = lebih
  konservatif, sesuai pola `max()` di `compile_runtime_policy`).
- `rate_cost` dan `active_concurrency` **tidak pernah** muncul di delta (tetap 1).

Properti ini memastikan: meski kebijakan salah, interseksi `min`/`max` di
`compile_runtime_policy` dan gate `==1` di `proposal_source` tetap menolak
pelonggaran. Degradasi tidak bisa berubah jadi eskalasi.

### 6.4 Rekomendasi halt

Jika `recommend_halt`, kebijakan **tidak** mengarang stop-condition deklaratif
(yang akan ditolak runtime). Sebaliknya ia mengembalikan sinyal yang dipakai
Jalur 2 untuk menghasilkan `feedback_type` yang memicu `DEFER_TO_STAGE6` atau
`NO_CHANGE` (berhenti mengusulkan probing lanjutan), bukan menyuntik stop ke
runtime.

## 7. Komponen C — Jalur 1: pacing per-attempt

Untuk kegagalan **tanpa I/O** (CONNECTION_FAILED/TIMEOUT) yang `retryable()`.
Request immutable sama; yang fresh hanya otorisasi GSS per attempt.

### 7.1 Perubahan pada `compile_runtime_policy`

Tambah parameter opsional sumber pengetat, mis.
`observed_tightening: Mapping | None = None`, yang hanya berisi hasil `delta`
dari Komponen B untuk field yang legal diubah per-attempt (window/deadline).
Terapkan dengan pola yang sudah ada:

```python
if observed_tightening:
    if "rate_window_seconds" in observed_tightening:
        limits["rate_window_seconds"] = max(
            limits["rate_window_seconds"],
            _number(observed_tightening["rate_window_seconds"], "observed.rate_window_seconds"),
        )
    if "timeout_seconds" in observed_tightening:
        limits["timeout_seconds"] = min(
            limits["timeout_seconds"],
            _number(observed_tightening["timeout_seconds"], "observed.timeout_seconds"),
        )
```

Catatan: budget request **tidak** diubah di Jalur 1 karena terikat request
immutable. Jalur 1 murni memperlambat, bukan mengubah cakupan.

### 7.2 Dari mana `observed_tightening` berasal

Otorisasi fresh untuk attempt retry membawa referensi ke `target_condition_signal`
attempt pendahulunya (via `retry_of_attempt_id`). Pembaca merujuk signal
tersegel itu, memanggil Komponen B, lalu meneruskan delta ke
`compile_runtime_policy`. Deterministik karena signal tersegel.

## 8. Komponen D — Jalur 2: re-proposal lebih lembut

Untuk 429/503/latensi (attempt terminal, tak bisa retry). Memanfaatkan
`cross_agent_feedback` + `orchestration/replanning.py` yang sudah ada.

### 8.1 feedback_type baru

Tambah `"TARGET_CONDITION_DEGRADE"` ke `CROSS_AGENT_FEEDBACK_TYPES`
(`cross_agent_feedback.py:92`). Pemetaan restart di `_feedback_restart_capability`:
kembalikan kapabilitas pengusul probing yang sama (recon/enumeration) agar
`build_local_replan_decision` menghasilkan `REPLAN_LOCAL` yang membuka kembali
subtask itu — **bukan** menaikkan scope.

### 8.2 Alur re-proposal

1. Feedback membawa `evidence_refs` ke `target_condition_signal` (harus sudah
   ada di shared_state — memenuhi `FEEDBACK_EVIDENCE_REFS_MUST_ALREADY_EXIST`).
2. `REPLAN_LOCAL` membuka subtask pengusul.
3. Saat subtask mengusulkan ulang, `derive_*_action_proposals` memanggil
   Komponen B untuk menurunkan parameter proposal (window lebih panjang / budget
   lebih kecil) — tetap `rate_cost==1`, `active_concurrency==1`.
4. Proposal lewat `evaluate_scope_roe` fail-closed → sealed ExecutionRequest baru
   → attempt baru yang lebih lembut.

### 8.3 Longgarkan hardcode parameter proposal

Saat ini `derive_recon_action_proposals` mematok `rate_cost=1, active_concurrency=1`
dan tidak menyetel window. Degradasi menambahkan **hint parameter lembut**
(mis. preferensi window rate) ke proposal/metadata, yang kemudian menjadi input
pengetat di `compile_runtime_policy` lewat constraint sumber — bukan menaikkan
`rate_cost`. `rate_cost`/`concurrency` tetap 1 agar gate intake lolos.

## 9. Ekstensi opsional — peralihan teknik aktif → pasif

Jika disertasi menuntut adaptasi teknik (bukan hanya parameter):

- Saat `waf_indicator`, Komponen B mengembalikan `technique_downgrade: "PASSIVE"`.
- Proposal baru memakai teknik pasif yang **sudah ada di allowlist** (mis.
  `PASSIVE_DISCOVERY` untuk recon). Jika teknik target tidak di allowlist,
  `technique_allowlist` di `compile_runtime_policy:90` menolaknya — fail-closed.
- Ini tetap degradasi (pasif ≤ aktif), tapi menyentuh pemilihan teknik, sehingga
  butuh acceptance test tambahan dan verifikasi bahwa teknik pasif tidak
  melakukan I/O aktif. Dibiarkan sebagai langkah terpisah dari inti parameter.

## 10. Rencana migrasi dan pengujian

Mengikuti pola `STAGE*_ACCEPTANCE` dan migrasi SQL bernomor yang ada.

- **Migrasi:** tabel/kolom untuk menyimpan `target_condition_signal` (append-only,
  hash-bound) di bawah repository Pentest/Execution yang sesuai. Satu file
  migrasi bernomor baru.
- **Unit (fungsi murni):**
  - Ekstraktor: evidence → signal deterministik; dua panggilan identik.
  - Kebijakan: tabel pemetaan; properti tighten-only (lihat 6.3) diuji secara
    menyeluruh termasuk kasus adversarial (signal menyuruh melonggarkan → delta
    tetap mengetatkan / kosong).
- **Integrasi Jalur 1:** retry tanpa I/O memakai window lebih panjang; budget
  request tidak berubah; deadline tidak melampaui batas sumber.
- **Integrasi Jalur 2:** 429 pada attempt → signal → feedback → REPLAN_LOCAL →
  proposal baru dengan window lebih panjang; `rate_cost`/`concurrency` tetap 1;
  governance eval ELIGIBLE; request baru tersegel.
- **Negatif/keamanan:**
  - Signal yang mencoba menaikkan budget/concurrency ditolak oleh interseksi
    `min` dan gate `==1`.
  - Tidak ada I/O target di jalur ekstraksi.
  - Tidak ada stop-condition deklaratif yang dikirim ke runtime.
  - Determinisme: hash signal/proposal stabil pada replay.

## 11. Urutan implementasi yang disarankan

1. Skema + ekstraktor sinyal kondisi (Komponen A) + migrasi + unit test.
2. Fungsi kebijakan deterministik (Komponen B) + unit test properti tighten-only.
3. Jalur 1: parameter `observed_tightening` di `compile_runtime_policy` + test.
4. Jalur 2: `feedback_type` baru + pemetaan replan + hint parameter proposal + test.
5. (Opsional) peralihan teknik pasif + test.

Setiap langkah berdiri sendiri dan menjaga sistem tetap hijau; langkah 1–2 tidak
mengubah perilaku runtime sama sekali (murni menambah data + fungsi).

## 11a. Status implementasi (per 7 November 2026)

Dikerjakan sebagai kode murni/aditif + satu sisipan defensif di jalur eksekusi,
semua dengan unit test lulus (59 test adaptif):

- **A — sinyal kondisi:** `execution_subsystem/condition_signal.py` (ekstraktor
  murni + helper `condition_signal_from_adapter_collection`). DIWIRE ke
  `adapter_service._run_reserved`: `condition_signal` kini masuk ke adapter
  result tersegel (defensif → `null` jika ekstraksi gagal; tak pernah memengaruhi
  status/seal). Aman: `verify_adapter_result` toleran field ekstra, kontrak 6.4
  tak meng-embed skema result.
- **B — kebijakan tighten-only:** `pentest_subsystem/adaptive_degradation.py`.
- **C — pacing:** `apply_observed_tightening` + kwarg `observed_tightening` di
  `compile_runtime_policy` (jalur default tak berubah; regresi wpt budget lulus).
- **D — re-proposal/keputusan Jalur 2:** `pentest_subsystem/adaptive_reproposal.py`.

Belum / sengaja ditunda:
- **Jalur retry (`observed_tightening`) TIDAK di-wire — inert.** `before_io`
  mewajibkan policy cocok eksak, dan `retryable()` hanya untuk kegagalan TANPA
  I/O target (429/503 tak pernah muncul di sana; Komponen B tak bereaksi pada
  connection-failure). Nilainya nol hari ini.
- **Version-bump kontrak `cross_agent_feedback`** untuk mengaktifkan
  `TARGET_CONDITION_DEGRADE` — hash berantai ke Stage 5.9/5.10/6.1 +
  `SHA256_STAGE5_8.txt` + script acceptance; peristiwa lintas-stage tersendiri.
- **Migrasi** persistensi sinyal sebagai store terpisah (opsional).

⚠️ **Verifikasi tertunda:** suite acceptance Stage 6.4/6.5 (yang menjalankan
`_run_reserved` end-to-end) TIDAK bisa dijalankan di lingkungan pengembangan saat
ini karena pytest ditolak akses direktori temp. Jalankan
`STAGE6_4_ACCEPTANCE.ps1` + `STAGE6_5_ACCEPTANCE.ps1` di mesin dengan izin temp
normal sebelum mempercayai wiring runtime. Catatan: test basi pre-existing
`test_contract_exact_predecessor_and_five_families` (`== 5` vs 6 adapter family)
tidak terkait perubahan ini.

## 12. Keputusan terbuka

- Nilai konstanta faktor pengetatan (4×, 2×, 0.5×, ambang latensi 5000 ms,
  N iterasi untuk halt) — perlu kalibrasi empiris pada target uji (mis. DVWA).
- Apakah `waf_indicator` diaktifkan (butuh signature header) atau ditunda.
- Apakah ekstensi peralihan teknik (Bagian 9) masuk ruang lingkup disertasi atau
  menjadi pekerjaan terpisah.
