# VulnDesk — Harmonized Actionable–Adaptive CTI Subsystem

Baseline arsitektur: **Agustus 2026**  
Target database: **MariaDB 10.4+ / MySQL-compatible InnoDB**  
Implementasi: **non-LLM-driven hierarchical heterogeneous Agent–Service architecture**.

## 1. Tujuan perubahan

Perubahan ini menyelaraskan VulnDesk dengan rancangan terpadu CTI Subsystem APTS dengan pemisahan tegas antara **Component Type** (Agent, Service, Data Artifact) dan **Computational/Decision Mechanism**. Kode mempertahankan batas kewenangan berikut:

- reasoning tidak berarti authority;
- recommendation tidak berarti authorization;
- vulnerability applicability tidak berarti exploitability;
- feasible attack path tidak berarti executable attack path;
- PIP validation objective bukan execution command;
- PIP Assembly & Validation tidak boleh menciptakan fakta CTI baru;
- provenance, temporal validity, evidence reference, dan version stamp dipertahankan pada state/artifact yang relevan.

## 2. Registry modul yang diimplementasikan

| ID | Komponen | Type | Mechanism | Authority Boundary | Implementasi |
|---|---|---|---|---|---|
| CTI-A01 | CTI Subsystem Orchestrator | Agent | Hybrid Reactive–Deliberative | Task proposal/coordination only | `cti_services/cti_subsystem_orchestrator.py` |
| CTI-A02 | CTI Acquisition & Freshness | Agent | RAO | Authorized source acquisition only | `cti_services/acquisition_freshness_agent.py` |
| CTI-S01 | Normalization & Provenance | Service | Neuro-Symbolic / Statistical-Symbolic | No mission agenda / no target actuation | `cti_services/normalization_provenance_service.py` |
| CTI-S02 | Asset Profiling & CPE Resolution | Service | Layered Neuro-Symbolic | Enrichment requirement only | `cti_services/asset_profiling_cpe_resolution_service.py` |
| CTI-S03 | Vulnerability Correlation | Service | Graph + Layered Neuro-Symbolic | Applicability only | `cti_services/vulnerability_correlation_service.py` |
| CTI-S04 | ATT&CK Mapping | Service | Neuro-Symbolic / Ontology | Mapping only | `cti_services/attack_mapping_service.py` |
| CTI-A03 | Attack-Path Reasoning | Optional Agent | Layered Neuro-Symbolic + Graph Planning | Proposed intelligence paths only | `cti_services/attack_path_reasoning_agent.py` |
| CTI-S05 | Threat Context | Service | Layered Neuro-Symbolic | Context synthesis only | `cti_services/threat_context_service.py` |
| CTI-A04 | Risk Prioritization | Agent | BDI | Priority recommendation only | `cti_services/risk_prioritization_agent.py` |
| CTI-S06 | PIP Assembly & Validation | Service | Deterministic Validation | Packaging/validation only | `cti_services/pip_assembly_validation_service.py` |
| CTI-D01 | Pentest Intelligence Package | Data Artifact | Canonical immutable data | No authority | persisted by CTI-S06 |

`CTI-INF01 Pentest Enrichment API Adapter` adalah **infrastructure service**, bukan modul domain CTI.

> Catatan metodologis: label Neuro-Symbolic, graph reasoning, BDI, dan RAO pada baseline kode ini diimplementasikan sebagai kontrak, state model, rule/heuristic/statistical scoring, graph reasoning, serta hard symbolic constraints yang deterministik dan dapat diuji. Kode ini **tidak mengklaim sudah memuat neural model terlatih**. Model eksperimental dapat ditambahkan di balik kontrak modul tanpa mengubah authority boundary.

## 3. Runtime dan dependency DAG

CTI-A01 menjalankan workflow sebagai **versioned dependency DAG**, bukan pipeline linear murni. Setiap task domain dibuat melalui:

`Deliberative Proposal -> Dependency/Policy Guard -> Committed Task Contract -> Dispatch -> Result/Audit`

State penting membawa `state_version`, `plan_version`, dan `policy_version`. Reactive proposal tersedia untuk event seperti source outage, rate limiting, freshness breach, parser failure, timeout, priority shift, policy change, dan authorization revocation.

Local pentest observation tidak otomatis direlabel sebagai external CTI. CTI-S01 hanya dipanggil bila payload mempunyai `raw_cti_envelopes`.

