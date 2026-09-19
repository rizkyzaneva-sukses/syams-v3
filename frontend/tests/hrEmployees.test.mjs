import test from 'node:test';
import assert from 'node:assert/strict';
import {
  SUMMARY_ENDPOINT,
  lifecycleEndpoint,
  statusLabel,
  isOpenStatus,
  migrationLabel,
  eventLabel,
  employeeLabel,
  summaryTiles,
  statusBreakdown,
  contractWatchList,
  migrationQueue,
  attendanceNotice,
  hrTraceTiles,
  timelineRows,
} from '../src/hrEmployees.js';

test('endpoint tetap read-only: hanya GET summary dan lifecycle', () => {
  assert.equal(SUMMARY_ENDPOINT, '/hr/employees-summary');
  assert.equal(lifecycleEndpoint(7), '/hr/employees/7/lifecycle');
  // Tidak boleh ada helper endpoint tulis attendance/payroll.
  const surface = [SUMMARY_ENDPOINT, lifecycleEndpoint(1)].join(' ');
  assert.doesNotMatch(surface, /attendance|payroll/i);
});

test('status kepegawaian punya label manusiawi dan penanda slot headcount', () => {
  assert.equal(statusLabel('ACTIVE'), 'Aktif');
  assert.equal(statusLabel('TERMINATED'), 'Berhenti (terminate)');
  assert.equal(statusLabel(''), '-');
  assert.equal(statusLabel('SESUATU_BARU'), 'SESUATU_BARU');
  assert.equal(isOpenStatus('ACTIVE'), true);
  assert.equal(isOpenStatus('on_leave'), false);
  assert.equal(isOpenStatus('TERMINATED'), false);
});

test('label migrasi dan kejadian tidak pernah menelan kode mentah', () => {
  assert.equal(migrationLabel('SEED_DEMO_ROW'), 'Data seed/demo — tidak boleh ada di produksi');
  assert.equal(migrationLabel('BELUM_DIKENAL'), 'BELUM_DIKENAL');
  assert.equal(eventLabel('JOINED'), 'Masuk kerja');
  assert.equal(eventLabel('KONTRAK_BARU'), 'KONTRAK_BARU');
  assert.equal(employeeLabel({employee_no: 'EMP-1', name: 'Siti'}), 'EMP-1 · Siti');
  assert.equal(employeeLabel({name: 'Tanpa NIP'}), 'tanpa NIP · Tanpa NIP');
  assert.equal(employeeLabel(null), '-');
});

test('summaryTiles memakai angka server, bukan hitungan ulang UI', () => {
  const summary = {
    total: 12, headcount_active: 9, headcount_inactive: 3,
    contract_watch: {window_days: 45, count: 2, expired_count: 1},
    migration: {needs_migration: 4},
  };
  const tiles = summaryTiles(summary);
  assert.equal(tiles.length, 6);
  assert.deepEqual(tiles.map((t) => t.value), [12, 9, 3, 2, 1, 4]);
  assert.equal(tiles[3].label, 'Kontrak \u2264 45 hari');
  // Tanpa data -> nol eksplisit, bukan crash.
  assert.deepEqual(summaryTiles(null), []);
  assert.equal(summaryTiles({})[0].value, 0);
});

test('statusBreakdown menandai status arsip sebagai bukan slot headcount', () => {
  const rows = statusBreakdown({
    by_employment_status: [
      {employment_status: 'ACTIVE', count: 9},
      {employment_status: 'TERMINATED', count: 2},
    ],
  });
  assert.deepEqual(rows, [
    {status: 'ACTIVE', label: 'Aktif', count: 9, open: true},
    {status: 'TERMINATED', label: 'Berhenti (terminate)', count: 2, open: false},
  ]);
  assert.deepEqual(statusBreakdown(undefined), []);
});

test('contractWatchList menghitung hari dan menandai yang mendesak', () => {
  const rows = contractWatchList({
    contract_watch: {
      employees: [
        {id: 1, employee_no: 'EMP-1', name: 'A', division: 'Produksi', days_to_contract_end: 3},
        {id: 2, employee_no: 'EMP-2', name: 'B', division: null, days_to_contract_end: -5},
        {id: 3, employee_no: 'EMP-3', name: 'C', division: 'QC', days_to_contract_end: 20},
      ],
    },
  });
  assert.equal(rows[0].daysLabel, '3 hari lagi');
  assert.equal(rows[0].urgent, true);
  assert.equal(rows[1].daysLabel, 'lewat 5 hari');
  assert.equal(rows[1].urgent, true);
  assert.equal(rows[2].urgent, false);
  assert.equal(rows[0].label, 'EMP-1 · A');
  assert.deepEqual(contractWatchList({}), []);
});

test('migrationQueue hanya memuat baris yang perlu migrasi, dengan alasan terbaca', () => {
  const queue = migrationQueue({
    employees: [
      {id: 1, employee_no: 'EMP-DEMO-1', name: 'Dummy', needs_migration: true, migration_flags: ['SEED_DEMO_ROW', 'MISSING_JOIN_DATE']},
      {id: 2, employee_no: 'EMP-2', name: 'Bersih', needs_migration: false, migration_flags: []},
    ],
  });
  assert.equal(queue.length, 1);
  assert.equal(queue[0].label, 'EMP-DEMO-1 · Dummy');
  assert.deepEqual(queue[0].reasons, [
    'Data seed/demo — tidak boleh ada di produksi',
    'Tanggal masuk kosong',
  ]);
  assert.deepEqual(migrationQueue({}), []);
});

test('attendanceNotice jujur soal ketersediaan dan menyebut sumber CFO', () => {
  const pending = attendanceNotice({
    attendance: {
      mode: 'READ_ONLY', source: 'CFO', available: false,
      reason: 'Ringkasan attendance per Employee/period belum diekspos ke HR.',
    },
  });
  assert.equal(pending.available, false);
  assert.match(pending.text, /belum diekspos/);

  const ready = attendanceNotice({attendance: {mode: 'READ_ONLY', source: 'CFO', available: true}});
  assert.equal(ready.available, true);
  assert.match(ready.text, /CFO/);
  assert.match(ready.text, /tidak mengubah/);

  // Payload tanpa blok attendance tidak boleh diklaim tersedia.
  assert.equal(attendanceNotice({}).available, false);
  assert.match(attendanceNotice({}).text, /belum tersedia/);
});

test('hrTraceTiles memisahkan jejak HR dari attendance CFO', () => {
  const tiles = hrTraceTiles({
    hr_trace: {
      training_records: 5, employees_without_training: 2,
      performance_records: 3, employees_without_performance: 4,
      employee_issues: 1, open_issues: 1,
    },
  });
  assert.deepEqual(tiles.map((t) => t.value), [5, 2, 3, 4, 1, 1]);
  assert.equal(tiles[0].label, 'Record training');
  assert.deepEqual(hrTraceTiles({}), []);
});

test('timelineRows tidak berpura-pura punya tanggal yang hilang', () => {
  const rows = timelineRows({
    events: [
      {date: '2026-09-05', type: 'TRAINING_START', label: 'Induksi', source: 'training_records'},
      {date: null, type: 'MIGRATED', label: 'Migrasi dari Lutfi', source: 'employees.migration_source'},
    ],
  });
  assert.equal(rows[0].typeLabel, 'Mulai training');
  assert.equal(rows[0].dateLabel, '2026-09-05');
  assert.equal(rows[1].dateLabel, 'tanggal tidak diketahui');
  assert.deepEqual(timelineRows(null), []);
});
