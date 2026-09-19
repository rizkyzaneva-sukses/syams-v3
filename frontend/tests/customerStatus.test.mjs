import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CUSTOMER_STATUS,
  customerStatus,
  customerStatusLabel,
  customerVisibleFields,
  customerHiddenFields,
  assertCustomerSafe,
  isCustomerSafe,
  toCustomerOrder,
  simplePaymentStatus,
} from '../src/customerStatus.js';

// Internal order rows shaped exactly like GET /api/orders.
const order = (over = {}) => ({
  order_id: 'SO-1',
  buyer: 'clover',
  flow_step: 'ORDER',
  overall_status: 'NEW',
  finance_status: 'UNPAID',
  finance_gate_status: 'PENDING',
  material_status: 'NOT_REQUESTED',
  shipment_status: 'NOT_READY',
  customer_close_status: 'OPEN',
  operational_close_status: 'OPEN',
  financial_close_status: 'OPEN',
  articles: [],
  ...over,
});

test('poin 6: each internal stage maps to the exact customer-safe sentence', () => {
  assert.equal(customerStatusLabel(order({ flow_step: 'ORDER', overall_status: 'NEW' })), 'Pesanan sedang diverifikasi');
  assert.equal(customerStatusLabel(order({ flow_step: 'INVOICE', finance_status: 'UNPAID', finance_gate_status: 'PENDING' })), 'Menunggu proses pembayaran');
  assert.equal(customerStatusLabel(order({ flow_step: 'SAMPLE', articles: [{ id: 1, sample_status: 'PROCESS' }] })), 'Sampel sedang diproses');
  assert.equal(customerStatusLabel(order({ flow_step: 'SPK', articles: [{ id: 1, sample_status: 'APPROVED', production_status: 'NOT_STARTED' }] })), 'Pesanan siap diproduksi');
  assert.equal(customerStatusLabel(order({ flow_step: 'PRODUCTION', articles: [{ id: 1, production_route: 'Cutting>Packing', production_status: 'IN_PROCESS' }] })), 'Pesanan sedang diproduksi');
  assert.equal(customerStatusLabel(order({ flow_step: 'QC', articles: [{ id: 1, production_status: 'PRODUCED', qc_status: 'PASS' }] })), 'Pemeriksaan kualitas selesai');
  assert.equal(customerStatusLabel(order({ flow_step: 'SHIPMENT', shipment_status: 'PREPARING' })), 'Pesanan siap dikirim');
  assert.equal(customerStatusLabel(order({ flow_step: 'DELIVERED', shipment_status: 'SHIPPED', overall_status: 'COMPLETED' })), 'Pesanan telah dikirim');
  assert.equal(customerStatusLabel(order({ flow_step: 'CLOSED', overall_status: 'CLOSED', operational_close_status: 'CLOSED', financial_close_status: 'CLOSED' })), 'Pesanan selesai');
});

test('poin 6: sentences are exactly the strings the spec requires', () => {
  assert.deepEqual(CUSTOMER_STATUS, {
    VERIFIKASI: 'Pesanan sedang diverifikasi',
    MENUNGGU_PEMBAYARAN: 'Menunggu proses pembayaran',
    SAMPEL: 'Sampel sedang diproses',
    SIAP_PRODUKSI: 'Pesanan siap diproduksi',
    PRODUKSI: 'Pesanan sedang diproduksi',
    QC_SELESAI: 'Pemeriksaan kualitas selesai',
    SIAP_KIRIM: 'Pesanan siap dikirim',
    DIKIRIM: 'Pesanan telah dikirim',
    SELESAI: 'Pesanan selesai',
  });
});

test('a closed order never reports "sedang diproduksi" even with WIP data left over', () => {
  const closed = order({
    flow_step: 'CLOSED',
    overall_status: 'CLOSED',
    operational_close_status: 'CLOSED',
    financial_close_status: 'CLOSED',
    customer_close_status: 'CLOSED',
    shipment_status: 'DELIVERED',
    articles: [{ id: 1, production_route: 'Cutting>Packing', production_status: 'IN_PROCESS' }],
  });
  assert.equal(customerStatus(closed).label, 'Pesanan selesai');
  assert.notEqual(customerStatus(closed).label, 'Pesanan sedang diproduksi');
  assert.match(customerStatus(closed).karena, /CLOSED/);
});