## 4. PIP dan hard quality gates

CTI-S06 membangun CTI-D01 sebagai artifact immutable dan menghitung canonical SHA-256. PIP memiliki hard gates:

- QG-H1 Schema validity
- QG-H2 Reference integrity
- QG-H3 Mission/scope binding
- QG-H4 Integrity/hash
- QG-H5 Provenance completeness
- QG-H6 Freshness/temporal validity
- QG-H7 No secrets/credentials
- QG-H8 Contradiction control
- QG-H9 Authorization semantics
- QG-H10 Revocation/deprecation check

Readiness: `PARTIAL`, `ACTIONABLE`, `VALIDATION_READY`, atau `REJECTED`. `execution_authorized` selalu `false` pada CTI PIP.

## 5. Database migration

Migration utama:

`sql_update_cti_harmonized/01_cti_harmonized_architecture_migration.sql`

Migration bersifat **non-destructive** terhadap tabel NVD/CPE/CVE/CWE/MITRE ATT&CK dan tabel pentest lama. Ia menambahkan registry, mission/event/plan/task state, evidence/provenance, correlation/mapping/path/context, BDI state, PIP, dan append-only audit state.

Lakukan backup terlebih dahulu, kemudian jalankan dari command line yang sesuai dengan instalasi Anda, misalnya:

```bash
mysql -u <user> -p vulndesk < sql_update_cti_harmonized/01_cti_harmonized_architecture_migration.sql
```

Migration menggunakan `LONGTEXT` untuk serialized JSON agar kompatibel dengan MariaDB 10.4 dan tidak bergantung pada perilaku native JSON yang berbeda antar-versi.

## 6. API

Endpoint legacy tetap dipertahankan:

- `POST /api/pentest/enrich-scan`
- `POST /api/pentest/resolve-cpe`
- `POST /api/pentest/match-cpe`
- `POST /api/pentest/map-attack`

Endpoint harmonized:

- `GET /api/cti/components`
- `GET /api/cti/architecture`
- `GET /api/cti/pip/<pip_id>`
- `POST /api/cti/enrich-scan`
- `POST /api/cti/normalize`
- `POST /api/cti/acquisition/propose`
- `POST /api/cti/pip/build`

API adapter hanyalah transport layer. Ia tidak menjadi domain reasoner dan tidak boleh memberikan execution authorization.

## 7. UI

Menu lama **CTI Service Manager** diubah menjadi **CTI Component Manager** dan tabel registry sekarang memperlihatkan:

`ID | Key | Name | Type | Mechanism | Authority Boundary | Optional | Enabled | Status | Last Error`

Hal ini membuat perbedaan Agent/Service/Data Artifact terlihat pada aplikasi.

## 8. Compatibility

- `VulnerabilityContextService` dipertahankan sebagai facade untuk integrasi lama, tetapi workflow domain dialihkan ke `CtiSubsystemOrchestrator`.
- `ThreatActorContextService` dipertahankan sebagai alias kompatibilitas untuk `ThreatContextService`.
- `CpeCveMatchingService` tetap tersedia sebagai capability internal yang dipakai CTI-S03; registry runtime-nya menggunakan `vulnerability_correlation_service`.
- Struktur data NVD/CPE/CVE/CWE/ATT&CK yang lama tidak dihapus.

## 9. Validasi

Validasi yang sudah dijalankan pada paket ini:

```bash
python -m compileall -q cti_services cti_ui main_window.py
python -m unittest tests.test_cti_harmonized_architecture -v
```

Empat unit test harmonisasi mencakup:

1. attack path tidak pernah berubah menjadi executable authorization;
2. hard BDI/policy constraint tidak dapat dikalahkan weighted utility;
3. PIP hard gates dan redaksi secret-like fields;
4. RAO source scoring deterministik.

Live migration ke MariaDB tidak dijalankan di lingkungan pembuatan artifact ini karena driver/server database tidak tersedia. SQL migration disiapkan agar dapat dijalankan pada database VulnDesk Anda setelah backup.

## 10. Instalasi dependency

Gunakan dependency project yang sudah ada:

```bash
pip install -r requirements.txt
```

File `.env` lokal berisi konfigurasi deployment dan **tidak disertakan ulang dalam ZIP hasil harmonisasi**. Pertahankan `.env` pada instalasi Anda, atau buat ulang dari `.env.example`.
