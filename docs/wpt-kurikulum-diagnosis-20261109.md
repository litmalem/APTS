# Diagnosis WPT kurikulum — 9 November 2026

Target: `https://kurikulum.del.ac.id:443`. Job `wpt-3ff35dea8c0e2ee866952ea692e74596`; Mission `mission-gmo-57851fd3-1f64-436f-b713-0b49e839bcc2`.

## Penyebab terverifikasi

Runtime attempt pertama FAILED dengan `RESOLVED_ADDRESS_OUTSIDE_SCOPE`. Hasil adapter membuktikan `target_network_io_performed=false`, resource sudah ditutup dan hasil memenuhi syarat explicit retry. Tidak ada respons HTTP atau hasil TLS pada attempt ini.

Resolver sistem Windows (getaddrinfo dan Resolve-DnsName) mengembalikan `172.21.2.2`, alamat RFC1918. Query eksplisit ke DNS publik 1.1.1.1 mengembalikan `103.167.217.156`. Hosts file tidak memetakan hostname ini. Mesin memiliki beberapa interface dan resolver DNS, termasuk Ethernet dengan DNS `172.22.2.46`. Perbedaan jawaban DNS terkonfirmasi; penyebab konfigurasi jaringan di hulu belum ditentukan.

Ketiga lapisan scope (Mission, boundary Pentest, task) hanya berisi URL ini dan `network_ranges=[]`. Broker mengizinkan DNS publik untuk URL yang tepat tetapi tidak mengizinkan hostname menjadi akses implisit ke jaringan privat. Penolakan sesuai implementasi, bukan masalah penulisan port 443 atau kegagalan TLS.

## Perubahan dan validasi

Detail job WPT sekarang menjelaskan kode penolakan alamat DNS dan langkah pemulihannya. Kode asli tetap terlihat. Syntax JavaScript dan pemeriksaan rendering/escaping lulus; aset aktif diverifikasi melalui HTTP. Tidak diperlukan restart layanan.

## Pemulihan yang masih memerlukan pilihan tujuan

- Jika server publik yang dimaksud: perbaiki resolusi hostname pada host runtime agar mengarah ke server publik yang benar, kemudian explicit retry job yang sama melalui Stage 6 dengan GSS baru.
- Jika server internal yang dimaksud: revisi scope resmi untuk mengizinkan IP internal tepat pada seluruh lapisan, lalu bentuk binding eksekusi yang sesuai revisi sebelum menjalankan WPT.

Pilihan server ditanyakan kepada operator. Tidak ada perubahan DNS sistem, perluasan scope, atau scan ulang sebelum pilihan tersebut diterima. Bukti terstruktur ada pada `wpt-kurikulum-diagnosis-20261109.json`.
