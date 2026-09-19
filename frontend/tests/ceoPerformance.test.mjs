import test from 'node:test';
import assert from 'node:assert/strict';
import {
  formatCurrency, formatCount, formatPercent, formatKpiValue, formatNullableCurrency,
  missingKpiIds, reconciliationMismatches, finalCloseReady, domainLabel, DATA_STATE_LABEL,
  HEALTH_TONE,
} from '../src/ceoPerformance.js';

/* Revisi #71 & #77 — Company Performance read-only.

   Kontrak yang diuji di sini ada di `src/ceoPerformance.js`: format angka per
   unit, dan pemisahan tegas antara "belum ada data" dan "nol". Keluhan asli
   #71 adalah AR tampil sebagai `5000000` mentah dan KPI kosong tampil seperti
   nol — supaya bug itu tidak kembali, nilainya diuji sebagai fungsi murni. */

test('mata uang diformat, bukan angka mentah (revisi #71)', () => {
  // Keluhan asli: AR tampil 5000000 tanpa format.
  const formatted = formatCurrency(5000000);
  assert.notEqual(formatted, '5000000');
  assert.match(formatted, /5[\.,]?000[\.,]?000/);
  assert.match(formatted, /Rp/);
  assert.equal(formatCurrency(0), formatCurrency(0));
  assert.equal(formatCurrency(null), null);
  assert.equal(formatCurrency(''), null);
  assert.equal(formatCurrency('bukan angka'), null);
});

test('null berarti belum ada data, bukan Rp 0 (revisi #71)', () => {
  assert.equal(formatNullableCurrency(null), 'Belum ada data');
  assert.notEqual(formatNullableCurrency(null), formatCurrency(0));
  assert.equal(formatNullableCurrency(0), formatCurrency(0));
});

test('persen dan angka biasa punya format masing-masing', () => {
  assert.equal(formatPercent(97.5), '97,5%');
  assert.equal(formatPercent(null), null);
  assert.match(formatCount(7500), /7[\.,]?500/);
  assert.equal(formatCount(null), null);
});

test('formatKpiValue memilih format dari unit API, bukan dari nama field', () => {
  const rupiah = formatKpiValue({ kpi_id: 'K', value: 5000000, unit: 'IDR', status: 'RED', data_state: 'VALUE' });
  assert.match(rupiah.text, /Rp/);
  assert.equal(rupiah.tone, 'red');

  const percent = formatKpiValue({ kpi_id: 'K', value: 90, unit: 'percent', status: 'YELLOW', data_state: 'VALUE' });
  assert.equal(percent.text, '90%');
  assert.equal(percent.tone, 'amber');

  const count = formatKpiValue({ kpi_id: 'K', value: 5, unit: 'count', status: 'GREEN', data_state: 'VALUE' });
  assert.equal(count.text, '5');
  assert.equal(count.tone, 'green');
});

test('nilai kosong tampil sebagai belum-ada-data, bukan 0 (revisi #71)', () => {
  const missing = formatKpiValue({ kpi_id: 'K', value: null, unit: 'percent', status: 'MISSING', data_state: 'MISSING' });
  assert.equal(missing.text, 'Belum ada data');
  assert.equal(missing.isMissing, true);
  assert.equal(missing.tone, 'gray');
  assert.notEqual(missing.text, '0');
  assert.notEqual(missing.text, '0%');

  // KPI yang memang tidak relevan punya teks sendiri, bukan "belum ada data".
  const na = formatKpiValue({ kpi_id: 'K', value: null, unit: 'count', status: 'NOT_APPLICABLE', data_state: 'NOT_APPLICABLE' });
  assert.equal(na.text, 'Tidak relevan');
  assert.equal(na.isMissing, false);
});

test('nol yang nyata tetap tampil sebagai nol (bukan missing)', () => {
  const zero = formatKpiValue({ kpi_id: 'K', value: 0, unit: 'count', status: 'GREEN', data_state: 'ZERO' });
  assert.equal(zero.text, '0');
  assert.equal(zero.state, 'ZERO');
  assert.equal(zero.isMissing, false);
  assert.notEqual(zero.text, 'Belum ada data');
});

test('KPI tanpa data tetap dilaporkan, tidak disembunyikan', () => {
  const payload = { kpis: [
    { kpi_id: 'A', label: 'Ada', source_module: 'CFO' },
    { kpi_id: 'B', label: 'Tanpa sumber', source_module: null },
    { kpi_id: null, label: 'Tanpa ID', source_module: 'COO' },
  ] };
  assert.deepEqual(missingKpiIds(payload), ['B', 'Tanpa ID']);
  assert.deepEqual(missingKpiIds(null), []);
});

test('rekonsiliasi menyorot baris yang tidak cocok (revisi #77)', () => {
  const payload = { reconciliation: [
    { check: 'Order aktif', match: true },
    { check: 'Piutang', match: false },
  ] };
  const bad = reconciliationMismatches(payload);
  assert.equal(bad.length, 1);
  assert.equal(bad[0].check, 'Piutang');
  assert.deepEqual(reconciliationMismatches(null), []);
});

test('final close hanya siap kalau backend menyatakannya (revisi #77)', () => {
  assert.equal(finalCloseReady({ final_close_ready: true }), true);
  assert.equal(finalCloseReady({ final_close_ready: false }), false);
  assert.equal(finalCloseReady(null), false);
  // Tanpa flag eksplisit, halaman tidak boleh menyimpulkan "siap".
  assert.equal(finalCloseReady({ operational: { open: 0 }, customer: { open: 0 }, financial: { open: 0 } }), false);
});

test('label domain dan tone status konsisten', () => {
  assert.equal(domainLabel('finance'), 'Finance / Cash & Collection');
  assert.equal(domainLabel('production'), 'Production Today');
  assert.equal(domainLabel('sales'), 'Sales Opportunity');
  assert.equal(domainLabel('people'), 'People Condition');
  assert.equal(domainLabel('lainnya'), 'lainnya');
  assert.equal(HEALTH_TONE.RED, 'red');
  assert.equal(HEALTH_TONE.MISSING, 'gray');
  assert.equal(DATA_STATE_LABEL.ZERO, 'nol');
  assert.equal(DATA_STATE_LABEL.MISSING, 'data belum ada');
  assert.notEqual(DATA_STATE_LABEL.ZERO, DATA_STATE_LABEL.MISSING);
});
