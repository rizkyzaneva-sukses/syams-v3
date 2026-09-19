import test from 'node:test';
import assert from 'node:assert/strict';
import {
  HR_QUEUE_COLUMNS,
  STAGE_ORDER,
  buildRows,
  canViewConfidentialRow,
  dueTone,
  formatMissing,
  formatUpdated,
  isTerminal,
  missingSchemaNotes,
  redactRow,
  sortRows,
  stageTone,
  summarize,
} from '../src/hrRecruitment.js';

// Bentuk respons persis seperti GET /api/hr/* (lihat backend/app/routers/hr_recruitment.py).
const manpowerRow = {
  task_id: 'MPR-00001', stage: 'HR_ELIGIBILITY', status: 'SUBMITTED',
  missing: ['decision', 'decision_reason'], next_action: 'HR review kelayakan',
  owner: 'CHRO_MANAGER', due: '2026-10-01', source: 'manpower_requests#1',
  updated_at: '2026-09-18T04:00:00+00:00', handoff: 'MANAGER_DIVISI',
  allowed_next_statuses: ['ELIGIBLE', 'REJECTED', 'NEED_CLARIFICATION'],
};
const candidateRow = {
  task_id: 'CAND-00001', stage: 'INTERVIEWED', status: 'INTERVIEWED',
  missing: ['interview_score', 'manager_assessment (penilaian manager terkait)'],
  next_action: 'Rekam keputusan hire/reject', owner: 'CHRO_MANAGER', due: null,
  source: 'recruitment_candidates#1', updated_at: '2026-09-17T00:00:00+00:00',
  handoff: 'MANAGER_INTERVIEW',
};
const performanceRow = {
  task_id: 'PR-00001', stage: 'PERIOD 2026-Q3', status: 'SUBMITTED',
  missing: [], next_action: 'Next sah: ACKNOWLEDGED', owner: 'CHRO_MANAGER',
  due: '2026-09-30', source: 'performance_records#1', updated_at: '2026-09-15T00:00:00+00:00',
  handoff: 'MANAGER_EVALUATOR', evaluator_is_manager: true, grade: 'B',
};
const confidentialIssue = {
  task_id: 'CASE-00007', stage: 'INVESTIGATION', status: 'INVESTIGATION',
  missing: ['investigator_id'], next_action: 'Rekam temuan investigasi + evidence',
  owner: 'CHRO_MANAGER', due: '2026-09-20', source: 'employee_issues#7',
  updated_at: '2026-09-16T00:00:00+00:00', handoff: 'HR_MANAGER',
  confidential: true, severity: 'RED', category: 'Discipline',
  escalated_to_ceo: false, escalation_log: [], description: 'Pelanggaran berat',
};

test('kolom wajib antrean HR lengkap dan berurutan sesuai blueprint #63', () => {
  assert.deepEqual(HR_QUEUE_COLUMNS.map(([k]) => k), [
    'task_id', 'stage', 'status', 'missing', 'next_action',
    'owner', 'due', 'source', 'updated_at', 'handoff',
  ]);
});

test('manpower request row memakai allowed_next_statuses, bukan dropdown bebas', () => {
  assert.deepEqual(manpowerRow.allowed_next_statuses, ['ELIGIBLE', 'REJECTED', 'NEED_CLARIFICATION']);
  const rows = buildRows({ manpower: { items: [manpowerRow] } }, 'CHRO_MANAGER');
  assert.equal(rows.length, 1);
  assert.equal(rows[0].kind, 'MANPOWER_REQUEST');
  assert.equal(rows[0].owner, 'CHRO_MANAGER');
  assert.equal(formatMissing(rows[0].missing), 'decision, decision_reason');
});

test('baris tanpa data kurang ditandai Lengkap', () => {
  assert.equal(formatMissing([]), 'Lengkap');
  assert.equal(formatMissing(null), 'Lengkap');
  assert.equal(formatMissing(['a', 'b']), 'a, b');
});

test('kasus confidential tersamarkan untuk HR Support, utuh untuk owner HR dan CEO', () => {
  assert.equal(canViewConfidentialRow('CHRO_MANAGER', confidentialIssue), true);
  assert.equal(canViewConfidentialRow('CEO', confidentialIssue), true);
  assert.equal(canViewConfidentialRow('HR_SUPPORT', confidentialIssue), false);

  const redacted = redactRow('HR_SUPPORT', confidentialIssue);
  assert.equal(redacted.status, 'RESTRICTED');
  assert.equal(redacted.description, null);
  assert.equal(redacted.severity, null);
  assert.deepEqual(redacted.escalation_log, []);
  assert.match(redacted.next_action, /CEO/);

  assert.equal(redactRow('CEO', confidentialIssue).description, 'Pelanggaran berat');
  assert.equal(redactRow('CEO', confidentialIssue).status, 'INVESTIGATION');
});

