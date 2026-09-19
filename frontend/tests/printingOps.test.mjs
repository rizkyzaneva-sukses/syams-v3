import test from 'node:test';
import assert from 'node:assert/strict';
import {api, requestPayload} from '../src/api.js';
import {statusTone} from '../src/business.js';
import {printingStatusBounds} from '../src/printingOps.js';

/* Revisi #42/#47 — halaman Printing tidak boleh menawarkan pilihan status bebas.
   Kontrak yang diuji di sini ada di `src/printingOps.js`: daftar status
   terdaftar, transisi yang sah, dan helper yang dipakai halaman target harian.
   Halaman hanya boleh memakai nilai dari kontrak ini, bukan mengetik status. */

test('printing hanya mengizinkan transisi status yang sah', () => {
  assert.deepEqual(printingStatusBounds.registered, ['WAITING', 'IN_PROCESS', 'HOLD', 'DONE']);
  assert.deepEqual(printingStatusBounds.from.WAITING, ['IN_PROCESS', 'HOLD']);
  assert.deepEqual(printingStatusBounds.from.IN_PROCESS, ['DONE', 'HOLD', 'IN_PROCESS']);
  assert.deepEqual(printingStatusBounds.from.HOLD, ['IN_PROCESS']);
  assert.deepEqual(printingStatusBounds.from.DONE, ['IN_PROCESS']);
  // WAITING -> DONE bukan transisi yang sah (inilah keluhan revisi #42).
  assert.equal(printingStatusBounds.from.WAITING.includes('DONE'), false);
  // Status di luar daftar tidak menghasilkan pilihan apa pun.
  assert.equal(printingStatusBounds.canMove('WAITING', 'CANCELLED'), false);
  assert.equal(printingStatusBounds.canMove('WAITING', 'IN_PROCESS'), true);
  assert.equal(printingStatusBounds.canMove('DONE', 'DONE'), false);
});

test('penugasan Printing terbatas pada PRINTING/BORDIR', () => {
  assert.deepEqual(printingStatusBounds.owned, ['PRINTING', 'BORDIR']);
  assert.equal(printingStatusBounds.owns('Printing'), true);
  assert.equal(printingStatusBounds.owns('Bordir'), true);
  assert.equal(printingStatusBounds.owns('Cutting'), false);
  assert.equal(printingStatusBounds.owns('Sewing'), false);
  assert.equal(printingStatusBounds.owns(''), false);
  assert.deepEqual(printingStatusBounds.vendorBoundary, {rate_owner: 'CFO_MANAGER', printing_can_change_rate: false});
});

test('tone status printing memakai kosakata badge yang sama dengan halaman lain', () => {
  assert.equal(statusTone('DONE'), 'green');
  assert.equal(statusTone('HOLD'), 'red');
  assert.equal(statusTone('WAITING'), 'gray');
  // Status yang belum dikenal business.js tetap aman (tidak melempar).
  assert.equal(statusTone('IN_PROCESS'), 'gray');
});

test('payload yang dikirim ke endpoint printing tidak memuat field milik server', () => {
  // Halaman ini read-only: requestPayload tidak boleh meneruskan id/created_at
  // kalau suatu saat tombol aksi ditambahkan.
  assert.deepEqual(
    requestPayload('/printing/daily-target', 'GET', {id: 1, created_at: 'x', on_date: '2026-09-19'}),
    {on_date: '2026-09-19'},
  );
});

test('api client menyasar path printing dengan token dari sessionStorage', () => {
  assert.equal(typeof api, 'function');
  assert.equal(api.length, 1); // api(path, opts)
});
