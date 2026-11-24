# CSRF Module — Black-Box State-Based Impact Verification (C6–C7)

Spesifikasi siap-implementasi untuk menambahkan **State Observer (C6)** dan
**Impact Verification Engine (C7)** ke modul CSRF pada Pentest Subsystem APTS.
Dibuat dari pembacaan kode `mission_orchestrator/pentest_subsystem/` per 2026-11-24.

> **Status gap terverifikasi:** APTS belum punya snapshot *state aplikasi target*
> sebelum/sesudah. Oracle yang ada (`cae_success_oracle.py`) bersifat
> *response/authorization-differential* (satu respons, cek kepemilikan objek),
> dan `ChallengeOracle` bergantung scoreboard Juice Shop (`GET /api/Challenges`).
> Modul ini menambahkan verifikasi **state-differential** (before/after) yang
> target-agnostic — jalur verifikasi KEDUA, aditif, tidak mengganti yang ada.

---

## 0. Prinsip (selaras CLAUDE.md)
- **Aditif.** Tidak mengubah jalur Stage 6 read-only maupun oracle yang ada.
- **Projection-only.** State Observer hanya membaca (GET), lewat transport/guard
  yang sama (LAB ∧ loopback ∧ allowlist). Tidak pernah mutasi, tidak mint otorisasi.
- **Deterministik & tersegel.** `φ`, `diff`, `compare` = fungsi murni tanpa I/O.
  Satu-satunya I/O = `StateObserver.snapshot()` (injected fetcher), dan hasilnya direkam.
- **Fail-closed.** Snapshot gagal / konteks cross-origin tak terbukti / atribut tak
  teramati → `INCONCLUSIVE`, dan outcome **bukan** EXPLOITED. Tak pernah mengarang bukti.

---

## 1. Pembedaan dari oracle yang ada (penting untuk pertahanan disertasi)
| Lapis | File | "Differential" atas apa | Ketergantungan |
|---|---|---|---|
| Scoreboard oracle | `active_exploitation_execution.ChallengeOracle` | flag `solved` di `GET /api/Challenges` | spesifik Juice Shop |
| Response/auth oracle | `cae_success_oracle.SuccessOracle` | satu respons: kepemilikan objek vs principal sesi (`body.data.UserId != self.userId`) | tidak butuh scoreboard, tapi satu respons |
| **State oracle (BARU)** | `impact_verification` + `state_observer` | **snapshot state aplikasi before→after**, dua eksperimen | target-agnostic, tanpa scoreboard |

Framing klaim: *"dari response-differential ke state-differential"* — bukan "menambah
differential" (itu sudah ada), melainkan memindahkan bukti ke perubahan state yang
teramati dari luar.

---

## 2. Komponen C6 — State Observer (`pentest_subsystem/state_observer.py`)

Tiru pola `ChallengeOracle` (yang sudah `snapshot()` + `newly_solved()`), tapi atas state aplikasi.

```python
class StateObserver:
    """Perception read-only atas state aplikasi target untuk satu principal/sesi.
    Mencerminkan ChallengeOracle, tetapi menghasilkan state abstrak (bukan scoreboard)."""
    def __init__(self, state_fetcher, *, projection):
        # state_fetcher(session_ref) -> observasi mentah (mis. GET /api/Users/me, /rest/user/whoami)
        # projection = konfigurasi deklaratif: atribut relevan + daftar field volatil yang dibuang
        ...
    def snapshot(self, session_ref):      # -> observasi mentah (I/O; direkam & disegel)
        ...
    def abstract(self, observation):      # -> S : dict atribut->nilai (fungsi φ, murni)
        ...
```

Fungsi abstraksi `φ` (`abstract`):
- **Whitelist** hanya atribut relevan terhadap eksperimen (dari `projection.attributes`).
- **Buang** field volatil: timestamp, `updatedAt`, token, id sementara, nonce.
- Kanonikalisasi nilai (urut key, normalisasi tipe) agar `S` deterministik.
- Contoh Juice Shop untuk CSRF: fetch `GET /api/Users/me`, `attributes=["username","email","preferred_language","theme"]`.

`projection` bersifat **data, bukan hardcode** — disuplai knowledge pack per target
(sejajar cara `exploit_primitive_library` memuat primitive dari `knowledge_packs/`).

---

## 3. Komponen C7 — Impact Verification (`pentest_subsystem/impact_verification.py`)

```python
STATE_CHANGE_CONFIRMED = "STATE_CHANGE_CONFIRMED"
NO_STATE_CHANGE        = "NO_STATE_CHANGE"
INCONCLUSIVE           = "INCONCLUSIVE"

def diff(s0, s1):                       # -> {attr: {"before": x, "after": y}} untuk atribut berubah
    ...
def compare(delta_baseline, delta_exploit, *, attributes_under_test):
    # STATE_CHANGE_CONFIRMED  : ada atribut dalam attributes_under_test yang berubah di
    #                           delta_exploit TAPI tidak di delta_baseline (perubahan
    #                           terkait eksperimen keamanan, bukan interaksi baseline biasa).
    # NO_STATE_CHANGE         : tak ada perubahan relevan pada eksperimen keamanan.
    # INCONCLUSIVE            : snapshot kurang / atribut tak teramati / konteks tak terbukti.
    ...
```

