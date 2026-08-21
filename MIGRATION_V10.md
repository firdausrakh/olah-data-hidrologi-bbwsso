# Migration v10

## Cache Pengolahan

- Pilihan Pengolahan tetap disimpan di `sessionStorage`.
- Saat sesi/tab baru belum memiliki state, mode periode tetap **Bulanan** dengan **bulan berjalan**.
- Setelah data diproses, pivot hasil disimpan pada cache sesi berdasarkan kombinasi logger/vendor, pos, parameter, kategori, periode, tanggal/bulan/tahun, dan faktor koreksi.
- Ketika berpindah Pengolahan -> Monitoring -> Pengolahan, hasil yang kombinasinya masih sama dipulihkan tanpa request dan tanpa menekan Proses Data lagi.
- Hasil periode yang masih berjalan hanya dipakai ulang pada tanggal kalender yang sama agar cache tidak melewati pergantian hari.
- Raw vendor response tidak disimpan di browser; hanya hasil pivot yang ringan.

## Status Monitoring

Status ketersediaan dihitung dari view jam-jaman, terlepas dari tampilan Monitoring yang sedang Jam-Jaman atau Harian.

- **Berhasil**: gap kosong kontinyu terpanjang per hari <= 6 jam.
- **Peringatan**: gap kosong kontinyu terpanjang per hari > 6 sampai 12 jam.
- **Terputus**: gap kosong kontinyu terpanjang per hari > 12 jam.
- **Gagal**: request/parameter vendor gagal diambil.
- Nilai `0.0` adalah data valid dan tidak dihitung sebagai kosong.
- Curah hujan memakai hari hidrologis 07:00-06:59; Tinggi Muka Air memakai hari kalender.
- Untuk periode berjalan, hanya slot sampai waktu efektif request yang diperiksa.

## Klasifikasi hujan

Label ekstrem menggunakan `>50` untuk intensitas dan `>150` untuk hujan harian.
