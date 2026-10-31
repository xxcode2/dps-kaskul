/* =========================================================
   DPS Pilkades · Desa Kasomalang Kulon
   Semua logika ada di sini: daftar, filter, dan cek NIK/KK.
   ========================================================= */

const CFG = {
  wa: "6281234567890",     // WhatsApp panitia (format 62…). Kosongkan "" untuk menyembunyikan tombol.
  perHalaman: 30,
  judul: "Cek DPS Pilkades · Desa Kasomalang Kulon",
};

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const I = { N: 0, NIK: 1, KK: 2, HN: 3, HK: 4, U: 5, JK: 6, RT: 7, RW: 8 };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => Number(n).toLocaleString("id-ID");
const norm = (s) => String(s ?? "").toLowerCase().normalize("NFD")
  .replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
const dua = (x) => (x && x.length === 3 && x[0] === "0" ? x.slice(1) : x || "–");
const tanggal = (iso) => {
  try {
    return new Date(iso + "T00:00:00").toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric" });
  } catch { return iso; }
};

const S = { rw: "", rt: "", tokens: [], total: 0, shown: 0, hasil: [], animate: true };
let META = null, ROWS = [], NAMA = [], byNik = new Map(), byKk = new Map();
let siap = false;

/* ---------------- util tampilan ---------------- */

function chipHTML(label, jumlah, aktif, nilai) {
  return `<button class="chip" type="button" data-nilai="${esc(nilai)}" aria-pressed="${aktif}">
    ${esc(label)}${jumlah != null ? `<small>${fmt(jumlah)}</small>` : ""}
  </button>`;
}

function potonganMeta(r) {
  const bagian = [];
  bagian.push(r[I.NIK] ? `<span class="nik">${esc(r[I.NIK])}</span>` : `<span class="nik">NIK belum tercatat</span>`);
  const wil = r[I.RT] ? `RT ${dua(r[I.RT])} / RW ${dua(r[I.RW])}` : `RW ${dua(r[I.RW])}`;
  bagian.push(`<b>${wil}</b>`);
  const u = Number(r[I.U]);
  if (u >= 17 && u <= 105) bagian.push(`<span class="umur">${u} th</span>`);
  return `<p class="meta">${bagian.join(" ")}</p>`;
}

function sorot(nama, tokens) {
  if (!tokens.length) return esc(nama);
  const pola = tokens.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).filter(Boolean).sort((a, b) => b.length - a.length);
  if (!pola.length) return esc(nama);
  const re = new RegExp(`(${pola.join("|")})`, "gi");
  return String(nama).split(re).map((s, i) => (i % 2 ? `<mark>${esc(s)}</mark>` : esc(s))).join("");
}

function barisHTML(r, nomor, tokens, opsi = {}) {
  const kelas = ["row"];
  if (opsi.fam) kelas.push("fam");
  if (opsi.utama) kelas.push("utama");
  const nomorTeks = opsi.utama ? "✓" : String(nomor).padStart(2, "0");
  return `<li class="${kelas.join(" ")}" style="--i:${opsi.i ?? 0}">
    <span class="no">${nomorTeks}</span>
    <div>
      <p class="nm">${sorot(r[I.N], tokens)}</p>
      ${potonganMeta(r)}
    </div>
    <span class="sex" data-sex="${esc(r[I.JK])}">${esc(r[I.JK])}</span>
  </li>`;
}

/* ---------------- memuat data ---------------- */

function skeleton() {
  const bar = (w, h = 12) => `<span class="sk-b" style="display:block;width:${w};height:${h}px"></span>`;
  $("#list").innerHTML = `<li class="sk">${Array.from({ length: 6 }, () => `
    <div class="sk-row"><span class="sk-b" style="width:30px;height:30px;border-radius:10px"></span>
    <div style="display:grid;gap:7px">${bar("62%")}${bar("42%", 10)}</div></div>`).join("")}</li>`;
  $("#hasil-info").textContent = "Memuat data…";
}

