# Stage 7 — Controlled Active Exploitation (CAE): Validasi Konsolidasi

**Subsistem:** `mission_orchestrator/pentest_subsystem` · **Target uji:** OWASP Juice Shop (loopback)
**Sifat:** aditif (sidecar) · fail-closed · loopback-only · RoE-gated · integrity-sealed · deterministic replay
**Status regresi:** 18 suite / ~117 test — **semua hijau** · 15 probe containment — **semua lulus**

> **Pembaruan (Fase generalisasi, 2026-11-21):** Stage 7 kini dipisah jadi **engine BAC umum** + **knowledge-pack
> per-target (data)**. Solve ditentukan **oracle bukti** (`cae_success_oracle`) dari respons nyata — bukan
> scoreboard. Scoreboard Juice turun pangkat jadi **corroborator lab** (validasi silang, bukan mekanisme).
> Sistem kini **menyintesis hipotesis BAC dari enumerasi** lalu menggerakkan gateway tanpa challenge key.
> Rinciannya di `RENCANA_STAGE7_GENERALISASI_BAC.md`. **Terbukti live:** easterEgg + basketAccess
> EXPLOITED/CONFIRMED via oracle, scoreboard cross-validation `agreed=True`.

---

## 1. Ringkasan

Pipeline APTS dasar (recon → hypothesis → STRIPS planning) **secara desain tidak mengeksploitasi**: ia
berhenti di hipotesis & rencana. Stage 7 menambah **lapisan eksekusi eksploitasi terkendali (CAE)**
sebagai modul aditif — tanpa mengubah pipeline dasar — sehingga APTS dapat *membuktikan* hipotesis
Broken Access Control pada OWASP Juice Shop, di bawah pagar Rules of Engagement yang ketat.

Prinsip pagar: hanya `127.0.0.1`/loopback; master-switch RoE wajib; kelas aksi eksplisit
(`ACTIVE_EXPLOITATION` / `STATE_MUTATION` / `DESTRUCTIVE`); persetujuan single-use time-bound untuk
mutasi/destruktif (destruktif = 2 persetujuan); auto-rollback; kill-switch; blast-radius cap; setiap
artefak di-seal SHA-256 (`UTF8_SORTED_JSON_V1`), append-only, dapat di-replay deterministik.

## 2. Modul (8, aditif, 1960 LOC)

| Modul | Stage | Peran |
|---|---|---|
| `active_exploit_contract.py` | 7.1 | Kontrak kelas aksi + kelayakan RoE (AE-ENV/LOOPBACK/MASTER/CLASS/METHOD/DESTRUCTIVE/CREDENTIAL/BLAST) |
| `exploit_primitive_library.py` | 7.2 | Pustaka primitive + chaining STRIPS + fakta sesi |
| `session_broker.py` | 7.3 | Provisioning kredensial lab, auth (incl. SQLi lab-only), capture token/bid |
| `active_exploitation_execution.py` | 7.4/4b/4c/6/7 | Gateway 3-kelas: guard→review→actuate→oracle→rollback; transport SPA |
| `approval_broker.py` | 7.5 | Kartu persetujuan single-use, time-bound, action-bound; kill-switch/emergency-stop |
| `browser_transport.py` | 7.4b | Transport SPA (Selenium): inject JWT ke localStorage, navigasi route SPA |
| `cae_containment.py` | 7.8 | 13 probe containment (APTS-AL-028) + harness eksternal |
| `cae_learning.py` | 7.9 | Learning loop: label CONFIRMED/REFUTED → posterior Beta + classifier terlatih |

## 2b. Engine BAC umum vs knowledge-pack (generalisasi)

Stage 7 bukan lagi solver Juice: *mesin* dipisah dari *pengetahuan target*.

| Lapisan | Modul | Peran |
|---|---|---|
| Oracle bukti | `cae_success_oracle.py` | Verdict CONFIRMED/REFUTED/INDETERMINATE dari respons (grammar tertutup, no `eval`, fail-closed). Menggantikan ketergantungan scoreboard. |
| Template umum | `bac_primitive_templates.py` | 8 template BAC target-agnostic + `instantiate()` → primitive tanpa challenge_key. |
| Knowledge-pack | `knowledge_packs/owasp_juice_shop.py` | Katalog Juice (14 primitive) + surface import + peta korroborasi — **data**, bukan engine. |
| Sintesis | `bac_hypothesis_synthesis.py` | Hipotesis BAC dari `endpoint_discoveries` enumerasi (IDOR/forced-browse/SSRF/CSRF). |
| Jembatan | `cae_service_runner.execute_bac_generic` | Hipotesis→primitive→gateway+oracle, tanpa scoreboard; + `cross_validate_with_scoreboard`, profil `WPT_BAC_CONTROLLED_V1`, identity-probe. |
| Runner live | `run_bac_generic_live.py` | Pipeline penuh surface→sintesis→plan→gateway→korroborasi (default read-active-safe). |

