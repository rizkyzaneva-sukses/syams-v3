import test from 'node:test';
import assert from 'node:assert/strict';
import {
  statusTone, canActOnStage, canBlock, canChangePic, canEditSettings, parseExtraSize,
  serializeExtraSize, extraSizeTotal, stageHint, boardQuery,
} from '../src/control.js';

test('status tone follows the sheet colours', () => {
  assert.equal(statusTone('SELESAI'), 'green');
  assert.equal(statusTone('URGENT'), 'red');
  assert.equal(statusTone('PERHATIAN'), 'amber');
  assert.equal(statusTone('PROGRES'), 'plain');
  assert.equal(statusTone('-'), 'muted');
  assert.equal(statusTone(''), 'empty');
  assert.equal(statusTone('NGAWUR'), 'empty');
});

test('stage action roles mirror the backend', () => {
  assert.ok(canActOnStage('PRINTING_PIC', 'PRINTING'));
  assert.ok(!canActOnStage('PRINTING_PIC', 'CUTTING'));
  assert.ok(canActOnStage('SHIPMENT_ADMIN', 'SHIPPING'));
  assert.ok(!canActOnStage('CMO_MANAGER', 'BAHAN'));
  assert.ok(!canActOnStage('COO_MANAGER', 'INVOICE'));
});

test('block roles: CMO and COO managers anywhere, divisions only on their stage', () => {
  assert.ok(canBlock('CMO_MANAGER', 'BAHAN') && canBlock('COO_MANAGER', null));
  assert.ok(canBlock('CFO_MANAGER', 'INVOICE') && !canBlock('CFO_MANAGER', 'BAHAN'));
  assert.ok(canBlock('PRINTING_PIC', 'PRINTING') && !canBlock('PRINTING_PIC', 'SEWING'));
  assert.ok(!canBlock('CEO', null) && !canBlock('CHRO_MANAGER', 'BAHAN'));
});

test('settings are CMO manager only; PIC change is CMO/COO manager', () => {
  assert.ok(canEditSettings('CMO_MANAGER'));
  for (const role of ['CEO', 'COO_MANAGER', 'CMO_SUPPORT']) assert.ok(!canEditSettings(role));
  assert.ok(canChangePic('COO_MANAGER') && canChangePic('CMO_MANAGER') && !canChangePic('PRODUCTION_PIC'));
});

test('extra size round-trips and totals like the sheet', () => {
  assert.deepEqual(parseExtraSize('M+2/L+1'), {M: 2, L: 1});
  assert.equal(serializeExtraSize({L: 1, M: 2}), 'M+2/L+1');
  assert.equal(serializeExtraSize({}), '');
  assert.equal(extraSizeTotal('S+1/M+2'), 3);
  assert.equal(extraSizeTotal(''), 0);
  assert.equal(extraSizeTotal(null), 0);
  assert.deepEqual(parseExtraSize('xl + 2, XL+1; junk'), {XL: 3});
  assert.equal(serializeExtraSize({M: 0, 30: 2}), '30+2');
});

test('stage hint prefers done date, then due date', () => {
  assert.equal(stageHint({status: 'SELESAI', done_at: '2026-10-16T08:00:00'}), 'selesai 2026-10-16');
  assert.equal(stageHint({status: 'URGENT', due_date: '2026-10-15'}), 'jatuh tempo 2026-10-15');
  assert.equal(stageHint({status: '-'}), 'tidak dipakai');
  assert.equal(stageHint(null), '');
});

test('board query only carries active filters', () => {
  assert.equal(boardQuery({pic: 'ALL', priority: 'ALL', q: ''}), '/control/board');
  assert.equal(boardQuery({pic: 'SITI', priority: 'URGENT', q: ' kyan '}), '/control/board?pic=SITI&priority=URGENT&q=kyan');
});

test('row tone mirrors the sheet: red urgent, yellow warning, white on track', async () => {
  const {rowTone} = await import('../src/control.js');
  assert.equal(rowTone('URGENT'), 'red');
  assert.equal(rowTone('PERHATIAN'), 'yellow');
  assert.equal(rowTone('PROGRES'), 'white');
  assert.equal(rowTone(undefined), 'white');
});