fetch("data.json", { cache: "no-cache" })
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then(mulai)
  .catch(() => {
    $("#list").innerHTML = "";
    $("#empty").hidden = false;
    $("#empty-title").textContent = "Data belum bisa dimuat";
    $("#empty-text").textContent = "Periksa koneksi internet, lalu muat ulang halaman ini.";
    $("#hasil-info").textContent = "Gagal memuat data";
  });

function mulai(data) {
  META = data.meta;
  ROWS = data.rows;
  NAMA = ROWS.map((r) => norm(r[I.N]));

  ROWS.forEach((r) => {
    if (r[I.HN]) {
      if (!byNik.has(r[I.HN])) byNik.set(r[I.HN], []);
      byNik.get(r[I.HN]).push(r);
    }
    if (r[I.HK]) {
      if (!byKk.has(r[I.HK])) byKk.set(r[I.HK], []);
      byKk.get(r[I.HK]).push(r);
    }
  });

  document.title = CFG.judul;
  siap = true;

  /* angka utama */
  const rwList = Object.keys(META.perRw || {});
  hitung($("#st-pemilih"), META.jumlah);
  hitung($("#st-kk"), META.kk);
  hitung($("#st-rw"), rwList.length);

  $("#info-jumlah").textContent = fmt(META.jumlah);
  if ($("#info-baris")) $("#info-baris").textContent = fmt(META.baris || 0);
  if ($("#info-ganda")) $("#info-ganda").textContent = fmt(META.ganda || 0);
  const dobel = $("#info-dobel");
  if (dobel && META.nikDobel) {
    dobel.hidden = false;
    dobel.textContent = `Catatan: ${fmt(META.nikDobel)} NIK tercatat untuk dua nama berbeda (kemungkinan salah ketik di berkas). Kedua nama itu tetap ditampilkan agar tidak ada warga yang hilang dari daftar.`;
  }
  $("#info-update").textContent = `Data ini disusun dari berkas ${META.sumber || "DPS"} dan terakhir disiapkan pada ${tanggal(META.dibuat)}. Kalau panitia memperbarui data, halaman ini ikut diperbarui.`;
  $("#note-meta").textContent = `${fmt(META.jumlah)} pemilih · ${fmt(META.kk)} KK · ${rwList.length} RW · diperbarui ${tanggal(META.dibuat)}`;

  const wa = `https://wa.me/?text=${encodeURIComponent(`${CFG.judul} — cek nama kamu di DPS Desa Kasomalang Kulon: `)}`;
  $("#wa-share").href = wa + encodeURIComponent(location.href);

  buatChipsRw();
  $("#empty").hidden = true;
  pakaiFilter(true);
}

/* animasi angka naik */
function hitung(el, target) {
  const akhir = Number(target) || 0;
  const ringan = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (ringan || akhir === 0 || document.hidden) { el.textContent = fmt(akhir); return; }
  const durasi = 950, mulaiWaktu = performance.now();
  let selesai = false;
  // jaring pengaman: kalau animasi tidak jalan (tab latar/hemat daya), isi angka akhir
  const cadangan = setTimeout(() => { if (!selesai) el.textContent = fmt(akhir); }, 1400);
  const langkah = (now) => {
    const p = Math.min(1, (now - mulaiWaktu) / durasi);
    const e = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(Math.round(akhir * e));
    if (p < 1) requestAnimationFrame(langkah);
    else { selesai = true; clearTimeout(cadangan); }
  };
  requestAnimationFrame(langkah);
}

/* ---------------- filter wilayah ---------------- */

function buatChipsRw() {
  const per = META.perRw || {};
  const kunci = Object.keys(per).sort();
  $("#rw-chips").innerHTML =
    chipHTML("Semua", META.jumlah, !S.rw, "") +
    kunci.map((rw) => chipHTML(`RW ${dua(rw)}`, per[rw], S.rw === rw, rw)).join("");

  $$("#rw-chips .chip").forEach((b) => b.addEventListener("click", () => {
    S.rw = b.dataset.nilai;
    S.rt = "";
    pakaiFilter(true);
  }));
}

