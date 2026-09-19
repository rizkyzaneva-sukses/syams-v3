// HR Recruitment / Performance / Issue — logika murni untuk antrean HR.
//
// Direvisi dari #63-#66: antrean HR bukan tabel CRUD, tapi daftar kerja dengan
// kolom wajib (ID, tahap proses, status saat ini, data yang kurang, next action,
// owner, due, source/evidence, updated_at, handoff). Logika di sini sengaja
// terpisah dari React supaya bisa diuji tanpa DOM.

export const HR_QUEUE_COLUMNS = [
  ['task_id', 'ID'],
  ['stage', 'Tahap proses'],
  ['status', 'Status saat ini'],
  ['missing', 'Data yang kurang'],
  ['next_action', 'Next action'],
  ['owner', 'Owner'],
  ['due', 'Due'],
  ['source', 'Source/evidence'],
  ['updated_at', 'Updated at'],
  ['handoff', 'Handoff'],
];

// Tahap proses per jenis antrean, urut sesuai lifecycle blueprint.
export const STAGE_ORDER = {
  MANPOWER_REQUEST: ['DRAFT', 'SUBMITTED', 'NEED_CLARIFICATION', 'ELIGIBLE', 'VACANCY_OPEN', 'SCREENING', 'INTERVIEW', 'OFFER', 'HIRED', 'CLOSED'],
  RECRUITMENT_CANDIDATE: ['NEW', 'SCREENING', 'SHORTLISTED', 'INTERVIEW_SCHEDULED', 'INTERVIEWED', 'OFFERED', 'OFFER_ACCEPTED', 'HIRED'],
  PERFORMANCE_REVIEW: ['DRAFT', 'SUBMITTED', 'ACKNOWLEDGED', 'FINALIZED', 'CORRECTED'],
  EMPLOYEE_ISSUE: ['OPEN', 'INVESTIGATION', 'ACTION_PLAN', 'PENDING_RESPONSE', 'ESCALATED_CEO', 'RESOLVED', 'CLOSED'],
};

// Status yang sudah selesai / tidak perlu ditindak.
const TERMINAL = new Set(['CLOSED', 'REJECTED', 'CANCELLED', 'HIRED', 'NO_CASE',
  'SCREENED_OUT', 'OFFER_REJECTED', 'OFFER_EXPIRED', 'RESTRICTED']);

export function isTerminal(status) {
  return TERMINAL.has(String(status || '').toUpperCase());
}

// Revisi #66: kasus confidential hanya untuk owner role HR + CEO.
export function canViewConfidentialRow(role, row) {
  if (!row || !row.confidential) return true;
  return role === 'CHRO_MANAGER' || role === 'CEO';
}

// Baris confidential yang tersamarkan tidak boleh menampilkan isi kasus.
export function redactRow(role, row) {
  if (!row) return row;
  if (canViewConfidentialRow(role, row)) return row;
  return {
    ...row,
    category: null,
    description: null,
    severity: null,
    status: 'RESTRICTED',
    missing: ['akses: hanya owner role HR + CEO'],
    next_action: 'Minta owner role HR / CEO membuka kasus ini',
    escalation_log: [],
    ceo_action_tracker: [],
  };
}

export function formatMissing(missing) {
  if (!missing || missing.length === 0) return 'Lengkap';
  return missing.join(', ');
}

export function formatUpdated(value) {
  if (!value) return '-';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// SLA sederhana: kuning <3 hari, merah sudah lewat / <=1 hari.
export function dueTone(due, today) {
  if (!due) return 'gray';
  const d = new Date(due);
  if (Number.isNaN(d.getTime())) return 'gray';
  const ref = today ? new Date(today) : new Date();
  const days = (d - ref) / 86400000;
  if (days < 0) return 'red';
  if (days <= 3) return 'amber';
  return 'green';
}

export function stageTone(status) {
  const s = String(status || '').toUpperCase();
  if (s === 'RESTRICTED' || s === 'ESCALATED_CEO') return 'red';
  if (isTerminal(s)) return 'gray';
  if (['SUBMITTED', 'NEED_CLARIFICATION', 'PENDING_RESPONSE', 'NEED_REVISION'].includes(s)) return 'amber';
  return 'blue';
}

// Bangun satu daftar baris dari tiga respons endpoint HR, siap dirender.
export function buildRows({ manpower, candidates, performances, issues } = {}, role) {
  const rows = [];
  const push = (kind, list) => {
    for (const item of (list || [])) {
      rows.push(redactRow(role, { ...item, kind, missing: item.missing || [] }));
    }
  };
  push('MANPOWER_REQUEST', manpower?.items || manpower?.queues);
  push('RECRUITMENT_CANDIDATE', candidates?.items || candidates?.queues);
  push('PERFORMANCE_REVIEW', performances?.items);
  push('EMPLOYEE_ISSUE', issues?.items);
  return rows;
}

export function sortRows(rows) {
  return [...rows].sort((a, b) => {
    const at = isTerminal(a.status) ? 1 : 0;
    const bt = isTerminal(b.status) ? 1 : 0;
    if (at !== bt) return at - bt;
    const ad = a.due ? new Date(a.due).getTime() : Infinity;
    const bd = b.due ? new Date(b.due).getTime() : Infinity;
    if (ad !== bd) return ad - bd;
    return String(a.task_id).localeCompare(String(b.task_id));
  });
}

export function missingSchemaNotes(payloads) {
  const notes = [];
  for (const [label, payload] of Object.entries(payloads || {})) {
    if (payload && payload.note) notes.push(`${label}: ${payload.note}`);
    else if (payload && payload.schema_ready === false) notes.push(`${label}: tabel belum tersedia`);
  }
  return notes;
}

export function summarize(rows) {
  const open = rows.filter((r) => !isTerminal(r.status));
  return {
    total: rows.length,
    open: open.length,
    blocked: open.filter((r) => (r.missing || []).length > 0).length,
    escalated: rows.filter((r) => r.escalated_to_ceo).length,
    confidential: rows.filter((r) => r.confidential).length,
    byKind: rows.reduce((acc, r) => {
      acc[r.kind] = (acc[r.kind] || 0) + 1;
      return acc;
    }, {}),
  };
}
