/* Ukuran standar BOS SYAMS (permintaan Bos 16 Okt 2026): XS, S, M, L, XL,
   XXL, XXXL, XXXXL. Dipusatkan di sini supaya form PO & Draft Order memakai
   daftar yang sama dan operator tidak perlu mengetik ukuran manual.

   Format penyimpanan tetap string "SIZE:qty" dipisah koma (mis.
   "S:10, M:20") — sama dengan data lama & seed, jadi tidak ada migrasi DB. */

export const SIZES = ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL', 'XXXXL'];

/* Terima angka ukuran juga (mis. 30, 32) supaya data lama berbasis angka tetap
   terbaca dan bisa ditampilkan sebagai baris tersendiri. */
export function parseSizeBreakdown(value) {
  const map = {};
  if (value && typeof value === 'object') {
    for (const [size, qty] of Object.entries(value)) {
      const n = Number(qty);
      if (size) map[String(size).toUpperCase()] = Number.isFinite(n) ? n : 0;
    }
    return map;
  }
  for (const part of String(value || '').split(/[,;\n]/)) {
    const [rawSize, rawQty] = part.split(':');
    const size = (rawSize || '').trim().toUpperCase();
    if (!size) continue;
    const n = Number((rawQty || '').trim());
    map[size] = Number.isFinite(n) ? n : 0;
  }
  return map;
}

/* Serialisasi ke "S:10, M:20". Baris ber-qty kosong/0 dibuang; urutan mengikuti
   SIZES lalu ukuran tak dikenal (mis. angka dari data lama) di belakang. */
export function serializeSizeBreakdown(map) {
  const known = SIZES.filter(size => map[size] > 0);
  const extra = Object.keys(map).filter(size => !SIZES.includes(size) && map[size] > 0).sort();
  return [...known, ...extra].map(size => `${size}:${map[size]}`).join(', ');
}

/* Total pcs dari seluruh ukuran. */
export function sizeBreakdownTotal(value) {
  return Object.values(parseSizeBreakdown(value)).reduce((sum, qty) => sum + (Number(qty) || 0), 0);
}

/* Daftar ukuran untuk baris input: ukuran standar + ukuran tak dikenal yang
   sudah terisi di data lama, supaya tidak hilang saat diedit. */
export function sizeRows(value, extraSizes) {
  const map = parseSizeBreakdown(value);
  const extras = (extraSizes || []).map(s => String(s).toUpperCase())
    .filter(s => s && !SIZES.includes(s));
  const fromData = Object.keys(map).filter(s => !SIZES.includes(s));
  return [...SIZES, ...[...new Set([...extras, ...fromData])]];
}
