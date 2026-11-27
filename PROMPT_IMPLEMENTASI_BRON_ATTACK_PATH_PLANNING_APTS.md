# Prompt Codex: Implementasi BRON Knowledge Graph untuk Attack-Path Planning APTS

Salin seluruh isi bagian **Prompt untuk Codex** di bawah ini ke Codex saat membuka repositori `D:\APTS`.

---

## Prompt untuk Codex

Anda bekerja di repositori APTS pada `D:\APTS`. Implementasikan peningkatan **Stage 5.5 Attack-Path Planning** agar memakai knowledge graph bergaya BRON untuk membentuk kandidat jalur serangan berbasis evidence target. Lakukan perubahan pada kode, bukan hanya memberi usulan. Baca `CLAUDE.md`, instruksi `AGENTS.md` yang berlaku, dan kode terkait sebelum mengubah file.

### 1. Konteks kode saat ini

Modul utama berada di `mission_orchestrator/pentest_subsystem/`.

- `attack_path_planning.py` membentuk kandidat jalur, graph, ranking, output, provenance, dan evidence bundle Stage 5.5.
- `cti_attack_chain.py` mengambil serta menyegel rantai pengetahuan dari VulnDesk. Saat ini rantai tersebut ditandai sebagai provenance deskriptif/non-kausal.
- `cti_hypothesis_adapter.py` menghubungkan hasil CTI dengan hipotesis kerentanan dan dapat memasang `attack_chain`.
- `symbolic_planner.py` membuat problem STRIPS berbasis hipotesis, precondition, effect, objective, evidence, dan feedback.
- `attack_path_workspace.py`, kontrak, repository, API, serta acceptance gate terkait mungkin perlu disesuaikan. Temukan alur pemanggilan aktual sebelum mengubahnya.
- Data CAPEC tersedia di `D:\APTS\capec.sql`; periksa cara data itu dimuat dan dipakai oleh VulnDesk sebelum memilih sumber ingest. Jangan mengasumsikan isi, nama tabel, atau status impor.

Kondisi penting saat ini: kandidat jalur Stage 5.5 memakai tahapan generik tetap dan symbolic planner berfokus pada validasi hipotesis. Tujuan perubahan adalah menggunakan relasi knowledge graph sebagai dasar pembentukan kandidat, lalu mengompilasi kandidat itu menjadi problem simbolik APTS. Jangan menganggap bahwa keberadaan edge katalog membuktikan kerentanan atau keterjangkauan pada target.

### 2. Hasil yang harus dicapai

Bangun alur berikut secara deterministik:

1. Ambil snapshot pengetahuan BRON-style dan observasi target dari input Stage 5.4/5.3 yang tersedia.
2. Telusuri relasi graph yang relevan dari asset/CPE/CVE/CWE menuju CAPEC, ATT&CK Technique, dan Tactic, serta arah balik bila diperlukan.
3. Gabungkan relasi katalog dengan fakta target spesifik seperti asset, versi produk, service, endpoint, HTTP method, parameter, auth context/role, dan objective—hanya jika fakta itu benar-benar tersedia di evidence APTS.
4. Hasilkan kandidat jalur yang menjelaskan urutan relasi, prasyarat, bukti pendukung, ketidakpastian, applicability, biaya/risiko, dan sumber setiap edge.
5. Kompilasi kandidat menjadi action model yang dapat diproses symbolic planner APTS. Setiap action hanya menunjuk pada capability validasi yang sudah diizinkan; knowledge graph tidak boleh memasok perintah shell, payload bebas, parameter tool bebas, atau aksi eksploitasi langsung.
6. Pertahankan keluaran sebagai kandidat perencanaan. Validasi/eksekusi tetap berada pada stage dan gateway yang sudah berwenang.

### 3. Model graph minimum

Gunakan node bertipe, minimal:

- `TACTIC`, `TECHNIQUE`, `CAPEC`, `CWE`, `CVE`, `CPE`
- node konteks misi yang dibutuhkan, misalnya `MISSION`, `ASSET`, `SERVICE`, `ENDPOINT`, `AUTH_CONTEXT`, `ROLE`, `OBJECTIVE`, `EVIDENCE`, `VULNERABILITY_HYPOTHESIS`, dan `VALIDATION_CAPABILITY`

Gunakan edge bertipe, minimal mencakup relasi katalog yang didukung sumber yang ada, misalnya:

- `TACTIC` ↔ `TECHNIQUE`
- `TECHNIQUE` ↔ `CAPEC`
- `CAPEC` ↔ `CWE`
- `CWE` ↔ `CVE`
- `CVE` ↔ `CPE`
- relasi target dari hasil observasi, misalnya asset `RUNS_CPE`, service `EXPOSES_ENDPOINT`, dan hipotesis `SUPPORTED_BY` evidence.

Nama relasi di atas bersifat ilustratif. Verifikasi semantik dan arah relasi dengan sumber data serta implementasi VulnDesk. Simpan arah relasi asal; traversal boleh dua arah, tetapi jangan mengubah arah/arti relasi saat menyimpan.

Setiap edge dan node yang dipakai planner harus dapat membawa atau merujuk:

- source catalog, source record ID/URI, dan versi/snapshot;
- mapping level/confidence yang terdefinisi dan tervalidasi;
- evidence refs untuk fakta target;
- timestamp/versi data yang diperlukan untuk freshness;
- integrity/hash sesuai pola `boundary_contract` APTS.

Bedakan paling tidak status `AUTHORITATIVE`, `RELATED`, `PARTIAL`, `HEURISTIC`, `OBSERVED`, `UNKNOWN`, dan `CONFLICTING` sesuai model kontrak yang dipilih. Jangan perlakukan `HEURISTIC` sebagai fakta. Jangan membuat relasi hanya dari kemiripan teks.

### 4. Persyaratan implementasi

#### 4.1 Graph repository dan ingest

- Ikuti pola berlapis repositori ini: contract/schema → repository → service → API/workspace bila memang dibutuhkan.
- Periksa storage dan migration yang sudah ada. Pilih backend yang paling sesuai dengan pola APTS saat ini; jangan menambah layanan database eksternal baru tanpa alasan teknis kuat dan integrasi yang jelas.
- Buat ingest/adaptor untuk memproyeksikan data yang benar-benar tersedia di VulnDesk menjadi node/edge bertipe. Gunakan jalur loopback VulnDesk yang sudah ada bila sesuai; jangan menambahkan network egress baru dari Stage 5.x.
- Tangani data yang hilang secara fail-open untuk enrichment opsional: planner tetap dapat berjalan dengan fakta yang ada, tetapi mencatat graph tidak lengkap. Jangan mengarang edge.
- Snapshot graph harus version-pinned dan identik inputnya menghasilkan output serta hash yang sama.
- Terapkan batas ukuran, fan-out, kedalaman traversal, dan jumlah kandidat untuk mencegah ledakan graph; hasil pruning harus deterministik dan tercatat.

#### 4.2 Query dan pembentukan jalur

- Query harus berangkat dari asset/CPE/CVE/CWE/hipotesis yang terikat pada Stage 5.4, bukan dari seluruh katalog tanpa batas.
- Hasilkan multi-hop candidate paths melalui relasi graph yang tersedia. Jalur harus memuat urutan node/edge, mapping level, target applicability, evidence refs, alasan pemilihan, status fakta, serta kondisi yang belum diketahui.
- Kaitkan kandidat ke endpoint/role web hanya melalui observasi target yang tercatat. Jangan menyimpulkan bahwa relasi CVE/CWE/CAPEC/ATT&CK berlaku terhadap endpoint tertentu tanpa evidence penghubung.
- Skor harus berupa prioritas validasi/biaya/risk yang terjelaskan, bukan probabilitas exploit sukses kecuali model probabilitas terkalibrasi memang sudah ada dan kontraknya mendukungnya.
- Jika trained ranker tersedia, ia hanya boleh mengurutkan kandidat sesuai kontrak APTS. Ia tidak boleh mengubah kebenaran fakta, menambah edge, melewati action mask, atau menentukan otorisasi.