test('sortRows sorts stably, supports both directions and keeps blanks last', async () => {
  const {sortRows} = await import('../src/control.js');
  const rows = [
    {order_id: 'SYM-2610-003', priority_sort: 2, pic: 'SITI', active_qty: 50, deadline: '2026-11-02', buyer: 'B', garment_types: ['HOODIE'], articles: ['x']},
    {order_id: 'SYM-2610-001', priority_sort: 1, pic: null, active_qty: 100, deadline: null, buyer: 'A', garment_types: [], articles: ['y']},
    {order_id: 'SYM-2610-002', priority_sort: 1, pic: 'IMAN', active_qty: 100, deadline: '2026-11-01', buyer: 'C', garment_types: ['JACKET'], articles: ['z']},
  ];
  const ids = (key, dir) => sortRows(rows, key, dir).map(r => r.order_id.slice(-1));
  assert.deepEqual(ids('priority_sort', 1), ['1', '2', '3']);          // seri: urutan awal dipertahankan
  assert.deepEqual(ids('qty', -1), ['1', '2', '3']);
  assert.deepEqual(ids('qty', 1), ['3', '1', '2']);
  assert.deepEqual(ids('pic', 1), ['2', '3', '1']);                     // pic kosong di bawah
  assert.deepEqual(ids('pic', -1), ['3', '2', '1']);                    // tetap di bawah saat turun
  assert.deepEqual(ids('deadline', 1), ['2', '3', '1']);
  assert.deepEqual(ids('garment', 1), ['3', '2', '1']);
  assert.deepEqual(ids('nonsense', 1), ['1', '2', '3']);                // kunci tak dikenal = urut prioritas
  assert.equal(rows[0].order_id, 'SYM-2610-003');                       // data asli tidak diubah
});

test('capacity and risk tones', async () => {
  const {capacityTone, riskTone} = await import('../src/control.js');
  assert.equal(capacityTone('OVERLOAD'), 'red');
  assert.equal(capacityTone('PERHATIAN'), 'amber');
  assert.equal(capacityTone('AVAILABLE'), 'green');
  assert.equal(capacityTone('TIDAK DIPAKAI'), 'gray');
  assert.equal(riskTone('URGENT'), 'red');
  assert.equal(riskTone('PERHATIAN'), 'yellow');
  assert.equal(riskTone('AMAN'), 'green');
  assert.equal(riskTone('TANPA DEADLINE'), 'gray');
});

test('load label caps the 999 sentinel', async () => {
  const {loadLabel} = await import('../src/control.js');
  assert.equal(loadLabel(90), '90%');
  assert.equal(loadLabel(0), '0%');
  assert.equal(loadLabel(999), '>999%');
  assert.equal(loadLabel(null), '-');
});

test('dates use the sheet format and local calendar day', async () => {
  const {formatDate, dateInputValue, plannerQuery} = await import('../src/control.js');
  assert.equal(formatDate('2026-10-16'), '16/10/2026');
  assert.equal(formatDate('2026-10-16T08:30:00'), '16/10/2026');
  assert.equal(formatDate(null), '-');
  assert.equal(dateInputValue(new Date(2026, 9, 5, 23, 59)), '2026-10-05');   // lokal, bukan UTC
  assert.equal(plannerQuery('2026-10-01', '2026-10-30'), '/control/capacity-planner?start=2026-10-01&end=2026-10-30');
});

test('invoice and sample tones follow the sheet vocabulary', async () => {
  const {invoiceTone, sampleTone} = await import('../src/control.js');
  assert.equal(invoiceTone('SELESAI'), 'green');
  assert.equal(invoiceTone('DP'), 'blue');
  assert.equal(invoiceTone('OUTSTANDING'), 'amber');
  assert.equal(invoiceTone('BELUM TERBIT'), 'gray');
  assert.equal(sampleTone('APPROVED'), 'green');
  assert.equal(sampleTone('REVISION'), 'red');
  assert.equal(sampleTone('PROGRES'), 'amber');
  assert.equal(sampleTone('SKIP'), 'gray');
});