test('priority order: closing > shipped > ready to ship > QC > production > SPK > sample > payment', () => {
  // Shipped beats production.
  assert.equal(customerStatusLabel(order({
    flow_step: 'QC',
    shipment_status: 'SHIPPED',
    articles: [{ id: 1, production_status: 'IN_PROCESS' }],
  })), 'Pesanan telah dikirim');

  // Shipment document finalised and waiting for dispatch.
  // PREPARING is NOT "siap dikirim": packing work is still running there, and
  // announcing readiness would over-promise to the buyer.
  assert.equal(customerStatusLabel(order({
    flow_step: 'SHIPMENT',
    shipment_status: 'PACKED',
    articles: [{ id: 1, production_status: 'PRODUCED' }],
  })), 'Pesanan siap dikirim');

  // QC pass beats production.
  assert.equal(customerStatusLabel(order({
    flow_step: 'PRODUCTION',
    articles: [{ id: 1, production_status: 'PRODUCED', qc_status: 'PASS' }],
  })), 'Pemeriksaan kualitas selesai');

  // Production beats sample: once real production progress exists, the sample
  // phase is over. A planned production_route alone does NOT count as running
  // production — draft orders carry a route from the start.
  assert.equal(customerStatusLabel(order({
    flow_step: 'SPK',
    shipment_status: 'NOT_READY',
    articles: [{ id: 1, sample_status: 'PROCESS', production_status: 'IN_PROCESS', production_route: 'Cutting>Packing' }],
  })), 'Pesanan sedang diproduksi');

  // Sample beats the SPK sentence when SPK is not released yet.
  assert.equal(customerStatusLabel(order({
    flow_step: 'SAMPLE',
    articles: [{ id: 1, sample_status: 'REQUESTED' }],
  })), 'Sampel sedang diproses');

  // Payment stage beats the generic draft sentence.
  assert.equal(customerStatusLabel(order({ flow_step: 'INVOICE', finance_status: 'PARTIAL' })), 'Menunggu proses pembayaran');
});

test('unfinished QC and unknown values fall back to safe text, never over-promise', () => {
  // QC in rework must not claim the inspection is finished.
  assert.equal(customerStatusLabel(order({
    flow_step: 'QC',
    articles: [{ id: 1, production_status: 'PRODUCED', qc_status: 'REWORK' }],
  })), 'Pesanan sedang diproduksi');

  const unknown = customerStatus({ flow_step: 'SOMETHING_NEW', internal_secret: 'x' });
  assert.equal(unknown.label, 'Pesanan sedang diverifikasi');
  assert.equal(unknown.karena.includes('internal_secret'), false);

  // NULL-ish payload must not throw.
  assert.equal(customerStatus(null).label, 'Pesanan sedang diverifikasi');
  assert.equal(customerStatus({}).label, 'Pesanan sedang diverifikasi');
});

test('poin 7: visible fields list and the customer projection contain no internal key', () => {
  assert.deepEqual(customerVisibleFields(), [
    'order_id', 'buyer', 'articles', 'tahap', 'projected_shipment',
    'sample_approval_request', 'status_pembayaran_sederhana', 'shipment', 'resi',
    'updated_at', 'riwayat_status',
  ]);

  const projected = toCustomerOrder(order({
    flow_step: 'PRODUCTION',
    projected_shipment: '2026-10-02',
    updated_at: '2026-09-16T04:28:33Z',
    hpp: 9000,
    margin: 0.25,
    internal_notes: 'do not ship to competitor',
    articles: [{ id: 7, article_code: 'xray', qty: 200, production_route: 'Cutting>Packing', production_status: 'IN_PROCESS' }],
  }));
  assert.ok(projected, 'safe order should project, not be rejected');
  assert.deepEqual(projected.articles, [{ code: 'xray', qty: 200 }]);
  assert.equal(projected.order_id, 'SO-1');
  assert.equal(projected.status_customer, 'Pesanan sedang diproduksi');
  assert.deepEqual(assertCustomerSafe(projected), []);

  // The source row may carry forbidden keys: the projection drops them all,
  // they are never copied into the customer view.
  const fromDirtySource = toCustomerOrder(order({ hpp: 12000, margin: 0.3, catatan_internal: 'x' }));
  assert.ok(fromDirtySource);
  assert.deepEqual(assertCustomerSafe(fromDirtySource), []);
  assert.equal(JSON.stringify(fromDirtySource).includes('12000'), false);

  // A projector fed an article row carrying a forbidden key must not copy it through.
  const dirtyArticles = toCustomerOrder({ ...order(), articles: [{ article_code: 'xray', qty: 1, hpp: 9000 }] });
  assert.deepEqual(dirtyArticles.articles, [{ code: 'xray', qty: 1 }]);
  assert.equal(JSON.stringify(dirtyArticles).includes('9000'), false);
});

