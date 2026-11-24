# Login cepat lokal untuk uji coba

Buka http://127.0.0.1:8802 dan klik **Masuk cepat ? uji coba lokal**. Tidak perlu mengetik token. Jika halaman lama masih terlihat, lakukan refresh Ctrl+F5.

Mode ini diaktifkan secara eksplisit di `.env` melalui `GSS_DEV_QUICK_LOGIN=1`. Default kode tetap menonaktifkannya. Web hanya mendengarkan loopback; login cepat juga memeriksa alamat peer, Host dan Origin.

Principal uji: `local-test-operator`, dengan role `GOVERNANCE_ADMIN`, `OPERATOR`, dan `SECURITY_APPROVER`. UI menampilkan MODE UJI COBA LOKAL. Pemeriksaan scope, policy, dan otorisasi eksekusi tetap berlaku.

Kredensial backend dibuat dan disimpan di server, tidak dikirim ke browser. Lokasi berkas internal ditetapkan oleh `GSS_DEV_QUICK_LOGIN_TOKEN_FILE`; registry hash ditetapkan oleh `GOV_APPROVAL_PRINCIPALS_FILE`. Berkas berada di `.secrets/`, dengan ACL dibatasi ke pengguna Windows yang menjalankan layanan. Jangan memasukkan direktori ini ke Git.

Browser tetap memakai session cookie HttpOnly/SameSite=Strict selama 30 menit dan CSRF untuk perubahan. Logout menghapus sesi. Backend langsung tetap menolak request tanpa autentikasi.

Untuk mematikan tombol login cepat, ubah `GSS_DEV_QUICK_LOGIN=0` lalu restart aptsGSS Web melalui Control Center. Untuk kembali ke akun pribadi, pulihkan registry principal asli, atur `GOV_APPROVAL_PRINCIPALS_FILE` ke lokasinya, dan restart backend aptsGS. Salinan `.env` sebelum pengaktifan tersedia di `.runtime/env-before-local-quick-login-20261106.bak`.

Verifikasi pada 6 November 2026: login cepat, sesi, overview dan logout pada layanan aktif mengembalikan HTTP 200; backend tanpa autentikasi tetap HTTP 401. Lima tes khusus login cepat lulus. Regresi autentikasi/konsol juga diperiksa; satu tes fixture konsol lama tetap dikecualikan seperti pada pemulihan sebelumnya.
