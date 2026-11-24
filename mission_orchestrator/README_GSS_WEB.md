# aptsGSS Web — Governance & Safety Console

Rilis implementasi Human Layer/Human Interaction 2026-10-07. Berbasis snapshot
`aptsGSS(20261007-042143).zip` dan `APTS_Control_Center(10).zip`. UI operasional memakai data API nyata; tidak ada
mode demo atau respons palsu pada aplikasi yang dikirimkan.

## Halaman dan fungsi

## Modul eksplisit Human Layer dan Human Interaction

Rilis ini mempertahankan implementasi governance yang sudah authoritative, lalu
menambahkan dua kontrak first-class tanpa membuat sumber kewenangan baru:

- **Human Layer (`HUMAN-LAYER`)** — external authority/oversight boundary untuk
  Define Goals, Define Scope & RoE, Approve High-Risk Actions, Review & Oversight,
  dan Emergency Control. Modul ini bukan agent dan tidak memiliki target execution authority.
- **Human Interaction (`HUMAN-INTERACTION`)** — authenticated human-system workflow
  untuk mission authoring, scope/RoE management, human approval, oversight, dan emergency.
  Identitas operator dan capability tetap diverifikasi di server.

Mission authoring pada UI mengirim canonical mission intent ke Global Mission Orchestrator
(port default 8780) melalui BFF loopback yang hanya membentuk path yang diizinkan. Membuat
mission tidak berarti memberi otorisasi execution. Scope, policy, approval, emergency, dan
revalidation tetap authoritative pada aptsGSS; controlled execution tetap berada di execution
gateway. Tidak ada endpoint arbitrary proxy dan tidak ada tool/pentest execution dari UI.

- Human Layer: definisi mission objective/success criteria, authority boundary, invariant,
  daftar mission yang dibuat manusia, dan shortcut ke Scope/RoE, Approval, serta Emergency.
- Human Interaction: antrean gabungan approval GSS dan mission attention, review mission,
  workflow boundary, audit/oversight, dan emergency control.
- Governance Overview: health/readiness operasional, MariaDB, CTI Event API, worker outbox,
  antrean approval yang belum kedaluwarsa, scope aktif/akan kedaluwarsa, event gagal.
- Human Approvals: antrean berfilter dan pagination, detail request/risiko/scope/bukti,
  APPROVE/DENY dengan alasan, peran server, expiry dan single-use dari engine asli.
  UI menampilkan respons keputusan final GSS; persetujuan tidak otomatis ALLOW.
- Scope & RoE: daftar, detail, formulir target/sumber/tindakan, metadata dan constraints,
  pembuatan, revisi dengan ID/hash baru dan versi meningkat, pencabutan scope.
  Revisi mencabut scope lama dalam transaksi yang sama. Perbarui binding Mission
  ke ID/hash/versi baru sebelum melanjutkan; UI tidak memalsukan binding otomatis.
- Policy Decisions: daftar ALLOW/DENY/REVIEW, alasan/batas/masa berlaku/hash dan revoke.
- Policies & Compliance: detail policy, inventaris rules dan obligations;
  administrasi nama/deskripsi/status/masa berlaku dengan kenaikan versi,
  audit before/after dan event POLICY_CHANGED. Engine lama tidak mengeksekusi
  gov_policy_rules sebagai generic rule engine. Izin tindakan diedit melalui
  Scope & RoE; tidak disediakan editor aturan yang memberi kesan palsu.
- Emergency Control: activate/release, alasan, konfirmasi, konflik versi, riwayat.
  Keadaan GSS bukan bukti seluruh worker sudah berhenti. Pelepasan tidak otomatis
  melanjutkan misi. Baca status pelaksana melalui Control Center untuk memverifikasi.
- Audit & Mission Trace: pencarian/filter/pagination, detail hash/payload dan
  korelasi per mission ID. Ekspor JSON hanya halaman yang sedang ditampilkan.
