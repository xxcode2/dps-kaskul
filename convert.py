#!/usr/bin/env python3
"""Ubah data DPS (XLSX/CSV) menjadi data.json yang aman dipublikasikan.

Semua sheet yang punya kolom NAMA + NIK akan digabung. Sheet RW yang terlihat
selalu ikut; sheet tersembunyi hanya ikut kalau namanya mengandung "TAMBAHAN"
(itu salinan daftar utama, dipakai sebagai cadangan). Sheet rekap dan sheet
tersembunyi lainnya otomatis dilewati.

Pakai:
    python convert.py "DAFTAR PEMILIH SEMENTARA (3).xlsx"

Butuh: pip install openpyxl   (hanya untuk XLSX)

Yang dilakukan skrip ini:
  * membaca sheet RW + sheet TAMBAHAN (termasuk yang tersembunyi)
  * merapikan RT/RW jadi 3 digit dan menebak RW dari nama sheet
  * membuang baris ganda (satu NIK = satu pemilih; baris TAMBAHAN dengan
    nama + RW yang sama dianggap orang yang sama)
  * menyamarkan NIK / No. KK (hanya sebagian digit yang tampil)
  * menyimpan sidik jari (PBKDF2) NIK & KK agar pencarian tetap bisa
    dilakukan tanpa menyimpan nomor aslinya
  * menulis data.json ringkas (array, bukan objek, supaya file kecil)
  * menulis laporan lokal: baris ganda, NIK yang perlu dicek, dan usia yang
    tidak cocok dengan tanggal lahir di NIK

JANGAN upload file XLSX/CSV atau laporan ini ke hosting. Hanya data.json.
"""
import csv
import datetime
import difflib
import json
import os
import re
import secrets
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from hashlib import pbkdf2_hmac

ITER = 100_000          # putaran PBKDF2, harus sama dengan yang dibaca index.html
AWAL, AKHIR = 4, 4      # digit NIK/KK yang tetap ditampilkan
PANJANG_HASH = 32       # 128 bit cukup, file lebih kecil
USIA_MIN, USIA_MAKS = 17, 110
TANGGAL_ACUAN = datetime.date.today()   # acuan hitung usia dari NIK

GELAR = {
    "SE", "SH", "ST", "SP", "SPD", "SSOS", "SKM", "SKEP", "SIP", "SHI", "SIKOM",
    "MM", "MPD", "MHI", "MSI", "MAP", "AMD", "AMK", "AMd", "SIP", "SAP", "SHUT",
    "SAG", "SPI", "SPT", "SPWK", "SSI", "SFARM", "SKED", "MKES", "MKM", "MH",
    "DRS", "DRA", "IR", "HJ", "H", "HAJI", "HAJJAH", "S", "M", "A", "MD", "BA",
}


def teks(x):
    return re.sub(r"\s+", " ", str(x if x is not None else "").strip()).upper()


def angka(x):
    return re.sub(r"\D", "", str(x if x is not None else ""))


def tiga(x):
    """'7' -> '007', '007' -> '007', '' -> ''."""
    x = angka(x)
    return x.zfill(3) if x else ""


def umur(tgl):
    """Umur penuh pada tanggal acuan."""
    return (TANGGAL_ACUAN.year - tgl.year -
            ((tgl.month, tgl.day) > (TANGGAL_ACUAN.month, TANGGAL_ACUAN.day)))


def lahir_dari_nik(nik, tertulis=None):
    """Tanggal lahir yang tersandi di NIK (hari +40 untuk perempuan).

    Tahun di NIK cuma dua digit, jadi dipilih kandidat (2000-an / 1900-an) yang
    umurnya masih masuk akal; kalau dua-duanya masuk, yang paling dekat dengan
    usia di berkas yang dipakai.
    """
    if len(nik) != 16:
        return None
    hari, bulan, tahun_kecil = int(nik[6:8]), int(nik[8:10]), int(nik[10:12])
    if hari > 40:
        hari -= 40
    kandidat = []
    for tahun in (2000 + tahun_kecil, 1900 + tahun_kecil):
        try:
            tgl = datetime.date(tahun, bulan, hari)
        except ValueError:
            continue
        if USIA_MIN - 5 <= umur(tgl) <= USIA_MAKS:
            kandidat.append(tgl)
    if not kandidat:
        return None
    if tertulis:
        kandidat.sort(key=lambda t: abs(umur(t) - tertulis))
    return kandidat[0]