function buatChipsRt() {
  const box = $("#rt-chips");
  if (!S.rw) { box.hidden = true; box.innerHTML = ""; return; }
  const per = META.perRt || {};
  const kunci = Object.keys(per).filter((k) => k.startsWith(S.rw + "/")).map((k) => k.split("/")[1]).sort();
  if (kunci.length < 2) { box.hidden = true; box.innerHTML = ""; S.rt = ""; return; }
  box.hidden = false;
  box.innerHTML =
    chipHTML("Semua RT", ROWS.reduce((n, r) => n + (r[I.RW] === S.rw ? 1 : 0), 0), !S.rt, "") +
    kunci.map((rt) => chipHTML(`RT ${dua(rt)}`, per[`${S.rw}/${rt}`], S.rt === rt, rt)).join("");
  $$("#rt-chips .chip").forEach((b) => b.addEventListener("click", () => {
    S.rt = b.dataset.nilai;
    pakaiFilter(true);
  }));
}

function segarkanChips() {
  $$("#rw-chips .chip").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.nilai === S.rw)));
  $$("#rt-chips .chip").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.nilai === S.rt)));

  // geser chip aktif ke tengah supaya tidak tersembunyi di layar HP
  if (innerWidth < 860) {
    [["#rw-chips", S.rw], ["#rt-chips", S.rt]].forEach(([sel, nilai]) => {
      const box = $(sel);
      const aktif = box.querySelector(`.chip[data-nilai="${nilai}"]`);
      if (!aktif || box.hidden) return;
      box.scrollTo({ left: aktif.offsetLeft - box.clientWidth / 2 + aktif.offsetWidth / 2, behavior: "smooth" });
    });
  }
  $("#reset").hidden = !S.rw;
  const label = [S.rw && `RW ${dua(S.rw)}`, S.rt && `RT ${dua(S.rt)}`].filter(Boolean).join(" · ");
  const badge = $("#filter-badge");
  badge.hidden = !label;
  badge.textContent = label;
}

/* ---------------- daftar pemilih ---------------- */

function pakaiFilter(animasi) {
  S.tokens = norm($("#q").value).split(" ").filter(Boolean);
  const hasil = [];
  for (let i = 0; i < ROWS.length; i++) {
    const r = ROWS[i];
    if (S.rw && r[I.RW] !== S.rw) continue;
    if (S.rt && r[I.RT] !== S.rt) continue;
    if (S.tokens.length) {
      let cocok = true;
      for (const t of S.tokens) { if (!NAMA[i].includes(t)) { cocok = false; break; } }
      if (!cocok) continue;
    }
    hasil.push(i);
  }
  S.hasil = hasil;
  S.total = hasil.length;
  S.shown = 0;
  S.animate = animasi !== false;
  buatChipsRt();
  segarkanChips();
  renderAwal();
}

function renderAwal() {
  const list = $("#list");
  list.innerHTML = "";
  list.classList.toggle("no-anim", !S.animate);
  $("#more").hidden = true;

  const kosong = S.total === 0;
  $("#empty").hidden = !kosong;
  if (kosong) {
    const adaCari = S.tokens.length > 0 || S.rw;
    $("#empty-title").textContent = adaCari ? "Nama tidak ditemukan" : "Daftar masih kosong";
    $("#empty-text").textContent = adaCari
      ? "Coba ejaan lain, atau cek lewat NIK / No. KK."
      : "Belum ada data pemilih yang bisa ditampilkan.";
  }

  muatLagi();
  perbaruiInfo();
}

