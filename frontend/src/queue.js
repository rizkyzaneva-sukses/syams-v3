/* Decision-queue column helpers (revisi #9 poin 3, #13 poin 3, #14 poin 3-6).

   Every queue row must expose: tahap proses, status saat ini, data/bukti yang
   kurang, next action, owner saat ini, due date/SLA, source, updated_at dan
   status handoff. The backend stores the process step (flow_step); these helpers
   turn that recorded state into the human-readable action columns, so the same
   mapping is used by Orders, the PPM/Sample feed and Buyer CRM. */

export const FLOW_LABELS = {
  ORDER: 'Order Diterima',
  INVOICE: 'Invoice & Pembayaran',
  PPM: 'PPM / Penyesuaian',
  SAMPLE: 'Sample / PPM',
  SAMPLE_APPROVED: 'Sample Disetujui',
  FOLLOW_UP: 'Follow-up / Pengembangan',
  SPK: 'SPK Release',
  PRODUCTION: 'Produksi',
  QC: 'QC & Packing',
  SHIPMENT: 'Pengiriman',
  DELIVERED: 'Diterima Customer',
  CLOSED: 'Order Selesai',
};

/* Who acts next, and what that action is, for each lifecycle step. */
const STEP_ACTION = {
  ORDER:     { owner: 'CMO_MANAGER', action: 'Review PO dan aktifkan order',          handoff: 'Lengkapi invoice & gate pembayaran' },
  INVOICE:   { owner: 'CFO_MANAGER', action: 'Terbitkan invoice dan verifikasi pembayaran', handoff: 'Evidence Sample/PPM disiapkan Deby' },
  PPM:       { owner: 'CMO_SUPPORT', action: 'Lengkapi bukti dan data PPM',           handoff: 'Keputusan Cecep atas PPM' },
  SAMPLE:    { owner: 'SAMPLE_PIC',  action: 'Selesaikan sample dan unggah bukti',    handoff: 'Keputusan customer dicatat Cecep' },
  SAMPLE_APPROVED: { owner: 'CMO_MANAGER', action: 'Catat keputusan customer atas sample', handoff: 'SPK di-Generate Deby' },
  FOLLOW_UP: { owner: 'CMO_SUPPORT', action: 'Follow up buyer dan catat hasil',       handoff: 'Repeat opportunity atau closing' },
  SPK:       { owner: 'CMO_MANAGER', action: 'Release SPK ke COO',                    handoff: 'Batch Release oleh Siti/COO' },
  PRODUCTION:{ owner: 'COO_MANAGER', action: 'Jalankan produksi dan pantau WIP',      handoff: 'QC & packing' },
  QC:        { owner: 'PRODUCTION_PIC', action: 'Periksa kualitas dan packing',       handoff: 'Shipment dibuat Shipment Admin' },
  SHIPMENT:  { owner: 'SHIPMENT_ADMIN', action: 'Kirim barang dan catat resi',        handoff: 'Konfirmasi penerimaan customer' },
  DELIVERED: { owner: 'CMO_SUPPORT', action: 'Konfirmasi penerimaan ke buyer',        handoff: 'Closing customer & operasional' },
  CLOSED:    { owner: '—',           action: 'Selesai — cari peluang repeat order',   handoff: '—' },
};

export function stepAction(step) {
  return STEP_ACTION[step] || { owner: '—', action: '—', handoff: '—' };
}

/* What evidence or data is still missing, inferred from recorded statuses. */
export function missingEvidence(order) {
  const missing = [];
  if (!order.buyer_deadline) missing.push('Deadline buyer');
  if (!order.projected_shipment) missing.push('Proyeksi shipment');
  if (order.finance_status && order.finance_status !== 'PAID' && order.finance_status !== 'CLEAR' && order.finance_status !== 'READY') {
    missing.push('Pembayaran');
  }
  if (order.material_status && !['READY', 'CLEAR'].includes(order.material_status)) missing.push('Material');
  return missing;
}

