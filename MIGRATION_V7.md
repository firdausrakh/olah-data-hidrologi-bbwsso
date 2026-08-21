# Migrasi v7 — Cache Sesi, Ringkasan Hujan, dan Metadata Beacon

## Metadata Beacon

Metadata Beacon sekarang mengikuti struktur vendor lain:

```text
data/
├── beacon/
│   ├── positions.json
│   └── parameter_catalog.json
├── higertech/
├── tatonas/
└── dashindo/
```

Backend membaca seed Beacon dari `data/beacon/`. Cache runtime Vercel untuk katalog parameter tetap menggunakan `/tmp`.

## Autentikasi

Akses telemetri kembali meminta kata sandi otomatis saat sesi browser belum terautentikasi. Login menggunakan `APP_PASSWORDS` seperti pada v6. Cookie akses sekarang bersifat session cookie dan sesi lama v6 diinvalisasi oleh versi autentikasi baru.

## Cache pilihan UI

Pengolahan dan Monitoring menggunakan `sessionStorage` untuk mempertahankan pilihan selama pengguna berpindah menu di tab yang sama. Metadata daftar pos dan parameter juga disimpan pada cache sesi selama enam jam sehingga kembali ke pilihan yang sama tidak memicu request metadata berulang.

Monitoring tidak melakukan request otomatis. Pada kunjungan pertama kategori menampilkan `Pilih Kategori`. Rentang awal tetap disiapkan sebagai H-2 s.d. hari ini. Jika pengguna kembali ke Monitoring dan hasil yang sama masih ada di cache sesi, hasil tersebut dapat dipulihkan tanpa request baru.

## Curah hujan

Semua nilai curah hujan pada tampilan dan export dibulatkan menjadi satu angka desimal. Ringkasan tertinggi Monitoring menempatkan satuan pada header tabel dan memberi warna klasifikasi hanya pada sel nilai yang memenuhi rentang klasifikasi.
