/* Kalkulator harga jual & penomoran invoice — murni (tanpa JSX) supaya bisa dites dengan `node --test`. */

export const COST_LINES = [
  ['kain', 'Kain'], ['sablon', 'Sablon / Bordir'], ['jahit', 'Jahit (CMT)'], ['aksesoris', 'Aksesoris & Label'],
  ['packaging', 'Packaging'], ['overhead', 'Overhead'], ['lainnya', 'Lain-lain'],
];

const num = value => {
  const n = Number(String(value ?? '').replace(/[^\d.-]/g, ''));
  return Number.isFinite(n) ? n : 0;
};

/* HPP per pcs = jumlah semua komponen biaya, ditambah cadangan reject.
   Harga jual = HPP ÷ (1 − margin%)  → margin dihitung dari HARGA JUAL, bukan dari HPP (markup).
   Pembulatan selalu ke ATAS ke kelipatan `roundTo` supaya margin tidak turun karena pembulatan. */
export function calcPrice({costs = {}, rejectPct = 0, marginPct = 30, roundTo = 500, qty = 1, ppnPct = 0} = {}) {
  const base = Object.values(costs).reduce((sum, v) => sum + Math.max(0, num(v)), 0);
  const reject = Math.min(Math.max(num(rejectPct), 0), 90);
  const margin = Math.min(Math.max(num(marginPct), 0), 95);
  const hpp = base * (1 + reject / 100);
  const raw = margin >= 100 ? 0 : hpp / (1 - margin / 100);
  const step = Math.max(1, num(roundTo));
  const price = raw === 0 ? 0 : Math.ceil(raw / step - 1e-9) * step;
  const profit = price - hpp;
  const units = Math.max(0, Math.round(num(qty)));
  const ppn = Math.max(0, num(ppnPct));
  return {
    base, hpp: Math.round(hpp), price, profit: Math.round(profit),
    realMarginPct: price > 0 ? Math.round((profit / price) * 1000) / 10 : 0,
    revenue: price * units, totalProfit: Math.round(profit * units),
    priceWithPpn: Math.round(price * (1 + ppn / 100)), units,
  };
}

/* Harga jual yang dibutuhkan agar margin tertentu tercapai untuk HPP yang sudah diketahui. */
export function priceForMargin(hpp, marginPct) {
  const margin = Math.min(Math.max(num(marginPct), 0), 95);
  return Math.round(num(hpp) / (1 - margin / 100));
}

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MEI', 'JUN', 'JUL', 'AGU', 'SEP', 'OKT', 'NOV', 'DES'];

/* Kode buyer 3 huruf dari konsonan pertama: WARCHIVE → WRC. Bila konsonan kurang, dilengkapi huruf lain. */
export function buyerCode(name) {
  const letters = String(name || '').toUpperCase().replace(/[^A-Z]/g, '');
  const consonants = letters.replace(/[AEIOU]/g, '');
  const code = (consonants + letters).slice(0, 3);
  return code.padEnd(3, 'X');
}

/* Usulan No Invoice mengikuti contoh Syams: "141026/WRC/OKT 2" = ddmmyy / kode buyer / bulan urutan. */
export function suggestInvoiceNo(date, buyer, existing = []) {
  const d = date instanceof Date ? date : new Date(date);
  const pad = n => String(n).padStart(2, '0');
  const stamp = `${pad(d.getDate())}${pad(d.getMonth() + 1)}${pad(d.getFullYear() % 100)}`;
  const prefix = `/${buyerCode(buyer)}/${MONTHS[d.getMonth()]} `;
  const used = existing.map(no => String(no)).filter(no => no.includes(prefix))
    .map(no => Number(no.split(prefix)[1])).filter(Number.isFinite);
  return `${stamp}${prefix}${used.length ? Math.max(...used) + 1 : 1}`;
}