/* Source document that put the row in the queue. */
export function queueSource(order) {
  if (order.flow_step === 'ORDER') return 'PO buyer / Draft Order';
  if (['SAMPLE', 'SAMPLE_APPROVED', 'PPM'].includes(order.flow_step)) return 'Bukti Sample/PPM';
  if (order.flow_step === 'SPK') return 'Versi SPK terkunci';
  if (order.flow_step === 'INVOICE') return 'Invoice & gate pembayaran';
  return 'Alur order';
}

export function isOverdue(dueDate) {
  if (!dueDate) return false;
  const due = new Date(dueDate + 'T23:59:59');
  return due < new Date();
}

/* SLA internal: sisa hari terhadap due date, dihitung dari kalender lokal.
   Due hari ini = 0 hari (bukan lewat), supaya baris "due today" tidak
   dilaporkan sebagai overdue oleh selisih jam. */
export function slaDays(dueDate, now) {
  if (!dueDate) return null;
  const due = new Date(dueDate + 'T00:00:00');
  if (Number.isNaN(due.getTime())) return null;
  const today = now ? new Date(now) : new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((due - today) / 86400000);
}

/* One SLA vocabulary for every queue. Cecep's Morning Priority API already
   ships `sla`/`sla_days`; halaman yang tidak menerima field itu menghitung
   nilainya dari due date lewat slaDays() sehingga labelnya tetap identik. */
export const SLA_LABELS = {
  OVERDUE: 'Lewat SLA',
  DUE_TODAY: 'Jatuh tempo hari ini',
  DUE_3_HARI: '≤ 3 hari lagi',
  DUE_7_HARI: '≤ 7 hari lagi',
  AMAN: 'Aman',
  TANPA_DUE: 'Tanpa due date',
};

export function slaLabel(code) {
  return SLA_LABELS[code] || code || SLA_LABELS.TANPA_DUE;
}

const SLA_TONE = { OVERDUE: 'red', DUE_TODAY: 'amber', DUE_3_HARI: 'amber', DUE_7_HARI: 'gray', AMAN: 'green' };

/* Badge SLA internal untuk sebuah baris antrean. `dueDate` = tenggat yang
   disepakati di internal (buyer_deadline / valid_until); `code` = nilai `sla`
   kalau endpoint sudah menghitungnya, supaya UI tidak menghitung ulang dengan
   aturan yang bisa berbeda dari server. */
export function slaBadge(dueDate, code, now) {
  const resolved = code || (dueDate ? (slaDays(dueDate, now) < 0 ? 'OVERDUE' : slaDays(dueDate, now) === 0 ? 'DUE_TODAY' : slaDays(dueDate, now) <= 3 ? 'DUE_3_HARI' : slaDays(dueDate, now) <= 7 ? 'DUE_7_HARI' : 'AMAN') : 'TANPA_DUE');
  const days = slaDays(dueDate, now);
  const suffix = resolved === 'OVERDUE' && days != null ? ` (${Math.abs(days)} hari)` : days != null && days > 0 ? ` (${days} hari)` : '';
  return { code: resolved, label: slaLabel(resolved) + suffix, tone: SLA_TONE[resolved] || 'gray', days };
}

/* Status handoff per-order (blueprint REF-DEBY poin 3, REF-CECEP poin 3):
   siapa pegang baris ini sekarang dan ke siapa baris ini diserahkan berikutnya.
   `queue` = hasil stepAction(flow_step) — antrean order (OrderList),
   `owner`/`handoff` bisa ditimpa pemanggil kalau pemilik baris bukan pemilik
   tahap (mis. antrean PO Inbox: Deby yang menyiapkan, Cecep yang memutuskan). */
export function handoffStatus({queue, owner, handoff, closed}={}) {
  const from = owner || queue?.owner;
  const to = handoff || queue?.handoff;
  if (closed || from === '—' || from == null) return { owner: from || '—', to: to || '—', label: 'Selesai — tidak ada handoff', tone: 'green' };
  return { owner: from, to: to || '—', label: `Di tangan ${from} → ${to}`, tone: from.startsWith('CMO_SUPPORT') ? 'blue' : from.startsWith('CMO_MANAGER') ? 'amber' : 'gray' };
}