Jalur challenge lama (`primitives_for_challenge`, `execute_bac_http`, scoreboard oracle) tetap utuh untuk
kompatibilitas & corroborasi lab. Containment menambah **P14** (oracle generik tanpa bukti ≠ EXPLOITED) &
**P15** (primitive generik, target non-loopback → BLOCKED).

## 3. Cakupan tantangan Broken Access Control (live di instance pengguna)

| Tantangan | Vektor | Kelas | Status live |
|---|---|---|---|
| basketAccessChallenge | IDOR GET basket | ACTIVE | **SOLVED (HTTP)** |
| basketManipulateChallenge | HTTP Parameter Pollution (duplikat `BasketId`, milik-sendiri dulu) | MUTATION | **SOLVED (HTTP)** |
| changeProductChallenge | PUT product (tamper) | MUTATION | **SOLVED (HTTP)** |
| easterEggLevelOneChallenge | Forced-browse poison null-byte `/ftp/eastere.gg%2500.md` | ACTIVE | **SOLVED (HTTP)** |
| forgedFeedbackChallenge | Parameter tampering (UserId/captcha-leak) | MUTATION | **SOLVED (HTTP)** |
| forgedReviewChallenge | PATCH review (IDOR write) | MUTATION | **SOLVED (HTTP)** |
| ssrfChallenge | Profil image URL → endpoint internal `/solve`, auth via cookie | MUTATION | **SOLVED (HTTP/cookie)** |
| adminSectionChallenge | Forced-browse route SPA `/administration` | ACTIVE | **SOLVED (SPA browser transport)** |
| web3SandboxChallenge | Forced-browse route SPA sandbox | ACTIVE | **SOLVED (SPA browser transport)** |
| loginAdminChallenge *(enabler)* | SQLi `' OR 1=1--` | ACTIVE | **Verified (SQLi, lab-only)** |
| csrfChallenge | CSRF ubah username (cross-origin htmledit) | MUTATION | Primitive siap — belum diverifikasi live |
| feedbackChallenge | Hapus feedback 5★ | DESTRUCTIVE | Tercakup (kelas destruktif, 2-persetujuan) |

**Ringkas:** 9 tantangan terverifikasi SOLVED live (7 HTTP/cookie + 2 SPA) + 1 enabler SQLi terverifikasi;
csrf siap-primitive; feedback destruktif tercakup di kelas 2-persetujuan.

## 4. Governance & containment

- **Kelas aksi** di-gate: kelas yang tidak di-enable → `DEFERRED` (bukan dieksekusi).
- **Persetujuan**: mutasi butuh token single-use (habis sekali pakai — diperbaiki dari celah reuse di 7.5);
  destruktif butuh 2 persetujuan; kill-switch menghentikan rantai.
- **Containment (APTS-AL-028)**: 13 probe CAE-P01..P13 — positive-control s.d. non-loopback-block,
  master-switch-off, approval-reuse, blast-radius — **semua lulus**; harness eksternal independen.
- **Integritas**: setiap run di-seal SHA-256 canonical; `verify_ae_run` memverifikasi rantai.

## 5. Learning loop (7.9) — menutup gap "neuro-symbolic not justified"

Pipeline lama tak bisa melatih classifier P3 (semua hasil CONFIRMED → satu kelas → `fit()` menolak).
CAE kini menghasilkan label **REFUTED** nyata (`ACTUATED`/`FAILED`), memberi dua kelas:

```
Sebelum (satu kelas): PRIOR_UNTRAINED  | NEURO_SYMBOLIC_NOT_JUSTIFIED_PRIOR_MODEL (SINGLE_CLASS)
Sesudah (dua kelas) : TRAINED          | NEURO_SYMBOLIC_JUSTIFIED_TRAINED  (acc 0.70, 5 CONFIRMED/5 REFUTED)
Reliability per-arm  : idor-read-basket 0.667  vs  idor-write-basket 0.25  (posterior Beta-Bernoulli)
```

Output bersifat **advisory** — tidak pernah melonggarkan RoE.

## 6. Reprodusibilitas

- Regresi hermetik: `for fp in tests/test_stage7*.py; do python3 "$fp"; done` (fake transport, tanpa jaringan).
- Verifikasi live: `mission_orchestrator/run_cae_live.py` (host runner; `--browser` untuk SPA via Selenium),
  wrapper `START_STAGE7_CAE_LIVE.ps1`. Reset Juice Shop sebelum run.
- Gap hermetik-vs-live: VM uji tak mencapai `localhost:3000` pengguna; karena itu test memakai fake,
  solve nyata diverifikasi lewat browser pada instance pengguna.

## 7. Batas & sisa

- `csrfChallenge`: primitive siap; verifikasi live cross-origin htmledit belum dijalankan.
- `juiceShopAIChallenge`/AI-debugging: perlu dependensi LLM — di luar lingkup CAE saat ini.
- Stage 7.9 classifier: ambang sampel diturunkan (8) untuk demonstrasi; ambang produksi P3 = 30.
