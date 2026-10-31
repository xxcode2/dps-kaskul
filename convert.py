#!/usr/bin/env python3
"""Ubah data DPS (XLSX/CSV) menjadi data.json yang aman dipublikasikan.

Semua sheet yang terlihat dan punya kolom NAMA + NIK akan digabung. Sheet
tersembunyi dan sheet rekap (contoh: "Sheet1") otomatis dilewati.

Pakai:
    python convert.py "DAFTAR PEMILIH SEMENTARA (2).xlsx"

Butuh: pip install openpyxl   (hanya untuk XLSX)

Yang dilakukan skrip ini:
  * membaca sheet yang terlihat dan melewati sheet tersembunyi
  * merapikan RT/RW jadi 3 digit dan menebak RW dari nama sheet
  * membuang baris ganda (satu NIK = satu pemilih)
  * menyamarkan NIK / No. KK (hanya sebagian digit yang tampil)
  * menyimpan sidik jari (PBKDF2) NIK & KK agar pencarian tetap bisa
    dilakukan tanpa menyimpan nomor aslinya
  * menulis data.json ringkas (array, bukan objek, supaya file kecil)

JANGAN upload file XLSX/CSV ke hosting. Hanya data.json.
"""
import csv
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
        if sheet.sheet_state != "visible":
            continue
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
                "tambahan": "TAMBAHAN" in sheet.title.upper(),
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


def tulis_laporan(folder, bajakan):
    """Laporan lokal tanpa NIK/KK mentah supaya panitia bisa cek data ganda."""
    if not bajakan:
        return
    try:
        import openpyxl
    except ImportError:
        return
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Duplikat"
    ws.append([
        "No.", "Nama baris duplikat", "RW duplikat", "RT duplikat",
        "Sheet duplikat", "Nama acuan (dipertahankan)", "RW acuan",
        "RT acuan", "Sheet acuan", "Status NIK", "Status No. KK",
        "Dasar penggabungan",
    ])
    nomor = 0
    for jenis, *isi in bajakan:
        if jenis != "ganda":
            continue
        simpan, buang = isi
        nomor += 1
        nik_sama = len(simpan["nik"]) == len(buang["nik"]) == 16 and simpan["nik"] == buang["nik"]
        kk_sama = len(simpan["kk"]) == len(buang["kk"]) == 16 and simpan["kk"] == buang["kk"]
        status_nik = ("Sama" if nik_sama else "Berbeda" if len(simpan["nik"]) == len(buang["nik"]) == 16
                      else "Tidak lengkap")
        status_kk = ("Sama" if kk_sama else "Berbeda" if len(simpan["kk"]) == len(buang["kk"]) == 16
                     else "Tidak lengkap")
        if nik_sama:
            dasar = "NIK sama; nama cocok menurut aturan konverter"
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

    konflik = wb.create_sheet("NIK beda nama")
    konflik.append(["Nama dan lokasi", "Jumlah nama berbeda", "Catatan"])
    for jenis, *isi in bajakan:
        if jenis != "nik-dobel":
            continue
        kantong = isi[0]
        rincian = []
        for _, daftar in kantong:
            r = daftar[0]
            rincian.append(f"{judul(r['nama'])} — RW {r['rw']}, RT {r['rt']} ({r['sheet']})")
        konflik.append([
            " | ".join(rincian), len(kantong),
            "Periksa dokumen sumber; nomor identitas tidak dicantumkan dalam laporan.",
        ])
    konflik.freeze_panes = "A2"
    konflik.auto_filter.ref = konflik.dimensions
    for kolom, lebar in zip("ABC", (100, 24, 72)):
        konflik.column_dimensions[kolom].width = lebar

    wb.save(os.path.join(folder, f"laporan-duplikat-{nomor}.xlsx"))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    mentah = baca_xlsx(src) if src.lower().endswith((".xlsx", ".xlsm")) else baca_csv(src)

    # satu NIK bisa saja dipakai dua orang berbeda (salah input). Baris seperti
    # itu JANGAN digabung, cukup dicatat di laporan untuk dicek panitia.
    kelompok = defaultdict(list)
    for r in mentah:
        kelompok[kunci(r)].append(r)
    bajakan = []                                     # catatan untuk laporan lokal
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
    ganda = len(mentah) - len(rows)

    # buang baris tanpa wilayah sama sekali
    rows = [r for r in rows if r["rw"]]
    rows.sort(key=lambda r: (r["rw"], r["rt"], r["nama"]))

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
            "dibuat": __import__("datetime").date.today().isoformat(),
            "salt": salt,
            "iter": ITER,
            "jumlah": len(rows),
            "baris": len(mentah),
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

    tulis_laporan(os.path.dirname(os.path.abspath(__file__)), bajakan)

    print(f"Baris dibaca     : {len(mentah)}")
    print(f"  dari sheet RW  : {sum(1 for r in mentah if not r['tambahan'])}")
    print(f"  dari TAMBAHAN  : {sum(1 for r in mentah if r['tambahan'])}")
    print(f"Pemilih unik     : {len(rows)}  ({ganda} baris ganda dibuang)")
    print(f"Kartu Keluarga   : {len(unik_kk)}")
    print(f"NIK tidak valid  : {sum(1 for r in rows if len(r['nik']) != 16)}")
    print(f"Tanpa No. KK     : {sum(1 for r in rows if len(r['kk']) != 16)}")
    print(f"Usia di luar {USIA_MIN}-{USIA_MAKS} : {sum(1 for r in rows if r['usia'] and not (USIA_MIN <= int(r['usia']) <= USIA_MAKS))}")
    print(f"L / P            : {data['meta']['pria']} / {data['meta']['wanita']}")
    print("Per RW           : " + ", ".join(f"{k}={v}" for k, v in sorted(per_rw.items())))
    print(f"Ukuran data.json : {os.path.getsize(tujuan) / 1024:.0f} KB -> {tujuan}")


if __name__ == "__main__":
    main()
