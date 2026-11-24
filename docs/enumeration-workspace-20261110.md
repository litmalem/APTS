# Enumeration workspace otomatis — 10 November 2026

## Perilaku

Halaman `/pentest/enumeration/` tidak lagi meminta Recon ID, Orchestration ID, atau JSON. Daftar otomatis memuat target, identitas CTI (`wptreq-auto-…`), teknologi/versi, kandidat CPE, status analisis, penerimaan WPT, dan eksekusi lanjutan. Pemilihan target membuka detail proses, hasil tervalidasi, dan identitas terkait. Tampilan diperbarui setiap 15 detik, mempertahankan pilihan serta data terakhir bila API gagal.

Endpoint GET `/api/pentest/ui/enumeration/workspace?limit=500` memproyeksikan analisis tersimpan dan outbox; GET tidak mengirim permintaan atau mengakses target. Endpoint context/manual lama tetap tersedia bagi integrasi API, tanpa form pada UI.

## Antrean dan relasi

Worker `mission_enumeration_wpt_delivery` berjalan setelah CTI → Enumeration dalam recovery sweep Mission. Worker membentuk satu request `wptreq-enum-…` per identitas analisis dan hash request Stage 5.3, menggunakan kontrak `apts-wpt-governed-intake-v3`.

Context request membawa intake CTI sumber, Enumeration Run, hash request analisis, Recon Run, hash source result, dan teknologi/versi. Sumber authority memuat ulang run dari repository Pentest dan mencocokkan keseluruhan request sebelum pemeriksaan scope/RoE/task/budget. Caller tidak dapat menentukan probe atau memperoleh otorisasi melalui context ini.

WPT menerima dan menyimpan context dalam kolom additive `governed_intakes.enumeration_context_json`. Replay dengan context berbeda ditolak. Worker hanya menyatakan `DELIVERED` setelah acknowledgment WPT cocok dengan intake. `enum_status` pada job sumber tidak digunakan sebagai bukti pengiriman outbound.

Outbox/progres tersimpan pada `mission_orchestrator/data/enumeration_delivery.db` (override `APTS_ENUMERATION_DELIVERY_DB`), dengan request immutable per identitas dan riwayat perubahan status. Acknowledgment tidak dihapus ketika authority kemudian kedaluwarsa. Hasil hanya ditampilkan jika record Stage 6 tersimpan dan terikat tepat ke mission, task, target, profile enumeration, serta evidence SEALED.

## Batas runtime yang ditemukan

Profil `wpt.bounded-enumeration.v1` masih `REGISTERED_NOT_EXECUTABLE` pada registry Stage 6. Perubahan UI/outbox ini tidak menyediakan adapter baru dan tidak mengubah budget, scope, atau keputusan Governance. Request yang diterima WPT dapat berstatus eksekusi BLOCKED; ini berbeda dari gagal mengirim request.

Setelah aktivasi pada data tersimpan:

- DVWA: NOT_SENT / BLOCKED / WPT_REQUEST_BUDGET_RESERVED.
- kurikulum.del.ac.id: NOT_SENT / BLOCKED / WPT_REQUEST_BUDGET_RESERVED.
- WebGoat: DELIVERED / BLOCKED / WPT_ENUMERATION_ADAPTER_UNAVAILABLE.

Ketiga request follow-up terbentuk otomatis. Ketiganya belum menghasilkan eksekusi enumeration lanjutan. Tidak ada batas Governance atau budget yang dilonggarkan untuk mengubah status tersebut.

## Verifikasi

- 76 tes gabungan workspace/delivery, CTI, Stage 5.3, governed intake, dan inbox lulus; setelah menambahkan kasus alasan budget, seluruh 17 tes workspace/delivery lulus ulang.
- 24 tes API WPT lulus, termasuk intake v3, replay, context berbeda, dan penerimaan tanpa target I/O.
- Browser lokal memperlihatkan daftar ketiga enrichment, perpindahan detail target, ID lengkap, serta status penerimaan WPT terpisah dari status eksekusi. Tidak ada form ID/JSON.
- Sintaks JavaScript dan `git diff --check` lolos.
- Mission, Pentest, dan WPT dimuat ulang dan health ketiganya diverifikasi.