function muatLagi() {
  const sisa = S.total - S.shown;
  const ambil = Math.min(CFG.perHalaman, sisa);
  const html = [];
  for (let k = 0; k < ambil; k++) {
    const idx = S.hasil[S.shown + k];
    html.push(barisHTML(ROWS[idx], S.shown + k + 1, S.tokens, { i: Math.min(k, 12) }));
  }
  $("#list").insertAdjacentHTML("beforeend", html.join(""));
  S.shown += ambil;

  const more = $("#more");
  const sisaBaru = S.total - S.shown;
  more.hidden = sisaBaru <= 0;
  if (sisaBaru > 0) $("#more-label").textContent = `Tampilkan ${fmt(Math.min(CFG.perHalaman, sisaBaru))} nama lagi`;
  perbaruiInfo();
}

function perbaruiInfo() {
  const info = $("#hasil-info");
  if (!siap) return;
  const wil = [S.rw && `RW ${dua(S.rw)}`, S.rt && `RT ${dua(S.rt)}`].filter(Boolean).join(" · ");
  if (S.total === 0) {
    info.textContent = "Tidak ada hasil untuk pencarian ini";
  } else if (S.tokens.length) {
    info.textContent = `${fmt(S.total)} hasil${wil ? ` di ${wil}` : ""} untuk “${$("#q").value.trim()}”` +
      (S.shown < S.total ? ` · ${fmt(S.shown)} ditampilkan` : "");
  } else {
    info.textContent = `${fmt(S.total)} pemilih${wil ? ` di ${wil}` : ""}` +
      (S.shown < S.total ? ` · ${fmt(S.shown)} ditampilkan` : " seluruhnya");
  }
  $("#bar-fill").style.width = `${S.total ? (S.shown / S.total) * 100 : 0}%`;
}

$("#more").addEventListener("click", () => { S.animate = true; $("#list").classList.remove("no-anim"); muatLagi(); });

$("#q").addEventListener("input", (e) => {
  $("#clear").hidden = !e.target.value;
  bersih(() => pakaiFilter(false), 110);
});

$("#clear").addEventListener("click", () => {
  const q = $("#q");
  q.value = "";
  $("#clear").hidden = true;
  pakaiFilter(true);
  q.focus();
});

$("#reset").addEventListener("click", () => {
  S.rw = ""; S.rt = "";
  pakaiFilter(true);
});

function bersih(fn, tunda) {
  clearTimeout(bersih.t);
  bersih.t = setTimeout(fn, tunda);
}

/* ---------------- cek NIK / No. KK ---------------- */

const dlg = $("#cek");
let mode = "nik";

function bukaCek() {
  dlg.showModal();
  setTimeout(() => { const s = $("#nomor"); s.focus({ preventScroll: true }); }, 260);
}

$("#open-cek").addEventListener("click", bukaCek);
$$("[data-open-cek]").forEach((b) => b.addEventListener("click", bukaCek));
$("#close-cek").addEventListener("click", () => dlg.close());
dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });

