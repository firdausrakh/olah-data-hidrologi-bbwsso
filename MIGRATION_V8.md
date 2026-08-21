# Migrasi v8 — Mapping Nama Pos Terpusat

Semua override nama pos operator sekarang berada dalam satu file:

```text
data/station_aliases.json
```

Tidak perlu lagi mengubah nama pos di `api/core.py`. Identifier yang digunakan untuk setiap vendor:

| Vendor | Kunci alias |
| --- | --- |
| Beacon | `id_logger` |
| Higertech | `deviceId` |
| Tatonas | `kd_hardware` |
| Dashindo | `id` sensor |

Contoh:

```json
{
  "tatonas": {
    "4105": "Opak Bintaran"
  },
  "higertech": {
    "HGT1465": "Kranggan"
  }
}
```

`positions.json` tetap menjadi metadata/seed vendor. Saat aplikasi memuat metadata, `station_aliases.json` dioverlay di atas nama vendor. Jika sebuah ID belum ada di alias, nama asli dari metadata/server tetap digunakan.

Perubahan alias dibaca saat aplikasi/instance dimulai. Pada local cukup restart `run.bat`; pada Vercel lakukan deploy ulang setelah mengubah file.