Fokus `compare` adalah **kesetaraan semantik dampak yang diuji**, bukan kesamaan seluruh
state. Baseline experiment (`delta_baseline`) berfungsi sebagai kontrol: perubahan yang
juga muncul pada baseline tidak dihitung sebagai bukti eksploit.

---

## 4. Wiring ke gateway (`active_exploitation_execution.py`)

Titik nyata: `ActiveExploitationGateway.run_chain(orchestration_id, target, primitive_chain, ...)`.
Konstruktor sudah menerima injeksi opsional (`success_oracle`, dst.) — tambahkan `state_observer=None`.

Untuk primitive ber-`verification: "state"` (lihat §5), pada langkah eksekusi:
1. `S_e0 = observer.abstract(observer.snapshot(session_ref))`  **sebelum** aksi keamanan.
2. Jalankan eksperimen keamanan (mis. CSRF cross-origin POST) — jalur yang sudah ada.
3. `S_e1 = observer.abstract(observer.snapshot(session_ref))`  **sesudah**.
4. `ΔS_e = diff(S_e0, S_e1)`.
5. Baseline experiment (opsional, bila didefinisikan primitive) → `ΔS_b`; bila tak ada, `ΔS_b = {}`.
6. `state_verdict = compare(ΔS_b, ΔS_e, attributes_under_test=primitive["state_attributes"])`.
7. Masukkan ke record step lewat `_step(..., state_verdict=..., state_evidence_ref=...)`
   (fungsi `_step` sudah menerima `**extra` — ikuti pola `oracle_verdict` yang ada di baris ~380).

**Kombinasi sinyal (Vulnerability Decision Engine tetap deterministik):**
- Untuk primitive `verification: "state"`, jadikan `STATE_CHANGE_CONFIRMED` sebagai sinyal
  EXPLOITED **menggantikan** ketergantungan scoreboard — ini inti target-agnostic.
- `oracle_verdict` (response) dan `is_solved` (scoreboard, bila ada) tetap dicatat sebagai
  **korroborator**, bukan syarat.
- `INCONCLUSIVE`/`NO_STATE_CHANGE` → outcome tetap non-EXPLOITED (mis. `NAVIGATED`/`INCONCLUSIVE`).

Jangan sentuh `evaluate_scope_roe`/governance. Verifikasi state murni *perception + reasoning*.

---

## 5. Perluasan skema primitive (knowledge pack)

Tambah field opsional pada primitive (lihat `knowledge_packs/owasp_juice_shop.py`,
primitive `csrf-change-username` saat ini `success_predicate: "challenge.csrfChallenge.solved==true"`):

```python
"verification": "state",                     # aktifkan jalur C6-C7
"state_attributes": ["username"],            # atribut yang diharapkan berubah oleh CSRF
"state_scope": "session_principal",          # observasi di-scope ke principal/sesi korban
# success_predicate & challenge_key DIPERTAHANKAN sebagai korroborator LAB, bukan satu-satunya oracle
```

Target CSRF Juice Shop (Challenge 100 / `csrfChallenge`): POST `/profile` lintas-origin
mengubah `username` → `state_attributes=["username"]`. Konfirmasi lewat perubahan state,
bukan lewat flag scoreboard.

---

## 6. Evidence & integritas
- Setiap snapshot disegel: `{"domain":"APTS_CSRF_STATE_SNAPSHOT_V1","state":S,"sha256":sha256_hex(...)}`.
- `diff` + `verdict` disegel domain `APTS_CSRF_STATE_VERIFICATION_V1`.
- Sertakan `state_evidence_ref` ke dalam record run agar tercakup `verify_ae_run(run)`.
- Pakai `boundary_contract.sha256_hex` / `canonical_json`. Append-only, replay deterministik.

---

## 7. Acceptance criteria (pola Stage 7.x-state)
- **A1.** `csrf-change-username` → EXPLOITED via `STATE_CHANGE_CONFIRMED` pada `username`,
  dengan `ChallengeOracle` **dinonaktifkan** (bukti target-agnostic).
- **A2.** Snapshot gagal / konteks cross-origin tak terbukti → `INCONCLUSIVE`, outcome bukan EXPLOITED.
- **A3.** Perubahan atribut sama oleh aksi same-origin terotorisasi (baseline) TIDAK memicu EXPLOITED
  (ter-mask oleh `ΔS_b`).
- **A4.** Determinisme: observasi terekam yang sama → verdict & segel identik saat replay.
- **A5.** Regresi: Stage 6 read-only + CAE lama tetap hijau; perubahan murni aditif.

---

## 8. Di luar lingkup dokumen ini
- **RL test-selection (Novelty 1)** — fase 2; offline-trained + frozen policy, di lapis prioritisasi.
- **Retrain GBDT/classifier** — pakai label dari `cae_learning.py` (Stage 7.9) yang sudah dua-kelas.

## 9. Urutan implementasi yang disarankan
1. `state_observer.py` (+ projection Juice Shop) dan unit test `φ`/snapshot (mock fetcher).
2. `impact_verification.py` (`diff`/`compare`) + unit test termasuk kasus `INCONCLUSIVE`.
3. Perluas skema primitive + `csrf-change-username` `verification: "state"`.
4. Wiring `run_chain` + `_step` (A1–A3), lalu segel evidence (A4) dan regresi (A5).