$$(".seg button").forEach((b) => b.addEventListener("click", () => {
  mode = b.dataset.mode;
  $$(".seg button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
  $("#nomor-label").textContent = mode === "nik" ? "NIK (16 digit)" : "Nomor KK (16 digit)";
  $("#nomor").value = "";
  $("#nomor").removeAttribute("aria-invalid");
  $("#cek-hint").className = "hint";
  $("#cek-hint").textContent = mode === "nik"
    ? "Ketik 16 digit sesuai KTP. Spasi otomatis ditambahkan."
    : "Ketik No. KK lengkap untuk melihat seluruh anggota keluarga.";
  $("#cek-out").innerHTML = "";
  $("#nomor").focus();
}));

$("#nomor").addEventListener("input", (e) => {
  const digit = e.target.value.replace(/\D/g, "").slice(0, 16);
  e.target.value = digit.replace(/(\d{4})(?=\d)/g, "$1 ");
  e.target.removeAttribute("aria-invalid");
  if ($("#cek-hint").classList.contains("err")) {
    $("#cek-hint").className = "hint";
    $("#cek-hint").textContent = mode === "nik"
      ? "Ketik 16 digit sesuai KTP. Spasi otomatis ditambahkan."
      : "Ketik No. KK lengkap untuk melihat seluruh anggota keluarga.";
  }
});

async function jari(kind, nilai) {
  const enc = new TextEncoder();
  const kunci = await crypto.subtle.importKey("raw", enc.encode(`${kind}:${nilai}`), "PBKDF2", false, ["deriveBits"]);
  const bit = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt: enc.encode(META.salt), iterations: META.iter, hash: "SHA-256" }, kunci, 128);
  return [...new Uint8Array(bit)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

$("#cek-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const isi = $("#nomor");
  const nilai = isi.value.replace(/\D/g, "");
  const out = $("#cek-out");
  if (nilai.length !== 16) {
    isi.setAttribute("aria-invalid", "true");
    $("#cek-hint").className = "hint err";
    $("#cek-hint").textContent = `Kurang ${16 - nilai.length} digit lagi. Pastikan nomornya 16 digit.`;
    isi.focus();
    return;
  }
  if (!siap) return;
  if (!crypto?.subtle) {
    out.innerHTML = kotakSalah("Peramban belum mendukung", "Buka halaman ini lewat Chrome, Safari, atau Edge terbaru dengan alamat https.");
    return;
  }

  const tombol = $("#cek-submit");
  tombol.classList.add("loading");
  tombol.querySelector(".lbl").textContent = "Mencocokkan…";
  out.innerHTML = "";
  try {
    const h = await jari(mode, nilai);
    await new Promise((r) => setTimeout(r, 120));
    if (mode === "nik") {
      const daftar = byNik.get(h) || [];
      if (!daftar.length) out.innerHTML = kotakSalah("NIK tidak ditemukan di DPS",
        "Periksa kembali angkanya. Kalau sudah benar tapi tetap tidak muncul, kemungkinan datanya belum masuk atau NIK-nya belum lengkap di berkas panitia.");
      else tampilNik(daftar);
    } else {
      const fam = byKk.get(h);
      if (!fam || !fam.length) out.innerHTML = kotakSalah("No. KK tidak ditemukan di DPS",
        "Periksa kembali angkanya, atau cari satu per satu lewat NIK masing-masing anggota keluarga.");
      else tampilKk(fam);
    }
    out.scrollIntoView({ block: "nearest", behavior: "smooth" });
  } catch (err) {
    out.innerHTML = kotakSalah("Gagal mencocokkan data", "Coba lagi sebentar. Kalau terus gagal, buka halaman ini lewat alamat https.");
  } finally {
    tombol.classList.remove("loading");
    tombol.querySelector(".lbl").textContent = "Cek data";
  }
});

function tag(teks, kelas = "") {
  return `<span class="tag ${kelas}">${esc(teks)}</span>`;
}

function tagOrang(r) {
  const keluar = [];
  const wil = r[I.RT] ? `RT ${dua(r[I.RT])} / RW ${dua(r[I.RW])}` : `RW ${dua(r[I.RW])}`;
  keluar.push(tag(wil));
  if (r[I.JK]) keluar.push(tag(r[I.JK] === "L" ? "Laki-laki" : "Perempuan"));
  const u = Number(r[I.U]);
  if (u >= 17 && u <= 105) keluar.push(tag(`${u} tahun`));
  else if (r[I.U]) keluar.push(tag(`Usia ${r[I.U]} · perlu dicek`, "warn"));
  else keluar.push(tag("Usia belum tercatat", "warn"));
  return keluar.join("");
}

function kotakSalah(judul, isi) {
  const wa = CFG.wa
    ? `<a class="btn btn-wa" target="_blank" rel="noopener" href="https://wa.me/${CFG.wa}?text=${encodeURIComponent("Halo panitia, saya ingin menanyakan data DPS saya.")}">Tanya panitia</a>`
    : "";
  return `<div class="notfound"><h3>${esc(judul)}</h3><p>${esc(isi)}</p>${wa}</div>`;
}

