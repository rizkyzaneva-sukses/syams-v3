import test from 'node:test';
import assert from 'node:assert/strict';
import {calcPrice, priceForMargin, buyerCode, suggestInvoiceNo, COST_LINES} from '../src/pricing.js';

test('price = HPP / (1 - margin), rounded UP to the step so margin never drops', () => {
  const r = calcPrice({costs: {kain: 40000, sablon: 15000, jahit: 10000, aksesoris: 3000, packaging: 2000}, rejectPct: 0, marginPct: 30, roundTo: 500, qty: 100});
  assert.equal(r.hpp, 70000);
  assert.equal(r.price, 100000);                 // 70.000 / 0.7 = 100.000 tepat
  assert.equal(r.profit, 30000);
  assert.equal(r.realMarginPct, 30);
  assert.equal(r.revenue, 10000000);
  assert.equal(r.totalProfit, 3000000);
  const odd = calcPrice({costs: {kain: 43210}, marginPct: 25, roundTo: 1000});
  assert.equal(odd.price, 58000);                // 57.613,3 → naik ke 58.000
  assert.ok(odd.realMarginPct >= 25);
});

test('reject allowance raises HPP before the margin is applied', () => {
  const r = calcPrice({costs: {kain: 50000, jahit: 50000}, rejectPct: 5, marginPct: 20, roundTo: 100});
  assert.equal(r.hpp, 105000);
  assert.equal(r.price, 131300);
});

test('ppn is shown on top of the selling price', () => {
  const r = calcPrice({costs: {kain: 70000}, marginPct: 30, roundTo: 500, ppnPct: 11});
  assert.equal(r.price, 100000);
  assert.equal(r.priceWithPpn, 111000);
});

test('bad input never produces NaN or negative prices', () => {
  const r = calcPrice({costs: {kain: 'abc', sablon: -5000, jahit: ''}, marginPct: 'x', qty: -3});
  assert.equal(r.hpp, 0);
  assert.equal(r.price, 0);
  assert.equal(r.units, 0);
  assert.ok(Number.isFinite(r.realMarginPct));
  assert.equal(calcPrice({costs: {kain: 1000}, marginPct: 500}).price > 0, true);   // margin dibatasi 95%
  assert.equal(calcPrice().price, 0);
});

test('priceForMargin and the cost lines list', () => {
  assert.equal(priceForMargin(70000, 30), 100000);
  assert.equal(priceForMargin(0, 30), 0);
  assert.equal(COST_LINES.length, 7);
});

test('buyer code uses the first consonants', () => {
  assert.equal(buyerCode('WARCHIVE'), 'WRC');
  assert.equal(buyerCode('Kyan'), 'KYN');
  assert.equal(buyerCode('Aa'), 'AAX');
  assert.equal(buyerCode(''), 'XXX');
  assert.equal(buyerCode('Noir Dept'), 'NRD');
});

test('invoice number follows the Syams sample and increments per buyer and month', () => {
  const day = new Date(2026, 9, 14);
  assert.equal(suggestInvoiceNo(day, 'WARCHIVE', []), '141026/WRC/OKT 1');
  assert.equal(suggestInvoiceNo(day, 'WARCHIVE', ['141026/WRC/OKT 1', '151026/WRC/OKT 2', '121026/KYN/OKT 7']), '141026/WRC/OKT 3');
  assert.equal(suggestInvoiceNo(new Date(2026, 10, 2), 'WARCHIVE', ['141026/WRC/OKT 2']), '021126/WRC/NOV 1');
});
