# Keyword Domain Scanner

Script Python untuk mencari URL dari keyword publik melalui Bing dan DuckDuckGo, lalu mengelompokkan hasilnya menjadi URL, domain, alamat IP, dan pasangan domain-IP.

Gunakan hanya untuk riset, inventarisasi aset, dan pengujian yang memiliki izin. Script ini tidak melakukan eksploitasi atau akses ke sistem target.

## Fitur

- Mencari keyword melalui Bing dan DuckDuckGo.
- Mendukung beberapa keyword dari argumen command line atau file teks.
- Mendukung region pencarian, termasuk Indonesia (`ID`).
- Menghapus URL dan domain duplikat.
- Mengubah hasil URL menjadi domain.
- Melakukan resolusi DNS IPv4 untuk domain yang ditemukan.
- Menulis hasil secara bertahap ke folder output.
- Menggunakan worker paralel untuk mempercepat proses.
- Memakai query biasa dan query dengan tanda kutip untuk keyword yang memiliki spasi.
- Menjelajahi halaman tambahan di luar kuota hasil utama.

## Persyaratan

- Python 3.10 atau lebih baru.
- Koneksi internet.
- Tidak memerlukan package eksternal; script hanya menggunakan standard library Python.

## Instalasi

Clone repository, lalu masuk ke folder project:

```bash
git clone https://github.com/USERNAME/NAMA-REPOSITORY.git
cd NAMA-REPOSITORY
```

Ganti URL clone dan nama repository sesuai repository GitHub Anda.

## Format file keyword

Buat file `keyword.txt` dengan satu keyword pada setiap baris:

```text
example company
public dashboard
site:example.com login
```

Baris kosong dan baris yang diawali `#` akan diabaikan. Keyword duplikat hanya diproses satu kali.

Jika `keyword.txt` berada di folder yang sama dengan `dork.py`, file tersebut akan dibaca secara otomatis.

## Penggunaan

### Mode interaktif

```bash
python dork.py
```

Jika tidak menggunakan `--regions`, script akan meminta pilihan region secara interaktif.

### Keyword langsung

```bash
python dork.py "public dashboard" "example company"
```

### Menggunakan file keyword

```bash
python dork.py --file keyword.txt
```

Keyword dari argumen dan file dapat digunakan bersamaan:

```bash
python dork.py "site:example.com login" --file keyword.txt
```

### Memilih region tanpa prompt

```bash
python dork.py --file keyword.txt --regions ID US SG
```

Kode region yang tersedia:

```text
ID US CA MX BR AR CL CO PE UK IE DE FR IT ES NL BE CH AT PL
SE NO DK FI PT CZ RO HU GR UA RU TR IN IL SA EG JP KR TW HK SG
MY TH VN PH AU NZ ZA AE
```

### Mengatur jumlah hasil dan output

```bash
python dork.py \
  --file keyword.txt \
  --regions ID \
  --max-results 50 \
  --extra-pages 5 \
  --output scan_results
```

Pada Windows PowerShell, perintah dapat ditulis dalam satu baris:

```powershell
python .\dork.py --file .\keyword.txt --regions ID --max-results 50 --extra-pages 5 --output .\scan_results
```

## Opsi command line

| Opsi | Default | Keterangan |
| --- | ---: | --- |
| `keywords` | - | Satu atau lebih keyword langsung |
| `-f`, `--file` | `keyword.txt` jika tersedia | File berisi satu keyword per baris |
| `-o`, `--output` | `scan_results` | Folder penyimpanan hasil |
| `--max-results` | `100` | Batas URL per keyword dan region |
| `--extra-pages` | `10` | Jumlah halaman tambahan yang dijelajahi |
| `--timeout` | `15` | Timeout request dan resolusi DNS dalam detik |
| `--delay` | `0.2` | Jeda antar request dalam detik |
| `--workers` | `10` | Jumlah pekerjaan paralel |
| `--regions REGION ...` | Semua region | Satu atau lebih kode region |

Gunakan bantuan bawaan untuk melihat sintaks terbaru:

```bash
python dork.py --help
```

## Output

Secara default, hasil disimpan di folder `scan_results`:

| File | Isi |
| --- | --- |
| `urls.txt` | URL unik yang ditemukan |
| `domains.txt` | Domain unik dari URL |
| `ips.txt` | Alamat IPv4 hasil resolusi DNS |
| `domain_ip.txt` | Pemetaan dalam format `domain -> IP` |

Contoh isi `domain_ip.txt`:

```text
example.com -> 93.184.216.34
```

File hasil dibuat atau dikosongkan saat proses dimulai, kemudian diperbarui selama pemindaian. Pada akhir proses, `urls.txt` dan `domains.txt` ditulis ulang berdasarkan hasil final.

## Perilaku scan besar

Jika jumlah pekerjaan melebihi 5.000 kombinasi keyword dan region, script mengaktifkan mode startup cepat:

- `max-results` otomatis menjadi `20` jika opsi tersebut tidak diberikan.
- `extra-pages` dibatasi maksimal `1`.
- Delay dinonaktifkan.
- Jumlah worker ditingkatkan untuk memproses antrian awal.

Batasi region atau gunakan nilai `--max-results` dan `--extra-pages` yang sesuai agar beban request tetap terkendali.

## Catatan penggunaan

- Hasil pencarian bergantung pada respons dan struktur halaman mesin pencari.
- Sebagian domain mungkin tidak memiliki record IPv4 atau gagal di-resolve.
- Gunakan delay dan jumlah worker yang wajar.
- Patuhi Terms of Service mesin pencari, hukum setempat, dan izin pemilik sistem.

## Lisensi

Tambahkan lisensi pilihan Anda sebelum mempublikasikan repository ini ke GitHub.
