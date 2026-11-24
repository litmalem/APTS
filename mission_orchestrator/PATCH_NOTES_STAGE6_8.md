# Stage 6.8 — Cleanup, Rollback & Post-Action Verification

Baseline: `Mission(20261003-222408).zip` (Stage 6.7).
Control: `stage6.8-cleanup-rollback-post-action-verification`.

Hotfix 1 memperbaiki race supervisor yang terungkap pada acceptance Windows:
`test_sql_insert_failure_is_atomic_and_does_not_redispatch` menerima tambahan
panggilan authority setelah attempt terbaca terminal. Tes deterministik sebelum
perbaikan mereproduksi perubahan `(2, 1)` menjadi `(3, 1)` yang sama.

- Completion menutup admission helper authority dengan lock yang sama, lalu
  menunggu helper yang sudah masuk sebelum memublikasikan terminal, maksimum
  dua detik dan tetap tunduk pada wall deadline.
- Helper yang tertunda saat source read atau authorization lock memeriksa
  lifecycle lagi sebelum query GSS. Respons yang terlambat tidak dipakai atau
  disimpan sebagai authorization baru. Cancellation tetap interruptible;
  panggilan control-plane yang sudah dikirim dapat selesai di background.
- Dua belas tes baru memaksakan interleaving pada Stage 6.7 dan 6.8: supervisor
  tertahan, delayed probe, delayed source, authority in-flight, cancellation
  saat menunggu lock, serta timeout quiescence/deadline.
- Tes SQL failure yang dilaporkan tetap utuh. Acceptance dan runner sekarang
  mewajibkan inventory lengkap **2.793** dan menjalankan **92** focused tests.
- Health mencantumkan completion fence; acceptance menolak proses lama yang
  belum direstart meskipun source di disk sudah diganti.

- Exact SHA-bound predecessor 6.7, canonical cleanup contract, intake/report schemas.
- Resource enrollment dari objek sandbox/socket milik runtime; tidak ada caller
  cleanup path, command, PID, executable, atau fabricated receipt.
- Verifikasi exit worker, closed pipe/socket, stopped readers, released Windows Job
  handle, dan absennya direktori sandbox, dengan kompensasi lokal terbatas.
- Receipt cleanup dan revocation lease lokal disimpan atomik dan append-only pada
  Execution migration 8. Deny lease tetap berlaku setelah restart/config reset.
- Laporan enam fase terikat ke exact terminal VEP, envelope, capture, runtime head,
  receipt, dan revocation. Satu laporan immutable per attempt; replay tidak I/O.
- Read/list/verify/export memeriksa ulang sumber Execution serta retained artifact
  bytes. Audit offline mempertahankan perbedaan antara internal verification,
  local cleanup, dan blocked closure.
- Legacy attempt tanpa receipt, orphan uncertainty, preterminal receipt tanpa
  durable result, acquisition credential yang unknown, dan issuer revocation yang
  belum terbukti tidak dapat menghasilkan penutupan sukses.
- Kompatibilitas API Stage 6.1–6.7 dipertahankan. Tidak ada writeback ke Mission,
  Pentest atau CTI, pengubahan VEP, maupun penghapusan retained evidence.
- Startup, acceptance PowerShell, CLI audit, regresi lengkap, panduan instalasi
  dan contoh self-contained export disertakan.

Rollback tersedia untuk resource lokal fixed adapters. Adapter saat ini tidak
memutasi target melalui operasi yang disediakan, dan tidak mengukur state target;
laporan tidak mengklaim target restore atau issuer token revocation. Penutupan
berlaku untuk exact attempt lokal, bukan task/mission upstream.

Inventory: **2.701 baseline + 80 tes Stage 6.8 + 12 tes completion = 2.793 canonical tests**.
Lihat `REGRESSION_EVIDENCE_STAGE6_8.txt` untuk hasil final pengujian. Windows native
Job Object/PowerShell perlu diperiksa melalui acceptance pada host pengguna.