def cek_usia(r):
    """(usia menurut NIK, tanggal lahir) atau None kalau tidak bisa dicek."""
    tertulis = int(r["usia"]) if r["usia"].isdigit() else None
    tgl = lahir_dari_nik(r["nik"], tertulis)
    if not tgl:
        return None
    return umur(tgl), tgl


def judul(nama):
    """'ABDUL LATIF, S.PD' -> 'Abdul Latif, S.PD' (gelar tetap kapital)."""
    out = []
    for kata in nama.split(" "):
        inti = kata.strip(",.")
        kecil = inti.replace(".", "")
        if not inti:
            out.append(kata)
        elif "." in kata or kecil in GELAR:
            out.append(kata)                                  # gelar: biarkan
        elif kata.isdigit():
            out.append(kata)
        else:
            out.append(kata[0] + kata[1:].lower())
    return " ".join(out)


def samar(x):
    if len(x) < AWAL + AKHIR + 1:
        return ""
    return x[:AWAL] + "*" * (len(x) - AWAL - AKHIR) + x[-AKHIR:]


def _hash(job):
    salt, kind, val = job
    return pbkdf2_hmac("sha256", f"{kind}:{val}".encode(), salt.encode(), ITER)[: PANJANG_HASH // 2].hex()


def baca_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    baris = []
    for sheet in wb.worksheets:
        tambahan = "TAMBAHAN" in sheet.title.upper()
        if sheet.sheet_state != "visible" and not tambahan:
            continue                                      # sheet rekap / catatan internal
        kepala = None
        for i, r in enumerate(sheet.iter_rows(values_only=True), start=1):
            sel = [teks(c) for c in r]
            if "NAMA" in sel and "NIK" in sel:
                kepala = {k: j for j, k in enumerate(sel) if k}
                break
        if not kepala:
            continue                                      # sheet rekap / kosong
        cocok = re.search(r"RW\.?\s*0*(\d+)", sheet.title, re.I)
        rw_sheet = tiga(cocok.group(1)) if cocok else ""
        for r in sheet.iter_rows(min_row=i + 1, values_only=True):
            def ambil(k):
                j = kepala.get(k)
                return r[j] if j is not None and j < len(r) else None
            nama = teks(ambil("NAMA"))
            if not nama or nama == "NAMA" or nama.isdigit():
                continue                                  # baris nomor urut / kosong
            baris.append({
                "nama": nama,
                "nik": angka(ambil("NIK")),
                "kk": angka(ambil("KK")),
                "jk": teks(ambil("JENIS KELAMIN")),
                "usia": angka(ambil("USIA")),
                "rt": tiga(ambil("RT")),
                "rw": tiga(ambil("RW")) or rw_sheet,
                "sheet": sheet.title,
                "tambahan": tambahan,
            })
    wb.close()
    return baris


def baca_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        s = f.read()
        d = csv.Sniffer().sniff(s[:2000], delimiters=",;\t")
        baris = []
        for r in csv.DictReader(s.splitlines(), delimiter=d.delimiter):
            g = {(k or "").strip().lower(): v for k, v in r.items()}
            nama = teks(g.get("nama"))
            if not nama:
                continue
            baris.append({"nama": nama, "nik": angka(g.get("nik")), "kk": angka(g.get("kk")),
                          "jk": teks(g.get("jenis kelamin")) or teks(g.get("jk")),
                          "usia": angka(g.get("usia")), "rt": tiga(g.get("rt")),
                          "rw": tiga(g.get("rw")), "sheet": "csv", "tambahan": False})
        return baris


SINGKATAN = {"M": "MUHAMMAD", "MUH": "MUHAMMAD", "MOH": "MUHAMMAD", "MOCH": "MUHAMMAD",
             "MOCHAMAD": "MUHAMMAD", "MOCHAMMAD": "MUHAMMAD", "MUHAMAD": "MUHAMMAD",
             "MOHAMAD": "MUHAMMAD", "MOHAMMAD": "MUHAMMAD"}


def kata_nama(nama):
    bersih = re.sub(r"[^A-Z ]", " ", nama.upper())
    return [SINGKATAN.get(k, k) for k in bersih.split() if k]


def nama_serupa(a, b):
    """Dua nama dianggap orang yang sama kalau cuma beda ejaan/singkatan."""
    ka, kb = kata_nama(a), kata_nama(b)
    if ka == kb:
        return True
    n = min(len(ka), len(kb))
    if n and ka[:n] == kb[:n]:                       # SHENDY ~ SHENDY FEBRIAN
        return True
    if difflib.SequenceMatcher(None, " ".join(ka), " ".join(kb)).ratio() >= 0.8:
        return True
    if len(ka) == len(kb):                           # TEDI SAPUTRA ~ TEDI SUPRIADI
        mirip = sum(1 for x, y in zip(ka, kb)
                    if difflib.SequenceMatcher(None, x, y).ratio() >= 0.6)
        return mirip == len(ka)
    return False


def kunci(r):
    """Satu orang = satu NIK. Kalau NIK rusak, pakai nama + KK (atau wilayah)."""
    if len(r["nik"]) == 16:
        return "nik:" + r["nik"]
    if len(r["kk"]) == 16:
        return "nm:" + r["nama"] + "|" + r["kk"]
    return "nm:" + r["nama"] + "|" + r["rt"] + "|" + r["rw"]


def mutu(r):
    """Makin kecil makin dipilih saat ada baris ganda."""
    return (r["tambahan"], not r["kk"], not (USIA_MIN <= int(r["usia"] or 0) <= USIA_MAKS),
            r["sheet"], r["rt"])


def pisah_tambahan(rows, bajakan):
    """Sheet TAMBAHAN pada dasarnya salinan daftar utama.

    Barisnya kadang di-input ulang sehingga NIK-nya berbeda karena salah ketik.
    Kalau hanya dipercaya lewat NIK, satu warga bisa tampil dua kali. Jadi baris
    TAMBAHAN yang nama + RW-nya sudah ada di sheet RW dianggap orang yang sama,
    dan kalau NIK-nya memang beda, itu dicatat untuk dicek panitia.
    """
    acuan = {}
    for r in rows:
        if not r["tambahan"]:
            acuan.setdefault((r["nama"], r["rw"]), r)
    tersisa = []
    for r in rows:
        u = acuan.get((r["nama"], r["rw"])) if r["tambahan"] else None
        if u is not None:
            bajakan.append(("ganda", u, r))
            if len(r["nik"]) == len(u["nik"]) == 16 and r["nik"] != u["nik"]:
                bajakan.append(("nik-tambahan", u, r))
            continue
        tersisa.append(r)
    return tersisa


def tulis_laporan(folder, bajakan, usia_melenceng):
    """Laporan lokal (tanpa NIK/KK utuh) supaya panitia bisa cek data ganda."""
    if not bajakan and not usia_melenceng:
        return
    try:
        import openpyxl
    except ImportError:
        return
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Duplikat"
    jumlah_ganda = sum(1 for jenis, *_ in bajakan if jenis == "ganda")
    ws.append([
        "No.", "Nama baris duplikat", "RW duplikat", "RT duplikat",
        "Sheet duplikat", "Nama acuan (dipertahankan)", "RW acuan",
        "RT acuan", "Sheet acuan", "Status NIK", "Status No. KK",
        "Dasar penggabungan",
    ])
    nomor = 0
    untuk_dicek = []
    for jenis, *isi in bajakan:
        if jenis != "ganda":
            continue
        simpan, buang = isi
        nomor += 1
        lengkap = len(simpan["nik"]) == len(buang["nik"]) == 16
        nik_sama = lengkap and simpan["nik"] == buang["nik"]
        kk_sama = len(simpan["kk"]) == len(buang["kk"]) == 16 and simpan["kk"] == buang["kk"]
        status_nik = ("Sama" if nik_sama else "Berbeda" if lengkap else "Tidak lengkap")
        status_kk = ("Sama" if kk_sama else "Berbeda" if len(simpan["kk"]) == len(buang["kk"]) == 16
                     else "Tidak lengkap")
        if nik_sama:
            dasar = "NIK sama; nama cocok menurut aturan konverter"
        elif lengkap:
            dasar = "Nama & RW sama tapi NIK berbeda — salah satu kemungkinan salah ketik"
            untuk_dicek.append((simpan, buang))
        elif kk_sama:
            dasar = "Nama dan No. KK sama; NIK tidak lengkap"
        else:
            dasar = "Nama dan RT/RW sama; NIK dan No. KK tidak lengkap"
        ws.append([
            nomor, judul(buang["nama"]), buang["rw"], buang["rt"], buang["sheet"],
            judul(simpan["nama"]), simpan["rw"], simpan["rt"], simpan["sheet"],
            status_nik, status_kk, dasar,
        ])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for kolom, lebar in zip("ABCDEFGHIJKL", (7, 32, 12, 12, 22, 32, 12, 12, 22, 18, 18, 54)):
        ws.column_dimensions[kolom].width = lebar

    def lokasi(r, nik=None):
        nik = r["nik"] if nik is None else nik
        kutip = f" — NIK {samar(nik)}" if len(nik) == 16 else ""
        return f"{judul(r['nama'])} — RW {r['rw']}, RT {r['rt']} ({r['sheet']}{kutip})"

    konflik = wb.create_sheet("NIK perlu dicek")
    konflik.append(["No.", "Jenis", "Yang tercatat", "Yang perlu dicek"])
    nomor = 0
    for jenis, *isi in bajakan:
        if jenis == "nik-dobel":
            kantong = isi[0]
            nomor += 1
            konflik.append([
                nomor, "Satu NIK untuk nama berbeda",
                " | ".join(lokasi(daftar[0]) for _, daftar in kantong),
                f"NIK yang sama dipakai {len(kantong)} nama; cocokkan dengan KTP / KK aslinya.",
            ])
    for simpan, buang in untuk_dicek:
        nomor += 1
        konflik.append([
            nomor, "NIK berbeda, nama & RW sama",
            f"{lokasi(simpan)} | {lokasi(buang)}",
            "Kemungkinan salah ketik NIK di salah satu sheet; yang tampil di daftar adalah baris sheet RW.",
        ])
    konflik.freeze_panes = "A2"
    konflik.auto_filter.ref = konflik.dimensions
    for kolom, lebar in zip("ABCD", (7, 34, 110, 60)):
        konflik.column_dimensions[kolom].width = lebar

    if usia_melenceng:
        us = wb.create_sheet("Usia perlu dicek")
        us.append(["No.", "Nama", "RW", "RT", "Sheet", "Usia di berkas",
                   "Tanggal lahir menurut NIK", "Usia hitungan", "Selisih"])
        for i, (r, u_nik, tgl) in enumerate(usia_melenceng, 1):
            us.append([i, judul(r["nama"]), r["rw"], r["rt"], r["sheet"],
                       int(r["usia"]) if r["usia"].isdigit() else r["usia"],
                       tgl.strftime("%d/%m/%Y"), u_nik, u_nik - int(r["usia"] or 0)])
        us.freeze_panes = "A2"
        us.auto_filter.ref = us.dimensions
        for kolom, lebar in zip("ABCDEFGHI", (7, 32, 8, 8, 14, 16, 28, 15, 10)):
            us.column_dimensions[kolom].width = lebar

    nama_file = f"laporan-duplikat-{jumlah_ganda}.xlsx"
    tujuan = os.path.join(folder, nama_file)
    wb.save(tujuan)
    return tujuan


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    mentah = baca_xlsx(src) if src.lower().endswith((".xlsx", ".xlsm")) else baca_csv(src)
    dibaca = len(mentah)
    dari_rw = sum(1 for r in mentah if not r["tambahan"])
    bajakan = []                                     # catatan untuk laporan lokal
    mentah = pisah_tambahan(mentah, bajakan)

    # satu NIK bisa saja dipakai dua orang berbeda (salah input). Baris seperti
    # itu JANGAN digabung, cukup dicatat di laporan untuk dicek panitia.
    kelompok = defaultdict(list)
    for r in mentah:
        kelompok[kunci(r)].append(r)
    hasil_kelompok = []
    dobel_nik = set()                                # NIK yang dipakai lebih dari satu nama
    for grup in kelompok.values():
        if len(grup) == 1:
            hasil_kelompok.append(grup)
            continue
        kantong = []                                 # daftar (nama wakil, [baris])
        for r in sorted(grup, key=mutu):
            for wakil, isi in kantong:
                if nama_serupa(wakil, r["nama"]):
                    isi.append(r)
                    break
            else:
                kantong.append((r["nama"], [r]))
        for wakil, isi in kantong:
            hasil_kelompok.append(isi)
            for r in isi[1:]:
                bajakan.append(("ganda", isi[0], r))
        if len(kantong) > 1:
            dobel_nik.add(grup[0]["nik"])
            bajakan.append(("nik-dobel", kantong))

    rows = [sorted(grup, key=mutu)[0] for grup in hasil_kelompok]

    # buang baris tanpa wilayah sama sekali
    rows = [r for r in rows if r["rw"]]
    rows.sort(key=lambda r: (r["rw"], r["rt"], r["nama"]))
    ganda = dibaca - len(rows)

    # usia yang tertulis di berkas vs usia yang tersandi di NIK
    usia_melenceng = []
    for r in rows:
        if not r["usia"].isdigit():
            continue                                      # usia kosong, tidak bisa dibandingkan
        cek = cek_usia(r)
        if cek and abs(cek[0] - int(r["usia"])) > 1:
            usia_melenceng.append((r, cek[0], cek[1]))
    usia_melenceng.sort(key=lambda x: (x[0]["rw"], x[0]["rt"], x[0]["nama"]))

    salt = secrets.token_hex(12)
    unik_nik = sorted({r["nik"] for r in rows if len(r["nik"]) == 16})
    unik_kk = sorted({r["kk"] for r in rows if len(r["kk"]) == 16})
    pekerjaan = [(salt, "nik", v) for v in unik_nik] + [(salt, "kk", v) for v in unik_kk]
    with ProcessPoolExecutor() as pool:
        hasil = list(pool.map(_hash, pekerjaan, chunksize=64))
    hnik = dict(zip(unik_nik, hasil[: len(unik_nik)]))
    hkk = dict(zip(unik_kk, hasil[len(unik_nik):]))

    keluaran = []
    for r in rows:
        keluaran.append([
            judul(r["nama"]),
            samar(r["nik"]),
            samar(r["kk"]),
            hnik.get(r["nik"], ""),
            hkk.get(r["kk"], ""),
            r["usia"],
            r["jk"] if r["jk"] in ("L", "P") else "",
            r["rt"],
            r["rw"],
        ])

    per_rw = Counter(r["rw"] for r in rows)
    per_rt = Counter(r["rw"] + "/" + r["rt"] for r in rows if r["rt"])
    data = {
        "meta": {
            "desa": "Desa Kasomalang Kulon",
            "kecamatan": "Kasomalang",
            "kabupaten": "Subang",
            "tahun": 2026,
            "sumber": os.path.basename(src),
            "dibuat": datetime.date.today().isoformat(),
            "salt": salt,
            "iter": ITER,
            "jumlah": len(rows),
            "baris": dibaca,
            "ganda": ganda,
            "nikDobel": len(dobel_nik),
            "kk": len(unik_kk),
            "pria": sum(1 for r in rows if r["jk"] == "L"),
            "wanita": sum(1 for r in rows if r["jk"] == "P"),
            "perRw": dict(sorted(per_rw.items())),
            "perRt": dict(sorted(per_rt.items())),
        },
        "rows": keluaran,
    }

    tujuan = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
    with open(tujuan, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    laporan = tulis_laporan(os.path.dirname(os.path.abspath(__file__)), bajakan, usia_melenceng)

    print(f"Baris dibaca     : {dibaca}")
    print(f"  dari sheet RW  : {dari_rw}")
    print(f"  dari TAMBAHAN  : {dibaca - dari_rw}")
    print(f"Pemilih unik     : {len(rows)}  ({ganda} baris ganda dibuang)")
    print(f"Kartu Keluarga   : {len(unik_kk)}")
    print(f"NIK tidak valid  : {sum(1 for r in rows if len(r['nik']) != 16)}")
    print(f"Tanpa No. KK     : {sum(1 for r in rows if len(r['kk']) != 16)}")
    print(f"Usia di luar {USIA_MIN}-{USIA_MAKS} : {sum(1 for r in rows if r['usia'] and not (USIA_MIN <= int(r['usia']) <= USIA_MAKS))}")
    print(f"Usia vs NIK beda : {len(usia_melenceng)}")
    print(f"L / P            : {data['meta']['pria']} / {data['meta']['wanita']}")
    print("Per RW           : " + ", ".join(f"{k}={v}" for k, v in sorted(per_rw.items())))
    print(f"Ukuran data.json : {os.path.getsize(tujuan) / 1024:.0f} KB -> {tujuan}")
    if laporan:
        print(f"Laporan duplikat : {laporan}")


if __name__ == "__main__":
    main()