/* Task ID formal (blueprint REF-DEBY poin 3): satu format untuk seluruh antrean
   CMO Support supaya Deby bisa menyebut baris yang sama ke divisi lain.
   Format: <KODE>-<REF>[, <KODE>-<REF>...] — kode task, bukan teks yang dikarang.
   Baris tanpa referensi tetap dapat Task ID supaya kolomnya tidak pernah kosong. */
const TASK_CODES = { PO: 'PO', ORDER: 'ORD', QUOTATION: 'QUO', SAMPLE: 'SMP', SPK: 'SPK', AFTER_SALES: 'AS', FOLLOW_UP: 'FU' };

export function taskId(prefix, refs) {
  const code = TASK_CODES[prefix] || prefix;
  const list = (Array.isArray(refs) ? refs : [refs]).filter(value => value != null && value !== '');
  if (!list.length) return `${code}-BARU`;
  return list.map(ref => `${code}-${ref}`).join(', ');
}

/* Handoff antrean PO Inbox (REF-DEBY poin 3-4). Bedanya dengan handoffStatus:
   baris PO berpindah pemilik karena STATUS PO-nya, bukan karena tahap order
   (flow_step) — Deby menyiapkan, Cecep memutuskan, CFO/COO menerima order aktif. */
export function poHandoff(row) {
  const status = row?.status;
  if (status === 'SUBMITTED') return { owner: 'CMO_MANAGER (Cecep)', to: 'Order aktif → CFO pricing/invoice', label: 'Diserahkan ke Cecep untuk accept/reject', tone: 'amber' };
  if (status === 'ACCEPTED') return { owner: 'CFO_MANAGER', to: 'Invoice, verifikasi pembayaran, lalu produksi (COO)', label: 'Serah terima ke CFO setelah order aktif', tone: 'green' };
  if (status === 'REJECTED') return { owner: 'CMO_SUPPORT (Deby)', to: 'Buyer — dokumen PO direvisi', label: 'Dikembalikan ke Deby untuk revisi dokumen buyer', tone: 'red' };
  return { owner: 'CMO_SUPPORT (Deby)', to: 'CMO_MANAGER (Cecep) setelah kelengkapan terpenuhi', label: 'Masih di meja Deby — belum diserahkan', tone: 'blue' };
}

/* Handoff antrean Quotation (REF-DEBY poin 7). Alur yang dikunci blueprint
   (poin 11): Deby siapkan harga → CFO setujui/tolak → Deby kirim ke buyer →
   Cecep catat balasan. Dirakit dari status + approval yang tercatat di server. */
export function quotationHandoff(quote) {
  if (quote?.ceo_approved_by_id) return { owner: 'CMO_SUPPORT (Deby)', to: 'Buyer — penawaran resmi dikirim', label: 'Di atas limit: sudah disetujui CEO, Deby meneruskan ke buyer', tone: 'green' };
  if (quote?.status === 'APPROVED') return { owner: 'CMO_SUPPORT (Deby)', to: 'Buyer — penawaran resmi dikirim', label: 'CFO sudah approve; Deby mengirim ke buyer', tone: 'blue' };
  if (quote?.approved_by_id) return { owner: 'CMO_SUPPORT (Deby)', to: 'Buyer — penawaran resmi dikirim', label: 'Harga siap — Deby menerbitkan penawaran', tone: 'blue' };
  if (quote?.status === 'REJECTED') return { owner: 'CMO_SUPPORT (Deby)', to: 'CFO_MANAGER — harga diperbaiki lalu diajukan ulang', label: 'Dikembalikan CFO untuk perbaikan harga', tone: 'red' };
  if (quote?.status === 'SENT') return { owner: 'BUYER (menunggu balasan)', to: 'CMO_MANAGER (Cecep) — catat keputusan buyer', label: 'Diserahkan ke buyer; hasil dicatat Cecep', tone: 'amber' };
  return { owner: 'CFO_MANAGER', to: 'CMO_SUPPORT (Deby) setelah harga/HPP disetujui', label: 'Menunggu keputusan harga CFO', tone: 'amber' };
}

export function dismissOnce(key) {
  /* Reserved for future per-row dismissals. Kept explicit so callers do not
     mutate module-level state (a bug that previously dropped sidebar entries). */
  return key;
}
