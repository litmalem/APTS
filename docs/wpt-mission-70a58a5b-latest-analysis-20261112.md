# Analisis terbaru WPT — 12 November 2026

Mission: `mission-gmo-70a58a5b-ad4a-4ed8-b462-7fcfb85cebe0`.
Target: `http://localhost:8080/WebGoat`.

Pemeriksaan read-only database aktif menemukan tiga attempt. Laporan diagnosis awal di folder ini hanya mencakup attempt pertama; kesimpulan bahwa belum ada retry dan belum ada target I/O sudah tidak menggambarkan keadaan terbaru.

| Attempt | Waktu terminal WIB (UTC+7) | Runtime | Penyebab terminal |
| --- | --- | --- | --- |
| 1 | 09:09:34.185 | ABORTED | RUNTIME_HEARTBEAT_LOST |
| 2 | 09:47:04.958 | ABORTED | RUNTIME_SOURCE_READ_TIMEOUT |
| 3 | 09:47:59.093 | TIMEOUT | RUNTIME_WALL_DEADLINE |

## Penyebab dan batas kepastian

Attempt pertama kehilangan heartbeat internal supervisor. Hasil adapter FAILED dengan ADAPTER_FAILURE:ExecutionSourceUnavailable, tanpa target network I/O. Sumber authority/context tidak tersedia; exception sumber aslinya tidak tersimpan dalam hasil ini.

Attempt kedua menguatkan adanya keterlambatan pada jalur pemeriksaan context/authority: probe tidak menyelesaikan pekerjaannya dalam 8.100591 detik. Hasil adapter BLOCKED, tanpa target network I/O. Probe mencakup masuk ke guard.authorization() dan pembacaan context; timeout ini sendiri belum membuktikan tabel SQLite, lock, atau komponen sumber tertentu yang tersangkut. Durasi pembacaan sukses terakhir (mission 0.004471 detik, proposal 0.036868 detik) bukan durasi komponen probe yang timeout.

Attempt ketiga mencapai deadline keseluruhan. Claim dibuat 02:47:41.777772Z dan timeout_seconds=15, sehingga deadline awal 02:47:56.777772Z. Adapter menyimpan hasil SUCCEEDED pada 02:47:58.704377Z, setelah deadline tersebut; runtime kemudian dipersist TIMEOUT pada 02:47:59.092667Z. Ini menjelaskan mengapa keberhasilan adapter tidak menjadi keberhasilan runtime.

Pada attempt ketiga target benar-benar menjawab: tiga request, tanpa request_errors, halaman login HTTP 200 setelah redirect, fingerprint Java Servlet dari cookie JSESSIONID. Scan berstatus PARTIAL, dengan favicon redirect diblokir. Target dapat dijangkau pada attempt ini; diagnosis umum bahwa WebGoat mati tidak didukung. GSS boundary authorization pada attempt ketiga ALLOW dan delapan checks PASS.

Waktu terminal adalah waktu persistensi. Bukti menunjukkan deadline terlewati, tetapi belum mengatribusikan seluruh waktu ke overhead authorization, scheduling, database, atau HTTP. Pemecahan durasi per fase diperlukan untuk atribusi yang pasti.

## Mengapa mission masih RUNNING

mission_states masih RUNNING versi 4. Kode mission_wpt_preparation.py mensyaratkan runtime SUCCEEDED sebelum pengiriman hasil Stage 6; status TIMEOUT menghasilkan STAGE6_SUCCESS_REQUIRED. Kode membatasi attempt_number < 3 untuk membuat retry/recovery berikutnya. Tiga attempt sudah terpakai dan attempt terakhir sudah melakukan target I/O, sehingga retry tanpa I/O juga tidak berlaku. mission.log terbaru berulang kali mencatat stage6_runtime TIMEOUT / RUNTIME_WALL_DEADLINE dan stage6_result_delivery PENDING / STAGE6_SUCCESS_REQUIRED.

## Arah perbaikan

1. Ukur waktu antrean/lock, pembacaan Mission/Pentest, revalidasi GSS, startup worker, HTTP dan parsing secara terpisah; simpan stack probe yang timeout.
2. Evaluasi anggaran wall time 15 detik terhadap seluruh fase tersebut. Pertahankan deadline dan revalidasi authority; jangan mempromosikan hasil lewat deadline menjadi sukses tanpa desain kontrak yang jelas.
3. Propagasikan terminal failure/exhausted recovery ke status mission/task agar pipeline tidak menunggu sukses tanpa batas.

Sumber: database aktif mission_orchestrator/data/execution_subsystem.db (attempts, events, adapter results/invocations); mission_orchestrator/data/mission_orchestrator.db (mission_states); APTS_Control_Center/logs/mission.log; execution_subsystem/runtime_service.py, adapter_service.py, runtime_contract.py; mission_orchestrator/mission_wpt_preparation.py.

Pemeriksaan ini tidak mengubah kode layanan, database, scope, atau menjalankan ulang target.