- Integrations & Outbox: statistik, kegagalan terbaru, retry sesuai backoff,
  inventaris interfaces/ports dan arsitektur. Tombol retry memproses satu event
  yang jatuh tempo; worker melanjutkan antrean. Retry merupakan tindakan pengiriman
  event; pada timeout hasilnya belum pasti dan harus diperiksa sebelum diulang.

## Arsitektur dan akses

`Browser -> gss_web (127.0.0.1:8802) -> GSS API (127.0.0.1:8770) -> MariaDB`

`                              \-> Mission API (127.0.0.1:8780)`
Web merupakan proses terpisah; tetap dapat menyajikan halaman login ketika API
berhenti. Status web aktif bukan status API/DB sehat. Web tidak menulis langsung
ke database dan tidak menjalankan alat pentest.

Registry HUMAN yang telah digunakan approval dipakai kembali. Token hanya
disimpan sebagai SHA-256 pada registry dan sementara dalam sesi memori server
web; browser menerima cookie HttpOnly/SameSite=Strict selama 30 menit. Tidak ada
token dalam localStorage atau bundle JavaScript. Session restart mengharuskan
login ulang. Perubahan enabled/roles di registry berlaku pada request berikutnya.

| Peran | Hak |
|---|---|
| VIEWER / AUDITOR | Membaca dan ekspor halaman |
| OPERATOR | Membaca, membuat mission intent, activate emergency, retry outbox |
| SECURITY_APPROVER | Membaca dan keputusan approval sesuai required role |
| GOVERNANCE_ADMIN | Membaca, membuat mission intent, scope, siklus policy, revoke, activate/release emergency, retry |

Admin tidak otomatis mendapat kewenangan approval; tambahkan SECURITY_APPROVER
secara eksplisit hanya bila orang tersebut memang berwenang.

Endpoint console dan write admin memeriksa principal/peran pada GSS, bukan hanya
menyembunyikan tombol. Endpoint approval tetap menggunakan transaksi single-use
asli. Identitas actor untuk emergency/revoke dan pembuat scope ditentukan server.
Pencarian terparameterisasi, tabel/rute di-allowlist, data UI di-escape, session
memakai CSRF dan host/origin checks. Web selalu bind loopback, tanpa remote mode.

Batas kompatibilitas: endpoint machine `scope-contracts` (POST),
`authorization/evaluate` dan `authorization/revalidate` tetap menerima caller
non-browser dari loopback agar Mission/CTI yang ada tidak rusak. Middleware
menolak caller remote serta Origin/Sec-Fetch-Site untuk endpoint tersebut.
Ini adalah batas kepercayaan proses lokal, bukan autentikasi machine-to-machine
penuh. Jangan mengekspos API GSS, web, atau Control Center ke LAN/Internet melalui
proxy. Distribusi remote membutuhkan desain identitas service tersendiri.
UI desktop lama tetap tersedia. Untuk emergency/retry dari desktop, set
`GOV_CONSOLE_TOKEN` pada lingkungan proses desktop menggunakan token berwenang.

## Instalasi pada Windows

1. Hentikan proses GSS dan Control Center. Backup folder D:\aptsGS dan
   D:\APTS_Control_Center serta database sesuai prosedur Bapak.
2. Ekstrak paket GSS ke D:\aptsGS (run.py dan run_web.py langsung di direktori itu).
   Pertahankan .env, registry principal, virtual environment dan konfigurasi pribadi.
   Paket tidak membawa .env/credential/database/log runtime.
3. Ekstrak paket Control Center ke folder Control Center yang digunakan.
   Pertahankan config.json lama bila root/port/interpreter sudah disesuaikan.
   Jalankan `python .\MERGE_GSS_WEB_CONFIG.py` dari folder Control Center untuk
   menambah entri gss_web tanpa mengubah konfigurasi modul yang lain. Jika entri
   sudah ada, script tidak mengubah apa pun. root gss_web kosong berarti mengikuti
   root modul gss; port default 8802. Tidak perlu mengganti interpreter modul lain.
4. Pasang dependency dan siapkan principal:

