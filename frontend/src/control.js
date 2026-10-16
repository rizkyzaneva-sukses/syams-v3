/* Control System — helper murni (tanpa JSX) supaya bisa dites dengan `node --test`.

   Istilah dan warna mengikuti sheet lama: SELESAI hijau, PROGRES putih, PERHATIAN
   kuning, URGENT merah, "-" = tahap tidak dipakai. */
import {SIZES} from './sizes.js';

export const STATUS_TONE = {SELESAI: 'green', PROGRES: 'plain', PERHATIAN: 'amber', URGENT: 'red', '-': 'muted', '': 'empty'};

export function statusTone(status) {
  return STATUS_TONE[status] ?? 'empty';
}

/* Cermin STAGE_ROLES di backend/app/control_service.py. Hanya untuk menyembunyikan
   tombol yang pasti ditolak server — server tetap penentu hak akses. */
const PROD = ['COO_MANAGER', 'PRODUCTION_PIC'];
const PRINT = ['COO_MANAGER', 'PRINTING_PIC', 'PRODUCTION_PIC'];
export const STAGE_ROLES = {
  BAHAN: PROD, CUTTING: PROD, SORTIR: PROD, SEWING: PROD, ACC: PROD, QC_PACK: PROD, REVISI: PROD,
  PRINTING: PRINT, BORDIR: PRINT, QC_SB: PRINT, SHIPPING: ['COO_MANAGER', 'SHIPMENT_ADMIN'],
};
const BLOCK_EXTRA = ['CMO_MANAGER', 'COO_MANAGER'];
const AUTO_BLOCK = ['CMO_SUPPORT', 'CFO_MANAGER', 'SAMPLE_PIC'];

export function canActOnStage(role, code) {
  return (STAGE_ROLES[code] || []).includes(role);
}

export function canBlock(role, code) {
  if (BLOCK_EXTRA.includes(role)) return true;
  if (!code) return [...AUTO_BLOCK, 'PRODUCTION_PIC', 'PRINTING_PIC', 'SHIPMENT_ADMIN'].includes(role);
  return STAGE_ROLES[code] ? STAGE_ROLES[code].includes(role) : AUTO_BLOCK.includes(role);
}

export function canChangePic(role) {
  return ['COO_MANAGER', 'CMO_MANAGER'].includes(role);
}

export function canEditSettings(role) {
  return role === 'CMO_MANAGER';
}

/* Extra size: "M+2/L+1" ⇄ {M:2, L:1}. Urutan keluaran mengikuti SIZES. */
export function parseExtraSize(value) {
  const map = {};
  for (const part of String(value || '').split(/[/,;]/)) {
    const match = part.trim().toUpperCase().match(/^([A-Z0-9]+)\s*\+\s*(\d+)$/);
    if (match && Number(match[2]) > 0) map[match[1]] = (map[match[1]] || 0) + Number(match[2]);
  }
  return map;
}

export function serializeExtraSize(map) {
  const known = SIZES.filter(size => map[size] > 0);
  const other = Object.keys(map).filter(size => !SIZES.includes(size) && map[size] > 0).sort();
  return [...known, ...other].map(size => `${size}+${map[size]}`).join('/');
}

export function extraSizeTotal(value) {
  return Object.values(parseExtraSize(value)).reduce((sum, qty) => sum + qty, 0);
}

/* Teks bantu untuk sel tahap: tanggal jatuh tempo bila ada. */
export function stageHint(stage) {
  if (!stage) return '';
  if (stage.status === 'SELESAI' && stage.done_at) return 'selesai ' + String(stage.done_at).slice(0, 10);
  if (stage.due_date) return 'jatuh tempo ' + stage.due_date;
  if (stage.status === '-') return 'tidak dipakai';
  return '';
}

export const PRIORITY_LABEL = {URGENT: 'URGENT', PERHATIAN: 'PERHATIAN', PROGRES: 'PROGRES', SELESAI: 'SELESAI'};

export const PRIORITY_FILTERS = [['ALL', 'Semua'], ['URGENT', 'Urgent'], ['PERHATIAN', 'Perhatian'], ['PROGRES', 'Progres'], ['SELESAI', 'Selesai']];

export function boardQuery({pic, priority, q}) {
  const params = new URLSearchParams();
  if (pic && pic !== 'ALL') params.set('pic', pic);
  if (priority && priority !== 'ALL') params.set('priority', priority);
  if (q && q.trim()) params.set('q', q.trim());
  const text = params.toString();
  return '/control/board' + (text ? '?' + text : '');
}

/* Morning Priority: warna baris (merah = urgent, kuning = perhatian, putih = on track). */
export function rowTone(priority) {
  return {URGENT: 'red', PERHATIAN: 'yellow'}[priority] || 'white';
}

const SORT_VALUE = {
  priority_sort: r => r.priority_sort,
  pic: r => r.pic,
  buyer: r => r.buyer,
  garment: r => (r.garment_types || []).join(', '),
  article: r => (r.articles || []).join(', '),
  stage: r => r.current_stage_label,
  qty: r => r.active_qty,
  problem: r => r.problem,
  next_action: r => r.next_action,
  order_id: r => r.order_id,
  deadline: r => r.deadline,
};

/* Urut stabil; nilai kosong selalu di bawah, apa pun arahnya. dir: 1 naik, -1 turun. */
export function sortRows(rows, key, dir = 1) {
  const pick = SORT_VALUE[key] || SORT_VALUE.priority_sort;
  const blank = value => value == null || value === '';
  return rows.map((row, index) => ({row, index, value: pick(row)})).sort((a, b) => {
    if (blank(a.value) !== blank(b.value)) return blank(a.value) ? 1 : -1;
    if (!blank(a.value) && a.value !== b.value) {
      const result = typeof a.value === 'number' ? a.value - b.value : String(a.value).localeCompare(String(b.value), 'id', {numeric: true});
      if (result) return result * dir;
    }
    return a.index - b.index;
  }).map(item => item.row);
}

/* Capacity Planner & Forecast */
export function capacityTone(status) {
  return {OVERLOAD: 'red', PERHATIAN: 'amber', AVAILABLE: 'green'}[status] || 'gray';
}

export function riskTone(risk) {
  return {URGENT: 'red', PERHATIAN: 'yellow', AMAN: 'green', SELESAI: 'green'}[risk] || 'gray';
}

/* Beban 999+ dari server berarti kapasitas 0 tetapi ada pekerjaan. */
export function loadLabel(pct) {
  if (pct == null) return '-';
  return pct >= 999 ? '>999%' : `${pct}%`;
}

/* "2026-10-16" → "16/10/2026" (format sheet lama). */
export function formatDate(value) {
  if (!value) return '-';
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${match[3]}/${match[2]}/${match[1]}` : String(value);
}

/* Nilai untuk <input type="date"> dari tanggal LOKAL (toISOString memakai UTC dan bisa mundur sehari). */
export function dateInputValue(date) {
  const pad = n => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function plannerQuery(start, end) {
  return `/control/capacity-planner?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
}

/* Kolom CMO di sheet lama. */
export function invoiceTone(status) {
  return {SELESAI: 'green', DP: 'blue', OUTSTANDING: 'amber'}[status] || 'gray';
}

export function sampleTone(status) {
  return {APPROVED: 'green', REVISION: 'red', PROGRES: 'amber'}[status] || 'gray';
}
