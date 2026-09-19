import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {
  slaDays, slaBadge, slaLabel, SLA_LABELS, isOverdue,
  handoffStatus, taskId, stepAction, poHandoff, quotationHandoff,
} from '../src/queue.js';

/* Revisi #9 (REF-DEBY) poin 3 dan 4/6/7 — kolom wajib antrean CMO Support:
   SLA internal, status handoff per-order, dan Task ID formal. Kontraknya ada di
   `src/queue.js` supaya PO Inbox, Draft Order (OrderList) dan Quotation memakai
   kosakata yang sama; halaman tidak boleh mengetik ulang label SLA. */

test('SLA internal dihitung sebagai kalender hari, bukan selisih jam', () => {
  const now = new Date('2026-09-19T23:30:00');
  // Due hari ini adalah HARI INI (0), walau jam sekarang 23:30 — bukan lewat.
  assert.equal(slaDays('2026-09-19', now), 0);
  assert.equal(slaDays('2026-09-22', now), 3);
  assert.equal(slaDays('2026-09-01', now), -18);
  assert.equal(slaDays(null), null);
  assert.equal(slaDays(''), null);
  assert.equal(slaDays('bukan-tanggal'), null);
});

test('badge SLA memakai kosakata dan warna badge halaman lain', () => {
  assert.deepEqual(slaBadge(null), {code: 'TANPA_DUE', label: 'Tanpa due date', tone: 'gray', days: null});
  const overdue = slaBadge('2026-09-01', undefined, new Date('2026-09-19T08:00:00'));
  assert.equal(overdue.code, 'OVERDUE');
  assert.equal(overdue.tone, 'red');
  // Selisih hari ikut tampil supaya Deby tahu seberapa lewat.
  assert.equal(overdue.label, 'Lewat SLA (18 hari)');
  // Due hari ini bukan overdue (mudah salah kalau memakai selisih jam).
  assert.equal(slaBadge('2026-09-19', undefined, new Date('2026-09-19T23:59:00')).tone, 'amber');
  // Kosakata bebas (TANPA_DUE..AMAN) tetap aman kalau kode tak dikenal.
  assert.equal(slaLabel('KODE_BARU'), 'KODE_BARU');
  assert.equal(SLA_LABELS.AMAN, 'Aman');
  assert.equal(isOverdue('2020-01-01'), true);
  assert.equal(isOverdue(null), false);
});

test('status handoff per-order menunjuk pemilik sekarang dan penerima berikutnya', () => {
  const order = handoffStatus({queue: stepAction('ORDER')});
  assert.equal(order.owner, 'CMO_MANAGER');
  assert.equal(order.to, 'Lengkapi invoice & gate pembayaran');
  assert.equal(order.label, 'Di tangan CMO_MANAGER → Lengkapi invoice & gate pembayaran');
  assert.equal(order.tone, 'amber');

  // Baris yang sudah selesai tidak menyebut handoff yang tidak akan terjadi.
  const closed = handoffStatus({queue: stepAction('CLOSED'), closed: true});
  assert.equal(closed.label, 'Selesai — tidak ada handoff');
  assert.equal(closed.tone, 'green');

  // Pemilik bisa ditimpa: antrean PO milik Deby walau tahap order milik Cecep.
  const overridden = handoffStatus({queue: stepAction('ORDER'), owner: 'CMO_SUPPORT (Deby)', handoff: 'Cecep review'});
  assert.equal(overridden.owner, 'CMO_SUPPORT (Deby)');
  assert.equal(overridden.to, 'Cecep review');
  assert.equal(overridden.tone, 'blue');
});

test('handoff antrean PO mengikuti status PO yang tercatat di server', () => {
  assert.match(poHandoff({status: 'SUBMITTED'}).owner, /CMO_MANAGER/);
  assert.equal(poHandoff({status: 'ACCEPTED'}).owner, 'CFO_MANAGER');
  assert.match(poHandoff({status: 'REJECTED'}).label, /revisi dokumen buyer/);
  // DRAFT / NEEDS_INFO / READY semuanya masih di meja Deby.
  for (const status of ['DRAFT', 'NEEDS_INFO', 'READY']) {
    assert.equal(poHandoff({status}).owner, 'CMO_SUPPORT (Deby)');
    assert.match(poHandoff({status}).to, /CMO_MANAGER/);
  }
  // Baris kosong tidak melempar — antrean tetap bisa dirender.
  assert.equal(poHandoff({}).owner, 'CMO_SUPPORT (Deby)');
});

