// Customer-safe status mapping (INT-ORDER-001 poin 6, 7, 8).
//
// Rule-only module: it never calls the API and never creates a customer
// tracking record of its own. The customer portal reads the SAME Order ID
// and the SAME internal status fields that the internal screens use, then
// translates them into a safe sentence before rendering.
//
// Internal vocabulary used below comes from the backend, not from guesses:
//   flow_step      : ORDER | INVOICE | PPM | SAMPLE | SAMPLE_APPROVED |
//                    FOLLOW_UP | SPK | PRODUCTION | QC | SHIPMENT |
//                    DELIVERED | CLOSED              (app/flow_engine.py)
//   finance_status : UNPAID | PARTIAL | PAID
//   finance_gate_status : PENDING | APPROVED | REJECTED | HOLD
//   material_status     : NOT_REQUESTED | WAITING | PARTIAL | READY | CLEAR
//   shipment_status     : NOT_READY | PREPARING | READY | HOLD | SHIPPED | DELIVERED
//   *_close_status      : OPEN | CLOSED
//   articles[].sample_status     : PROCESS | REQUESTED | APPROVED | REJECTED | NOT_REQUIRED
//   articles[].production_status : NOT_STARTED | IN_PROCESS | DONE | PRODUCED | SHIPPED

// ──────────── POIN 6 — STATUS AMAN UNTUK CUSTOMER ────────────

/** Exact customer-facing sentences required by INT-ORDER-001 poin 6. */
export const CUSTOMER_STATUS = {
  VERIFIKASI: 'Pesanan sedang diverifikasi',
  MENUNGGU_PEMBAYARAN: 'Menunggu proses pembayaran',
  SAMPEL: 'Sampel sedang diproses',
  SIAP_PRODUKSI: 'Pesanan siap diproduksi',
  PRODUKSI: 'Pesanan sedang diproduksi',
  QC_SELESAI: 'Pemeriksaan kualitas selesai',
  SIAP_KIRIM: 'Pesanan siap dikirim',
  DIKIRIM: 'Pesanan telah dikirim',
  SELESAI: 'Pesanan selesai',
};

// Production process words that map onto "Pesanan sedang diproduksi"
// (poin 6: "Cutting sampai Packing"). Kept as words, not hard-coded article
// rows, because production_route is free text typed by the COO.
export const PRODUCTION_PROCESSES = [
  'CUTTING', 'SEWING', 'JAHIT', 'PRINTING', 'PRINT', 'BORDIR', 'EMBROIDERY',
  'SABLON', 'STEAM', 'FINISHING', 'PACKING', 'PACK', 'PACKED', 'PENGEPAKAN', 'QC',
];

// QC states that are not finished yet, so they may NOT claim "selesai".
const QC_UNFINISHED = ['PENDING', 'PROCESS', 'IN_PROCESS', 'REWORK', 'FAIL', 'REJECTED'];

// Shipment states that mean goods have physically left, not merely prepared.
const SHIPMENT_SENT = ['SHIPPED', 'DELIVERED'];
const SHIPMENT_READY = ['READY', 'PREPARING', 'PACKED', 'PACKING'];
const CLOSE_OPEN = ['OPEN', 'PENDING', 'PARTIAL'];

/** Normalise any server value for comparison: 'in process' / 'shipped' -> 'IN_PROCESS'. */
const norm = (value) =>
  String(value ?? '').trim().toUpperCase().replace(/[\s-]+/g, '_');

const anyIn = (value, list) => list.includes(norm(value));

/** True when at least one article is actually running on the floor. */
function productionStarted(order) {
  const articles = order?.articles || [];
  return articles.some(
    (a) => !['NOT_STARTED', ''].includes(norm(a?.production_status)),
  );
}

/** True once cutting→packing work exists: a route was planned or movements exist. */
function productionEngaged(order) {
  const articles = order?.articles || [];
  return articles.some(
    (a) => String(a?.production_route || '').trim() !== '' || productionStarted(order),
  );
}

