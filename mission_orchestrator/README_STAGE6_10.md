# Stage 6.10 — Full APTS End-to-End Acceptance & Regression Gate

Stage 6.10 menambahkan gate eksternal untuk memeriksa seluruh corpus Stage 1–6, satu skenario native yang terhubung, dan rekonstruksi bukti lintas komponen. Deklarasi kontrak atau `/health` yang sehat tidak menghasilkan PASS. Endpoint runtime selalu menyatakan `DECLARED_ONLY`.

Baseline patch adalah `Mission(20261004-041322).zip`, dengan sumber pasangan `aptsGSS(20261004-041235).zip` dan `Vulndesk(20261004-041313).zip`. Ekstrak isi patch ke folder Mission yang sama. Panduan lengkap tersedia dalam `INSTALL_STAGE6_10.txt`.

## Menjalankan acceptance di Windows

Pasang dependensi backend dari folder Mission:

```powershell
python -m pip install -r requirements-stage6_10.txt
```

Jalankan GSS dan API CTI sesuai konfigurasi yang sudah digunakan. Setelah menghentikan proses Mission, Pentest, dan Execution sebelumnya, jalankan masing-masing skrip ini dalam terminal terpisah:

```powershell
.\START_STAGE6_10_MISSION.ps1
.\START_STAGE6_10_PENTEST.ps1
.\START_STAGE6_10_EXECUTION.ps1
```

Jalankan gate dalam terminal keempat:

```powershell
.\STAGE6_10_ACCEPTANCE.ps1 -GssRoot D:\aptsGSS -VulndeskRoot D:\Vulndesk
```

Sesuaikan direktori sumber dan parameter URL bila konfigurasi berbeda. Parameter `-RegressionWorkers` menerima 1–8; nilai awal 4. Skrip menggunakan interpreter `python` yang aktif. PowerShell harus mengizinkan skrip proyek dijalankan; pengaturan untuk satu proses dijelaskan dalam panduan instalasi.

Preflight memeriksa lima layanan, versi kontrak yang tepat, tingkat migrasi, runtime owner, completion fence, sumber database yang sama, serta URL Governance yang dipakai Mission dan Execution. Stage 6 menggunakan sumber Mission SQLite; preflight menolak Mission dengan driver MySQL yang tidak dibaca oleh sumber Execution tersebut. Jangan mengganti database produksi untuk membuat gate lulus.

Untuk build tanpa proses layanan yang berjalan:

```powershell
.\STAGE6_10_ACCEPTANCE.ps1 -GssRoot D:\aptsGSS -VulndeskRoot D:\Vulndesk -BuildOnly
```

Mode build menghasilkan `STAGE 6.10 BUILD ACCEPTANCE: PASS`. Mode deployment menghasilkan `STAGE 6.10 DEPLOYMENT ACCEPTANCE: PASS` setelah preflight sebelum dan sesudah pengujian berhasil. Keduanya menjalankan regresi dan target loopback dalam lingkungan terisolasi. Mode deployment membuktikan kesiapan layanan yang diperiksa; eksekusi terhadap misi atau target pengguna tetap belum dibuktikan.

## Jalur end-to-end yang diperiksa

Skenario dimulai dari objective operator dalam Mission native. Scope/RoE dan binding Governance direkam, lalu kode asli `PipAssemblyValidationService` VulnDesk membangun PIP dengan sepuluh quality gate. Identitas PIP yang telah dipesan oleh envelope Mission dipublikasikan menggunakan fixture allocator; hashing, sanitasi, validasi, dan pernyataan SQL publikasi tetap memakai kode CTI asli.

PIP diproyeksikan ke kontrak Stage 4.2 dengan identitas, revisi, hash sumber CTI, dan intelligence yang sama. PentestTask mengikat planned task asli dari plan Mission, kemudian workflow menjalankan keenam specialist Stage 5.2–5.7. Hypothesis Agent menerima knowledge dari PIP CTI tersebut. Semua intelligence awal dan repository authority pada skenario ini adalah fixture yang dinyatakan secara eksplisit.

Action proposal masuk ke Execution Stage 6.10. Client asli memanggil kode Governance GSS asli melalui HTTP loopback untuk admission dan pemeriksaan tepat sebelum target I/O. Worker native melakukan satu observasi HTTP HEAD terhadap server loopback. Bukti dan byte tersimpan masuk ke VEP, post-action closure, feedback CTI, serta revisi knowledge di database feedback khusus.

Mission membaca revisi tersebut melalui consumer read-only, lalu menjalankan klasifikasi, eligibility, snapshot, candidate, validation, dan governed commit yang sudah ada. Successor plan mencapai versi 2. Rekonstruksi forensic diperiksa ulang setelah restart Mission; replay intake dan execution tidak menambah target I/O. Misi tetap `RUNNING`, hasil hypothesis `INCONCLUSIVE`, dan validasi lanjutan tetap diperlukan.

