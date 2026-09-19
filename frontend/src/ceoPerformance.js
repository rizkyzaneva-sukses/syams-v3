/* Kontrak tampilan Company Performance (revisi #71 & #77).

   Halaman CEO hanya BOLEH menampilkan angka yang datang dari API beserta
   provenance-nya. Modul ini memegang aturan format supaya halaman tidak
   menebak-nebak sendiri:

   - angka nol, data yang belum ada (MISSING), dan yang memang tidak relevan
     (NOT_APPLICABLE) tidak boleh tampil sama;
   - mata uang, persen, dan tanggal punya format masing-masing;
   - setiap KPI wajib punya KPI ID + sumber, jadi label kosong = bug, bukan
     sesuatu yang ditutupi dengan tanda "-".

   Semuanya fungsi murni supaya bisa diuji tanpa browser. */

export const HEALTH_TONE = { GREEN: 'green', YELLOW: 'amber', RED: 'red', MISSING: 'gray', NOT_APPLICABLE: 'gray' };

/* Blueprint #71: bedakan missing data, zero, dan not applicable. */
export const DATA_STATE_LABEL = {
  VALUE: 'terukur',
  ZERO: 'nol',
  MISSING: 'data belum ada',
  NOT_APPLICABLE: 'tidak relevan',
};

const currency = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 2 });

/** Format mata uang; null berarti "belum ada data", bukan Rp 0. */
export function formatCurrency(value) {
  if (value == null || value === '') return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return currency.format(number);
}

/** Format angka biasa (ada pemisah ribuan). */
export function formatCount(value) {
  if (value == null || value === '') return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return decimal.format(number);
}

/** Format persen mengikuti `unit` dari API, bukan ditebak dari nama field. */
export function formatPercent(value) {
  if (value == null || value === '') return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return `${decimal.format(number)}%`;
}

/**
 * Satu-satunya jalan menampilkan nilai KPI.
 * @returns {{text: string, tone: string, state: string, isMissing: boolean}}
 */
export function formatKpiValue(kpi) {
  if (!kpi) return { text: '—', tone: 'gray', state: 'MISSING', isMissing: true };
  const state = kpi.data_state || (kpi.value == null ? 'MISSING' : 'VALUE');
  if (state === 'NOT_APPLICABLE') {
    return { text: 'Tidak relevan', tone: 'gray', state, isMissing: false };
  }
  if (kpi.value == null) {
    return { text: 'Belum ada data', tone: 'gray', state: 'MISSING', isMissing: true };
  }
  const unit = String(kpi.unit || '').toLowerCase();
  let text;
  if (unit === 'idr' || unit === 'currency') text = formatCurrency(kpi.value);
  else if (unit === 'percent') text = formatPercent(kpi.value);
  else text = formatCount(kpi.value);
  if (text == null) return { text: 'Belum ada data', tone: 'gray', state: 'MISSING', isMissing: true };
  return { text, tone: HEALTH_TONE[kpi.status] || 'gray', state, isMissing: false };
}

/** Angka rupiah yang bisa `null` — jangan mengubahnya jadi 0 (revisi #71). */
export function formatNullableCurrency(value) {
  return formatCurrency(value) ?? 'Belum ada data';
}

/** Berapa KPI yang belum punya sumber otoritatif. */
export function missingKpiIds(payload) {
  const kpis = payload?.kpis || [];
  return kpis.filter((kpi) => !kpi.kpi_id || !kpi.source_module).map((kpi) => kpi.kpi_id || kpi.label);
}

/** Rekonsiliasi: baris yang totalnya tidak sama dengan modul otoritatif. */
export function reconciliationMismatches(payload) {
  return (payload?.reconciliation || []).filter((row) => !row.match);
}

/** Final close hanya siap kalau ketiga dimensi lulus (revisi #77). */
export function finalCloseReady(payload) {
  if (!payload) return false;
  return Boolean(payload.final_close_ready);
}

const DOMAIN_LABELS = {
  finance: 'Finance / Cash & Collection',
  production: 'Production Today',
  sales: 'Sales Opportunity',
  people: 'People Condition',
};

export function domainLabel(domain) {
  return DOMAIN_LABELS[domain] || domain;
}

/** Baris drill-down dipetakan ke kolom yang dideklarasikan API, bukan hard-code. */
export function drilldownTable(payload) {
  const rows = payload?.rows || payload?.employees || payload?.quotations || [];
  const columns = payload?.columns || [];
  return { columns, rows };
}
