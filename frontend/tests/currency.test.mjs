import test from 'node:test';
import assert from 'node:assert/strict';
import {CURRENCIES, DEFAULT_CURRENCY, currencyOptions} from '../src/currency.js';

/* Permintaan Bos 16 Okt 2026: currency disediakan 6 jenis — IDR, EUR, USD,
   AUSD, MYR, SGD. Form PO, Quotation dan Banking memakai daftar yang sama supaya
   tidak ada input bebas yang bisa salah ketik. */

test('daftar currency resmi berisi 6 kode sesuai permintaan', () => {
  assert.deepEqual(CURRENCIES, ['IDR', 'EUR', 'USD', 'AUSD', 'MYR', 'SGD']);
  assert.equal(CURRENCIES.length, 6);
  assert.equal(DEFAULT_CURRENCY, 'IDR');
});

test('currencyOptions menampilkan 6 pilihan saat nilai kosong', () => {
  assert.deepEqual(currencyOptions(''), CURRENCIES);
  assert.deepEqual(currencyOptions(null), CURRENCIES);
  assert.deepEqual(currencyOptions(undefined), CURRENCIES);
});

test('currencyOptions mempertahankan kode resmi apa adanya', () => {
  assert.deepEqual(currencyOptions('USD'), CURRENCIES);
  assert.deepEqual(currencyOptions('sgd'), CURRENCIES);
});

test('kode lama di luar daftar tetap tampil paling atas supaya tidak hilang saat disimpan', () => {
  const options = currencyOptions('CNY');
  assert.equal(options[0], 'CNY');
  assert.equal(options.length, 7);
  assert.ok(CURRENCIES.every(code => options.includes(code)));
});
