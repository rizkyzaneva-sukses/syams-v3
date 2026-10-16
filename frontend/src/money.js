/* Format Rupiah untuk seluruh aplikasi (permintaan pemilik 16 Okt 2026):
   angka yang diketik otomatis tampil sebagai "Rp. 1.000.000". Nilai yang dikirim ke server
   tetap angka polos; hanya tampilan yang diformat. Rupiah tidak memakai desimal. */

/* Angka → "Rp. 1.000.000". Kosong/NaN → "Rp. 0". Negatif tetap ditampilkan ("-Rp. 5.000"). */
export function formatRupiah(value) {
  const number = Math.round(Number(value) || 0);
  const digits = String(Math.abs(number)).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  return (number < 0 ? '-' : '') + 'Rp. ' + digits;
}

/* Teks bebas yang diketik pengguna → string digit murni ("Rp. 1.000.000" → "1000000").
   Titik/koma pemisah dibuang; hasil kosong bila tidak ada angka. */
export function digitsOnly(text) {
  return String(text ?? '').replace(/\D/g, '').replace(/^0+(?=\d)/, '');
}

/* Nilai dari state/API → string digit. Angka desimal dari server ("20000000.00", 1500.6) dibulatkan;
   string lain diperlakukan sebagai teks ketikan (hanya digit yang dipakai). */
export function normalizeMoney(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? String(Math.round(value)) : '';
  const text = String(value ?? '').trim();
  if (/^\d+\.\d{1,2}$/.test(text)) return String(Math.round(Number(text)));
  return digitsOnly(text);
}

/* String digit → teks input. Kosong tetap kosong supaya placeholder terlihat. */
export function rupiahInputText(digits) {
  const clean = normalizeMoney(digits);
  return clean === '' ? '' : formatRupiah(clean);
}

/* Nilai dari <MoneyInput> (string digit) → angka untuk API; kosong = 0. */
export function rupiahNumber(digits) {
  const clean = normalizeMoney(digits);
  return clean === '' ? 0 : Number(clean);
}

/* Sisa Tagihan = Jumlah Tagihan − DP, tidak pernah negatif. */
export function sisaTagihan(amount, dp) {
  return Math.max(0, rupiahNumber(amount) - rupiahNumber(dp));
}

/* DP tidak boleh melebihi tagihan. */
export function dpValid(amount, dp) {
  return rupiahNumber(dp) >= 0 && rupiahNumber(dp) <= rupiahNumber(amount);
}