test('handoff antrean quotation mengikuti alur Deby → CFO → buyer', () => {
  // Draft tanpa approval: masih menunggu keputusan harga CFO.
  assert.equal(quotationHandoff({status: 'DRAFT'}).owner, 'CFO_MANAGER');
  // Disetujui CFO: kembali ke Deby untuk dikirim ke buyer.
  assert.equal(quotationHandoff({status: 'APPROVED'}).owner, 'CMO_SUPPORT (Deby)');
  assert.match(quotationHandoff({status: 'APPROVED'}).to, /Buyer/);
  // Ditolak CFO: kembali ke Deby untuk perbaikan harga.
  assert.match(quotationHandoff({status: 'REJECTED'}).to, /CFO_MANAGER/);
  // Sudah dikirim: bola ada di buyer, hasilnya dicatat Cecep.
  assert.match(quotationHandoff({status: 'SENT'}).owner, /BUYER/);
  assert.match(quotationHandoff({status: 'DRAFT', approved_by_id: 4}).to, /Buyer/);
  // Approval CEO di atas limit mengalahkan status DRAFT.
  assert.match(quotationHandoff({status: 'DRAFT', approved_by_id: 4, ceo_approved_by_id: 1}).label, /CEO/);
  assert.equal(quotationHandoff({}).owner, 'CFO_MANAGER');
});

test('Task ID formal punya satu format untuk seluruh antrean CMO', () => {
  assert.equal(taskId('PO', 12), 'PO-12');
  assert.equal(taskId('PO', 'PO-2026-001'), 'PO-PO-2026-001');
  assert.equal(taskId('ORDER', 'ORD-9'), 'ORD-ORD-9');
  assert.equal(taskId('QUOTATION', 'QT-7'), 'QUO-QT-7');
  assert.equal(taskId('PO', ['A', 'B']), 'PO-A, PO-B');
  // Task ID tidak pernah kosong walau barisnya masih baru.
  assert.equal(taskId('PO', null), 'PO-BARU');
  assert.equal(taskId('PO', []), 'PO-BARU');
  assert.equal(taskId('PO', ''), 'PO-BARU');
});

/* Penjaga struktur halaman. File .jsx tidak bisa diimpor `node --test`, dan
   file .jsx yang tidak diimpor siapa pun tidak pernah di-compile — jadi kolom
   baru bisa hilang tanpa terdeteksi. Tes ini membaca sumber halaman sebagai
   teks dan memastikan kolom wajib tetap dirender dari helper bersama. */
const PAGE_DIR = new URL('../src/pages/', import.meta.url);
const readPage = name => readFileSync(new URL(name, PAGE_DIR), 'utf8');

test('tiga halaman antrean CMO merender Task ID, SLA internal dan handoff', () => {
  const expectations = {
    'POInboxPage.jsx': ['taskId', 'slaBadge', 'poHandoff'],
    'OrderList.jsx': ['taskId', 'slaBadge', 'handoffStatus'],
    'QuotationPage.jsx': ['taskId', 'slaBadge', 'quotationHandoff'],
  };
  for (const [page, helpers] of Object.entries(expectations)) {
    const source = readPage(page);
    for (const helper of helpers) {
      assert.ok(source.includes(helper), `${page} harus memakai ${helper} dari queue.js`);
    }
    // Label "Handoff" dan "Task ID" harus benar-benar jadi kolom tabel.
    assert.match(source, /<th>Task ID<\/th>/, `${page} tidak punya kolom Task ID`);
    assert.match(source, /Handoff/, `${page} tidak punya kolom Handoff`);
    // updated_at wajib tampil di halaman antrean (poin 3).
    assert.match(source, /updated_at/, `${page} tidak merender updated_at`);
  }
});

test('klaim SLA dan handoff tidak ditulis ulang di dalam halaman', () => {
  for (const page of ['POInboxPage.jsx', 'OrderList.jsx', 'QuotationPage.jsx']) {
    const source = readPage(page);
    // Halaman memakai helper bersama; kalau salah satu fungsi ini disalin ke
    // halaman, label SLA akan mulai menyimpang antar-antrean.
    assert.ok(!/export function slaDays|export function slaBadge|export function taskId/.test(source),
      `${page} menyalin helper queue.js — pakai impor, jangan salin`);
  }
});