Skenario negatif memeriksa DENY, REVIEW, timeout, emergency, revocation, abort Mission, perubahan scope, cancel, dan kill. Semua pemeriksaan mempertahankan batas authority Stage 6 sebelumnya.

## Syarat PASS dan bukti

Inventory `acceptance/stage6_10_inventory.json` mengunci setiap node pytest dari ketiga sumber. Corpus GSS mencakup 58 tes native GSS dan 72 salinan tes Stage 6.9; seluruhnya dijalankan. Bootstrap import hanya menyediakan dependensi Mission yang lengkap untuk namespace parsial dalam arsip GSS.

Gate menjalankan kompilasi sumber, probe sandbox native, seluruh batch pytest, serta audit trajectory yang terhubung. PASS membutuhkan cakupan JUnit yang tepat, exit code nol, tanpa failure/error/skip, semua 14 gate roadmap terpenuhi, serta snapshot sumber yang sama sebelum dan sesudah pengujian. Direktori bukti harus baru; hasil lama tidak digunakan kembali atau ditimpa.

| Gate roadmap | Bukti utama |
|---|---|
| Authorization integrity | Mission authorization, GSS revalidation, Execution admission dan boundary |
| Mission integrity | Envelope, lifecycle, version/concurrency, binding database |
| Scope/RoE preservation | Scope canonical, enforce RoE, drift rejection |
| Agent identity | Registry dan enam specialist, sumber proposal |
| Task lineage | Planned task → PentestTask → request → VEP/knowledge |
| Execution isolation | Adapter tetap, sandbox native, runtime owner |
| Evidence integrity | Hash, manifest, provenance, byte evidence yang disimpan |
| VEP integrity | Snapshot execution dan source, export, tamper rejection |
| Restart/recovery | Corpus recovery dan rekonstruksi setelah restart |
| Replay determinism | Idempotency, lineage, replay tanpa I/O tambahan |
| Closed-loop feedback | CTI native PIP, revisi knowledge, governed successor plan |
| Kill/abort behavior | Cancel/kill, abort Mission, revocation dan completion fence |
| Forensic reconstruction | Export Mission/knowledge/PIP dan rekonstruksi causal |
| Full regression | Seluruh node canonical dari Mission, GSS, dan VulnDesk |

Setiap eksekusi menghasilkan `acceptance_result.json`, hasil probe, dan subdirektori `regression` berisi inventory, snapshot SHA-256 sumber, JUnit/log per batch, empat export trajectory, audit trajectory, serta report regresi. Verifier menghitung ulang cakupan, hash, sumber saat ini, dan lineage; ia tidak menerima boolean PASS begitu saja.

Contoh pemeriksaan ulang:

```powershell
python run\stage6_10_regression.py --gss-root D:\aptsGSS --vulndesk-root D:\Vulndesk --verify-only --output <direktori-bukti>\regression
```

Perubahan sumber membatalkan bukti sebelumnya dan memerlukan eksekusi baru. Hash internal membuktikan konsistensi bukti, bukan tanda tangan independen dari target atau authority. Endpoint runtime menolak POST yang mengirim PASS atau evidence buatan caller.

## Perubahan dan batas kompatibilitas

Runtime 6.10 mewarisi runtime 6.9 dan completion fence 6.8. Tingkat migrasi tetap Mission 53 / Pentest 16 / Execution 9 / CTI feedback 1. Patch tidak memuat database, `.env`, credential, perubahan sumber GSS/VulnDesk, atau impor SQL dump.

Satu perbaikan kompatibilitas ada pada evaluasi deterministic replan: `cti_feedback_requirements` yang berasal dari snapshot terpercaya kini disertakan dalam perbandingan payload candidate. Sebelumnya candidate CTI yang sah ditolak karena field tersebut tidak masuk sisi observed. Candidate dengan requirement hilang, hash berubah, flag review berubah, atau context snapshot yang berbeda tetap ditolak.

Runtime tidak mengesahkan acceptance sendiri, tidak menciptakan authority baru, tidak menulis core database VulnDesk, tidak menaikkan observasi menjadi confirmed vulnerability, dan tidak menyatakan misi selesai. Probe dan tes Linux membuktikan backend `SECCOMP_RLIMIT`; Windows harus menjalankan gate lokal untuk memeriksa backend `JOB_OBJECT_FIXED_WORKER` dan deployment setempat.

Hasil build yang disertakan dalam paket dijelaskan dalam `REGRESSION_EVIDENCE_STAGE6_10.txt`.