function qcFinished(order) {
  const articles = order?.articles || [];
  const statuses = articles
    .map((a) => norm(a?.qc_status ?? a?.final_qc_status))
    .filter(Boolean);
  if (statuses.some((s) => QC_UNFINISHED.includes(s))) return false;
  if (statuses.length && statuses.every((s) => s === 'PASS')) return true;
  // QC step is only "finished" once the SPK route reached its final process,
  // which the backend exposes as article.production_status.
  return articles.length > 0 && articles.every((a) => ['PRODUCED', 'DONE'].includes(norm(a?.production_status)));
}

function sampleInProgress(order) {
  const articles = order?.articles || [];
  return articles.some((a) => ['PROCESS', 'REQUESTED', 'IN_PROCESS', 'PENDING'].includes(norm(a?.sample_status)))
    || articles.some((a) => a?.sample_required === true && !norm(a?.sample_status));
}

/**
 * Map one order (fields exactly as returned by /api/orders) to the single
 * customer-safe sentence allowed by INT-ORDER-001 poin 6.
 *
 * Check order is deliberate and highest-authority-first:
 *   closing → shipment → QC → production → SPK → sample → payment gate →
 *   draft/review. A closed order therefore can never report "sedang diproduksi".
 *
 * @returns {{label: string, karena: string}}
 */
export function customerStatus(order) {
  const o = order || {};
  const step = norm(o.flow_step) || 'ORDER';
  const overall = norm(o.overall_status);
  const operational = norm(o.operational_close_status);
  const financial = norm(o.financial_close_status);
  const customer = norm(o.customer_close_status);
  const finance = norm(o.finance_status);
  const gate = norm(o.finance_gate_status);
  const shipment = norm(o.shipment_status);
  const material = norm(o.material_status);

  // 1) Closing beats everything: operational + financial closed = Pesanan selesai.
  if (
    step === 'CLOSED'
    || overall === 'CLOSED'
    || (operational === 'CLOSED' && financial === 'CLOSED')
    || (customer === 'CLOSED' && operational === 'CLOSED' && financial === 'CLOSED')
  ) {
    return { label: CUSTOMER_STATUS.SELESAI, karena: 'closing operasional dan finansial sudah CLOSED' };
  }

  // 2) Already with the buyer / on the way beats production and QC.
  if (SHIPMENT_SENT.includes(shipment) || ['DELIVERED', 'SHIPPED'].includes(step) || overall === 'COMPLETED') {
    return { label: CUSTOMER_STATUS.DIKIRIM, karena: `shipment_status=${shipment || 'SHIPPED'}` };
  }

  // 3) Shipment document exists but not dispatched = siap dikirim.
  if (step === 'SHIPMENT' || SHIPMENT_READY.includes(shipment) || shipment === 'HOLD') {
    return { label: CUSTOMER_STATUS.SIAP_KIRIM, karena: `tahap pengiriman (shipment_status=${shipment || 'PREPARING'}, flow_step=SHIPMENT)` };
  }

  // 4) Quality check finished (before production is declared done).
  if (qcFinished(o)) {
    return { label: CUSTOMER_STATUS.QC_SELESAI, karena: 'seluruh QC final artikel PASS' };
  }

  // 5) Cutting sampai Packing = sedang diproduksi.
  if (step === 'PRODUCTION' || step === 'QC' || step === 'DELIVERED' || productionStarted(o) || productionEngaged(o)) {
    return { label: CUSTOMER_STATUS.PRODUKSI, karena: `produksi berjalan (flow_step=${step}, material=${material || 'READY'})` };
  }

  // 6) Released SPK = siap produksi (belum ada pergerakan Cutting).
  if (step === 'SPK') {
    return { label: CUSTOMER_STATUS.SIAP_PRODUKSI, karena: 'SPK sudah dirilis, produksi belum mulai' };
  }

  // 7) Sample / PPM still in the sample process.
  if (step === 'SAMPLE' || step === 'PPM' || sampleInProgress(o)) {
    return { label: CUSTOMER_STATUS.SAMPEL, karena: `tahap sampel (flow_step=${step || 'SAMPLE'})` };
  }

  // 8) Sample already approved: waiting on the SPK to be released.
  if (step === 'SAMPLE_APPROVED') {
    return { label: CUSTOMER_STATUS.SIAP_PRODUKSI, karena: 'sampel disetujui, menunggu rilis SPK' };
  }

  // 9) Finance gate / payment stage.
  if (step === 'INVOICE') {
    if (finance === 'PAID' && gate !== 'REJECTED') {
      return { label: CUSTOMER_STATUS.VERIFIKASI, karena: 'pembayaran diterima, menunggu verifikasi internal' };
    }
    return { label: CUSTOMER_STATUS.MENUNGGU_PEMBAYARAN, karena: `tahap invoice (finance_status=${finance || 'UNPAID'}, gate=${gate || 'PENDING'})` };
  }

  // 10) Draft / review CMO = sedang diverifikasi. Also the safe fallback for
  //     every unrecognised combination (never leak internals, never over-promise).
  return { label: CUSTOMER_STATUS.VERIFIKASI, karena: `order masih di tahap awal (flow_step=${step}, overall_status=${overall || 'NEW'})` };
}

