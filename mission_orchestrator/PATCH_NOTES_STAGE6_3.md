# Stage 6.3 — Controlled Execution Gateway

Gateway admission terpusat menghubungkan immutable ExecutionRequest, fresh GSS authorization, current source checks, constraint enforcement dan atomic budget reservation.

- Additive Execution migration 3; Mission 53 dan Pentest 16 tetap read-only.
- Server-owned fresh revalidation identities; caller tidak dapat memasukkan ALLOW, cached authorization, command, target atau adapter.
- Restriction/unknown/malformed constraints fail closed; deny/review tetap dipertahankan.
- Satu admission per execution; budget Mission/Pentest/local-task dihitung dan direservasi dalam satu transaction, termasuk competing processes.
- Append-only hash-bound gateway audit, historical-only replay, restart verification dan fresh retry setelah crash.
- API/CLI baru, loopback boundary, Windows starter/acceptance dan 111 focused tests.
- Tidak ada target/tool dispatch sebelum Authorized Tool Adapters & Sandboxing Stage 6.4. Receipt bukan permit reusable.

Semua file baseline dipertahankan. Patch tidak menyertakan database. Live GSS dan Windows acceptance perlu verifikasi pada host pengguna; evidence lokal hanya memakai authority terisolasi pada tests.
