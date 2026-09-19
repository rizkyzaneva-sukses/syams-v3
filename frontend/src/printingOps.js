/* Kontrak batas untuk halaman Printing (revisi #42/#47).
   Dipakai `PrintingDailyTargetPage.jsx` supaya halaman tidak mengetik ulang
   status/transisi: nilai yang ditampilkan identik dengan yang dipaksakan
   backend (`GET /printing/eligibility` -> status_transitions, owned_processes).
   Modul ini murni data + helper, tanpa JSX, jadi bisa diuji langsung dengan
   `node --test`. */

export const PRINTING_STATUSES = ['WAITING', 'IN_PROCESS', 'HOLD', 'DONE'];

/* Status tujuan yang sah per status asal. DONE pada IN_PROCESS artinya submit
   hasil; HOLD/IN_PROCESS pada IN_PROCESS artinya update progress / tahan.
   WAITING tidak boleh langsung DONE. */
export const PRINTING_STATUS_TRANSITIONS = {
  WAITING: ['IN_PROCESS', 'HOLD'],
  IN_PROCESS: ['DONE', 'HOLD', 'IN_PROCESS'],
  HOLD: ['IN_PROCESS'],
  DONE: ['IN_PROCESS'],
};

export const PRINTING_OWNED_PROCESSES = ['PRINTING', 'BORDIR'];

export const PRINTING_ACTIONS = ['START', 'UPDATE_PROGRESS', 'REPORT_RESULT', 'SUBMIT_RESULT', 'HANDOFF'];

const OWNED_KEYS = PRINTING_OWNED_PROCESSES.map(process => process.toLowerCase());

export function ownsPrintingProcess(process) {
  if (!process) return false;
  return String(process)
    .replace(/[_-]/g, ' ')
    .split(/\s+/)
    .some(token => OWNED_KEYS.includes(token.toLowerCase()));
}

export function canMove(from, to) {
  const allowed = PRINTING_STATUS_TRANSITIONS[String(from || '').toUpperCase()];
  return Array.isArray(allowed) && allowed.includes(String(to || '').toUpperCase());
}

export function statusOptions(from) {
  return [...(PRINTING_STATUS_TRANSITIONS[String(from || '').toUpperCase()] || [])];
}

/* Nilai yang ditampilkan halaman; sengaja berupa data agar mudah diaudit dan
   diuji terhadap jawaban server. */
export const printingStatusBounds = {
  registered: PRINTING_STATUSES,
  from: PRINTING_STATUS_TRANSITIONS,
  owned: PRINTING_OWNED_PROCESSES,
  actions: PRINTING_ACTIONS,
  canMove,
  statusOptions,
  owns: ownsPrintingProcess,
  vendorBoundary: {rate_owner: 'CFO_MANAGER', printing_can_change_rate: false},
};

export default printingStatusBounds;
