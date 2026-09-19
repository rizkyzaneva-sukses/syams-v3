import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

/* Revisi #74 & #77 — batas halaman CEO.

   Konvensi repo (frontend/src/business.js):
   'CEO tidak punya halaman kerja operasional: pembuatan/ubah PO, invoice, dan
   aksi operasional lain bukan milik CEO.'

   Karena itu halaman Company Performance wajib murni baca. Tes ini membaca
   sumbernya dan menolak setiap metode tulis ke endpoint operasional. Halaman
   override boleh menulis, tapi hanya ke /ceo/overrides — bukan ke transaksi
   divisi. */

const read = (p) => readFileSync(new URL(`../src/pages/${p}`, import.meta.url), 'utf8');

const OPERATIONAL_WRITE_PATTERNS = [
  /\/cfo\/purchase-orders/i,
  /\/cfo\/invoices/i,
  /\/cfo\/shipments/i,
  /\/coo\/closings?/i,
  /\/coo\/deliveries/i,
  /\/coo\/bom/i,
  /\/coo\/material-requests/i,
  /\/cmo\/quotations/i,
];

test('Company Performance hanya membaca (tidak ada metode tulis)', () => {
  const src = read('CEOCompanyPerformance.jsx');
  const writes = [...src.matchAll(/method\s*:\s*['"](\w+)['"]/g)].map((m) => m[1].toUpperCase());
  assert.deepEqual(writes, [], 'halaman read-only tidak boleh memakai method:');
  assert.equal(/\bmethod\s*:/.test(src), false);
  // Setiap panggilan api() harus GET (default) dan tidak mengirim body.
  const calls = [...src.matchAll(/api\(/g)].map((m) => m.index);
  assert.ok(calls.length > 0, 'halaman harus memanggil API');
  assert.equal(/api\([^)]*,\s*\{/.test(src), false, 'api() di halaman ini tidak boleh memakai opsi');
});

test('Company Performance tidak menulis ke endpoint operasional', () => {
  const src = read('CEOCompanyPerformance.jsx');
  for (const pattern of OPERATIONAL_WRITE_PATTERNS) {
    assert.equal(pattern.test(src), false, `tidak boleh menyentuh ${pattern}`);
  }
});

test('Company Performance memakai kontrak format, bukan angka mentah', () => {
  const src = read('CEOCompanyPerformance.jsx');
  // Angka uang wajib lewat helper, bukan template mentah.
  assert.match(src, /formatKpiValue/);
  assert.match(src, /formatNullableCurrency/);
  assert.match(src, /from '\.\.\/ceoPerformance'/);
  // Tidak boleh ada hard-code angka contoh dari blueprint.
  assert.equal(/\b5000000\b/.test(src), false, 'angka ilustrasi blueprint tidak boleh di-hard-code');
  assert.equal(/\bRp\s?\d/.test(src), false, 'rupiah tidak boleh ditulis manual');
});

test('halaman override hanya menulis ke /ceo/overrides', () => {
  const src = read('CEOOverride.jsx');
  const writeCalls = [...src.matchAll(/api\(\s*[`'"]([^`'"]+)[`'"]\s*,\s*\{\s*method\s*:\s*['"](\w+)['"]/g)]
    .map((m) => ({path: m[1], method: m[2].toUpperCase()}));
  assert.ok(writeCalls.length > 0, 'halaman override harus punya aksi keputusan');
  for (const call of writeCalls) {
    assert.match(call.path, /^\/ceo\/overrides/, `tulis hanya boleh ke /ceo/overrides, bukan ${call.path}`);
    assert.equal(call.method, 'POST');
  }
  for (const pattern of OPERATIONAL_WRITE_PATTERNS) {
    assert.equal(pattern.test(src), false, `halaman override tidak boleh menyentuh ${pattern}`);
  }
});

test('pemutus override dibaca dari API, bukan ditulis ulang di UI', () => {
  const src = read('CEOOverride.jsx');
  // Governance (siapa pemutus) harus datang dari payload, bukan peta lokal.
  assert.match(src, /governance\[row\.override_type\]\?\.decider/);
  assert.equal(/decider\s*:\s*['"]CEO['"]/.test(src), false, 'pemutus tidak boleh di-hard-code di UI');
  assert.match(src, /data\?\.governance/);
});