```powershell
cd D:\aptsGS
# Hanya bila .venv belum tersedia:
# py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe .\scripts\provision_console_user.py --principal anthon-admin --roles GOVERNANCE_ADMIN SECURITY_APPROVER
```

Script menampilkan path registry dan token pribadi satu kali. Simpan token secara
aman untuk login. Registry existing dipertahankan; principal existing tidak
tertindih tanpa flag --rotate. Bila memakai registry yang sudah ada, gunakan
`--registry D:/aptsGS/<lokasi-registry-existing>.json` secara eksplisit atau
pastikan GOV_APPROVAL_PRINCIPALS_FILE sudah benar di .env sebelum provisioning.
Registry menyimpan hash token; file token plaintext tidak dibuat.

Tambahkan/periksa .env (contoh path default):

```dotenv
GOV_HOST=127.0.0.1
GOV_PORT=8770
GOV_APPROVAL_PRINCIPALS_FILE=D:/aptsGS/.secrets/governance-principals.json
```

Pertahankan GOV_DB_* dan konfigurasi lainnya. Gunakan path hasil provisioning
bila berbeda. Restart GSS setelah mengubah path konfigurasi.

5. Jalankan melalui APTS Control Center: Mulai **aptsGS**, kemudian Mulai
   **aptsGSS Web**, lalu **Buka Web**. Alternatif dua terminal:

```powershell
# Terminal 1
cd D:\aptsGS
.\.venv\Scripts\python.exe .\run.py

# Terminal 2
cd D:\aptsGS
.\.venv\Scripts\python.exe .\run_web.py --port 8802 --api-port 8770 --mission-port 8780
```

Buka http://127.0.0.1:8802 dan gunakan token principal yang baru dibuat.
Buka menu **Human Layer** untuk membuat canonical mission intent dan menu **Human Interaction**
untuk menangani approval/attention. Data kosong ditampilkan sebagai data kosong; tidak ada
seed misi/demo otomatis. Tidak diperlukan migrasi skema baru karena modul baru mengomposisikan
tabel dan authority yang sudah ada. Jangan impor ulang dump SQL yang berisi
DROP TABLE ke database berjalan.

## Pengujian lokal

```powershell
cd D:\aptsGS
.\.venv\Scripts\python.exe .\scripts\web_console_acceptance.py
```

Script memeriksa digest rilis GSS_WEB_MANIFEST.json dan menjalankan regresi GSS
serta security/BFF tests. Test lintas subsistem Stage 6.9 bukan bagian acceptance
lokal ini. Test MariaDB eksplisit tidak dijalankan kecuali diminta.

Pengujian database memakai schema sementara baru berprefix
`gss_approval_test_`, tidak memakai database operasi. Siapkan file JSON pribadi:

```json
{"host":"127.0.0.1","port":3306,"user":"test_user","password":"ISI_SECARA_LOKAL","database":"gss_approval_test_web"}
```

Account pengujian harus memiliki hak membuat/menghapus database sementara.
Lalu:

```powershell
$env:GSS_TEST_DB_CONFIG = 'D:\aptsGS\.secrets\isolated-test-db.json'
.\.venv\Scripts\python.exe .\scripts\web_console_acceptance.py --database
```

Jika GSS_TEST_DB_CONFIG tidak diset, dua test console MariaDB ditandai skipped.
Jangan mengisi nama database operasi sebagai prefix konfigurasi pengujian.

## Bukti dan batas verifikasi

Lihat evidence/gss_web/RELEASE_VALIDATION.md. Hasil historis Stage 6.4/6.9 maupun
GSS_SOURCE_MANIFEST.json lama tidak membuktikan rilis baru. Manifest lama tidak
diubah untuk membuat gate lama tampak lolos. Gate yang mengunci hash baseline lama
akan mendeteksi perubahan source; perlu pembaruan baseline APTS yang ditinjau dan
regresi terintegrasi terpisah. GSS_WEB_MANIFEST.json dan acceptance web hanya
membuktikan cakupan rilis web yang dinyatakan, bukan full APTS Stage 6.10.

Tidak ada deployment pada komputer Bapak atau eksekusi target dari lingkungan ini.
