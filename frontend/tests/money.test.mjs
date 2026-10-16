import test from 'node:test';
import assert from 'node:assert/strict';
import {formatRupiah, digitsOnly, rupiahInputText, rupiahNumber, sisaTagihan, dpValid} from '../src/money.js';

test('formatRupiah groups thousands with dots and the Rp. prefix', () => {
  assert.equal(formatRupiah(1000000), 'Rp. 1.000.000');
  assert.equal(formatRupiah('2500000'), 'Rp. 2.500.000');
  assert.equal(formatRupiah(999), 'Rp. 999');
  assert.equal(formatRupiah(0), 'Rp. 0');
  assert.equal(formatRupiah(null), 'Rp. 0');
  assert.equal(formatRupiah(undefined), 'Rp. 0');
  assert.equal(formatRupiah(1234567890), 'Rp. 1.234.567.890');
  assert.equal(formatRupiah(1500.6), 'Rp. 1.501');
  assert.equal(formatRupiah(-5000), '-Rp. 5.000');
  assert.equal(formatRupiah('abc'), 'Rp. 0');
});

test('digitsOnly strips everything but digits and leading zeros', () => {
  assert.equal(digitsOnly('Rp. 1.000.000'), '1000000');
  assert.equal(digitsOnly('1,000,000'), '1000000');
  assert.equal(digitsOnly('007'), '7');
  assert.equal(digitsOnly('0'), '0');
  assert.equal(digitsOnly(''), '');
  assert.equal(digitsOnly(null), '');
  assert.equal(digitsOnly('abc'), '');
});

test('typing digits one by one produces the live Rp. format', () => {
  let typed = '';
  const shown = [];
  for (const key of '1000000') { typed = digitsOnly(rupiahInputText(typed) + key); shown.push(rupiahInputText(typed)); }
  assert.deepEqual(shown, ['Rp. 1', 'Rp. 10', 'Rp. 100', 'Rp. 1.000', 'Rp. 10.000', 'Rp. 100.000', 'Rp. 1.000.000']);
  assert.equal(rupiahInputText(''), '');
  assert.equal(rupiahInputText(digitsOnly(rupiahInputText('1000000').slice(0, -1))), 'Rp. 100.000');   // backspace
});

test('rupiahNumber treats empty as zero', () => {
  assert.equal(rupiahNumber('1500000'), 1500000);
  assert.equal(rupiahNumber(''), 0);
  assert.equal(rupiahNumber(undefined), 0);
});

test('sisa tagihan is amount minus DP and never negative', () => {
  assert.equal(sisaTagihan('10000000', '4000000'), 6000000);
  assert.equal(sisaTagihan('10000000', ''), 10000000);
  assert.equal(sisaTagihan('', ''), 0);
  assert.equal(sisaTagihan('1000', '5000'), 0);
});

test('DP must stay between zero and the invoice amount', () => {
  assert.ok(dpValid('10000000', '10000000'));
  assert.ok(dpValid('10000000', ''));
  assert.ok(!dpValid('10000000', '10000001'));
});

test('normalizeMoney rounds server decimals but keeps typed digits intact', async () => {
  const {normalizeMoney} = await import('../src/money.js');
  assert.equal(normalizeMoney('20000000.00'), '20000000');
  assert.equal(normalizeMoney('1500.60'), '1501');
  assert.equal(normalizeMoney(1500.6), '1501');
  assert.equal(normalizeMoney('1000'), '1000');
  assert.equal(normalizeMoney(''), '');
  assert.equal(normalizeMoney(null), '');
  assert.equal(normalizeMoney('Rp. 1.000.000'), '1000000');
});

test('API decimals do not get inflated 100x when shown or summed', async () => {
  const {rupiahInputText, rupiahNumber, sisaTagihan} = await import('../src/money.js');
  assert.equal(rupiahInputText('20000000.00'), 'Rp. 20.000.000');
  assert.equal(rupiahNumber('6000000.00'), 6000000);
  assert.equal(sisaTagihan('20000000.00', '6000000.00'), 14000000);
});
