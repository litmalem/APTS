# Perbaikan human approval GSS dan dependensi

Endpoint keputusan approval sekarang memakai identitas manusia dan role dari
registry credential yang dikelola di sisi server. Payload `approver_id` dan
`approver_role` hanya assertion opsional; nilainya harus cocok dengan identitas
terautentikasi dan role yang diwajibkan approval tersimpan.

## Pemasangan di D:\\aptsGS

1. Overlay isi arsip yang diperbarui ke `D:\aptsGS`, lalu aktifkan virtual environment GSS.
2. Instal API dengan `python -m pip install -r requirements.txt`.
   Untuk acceptance gunakan `python -m pip install -r requirements-dev.txt`.
   Untuk desktop console gunakan `python -m pip install -r requirements-gui.txt`.
3. Buat credential manusia pada mesin GSS:

```powershell
python .\scripts\provision_human_approver.py --registry D:\aptsGS-private\approval-principals.json --principal-id operator-security-01 --role SECURITY_APPROVER
```

Simpan token yang ditampilkan dalam penyimpanan credential operator. Registry
hanya menyimpan SHA-256 token. Lindungi file registry dengan ACL administrator
dan akun proses GSS; jangan masukkan file/token itu ke arsip atau source control.
Credential ini khusus manusia dan tidak diberikan kepada caller agen/service.
Bearer token yang sama dapat dipakai ulang untuk autentikasi; setiap *approval
request* hanya dapat diputuskan sekali. Mengubah `enabled` menjadi `false`
mencabut credential pada permintaan berikutnya tanpa restart.

4. Tambahkan konfigurasi berikut ke `.env` GSS atau environment proses GSS,
   kemudian restart GSS agar lokasi registry terbaca:

```text
GOV_APPROVAL_PRINCIPALS_FILE=D:/aptsGS-private/approval-principals.json
```

API GSS tetap dapat menerbitkan REVIEW jika registry belum disiapkan, tetapi
keputusan approval akan ditolak. Registry contoh kosong bukan credential aktif.

5. Jalankan acceptance baru:

```powershell
cd D:\aptsGS
.\GSS_APPROVAL_ACCEPTANCE.ps1 -GovernanceUrl http://127.0.0.1:8770
```

Gate ini memverifikasi manifest SHA-256 sumber/dependensi, import API dari
environment aktif, inventory dan seluruh tes GSS, rejection caller/role,
approval sah, anti-replay, serta perubahan sumber selama pengujian. Tes Mission
Stage 6.9 yang terbawa dalam arsip lama tetap milik paket Mission dan tidak
menjadi inventory GSS.

Untuk menguji transaksi dengan MariaDB, berikan `-DatabaseConfig` menunjuk JSON
berisi konfigurasi PyMySQL untuk **database uji terisolasi** yang namanya diawali
`gss_approval_test_`. Pengujian membuat dan menghapus schema baru dengan prefix
itu dan suffix acak. Jangan berikan
nama database operasional. Gunakan `-SourceOnly` jika hanya memeriksa sumber
tanpa health endpoint live; status source tidak membuktikan acceptance live.

Contoh konfigurasi database uji lokal (simpan file ini di luar arsip):

```json
{"host":"127.0.0.1","port":3306,"user":"gss_test_operator","password":"<credential-local>","database":"gss_approval_test_local","charset":"utf8mb4"}
```

Operator uji harus dapat membuat/menghapus schema dengan prefix tersebut.
Schema dump yang diberikan pada tugas ini tidak berisi INSERT data; fixture
uji menambahkan kebijakan dan state awal sintetis pada schema uji saja.

## Kontrak keputusan

```http
POST /api/governance/approvals/<approval_request_id>/decision
Authorization: Bearer <token-operator>
Content-Type: application/json

{"decision":"APPROVE","reason":"Reviewed action within approved scope"}
```

| Kondisi | Hasil |
| --- | --- |
| Credential hilang, tidak dikenal, atau dinonaktifkan | 401 |
| Principal AGENT/SERVICE, role tidak sesuai, identity/role spoofing | 403 |
| Approval tidak ditemukan | 404 |
| Approval kedaluwarsa, sudah diputuskan, binding berubah, role requirement berubah | 409 |
| Field authority tambahan atau reason kosong | 422 |
| Registry belum dikonfigurasi, rusak, atau tidak dapat dibaca | 503 |
| Human credential dan required role sah | 200; current policy gate diperiksa ulang |

APPROVE yang sah dapat menghasilkan PolicyDecision DENY ketika emergency stop,
scope, policy, revocation, risk atau restriction saat ini melarang tindakan.
Approval tidak menjalankan tindakan target. Metadata approval terautentikasi
diikat ke hash keputusan, audit dan outbox; token tidak disimpan di sana.

Konsumsi PENDING, bukti keputusan, PolicyDecision, status authorization,
audit dan outbox menggunakan satu transaksi. Conditional update menghindari
dua keputusan bersamaan. Kegagalan penulisan membatalkan seluruh transaksi.
Tidak diperlukan migrasi schema pada dump AptsGSS yang diberikan.

## Manifest dan acceptance setelah perubahan hash

`GSS_SOURCE_MANIFEST.json` adalah baseline baru khusus perbaikan ini.
`requirements.txt` adalah runtime GSS; overlay Mission tidak boleh menimpanya.
Dependency manifest memisahkan runtime API, tes dan GUI. Versi yang diuji dicatat
pada evidence; rentang dependency bukan lock semua dependency transitif.

Evidence Stage 6.4/6.9 lama tetap merupakan riwayat pengujian sumber sebelumnya.
Evidence baru di `evidence/gss_approval_fix` mengikat source snapshot sebelum dan
sesudah acceptance. Gate menolak sumber yang berbeda dari baseline ini; jangan
mengubah hash hanya untuk menyembunyikan kegagalan.

Sesudah memasang/restart GSS di Windows, jalankan ulang acceptance Stage 6.10
di `D:\mission_orchestrator` untuk memperoleh bukti integrasi pada sumber GSS
baru. Acceptance GSS terisolasi tidak menggantikan live full APTS acceptance.