test('buildRows menyamarkan hanya baris confidential saat role HR Support', () => {
  const payload = {
    issues: { items: [confidentialIssue, { ...confidentialIssue, task_id: 'CASE-00008', confidential: false, description: 'Terlambat' }] },
  };
  const support = buildRows(payload, 'HR_SUPPORT');
  assert.equal(support[0].status, 'RESTRICTED');
  assert.equal(support[1].status, 'INVESTIGATION');
  assert.equal(support[1].description, 'Terlambat');
});

test('buildRows menggabungkan empat jenis antrean dan menandai kind', () => {
  const rows = buildRows({
    manpower: { items: [manpowerRow] },
    candidates: { items: [candidateRow] },
    performances: { items: [performanceRow] },
    issues: { items: [confidentialIssue] },
  }, 'CHRO_MANAGER');
  assert.equal(rows.length, 4);
  assert.deepEqual(rows.map((r) => r.kind).sort(), [
    'EMPLOYEE_ISSUE', 'MANPOWER_REQUEST', 'PERFORMANCE_REVIEW', 'RECRUITMENT_CANDIDATE',
  ]);
});

test('baris terminal diletakkan paling bawah, sisanya urut due terdekat', () => {
  const rows = sortRows([
    { ...candidateRow, task_id: 'CAND-1', status: 'HIRED', due: '2026-09-19' },
    { ...performanceRow, task_id: 'PR-2', status: 'SUBMITTED', due: '2026-09-25' },
    { ...manpowerRow, task_id: 'MPR-3', status: 'SUBMITTED', due: '2026-09-20' },
    { ...performanceRow, task_id: 'PR-4', status: 'SUBMITTED', due: null },
  ]);
  assert.deepEqual(rows.map((r) => r.task_id), ['MPR-3', 'PR-2', 'PR-4', 'CAND-1']);
  assert.equal(isTerminal('HIRED'), true);
  assert.equal(isTerminal('SUBMITTED'), false);
});

test('escalated CEO dan RESTRICTED diberi nada merah', () => {
  assert.equal(stageTone('ESCALATED_CEO'), 'red');
  assert.equal(stageTone('RESTRICTED'), 'red');
  assert.equal(stageTone('SUBMITTED'), 'amber');
  assert.equal(stageTone('INVESTIGATION'), 'blue');
  assert.equal(stageTone('CLOSED'), 'gray');
});

test('due memakai SLA: lewat = merah, <=3 hari = kuning, jauh = hijau', () => {
  const today = '2026-09-19T00:00:00Z';
  assert.equal(dueTone('2026-09-18', today), 'red');
  assert.equal(dueTone('2026-09-21', today), 'amber');
  assert.equal(dueTone('2026-10-01', today), 'green');
  assert.equal(dueTone(null, today), 'gray');
});

test('tahap proses mengenal urutan lifecycle per jenis', () => {
  assert.equal(STAGE_ORDER.EMPLOYEE_ISSUE[0], 'OPEN');
  assert.ok(STAGE_ORDER.EMPLOYEE_ISSUE.indexOf('ESCALATED_CEO') > STAGE_ORDER.EMPLOYEE_ISSUE.indexOf('ACTION_PLAN'));
  assert.equal(STAGE_ORDER.MANPOWER_REQUEST[0], 'DRAFT');
  assert.equal(STAGE_ORDER.RECRUITMENT_CANDIDATE.at(-1), 'HIRED');
});

test('ringkasan memisahkan open, kurang data, eskalasi CEO dan confidential', () => {
  const rows = buildRows({
    manpower: { items: [manpowerRow] },
    candidates: { items: [candidateRow] },
    performances: { items: [performanceRow] },
    issues: { items: [{ ...confidentialIssue, escalated_to_ceo: true }] },
  }, 'CHRO_MANAGER');
  const s = summarize(rows);
  assert.equal(s.total, 4);
  assert.equal(s.open, 4);
  assert.equal(s.blocked, 3);
  assert.equal(s.escalated, 1);
  assert.equal(s.confidential, 1);
  assert.equal(s.byKind.MANPOWER_REQUEST, 1);
});

test('catatan schema kosong dikumpulkan supaya tabel yang belum ada terlihat', () => {
  const notes = missingSchemaNotes({
    Manpower: { schema_ready: false, note: 'Tabel manpower_requests belum ada.' },
    Kandidat: { schema_ready: true, note: null },
    Issue: { schema_ready: false, note: 'employee_issues ada; investigasi belum ada.' },
  });
  assert.equal(notes.length, 2);
  assert.match(notes[0], /manpower_requests/);
  assert.equal(missingSchemaNotes({ Kandidat: { schema_ready: true } }).length, 0);
});

test('updated_at diformat stabil dan nilai kosong menjadi tanda hubung', () => {
  assert.equal(formatUpdated(null), '-');
  assert.match(formatUpdated('2026-09-18T04:05:00Z'), /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
});
