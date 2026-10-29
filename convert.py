#!/usr/bin/env python3
"""Ubah data DPS (CSV/XLSX) menjadi data.json AMAN untuk dipublikasikan.
Pakai:  python3 convert.py data-dps.xlsx      (XLSX butuh: pip install openpyxl)
Kolom wajib (baris pertama): nama, nik, kk   Opsional: rt, rw, tps
JANGAN upload file sumber (csv/xlsx) ke Vercel. Hanya upload data.json."""
import csv, json, re, sys, secrets, hashlib

ITER = 100000      # makin besar makin sulit ditebak, harus sama dengan yang tertulis di data.json
AWAL, AKHIR = 4, 3  # jumlah digit yang ditampilkan di awal dan di ujung

def pad(x):
    x = re.sub(r"\.0$", "", str(x if x is not None else "").strip())
    return x.zfill(2) if x.isdigit() else x
def digit(x): return re.sub(r"\D", "", str(x if x is not None else ""))
def samar(x): return x[:AWAL] + "*" * (len(x) - AWAL - AKHIR) + x[-AKHIR:]
def hsh(salt, kind, val):
    return hashlib.pbkdf2_hmac("sha256", f"{kind}:{val}".encode(), salt.encode(), ITER).hex()

def baca(path):
    if path.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        it = openpyxl.load_workbook(path, read_only=True, data_only=True).active.iter_rows(values_only=True)
        kepala = [str(c or "").strip().lower() for c in next(it)]
        return [dict(zip(kepala, r)) for r in it]
    with open(path, encoding="utf-8-sig", newline="") as f:
        s = f.read(); d = csv.Sniffer().sniff(s[:2000], delimiters=",;\t")
        return [{(k or "").strip().lower(): v for k, v in r.items()} for r in csv.DictReader(s.splitlines(), delimiter=d.delimiter)]

def main():
    if len(sys.argv) < 2: sys.exit(__doc__)
    salt = secrets.token_hex(12); rows = []; kk_cache = {}; lewat = 0
    for r in baca(sys.argv[1]):
        nama = str(r.get("nama") or "").strip(); nik = digit(r.get("nik")); kk = digit(r.get("kk"))
        if not nama or len(nik) != 16 or len(kk) != 16:
            lewat += 1; print(f"DILEWATI (nama/NIK/KK tidak valid): {nama or '(kosong)'}"); continue
        if kk not in kk_cache: kk_cache[kk] = hsh(salt, "kk", kk)
        rows.append({"n": nama, "nk": samar(nik), "kk": samar(kk), "hn": hsh(salt, "nik", nik), "hk": kk_cache[kk],
                     "rt": pad(r.get("rt")), "rw": pad(r.get("rw")), "t": str(r.get("tps") or "").strip()})
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump({"salt": salt, "iter": ITER, "rows": rows}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Selesai: {len(rows)} pemilih, {len(kk_cache)} KK, {lewat} dilewati -> data.json")
main()