#### 4.3 Kompilasi ke symbolic planner

- Perluas `symbolic_planner.py` secara kompatibel agar menerima action model hasil kompilasi jalur graph: `preconditions`, `effects`, `cost`, `impact`, `confidence/belief`, `evidence_refs`, `source_path_refs`, dan referensi capability yang tervalidasi.
- Pertahankan logika STRIPS/evidence yang ada, termasuk status unknown/conflicting dan action mask. Unknown tidak boleh otomatis menjadi true.
- Jangan menjadikan ATT&CK Technique atau CAPEC sebagai action executable. Keduanya adalah konteks pengetahuan; hanya registry capability/validation APTS yang dapat menyediakan action validasi yang diizinkan.
- Jangan merusak perilaku lama untuk misi tanpa graph atau tanpa enrichment. Sediakan fallback eksplisit dan ber-provenance ke planner lama, dengan penanda `graph_enrichment_status` yang jelas.

#### 4.4 Kontrak, provenance, dan kompatibilitas

- Jaga lineage Stage 5.4, mission ID, pentest/task ID, predecessor hash, evidence bundle, deterministic ID, canonical JSON, dan integrity verification.
- Jika skema output/DB berubah, buat migration dan version bump eksplisit sesuai pola repo. Perbarui verifier, contract, workspace, serta acceptance gate yang memang terpengaruh.
- Keluaran perlu mencakup sekurang-kurangnya:
  - `knowledge_graph_snapshot_id` dan versi schema;
  - `graph_enrichment_status` (misalnya `COMPLETE`, `PARTIAL`, `UNAVAILABLE`);
  - candidate path berisi nodes, edges, action model, evidence, applicability, uncertainty, score/ranking, dan provenance;
  - semantik yang menyatakan kandidat belum tervalidasi/dieksekusi dan belum membuktikan reachability.
- Verifier harus memvalidasi edge/node types, ID, provenance, snapshot, action references, evidence binding, limits, dan integrity. Tolak graph/path malformed secara fail-closed.

#### 4.5 Batasan keselamatan/governance wajib

Patuhi `CLAUDE.md` dan kontrak APTS. Khusus Stage 5.x:

- `external_network_io_performed=False`
- `target_actuation=False`
- `authorization_minted=False`
- tidak memanggil tool/binary atau membuat execution request
- tidak mengubah scope, RoE, approval, policy decision, atau governance
- tidak memindahkan otoritas eksekusi dari gateway yang sudah ditentukan
- graph planner hanya menghasilkan candidate plan/proposal; stage eksekusi yang telah ada tetap menjadi satu-satunya pihak yang dapat melakukan aksi sesuai governance.

Jangan menjalankan exploit atau probe pada target selama implementasi. Jangan menyentuh database runtime atau file pengguna yang tidak terkait. Pertahankan perubahan lokal yang sudah ada; jangan reset/revert perubahan working tree.

### 5. Integrasi yang perlu diperiksa

Telusuri dan sesuaikan hanya bagian yang diperlukan dari:

- `cti_attack_chain.py` dan `cti_hypothesis_adapter.py` untuk provenance/enrichment;
- `attack_path_planning.py` untuk kandidat graph-grounded, output, ranking, dan lineage;
- `symbolic_planner.py` untuk kompilasi action model;
- repository/contract/service/API/workspace terkait dan migration-nya;
- acceptance gate serta test terkait Stage 5.4, 5.5, dan handoff stage berikutnya.

