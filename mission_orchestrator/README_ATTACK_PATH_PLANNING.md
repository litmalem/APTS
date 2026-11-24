# Attack-Path Planning, tahap 04

Halaman: `/pentest/attack-path-planning/` pada service Pentest aktif (Stage 5.10,
port default 8790). Restart service Pentest untuk memuat route Python baru.
Navigasi tahap 01–03 mengarah ke halaman ini; tautan dari tahap 03 mempertahankan
orchestration ID. UI mengambil seluruh hipotesis authoritative dari run terpilih,
bukan JSON pratinjau atau subset checkbox pada halaman hipotesis.

## Implementasi

- `symbolic_planner.py`: monotone STRIPS dengan preconditions/effects positif,
  uniform-cost search, action masking, alternatif jalur, dependency lintas
  hipotesis, dan analisis fixed-point untuk gap/cycle yang tak terjangkau.
- CTI knowledge dapat menyertakan `planning_model`; kontrak dinormalisasi dan
  masuk dalam hash knowledge serta model hipotesis. Model yang tidak menyatakan
  efek hanya menghasilkan aksi validasi, tanpa asumsi akses/privilege.
- `task.objective.goal_predicates` menjadi tujuan formal. Jika belum tersedia,
  tujuan model adalah cakupan validasi seluruh hipotesis. Ini ditandai eksplisit
  dan bukan klaim bahwa tujuan misi tercapai.
- Biaya pencarian: `cost + 0.25 * impact + (1 - evidence_confidence)`;
  faktor impact NONE/LOW/MEDIUM/HIGH/CRITICAL = 0/1/2/4/8. Ini heuristik, bukan
  probabilitas sukses. Biaya positif menjaga pencarian tanpa loop menguntungkan.
- Batas default: 10 alternatif, kedalaman 32, 10.000 ekspansi, frontier 20.000.
  Jika batas terlampaui, output menyatakan `search_limited`; tidak mengklaim
  kelengkapan atau optimalitas global dari pencarian yang terpotong.

Contoh bagian knowledge CTI (predicate ID adalah simbol, bukan command):

```json
{
  "planning_model": {
    "preconditions": ["access:asset-a"],
    "effects": ["assessment:asset-b"],
    "cost": 2
  }
}
```

Planner menambahkan `observed:<asset_id>` sebagai prasyarat dan
`validated:<hypothesis_id>` sebagai efek. Predicate tambahan tidak dianggap fakta
hanya karena tercantum dalam model. Antar-target harus dinyatakan oleh model CTI;
planner tidak menginferensikan reachability dari CVE atau versi software saja.

## Revisi dan belief

`POST /api/pentest/ui/attack-path-planning/run` menerima hanya
`orchestration_id` dan opsional `max_paths` (1–100). Data hipotesis, task, dan
feedback dibaca langsung dari repository. Tidak menerima aksi atau observasi
target dari browser. Pembatasan origin sama dengan endpoint UI lainnya.

`GET /api/pentest/ui/attack-path-planning/workspace?limit=100` menampilkan konteks
enumeration, hipotesis dan revisi tersimpan tanpa mencampur run.

Tabel additive `pentest_symbolic_plan_revisions` dibuat idempotent pada SQLite
repository Pentest; tidak menurunkan migration marker stage lain. Snapshot
identik direplay. Snapshot berubah mendapat nomor revisi baru, hash pendahulu,
hash input/policy dan daftar jalur ditambah/dihapus. Record dan plan diverifikasi
saat dibaca. Transaksi `BEGIN IMMEDIATE` melindungi penomoran revisi concurrent.

Feedback repository bertipe conflicting evidence, stale intelligence, specialist
failure atau scope/RoE change menahan kandidat. `metadata.hypothesis_ids` membatasi
hold ke kandidat tertentu; tanpa daftar tersebut hold berlaku pada konteks.
Hanya feedback dalam orchestration yang sama dengan evidence refs yang dipakai.
Belief adalah evidence-supported facts / unknown / conflicting, **bukan solver
POMDP probabilistik**. Feedback umum belum merupakan bukti hasil eksekusi.
Adapter otomatis dari hasil validasi Stage 6 ke efek faktual belum tersedia;
planner tidak mengubah feedback generik menjadi bukti kompromi.

Keluaran Stage 5.5 kini menyertakan `symbolic_plan` beserta evidence refs.
Empat checkpoint legacy dan kontrak handoff Stage 5.6 tetap tersedia untuk
kompatibilitas. Revisi UI merupakan artefak perencanaan: tidak mengganti proposal
Stage 5.6, me-release task, atau menjadwalkan eksekusi secara otomatis.

## PPO offline

`masked_ppo.py` menyediakan baseline PPO linear, clipped surrogate, scalar critic,
dan action masking tanpa dependency tambahan. Ini bukan reproduksi penuh PKPPO
atau HAML-DQN dan tidak menyertakan policy pretrained.

Simpan satu objek revisi dari panel audit UI sebagai JSON, atau kumpulkan beberapa
revisi untuk skenario pelatihan. Jalankan dari direktori `mission_orchestrator`:

```powershell
python -m pentest_subsystem.train_attack_policy --input scenarios.json --output attack-policy.json --episodes 500
$env:APTS_ATTACK_PATH_PPO_CHECKPOINT = (Resolve-Path attack-policy.json).Path
```

Set environment pada proses service Pentest sebelum menjalankan/restart service.
Checkpoint valid dan pernah dilatih diperlukan; checksum dan finite weights
diverifikasi. PPO hanya mengurutkan ekspansi kandidat yang lolos mask. Uniform-cost
search tetap mengurutkan biaya jalur dan seluruh output tetap kandidat. Pelatihan
memakai transisi simbolik deterministik, bukan target nyata. Evaluasi cyber range,
kalibrasi probabilitas, dan benchmarking kebijakan diperlukan sebelum mengklaim
peningkatan kinerja operasional.

## Validasi

```powershell
python -m pytest tests/test_symbolic_attack_planner.py tests/test_stage5_5_attack_path_planning_agent.py tests/test_stage5_4_vulnerability_hypothesis_agent.py tests/test_vulnerability_hypothesis_workspace.py -q -k "not http" -p no:cacheprovider
node tests/test_planning_ui.cjs
node tests/test_hypothesis_ui.cjs
```

Tes baru memeriksa causal chaining, optimalitas pada fixture kecil, action masks,
cycle/gap, batas pencarian, propagasi CTI, objective, snapshot/replay/tampering,
feedback, PPO offline, route UI/origin dan isolasi konteks. Tes HTTP socket pada
environment terbatas dapat gagal dengan Windows 10013; route juga diuji langsung
tanpa socket. Pemeriksaan visual browser belum berhasil karena timeout localhost.