/** Convenience: just the safe sentence. */
export function customerStatusLabel(order) {
  return customerStatus(order).label;
}

/** The flow label a customer is allowed to see, or null when unknown. */
export function customerStageLabel(order) {
  const step = norm(order?.flow_step);
  const stage = {
    ORDER: 'Verifikasi pesanan',
    INVOICE: 'Pembayaran',
    PPM: 'Sampel',
    SAMPLE: 'Sampel',
    SAMPLE_APPROVED: 'Persetujuan sampel',
    FOLLOW_UP: 'Tindak lanjut',
    SPK: 'Siap produksi',
    PRODUCTION: 'Produksi',
    QC: 'Pemeriksaan kualitas',
    SHIPMENT: 'Pengiriman',
    DELIVERED: 'Terkirim',
    CLOSED: 'Selesai',
  };
  return stage[step] || null;
}

// ──────────── POIN 7 — FIELD YANG BOLEH TAMPIL ────────────

/**
 * Customer-visible fields (INT-ORDER-001 poin 7).
 * Only these may ever be read/serialised for the customer portal.
 */
export function customerVisibleFields() {
  return [
    'order_id',
    'buyer',
    'articles',                       // code + qty only, see customerArticles()
    'tahap',
    'projected_shipment',
    'sample_approval_request',
    'status_pembayaran_sederhana',
    'shipment',
    'resi',
    'updated_at',
    'riwayat_status',
  ];
}

// ──────────── POIN 8 — FIELD YANG DILARANG TAMPIL ────────────

/**
 * Fields that must never reach the customer (INT-ORDER-001 poin 8).
 * Compared case-insensitively and matching nested keys at any depth.
 */
export function customerHiddenFields() {
  return [
    'hpp',
    'margin',
    'harga_supplier',
    'cash_position',
    'kapasitas_detail',
    'masalah_karyawan',
    'catatan_internal',
    'exception_internal',
  ];
}

