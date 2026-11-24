# Stage 2.1–2.5 — PolicyDecision ↔ TaskContract (VulnDesk-dominant)

## Scope

Patch ini mengimplementasikan binding otorisasi authoritative dari **aptsGSS/GOV-PLANE** ke **TaskContract milik VulnDesk CTI-A01**. Patch tidak memindahkan authority ke VulnDesk dan tidak membuat foreign key lintas database.

Control version setelah patch:

`hybrid-event-driven-2.1-policy-bound`

## Stage 2.1 — Ownership dan invariant

- `PolicyDecision` tetap dimiliki aptsGSS/GOV-PLANE.
- `TaskContract` tetap dimiliki VulnDesk/CTI-A01.
- Local policy/dependency/quality guard hanya menentukan workflow admissibility dan dapat mempersempit keputusan; local guard tidak boleh menciptakan external authority.
- Task internal menggunakan `authorization_mode=NOT_REQUIRED_INTERNAL`.
- CTI source acquisition menggunakan `authorization_mode=REQUIRED`.

Implementasi utama: `cti_services/contracts.py`.

## Stage 2.2 — Schema binding

Migration baru:

`sql_update_cti_harmonized/03_policydecision_taskcontract_binding.sql`

Migration menambahkan binding fields ke `cti_task_contracts`, antara lain:

- `authorization_mode`
- `authorization_authority`
- `authorization_authority_component`
- `policy_decision_id`
- `authorization_request_id`
- `policy_decision_hash`
- `authorization_decision`
- `authorization_status`
- `authorization_valid_from` / `authorization_valid_until`
- `scope_contract_id` / `scope_version`
- `policy_set_id`
- `approval_request_id`
- action/resource dimensions dari authorization request
- reason codes dan governance constraints
- `authorization_bound_at`

Tidak ada cross-database FK ke database aptsGSS.

## Stage 2.3 — First-class contracts

`cti_services/contracts.py` menambahkan:

- `PolicyDecisionBinding`
- `TaskContract`
- `ContractValidationError`
- canonical `decision_hash` verification compatible dengan `aptsGSS.app.utils.sha256_json`

`TaskContract.validate()` menolak commit jika:

- local guard bukan `ALLOW`;
- `authorization_mode=REQUIRED` tetapi tidak ada PolicyDecisionBinding;
- binding bukan authoritative `aptsGSS/GOV-PLANE`;
- decision bukan `ALLOW`;
- decision tidak `ACTIVE`;
- decision masih membutuhkan human approval;
- mission/scope/action/resource tidak cocok;
- decision hash tidak valid;
- validity window belum aktif atau sudah kedaluwarsa.

## Stage 2.4 — GovernanceClient hardening

`cti_services/governance_client.py` sekarang:

- memvalidasi field wajib `PolicyDecision`;
- memvalidasi `mission_id` dan explicit `scope_contract_id`;
- melakukan canonical SHA-256 verification pada response `POST /authorization/evaluate`;
- menyimpan authorization-request dimensions sebagai transport metadata untuk task binding;
- menambahkan `GET /api/governance/decisions/{decision_id}` melalui `get_policy_decision()`;
- tetap fail-closed pada service/protocol failure.

Catatan: response GET dari persisted MariaDB row membawa original `decision_hash` dan lifecycle status. Karena SQL `DATETIME` bukan byte-identical dengan JSON timestamp yang pertama kali di-hash, GET tidak menghitung ulang hash; initial POST sudah diverifikasi, dan hash GET disiapkan untuk exact hash comparison pada Stage 2.6 pre-dispatch revalidation.

## Stage 2.5 — `_commit_task()` refactor

`CtiSubsystemOrchestrator._commit_task()` sekarang membangun dan memvalidasi `TaskContract` **sebelum** proposal diubah menjadi `COMMITTED`.

Untuk CTI-A02 source acquisition:

`RAO Proposal → aptsGSS PolicyDecision → PolicyDecisionBinding → TaskContract(COMMITTED)`

Task tidak dapat committed jika required binding gagal.

Task domain internal tetap committed dengan:

`authorization_mode=NOT_REQUIRED_INTERNAL`

sehingga workflow guard tidak disalahartikan sebagai external authorization.

## File yang berubah

- `cti_services/contracts.py` — baru
- `cti_services/governance_client.py`
- `cti_services/cti_subsystem_orchestrator.py`
- `cti_services/interface_catalog.py`
- `cti_services/architecture.py`
- `cti_services/pentest_enrichment_api_service.py`
- `cti_services/__init__.py`
- `sql_update_cti_harmonized/01_cti_harmonized_architecture_migration.sql`
- `sql_update_cti_harmonized/03_policydecision_taskcontract_binding.sql` — baru
- `tests/test_governance_client.py`
- `tests/test_cti_event_driven_runtime.py`
- `tests/test_policydecision_taskcontract_stage2.py` — baru

## Urutan deployment lokal

1. Backup database `vulndesk`.
2. Stop VulnDesk API/runtime.
3. Jalankan migration Stage 2:

   ```bat
   "C:\Program Files\MariaDB 10.11\bin\mysql.exe" -u root -p -P 3307 vulndesk < sql_update_cti_harmonized\03_policydecision_taskcontract_binding.sql
   ```

   Sesuaikan port/user jika konfigurasi lokal berbeda.

4. Replace source code dengan patch ini.
5. Pastikan aptsGSS berjalan dan endpoint berikut reachable:
   - `POST /api/governance/authorization/evaluate`
   - `GET /api/governance/decisions/{decision_id}`
6. Start VulnDesk.
7. Jalankan unit test Stage 2:

   ```bat
   python -m unittest tests.test_governance_client tests.test_policydecision_taskcontract_stage2 tests.test_cti_event_driven_runtime tests.test_stage1_closure_fixes
   ```

## Verifikasi database setelah satu source acquisition ALLOW

```sql
SELECT
    task_id,
    mission_id,
    task_type,
    status,
    authorization_mode,
    authorization_authority,
    policy_decision_id,
    authorization_request_id,
    authorization_decision,
    authorization_status,
    scope_contract_id,
    scope_version,
    governance_action_class,
    governance_resource_type,
    governance_resource_value,
    authorization_valid_until
FROM cti_task_contracts
ORDER BY id DESC
LIMIT 20;
```

Expected untuk source acquisition:

- `authorization_mode = REQUIRED`
- `authorization_authority = aptsGSS`
- `authorization_decision = ALLOW`
- `policy_decision_id` tidak NULL
- `authorization_request_id` tidak NULL
- `policy_decision_hash` 64 hex chars
- `governance_action_class = CTI_SOURCE_READ`
- `governance_resource_type = CTI_SOURCE`
- `governance_resource_value` sesuai source yang dijalankan.

## Batas patch

Patch ini berhenti pada Stage 2.5. **Pre-dispatch remote revalidation, granular revocation indexing, dan full lineage observability belum diaktifkan**; itu merupakan Stage 2.6–2.9 berikutnya.