function kartuOrang(r) {
  return `<div class="found">
      <span class="found-tag"><svg viewBox="0 0 24 24"><path d="M5 13l4 4 10-11"/></svg>Terdaftar di DPS</span>
      <h3>${esc(r[I.N])}</h3>
      <div class="nums">
        <span>NIK ${esc(r[I.NIK] || "belum tercatat")}</span>
        <span>KK&nbsp; ${esc(r[I.KK] || "belum tercatat")}</span>
      </div>
      <div class="tags">${tagOrang(r)}</div>
    </div>`;
}

function tampilNik(daftar) {
  const r = daftar[0];
  if (daftar.length > 1) {
    /* satu NIK tercatat untuk lebih dari satu nama (salah input di berkas panitia) */
    $("#cek-out").innerHTML = `
      <p class="cat-nik">NIK ini tercatat pada ${daftar.length} data berbeda di berkas panitia. Semuanya ditampilkan supaya tidak ada yang terlewat — mohon dikonfirmasi ke panitia.</p>
      ${daftar.map(kartuOrang).join("")}`;
    return;
  }

  const fam = byKk.get(r[I.HK]) || [];
  const lain = fam.filter((x) => x !== r);
  $("#cek-out").innerHTML = `${kartuOrang(r)}
    ${lain.length ? `<button class="btn btn-ghost btn-block" type="button" id="lihat-fam">Lihat ${lain.length + 1} anggota keluarga</button>` : ""}
    <div id="fam-wrap"></div>`;

  const b = $("#lihat-fam");
  if (b) {
    b.addEventListener("click", () => {
      $("#fam-wrap").innerHTML = `
        <div class="kepala">
          <div><h3>Anggota keluarga</h3><p>Satu Kartu Keluarga di DPS</p></div>
          <span class="count">${fam.length}</span>
        </div>
        <div class="fam-list" style="margin-top:8px"><ul>${fam.map((x, i) => barisHTML(x, i + 1, [], { fam: true, utama: x === r })).join("")}</ul></div>`;
      b.remove();
      $("#fam-wrap").scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  }
}

function tampilKk(fam) {
  const l = fam.filter((x) => x[I.JK] === "L").length;
  const p = fam.filter((x) => x[I.JK] === "P").length;
  $("#cek-out").innerHTML = `
    <div class="kepala">
      <div><h3>Keluarga dengan No. KK ini</h3><p>${fam.length} anggota terdaftar · ${l} laki-laki, ${p} perempuan</p></div>
      <span class="count">${fam.length}</span>
    </div>
    <div class="fam-list"><ul>${fam.map((x, i) => barisHTML(x, i + 1, [], { fam: true })).join("")}</ul></div>`;
}

/* ---------------- tautan & interaksi kecil ---------------- */

$("#copy-link").addEventListener("click", async () => {
  const b = $("#copy-link");
  const asli = b.textContent;
  try {
    await navigator.clipboard.writeText(location.href);
    b.textContent = "Tersalin!";
  } catch {
    b.textContent = "Gagal menyalin";
  }
  setTimeout(() => { b.textContent = asli; }, 1800);
});

/* dock menempel + tombol ke atas */
const dock = $("#dock"), toTop = $("#to-top");
let menempel = false, dekatBawah = false;
function aturToTop(y) {
  toTop.hidden = y < 900 || dekatBawah;
}
const pengamat = new IntersectionObserver((entries) => {
  dekatBawah = entries.some((e) => e.isIntersecting);
  aturToTop(scrollY);
}, { rootMargin: "0px 0px -24px 0px" });
const sasaran = [$("footer")].filter(Boolean);
sasaran.forEach((el) => pengamat.observe(el));

let tickTerakhir = 0;
addEventListener("scroll", () => {
  if (tickTerakhir) return;
  tickTerakhir = requestAnimationFrame(() => {
    tickTerakhir = 0;
    const y = scrollY;
    const tempel = y > 60 && dock.getBoundingClientRect().top <= 2;
    if (tempel !== menempel) { menempel = tempel; dock.classList.toggle("is-stuck", tempel); }
    aturToTop(y);
  });
}, { passive: true });

toTop.addEventListener("click", () => scrollTo({ top: 0, behavior: "smooth" }));

skeleton();
