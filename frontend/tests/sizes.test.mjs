import test from 'node:test';
import assert from 'node:assert/strict';
import {SIZES, parseSizeBreakdown, serializeSizeBreakdown, sizeBreakdownTotal, sizeRows} from '../src/sizes.js';

/* Permintaan Bos 16 Okt 2026: size breakdown dipilih dari daftar XS…XXXXL
   (tidak perlu mengetik). Modul ini menyimpan daftar resmi + konversi ke/dari
   format "S:10, M:20" yang sudah dipakai data lama, sehingga tidak perlu
   migrasi DB. */

test('daftar ukuran resmi berisi XS hingga XXXXL', () => {
  assert.deepEqual(SIZES, ['XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL', 'XXXXL']);
});

test('parse memahami format string "S:10, M:20"', () => {
  assert.deepEqual(parseSizeBreakdown('S:10, M:20'), {S: 10, M: 20});
  assert.deepEqual(parseSizeBreakdown('XS:5;L:7'), {XS: 5, L: 7});
  assert.deepEqual(parseSizeBreakdown(''), {});
  assert.deepEqual(parseSizeBreakdown(null), {});
});

test('parse juga memahami objek (dibaca balik dari server)', () => {
  assert.deepEqual(parseSizeBreakdown({S: 50, M: '20'}), {S: 50, M: 20});
});

test('serialize menyusun ulang ke "SIZE:qty" mengikuti urutan ukuran standar', () => {
  assert.equal(serializeSizeBreakdown({L: 5, S: 10, M: 0, XL: ''}), 'S:10, L:5');
  assert.equal(serializeSizeBreakdown({}), '');
});

test('ukuran angka dari data lama tetap dipertahankan di belakang', () => {
  assert.equal(serializeSizeBreakdown({30: 4, S: 10}), 'S:10, 30:4');
});

test('total pcs menjumlahkan seluruh ukuran', () => {
  assert.equal(sizeBreakdownTotal('S:10, M:20, L:5'), 35);
  assert.equal(sizeBreakdownTotal(''), 0);
});

test('sizeRows menampilkan semua ukuran standar + ukuran lama tak dikenal', () => {
  const rows = sizeRows('30:4');
  assert.deepEqual(rows.slice(0, SIZES.length), SIZES);
  assert.ok(rows.includes('30'));
});