Jangan melakukan refactor massal atau mengubah stage lain yang tidak dibutuhkan. Pertahankan API dan schema lama dengan default/fallback yang kompatibel bila aman; jika kompatibilitas tidak mungkin, dokumentasikan breaking change dan migrasinya.

### 6. Kriteria penerimaan

Implementasi dinyatakan selesai bila:

1. Jalur kandidat dibentuk dari traversal graph dengan provenance, bukan hanya dari template tahap generik.
2. Jalur menghubungkan relasi katalog dan observasi target hanya ketika ada evidence yang sesuai.
3. Output menunjukkan edge mana yang katalog-authoritative, related/partial/heuristic, observed, unknown, atau conflicting.
4. Missing mapping menghasilkan graph parsial/fallback yang tercatat; tidak ada relasi atau fakta target yang difabrikasi.
5. Action planner hanya menggunakan capability validasi yang telah diizinkan dan tetap mematuhi preconditions/action mask.
6. Identik snapshot + request + evidence menghasilkan ID, urutan kandidat, dan hash yang deterministik.
7. Semua hash, lineage, schema verifier, migration, serta acceptance gate terkait konsisten.
8. Tidak ada I/O jaringan atau aktuasi target dari Stage 5.x; tidak ada perubahan governance/otorisasi.
9. UI/workspace, jika diubah, dapat menunjukkan jalur, confidence/mapping level, evidence, unknowns, serta alasan ranking tanpa mengubah fungsi eksekusi.
10. Pengujian terkait yang diwajibkan `CLAUDE.md` lulus. Laporkan pengujian yang dijalankan dan hasilnya; jangan menyatakan lulus bila tidak dijalankan.

### 7. Urutan kerja Codex

1. Inspeksi instruksi repo, `git status`, pemanggil Stage 5.5, contracts, repository/migrations, data CAPEC/VulnDesk, planner, verifier, UI, dan acceptance gates.
2. Ringkas temuan teknis dan rencana file yang akan diubah; lanjutkan implementasi tanpa menunggu persetujuan untuk pilihan rutin.
3. Implementasikan graph contract/repository dan snapshot/versioning terlebih dahulu.
4. Implementasikan traversal deterministik dan compiler graph-path → action model simbolik.
5. Integrasikan dengan Stage 5.5, provenance, verifier, persistence, serta fallback lama.
6. Tambahkan atau sesuaikan pengujian/acceptance gate yang diwajibkan instruksi repo; jalankan pengujian terkait.
7. Tinjau diff untuk memastikan tidak ada file runtime/database tidak terkait yang berubah dan seluruh invarian keamanan tetap dipenuhi.
8. Berikan ringkasan perubahan per file, desain graph yang benar-benar terimplementasi, contoh bentuk output, hasil pengujian, keterbatasan coverage graph, dan pekerjaan lanjutan yang masih tersisa.

### 8. Rujukan konsep

Gunakan BRON sebagai model graph relasional yang mempertahankan entri dan relasi dari sumber threat/vulnerability, bukan sebagai klaim bahwa seluruh relasi katalog lengkap atau bahwa semua jalur katalog dapat dieksekusi pada target. Implementasi APTS harus menjaga perbedaan antara **hubungan pengetahuan katalog**, **fakta observasi target**, dan **aksi validasi**.

Rujukan BRON: Erik Hemberg et al., *Linking Threat Tactics, Techniques, and Patterns with Defensive Weaknesses, Vulnerabilities and Affected Platform Configurations for Cyber Hunting*, https://arxiv.org/abs/2010.00533 ; repositori proyek https://github.com/ALFA-group/BRON.

---

## Catatan penggunaan

Prompt ini meminta Codex mengimplementasikan graph-grounded Attack-Path Planning pada Stage 5.5 APTS. Prompt tersebut tidak meminta Codex mengimpor ulang `capec.sql`, mengubah governance, atau menjalankan aksi terhadap target tanpa terlebih dahulu memeriksa implementasi dan batasan lokal yang berlaku.
