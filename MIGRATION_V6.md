# Migrasi v6 — Backend Modular & Multiple App Passwords

## Perubahan `.env`

File `.env` tetap berada di **root repository**, sejajar dengan `config.py`, `run.bat`, dan `requirements.txt`.

Sebelumnya:

```env
APP_PASSWORD=password_lama
```

Sekarang disarankan:

```env
APP_PASSWORDS=password_admin,password_operator,password_lapangan
```

Semua password pada `APP_PASSWORDS` memiliki hak akses aplikasi yang sama. Pemisah koma, titik koma, baris baru, dan JSON array didukung. Contoh JSON:

```env
APP_PASSWORDS=["password_admin","password_operator","password_lapangan"]
```

`APP_PASSWORD` lama masih dibaca sebagai fallback agar deployment lama tidak langsung rusak, tetapi konfigurasi baru sebaiknya menggunakan `APP_PASSWORDS`.

## Struktur backend

```text
api/
├── app.py
├── core.py
├── routes/
│   ├── auth.py
│   ├── telemetry.py
│   ├── monitoring.py
│   └── download.py
└── services/
    └── monitoring.py
```

`api/app.py` sekarang hanya menjadi entry point Flask/Vercel. Adapter vendor, parser, cache, dan fungsi pengolahan inti tetap berada di `api/core.py`, sedangkan route HTTP dan service Monitoring dipisahkan agar perubahan fitur lebih mudah diuji dan dirawat.

## Nama pos Tatonas

Hardware Tatonas `4105` sekarang ditampilkan sebagai **Opak Bintaran**. `location_original` tetap `Bintaran` agar nama asli dari server vendor tidak hilang dari metadata.