// Aliases so server spellings of the same forbidden concept are caught too.
const HIDDEN_ALIASES = {
  hpp: ['hpp', 'hpp_total', 'harga_pokok_produksi', 'unit_cost', 'cost'],
  margin: ['margin', 'margin_pct', 'margin_percent', 'profit', 'laba'],
  harga_supplier: ['harga_supplier', 'supplier_price', 'harga_beli'],
  cash_position: ['cash_position', 'posisi_kas', 'saldo_kas', 'cashflow', 'cash_flow'],
  kapasitas_detail: ['kapasitas_detail', 'capacity_detail', 'kapasitas_harian'],
  masalah_karyawan: ['masalah_karyawan', 'employee_issue', 'employee_issues', 'hr_issue'],
  catatan_internal: ['catatan_internal', 'internal_note', 'internal_notes', 'notes_internal'],
  exception_internal: ['exception_internal', 'internal_exception', 'exception_detail'],
};

function leakBucket(key) {
  const k = norm(key).toLowerCase();
  for (const [canonical, aliases] of Object.entries(HIDDEN_ALIASES)) {
    if (aliases.includes(k)) return canonical;
  }
  // Any *hpp* / *margin* style key also counts as the same bucket.
  if (k.includes('hpp')) return 'hpp';
  if (k.includes('margin')) return 'margin';
  return null;
}

/**
 * Detect forbidden fields leaking into an object, including nested objects and
 * arrays (INT-ORDER-001 poin 8). Matching is case-insensitive and returns the
 * DOTTED PATHS of the leaked keys so the caller can log/fix them.
 *
 * @returns {string[]} leaked key paths; empty array means the payload is safe.
 */
export function assertCustomerSafe(obj) {
  const leaks = new Set();

  const walk = (value, path) => {
    if (Array.isArray(value)) {
      value.forEach((item, index) => walk(item, `${path}[${index}]`));
      return;
    }
    if (!value || typeof value !== 'object') return;
    for (const [key, child] of Object.entries(value)) {
      const here = path ? `${path}.${key}` : key;
      if (leakBucket(key)) leaks.add(here);
      walk(child, here);
    }
  };

  walk(obj, '');
  return [...leaks];
}

/** True when the payload carries no forbidden field. Handy as a guard clause. */
export function isCustomerSafe(obj) {
  return assertCustomerSafe(obj).length === 0;
}

/**
 * Reduce an internal order row to the customer-safe projection: only poin 7
 * fields, with articles trimmed to code + qty and the safe status sentence.
 * Returns null when the payload would still leak (fail closed).
 */
export function toCustomerOrder(order) {
  if (!order) return null;
  const projection = {
    order_id: order.order_id,
    buyer: order.buyer,
    articles: (order.articles || []).map((a) => ({ code: a.article_code ?? a.code, qty: a.qty })),
    tahap: customerStageLabel(order),
    projected_shipment: order.projected_shipment ?? null,
    sample_approval_request: order.sample_approval_request ?? null,
    status_pembayaran_sederhana: simplePaymentStatus(order),
    shipment: order.shipment ?? (norm(order.shipment_status) || null),
    resi: order.resi ?? order.tracking_no ?? null,
    updated_at: order.updated_at ?? null,
    riwayat_status: order.riwayat_status ?? [],
    status_customer: customerStatus(order).label,
  };
  return assertCustomerSafe(projection).length === 0 ? projection : null;
}

/** Plain-payment wording for customers: never exposes amounts, terms or credit. */
export function simplePaymentStatus(order) {
  const finance = norm(order?.finance_status);
  const gate = norm(order?.finance_gate_status);
  if (finance === 'PAID' && ['APPROVED', 'CLEAR', 'PAID'].includes(gate)) return 'Pembayaran lunas';
  if (finance === 'PARTIAL') return 'Pembayaran sebagian diterima';
  if (finance === 'PAID') return 'Pembayaran diterima';
  return 'Menunggu pembayaran';
}

export const customerStatusModule = {
  CUSTOMER_STATUS,
  PRODUCTION_PROCESSES,
  customerStatus,
  customerStatusLabel,
  customerStageLabel,
  customerVisibleFields,
  customerHiddenFields,
  assertCustomerSafe,
  isCustomerSafe,
  toCustomerOrder,
  simplePaymentStatus,
};

export default customerStatusModule;
