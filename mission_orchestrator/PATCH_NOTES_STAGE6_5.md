# Stage 6.5 — Execution Runtime Control

Execution gateway Stage 6.4 sebelumnya menyimpan claim/result tanpa lifecycle yang dapat dikontrol selama I/O. Patch ini menambahkan asynchronous attempts, state machine, heartbeat server, penghentian resource, retry sebelum I/O, serta recovery tanpa redispatch.

- Execution migration 5: immutable attempts, hash-chained events, immutable cancellation/kill commands, dan guard terhadap claim tanpa runtime admission.
- Admission menyimpan claim adapter, attempt identity, dan AUTHORIZED event secara atomik. Result dan terminal event juga atomik sesudah resource ditutup.
- Broker socket dan native worker terhubung ke resource guard yang dapat dihentikan oleh operator, deadline, source/GSS revalidation, atau watchdog.
- Retry maksimum 3, manual, fresh GSS, exact latest terminal head, dan bukti tidak ada target I/O. Budget konservatif tanpa refund.
- OS owner lock; shutdown terkontrol; proses crash direcover sebagai ABORTED dengan I/O uncertain. Legacy v4 orphan tetap dikarantina.
- API, runner, schemas, Windows acceptance, dan exact-inventory regression runner ditambahkan.
- Hooks default pada Stage 6.4 tetap mempertahankan perilaku historis; kontrak predecessor tidak diubah.

Mission migration 53, Pentest migration 16, source DB, GSS, dan VulnDesk tidak dimodifikasi. Bukti ada pada `REGRESSION_EVIDENCE_STAGE6_5.txt`. Runtime lifecycle belum memublikasikan Pentest ActionResult/evidence repository/VEP; Stage 6.6 berikutnya menangani artifact/evidence capture.

Verifikasi lanjutan memakai `aptsGS(4).zip`: 58 tes GSS, 22 skenario source compatibility melalui route FastAPI/GovernanceService yang sebenarnya, dan 70 tes runtime ulang lulus. Tidak ada perubahan tambahan pada kode runtime atau GSS. Paket menambahkan proof yang dapat diulang, log/JUnit, serta snapshot sumber. Suite tambahan terpisah dari full canonical regression 2539. Repository GSS terisolasi; production MySQL, pengiriman outbox aktif, dan host Windows belum diuji.

Hotfix acceptance Windows: tes timeout setelah I/O serta tes DNS timeout kini menunggu fase yang hendak diuji sebelum memajukan clock fixture ke deadline. Delay startup 0,45 detik mereproduksi kegagalan tes lama dan lulus pada tes yang diperbaiki. Proof terpisah memastikan timeout startup tanpa I/O tetap dapat di-retry. Runner full regression mencetak testcase dan traceback ketika gagal. Perubahan terbatas pada tes dan pelaporan regresi; layanan runtime, retry policy, batas deadline, kontrak dan migration tetap sama. Lihat `HOTFIX_STAGE6_5_TIMEOUT_RETRY.md`.
