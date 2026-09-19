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

export function dismissOnce(key) {
  /* Reserved for future per-row dismissals. Kept explicit so callers do not
     mutate module-level state (a bug that previously dropped sidebar entries). */
  return key;
}