test('poin 8: assertCustomerSafe flags forbidden keys, nested and case-insensitive', () => {
  assert.deepEqual(customerHiddenFields(), [
    'hpp', 'margin', 'harga_supplier', 'cash_position',
    'kapasitas_detail', 'masalah_karyawan', 'catatan_internal', 'exception_internal',
  ]);

  // Flat leak.
  assert.deepEqual(assertCustomerSafe({ order_id: 'SO-1', hpp: 9000 }), ['hpp']);
  assert.equal(isCustomerSafe({ order_id: 'SO-1', hpp: 9000 }), false);

  // Case-insensitive spelling.
  assert.deepEqual(assertCustomerSafe({ HPP: 1, Margin: 2, HARGA_SUPPLIER: 3 }), ['HPP', 'Margin', 'HARGA_SUPPLIER']);

  // Same concept under an alias used elsewhere in the repo.
  assert.deepEqual(assertCustomerSafe({ internal_notes: 'x' }), ['internal_notes']);
  assert.deepEqual(assertCustomerSafe({ cost: 5 }), ['cost']);

  // Nested through objects and arrays, reported as dotted paths.
  const nested = {
    order_id: 'SO-1',
    buyer: 'clover',
    detail: { kapasitas_detail: { line: 3, kapasitas_harian: 400 } },
    articles: [{ code: 'xray', cost: 9000 }, { code: 'delta', margin_pct: 12 }],
    clean: [{ code: 'fine' }],
  };
  assert.deepEqual(assertCustomerSafe(nested), [
    'detail.kapasitas_detail',
    'detail.kapasitas_detail.kapasitas_harian',
    'articles[0].cost',
    'articles[1].margin_pct',
  ]);

  // A fully audited customer payload is clean.
  assert.deepEqual(assertCustomerSafe({
    order_id: 'SO-1',
    buyer: 'clover',
    articles: [{ code: 'xray', qty: 200 }],
    tahap: 'Produksi',
    status_pembayaran_sederhana: 'Menunggu pembayaran',
    updated_at: '2026-09-16T04:28:33Z',
    riwayat_status: [{ at: '2026-09-16', label: 'Pesanan sedang diproduksi' }],
  }), []);

  // Null / scalar payloads are safe and must not throw.
  assert.deepEqual(assertCustomerSafe(null), []);
  assert.deepEqual(assertCustomerSafe('hpp'), []);
});

test('simple payment status never exposes amounts, terms or credit limits', () => {
  assert.equal(simplePaymentStatus(order({ finance_status: 'UNPAID' })), 'Menunggu pembayaran');
  assert.equal(simplePaymentStatus(order({ finance_status: 'PARTIAL' })), 'Pembayaran sebagian diterima');
  assert.equal(simplePaymentStatus(order({ finance_status: 'PAID', finance_gate_status: 'APPROVED' })), 'Pembayaran lunas');
  const text = simplePaymentStatus(order({ finance_status: 'PAID', finance_gate_status: 'REJECTED' }));
  assert.equal(/rp|idr|\d{4,}/i.test(text), false);
});

test('over-promise guards: PREPARING is not ready-to-ship, planned route is not production', () => {
  // Regresi: 3 order live ber-flow_step=ORDER + shipment_status=PREPARING dulu
  // tampil "siap dikirim" padahal belum ada shipment sama sekali.
  assert.equal(customerStatusLabel(order({
    flow_step: 'ORDER',
    overall_status: 'NEW',
    shipment_status: 'PREPARING',
    articles: [{ id: 1, production_status: 'NOT_STARTED', production_route: 'Cutting > Sewing > QC' }],
  })), 'Pesanan sedang diverifikasi');

  // Regresi: production_route yang cuma direncanakan tidak boleh diklaim
  // sebagai produksi berjalan.
  assert.equal(customerStatusLabel(order({
    flow_step: 'ORDER',
    overall_status: 'NEW',
    shipment_status: 'NOT_READY',
    articles: [{ id: 1, production_status: 'NOT_STARTED', production_route: 'Cutting > Sewing' }],
  })), 'Pesanan sedang diverifikasi');
});
