# Cek DPS Pilkades — Desa Kasomalang Kulon

Halaman statis untuk warga mengecek namanya di **Daftar Pemilih Sementara (DPS)**
Pemilihan Kepala Desa Kasomalang Kulon 2026. Tanpa framework, tanpa server,
cukup tiga berkas: `index.html`, `styles.css`, `app.js`, dan satu `data.json`.

## Isi halaman

- **Cari nama** — langsung tersaring saat mengetik, bisa dipersempit per RW/RT.
- **Cek NIK / No. KK** — lewat tombol di samping kolom pencarian; bisa melihat
  seluruh anggota keluarga dalam satu KK.
- Nomor NIK/KK **tidak pernah dikirim ke server**. Yang disimpan di `data.json`
  hanya bentuk tersamar (`3213********0001`) dan sidik jari PBKDF2-nya.

## Mengganti data

1. Siapkan berkas DPS (`.xlsx` atau `.csv`). Kolom yang dibaca: `NAMA`, `NIK`,
   `KK`, `JENIS KELAMIN`, `USIA`, `RT`, `RW`. Huruf besar/kecil dan urutan kolom
   bebas, semua sheet yang terlihat dengan kolom NAMA + NIK otomatis digabung;
   sheet tersembunyi dan sheet rekap dilewati.
2. Jalankan:

   ```bash
   pip install openpyxl
   python convert.py "DAFTAR PEMILIH SEMENTARA (2).xlsx"
   ```

   Skrip akan merapikan RT/RW, membuang baris ganda, menyamarkan NIK/KK,
   lalu menulis `data.json` baru dan `laporan-duplikat-<jumlah>.xlsx` untuk
   pemeriksaan lokal. Laporan berisi nama, wilayah, dan status kecocokan NIK/KK
   tanpa mencantumkan nomornya (sekitar 3 menit karena sidik jari PBKDF2).
3. Buka `index.html` lewat server lokal untuk memeriksa hasilnya:

   ```bash
   python -m http.server 8765
   ```

**Jangan unggah berkas XLSX/CSV ke hosting.** Hanya `data.json` yang perlu ikut
ter-deploy; `.gitignore` dan `.vercelignore` sudah menolak berkas sumber.

## Pengaturan kecil

Di bagian atas `app.js`:

```js
const CFG = {
  wa: "6281234567890",   // WhatsApp panitia, kosongkan "" untuk menyembunyikan tombol
  perHalaman: 30,        // jumlah nama yang tampil sekali muat
};
```

Ganti `wa` dengan nomor WhatsApp panitia yang sebenarnya.

## Catatan data

- Satu NIK = satu baris. Baris yang tercatat ganda (misalnya muncul di RT
  berbeda atau di sheet berbeda) otomatis digabung, jadi jumlah di halaman ini
  bisa lebih kecil daripada rekapan mentah panitia.
- Sebagian baris di berkas sumber belum punya NIK lengkap. Baris seperti itu
  tetap tampil di daftar, tetapi tidak bisa dicek lewat NIK.
- Usia di luar rentang 17–110 tahun ditandai “perlu dicek” di hasil pencarian.

## Deploy

Proyek ini statis, jadi bisa langsung diunggah ke Vercel/GitHub Pages/Netlify.
`vercel.json` memasang header `noindex` agar halaman tidak terindeks mesin pencari.
