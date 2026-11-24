# Stage 6.1 patch

- Menambahkan plane `execution_subsystem` dalam root proyek yang sama.
- Mendefinisikan seluruh sepuluh field ExecutionRequest dan canonical action envelope yang disegel SHA-256.
- Mengikat request ke persisted Stage 5.6 proposal, assignment, task/PIP binding, attack path, local eligibility, hypothesis, dan evidence basis.
- Menambahkan read-only Pentest proposal source tanpa initializer/migration pada database Pentest.
- Menambahkan execution request store migration 1 dengan idempotency, restart replay, indexed-read integrity checks, dan append-only triggers.
- Menambahkan local HTTP service port 8791, CLI, startup script, dan acceptance harness Windows.
- Menambahkan 73 tests Stage 6.1. Inventory berubah dari 2045 menjadi 2118.
- Semua kode, contract, migration, handler, dan test historis Stage 3–5 dipertahankan.
- Request selalu `AWAITING_AUTHORIZATION`; otorisasi, dispatch, tool invocation, target actuation, ActionResult, dan target evidence belum diaktifkan.

Berikutnya: **Stage 6.2 — Authoritative Execution Authorization**.
