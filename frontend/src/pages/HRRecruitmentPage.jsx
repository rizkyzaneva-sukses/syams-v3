import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { AlertTriangle, Lock, Search, ShieldAlert, RefreshCw } from 'lucide-react';
import {
  HR_QUEUE_COLUMNS,
  STAGE_ORDER,
  buildRows,
  dueTone,
  formatMissing,
  formatUpdated,
  isTerminal,
  missingSchemaNotes,
  sortRows,
  stageTone,
  summarize,
} from '../hrRecruitment.js';

// Revisi #63-#66 — Manpower Request & Recruitment, Performance Review,
// Employee Issue (confidential + eskalasi CEO).
// Halaman ini READ-ONLY: HR mengelola proses, bukan mem-posting payroll dan
// bukan menilai dirinya sendiri. Tidak ada dropdown status bebas.

const KINDS = [
  { key: 'ALL', label: 'Semua' },
  { key: 'MANPOWER_REQUEST', label: 'Manpower Request' },
  { key: 'RECRUITMENT_CANDIDATE', label: 'Kandidat' },
  { key: 'PERFORMANCE_REVIEW', label: 'Performance Review' },
  { key: 'EMPLOYEE_ISSUE', label: 'Employee Issue' },
];

const EMPTY = { manpower: null, candidates: null, performances: null, issues: null, onboarding: null };

export default function HRRecruitmentPage({ role = 'CHRO_MANAGER' }) {
  const [data, setData] = useState(EMPTY);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [q, setQ] = useState('');
  const [kind, setKind] = useState('ALL');
  const [onlyBlocked, setOnlyBlocked] = useState(false);

  function load() {
    setLoading(true);
    setErr('');
    Promise.all([
      api('/hr/manpower-requests'),
      api('/hr/candidates'),
      api('/hr/performance-reviews'),
      api('/hr/employee-issues'),
      api('/hr/onboarding'),
    ])
      .then(([manpower, candidates, performances, issues, onboarding]) => {
        setData({ manpower, candidates, performances, issues, onboarding });
      })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  const rows = useMemo(() => {
    const all = sortRows(buildRows(data, role));
    return all.filter((r) => {
      if (kind !== 'ALL' && r.kind !== kind) return false;
      if (onlyBlocked && (r.missing || []).length === 0) return false;
      if (!q) return true;
      const t = q.toLowerCase();
      return ['task_id', 'stage', 'status', 'owner', 'handoff', 'next_action', 'source']
        .some((f) => String(r[f] ?? '').toLowerCase().includes(t))
        || (r.missing || []).some((x) => String(x).toLowerCase().includes(t));
    });
  }, [data, role, kind, q, onlyBlocked]);

  const s = summarize(sortRows(buildRows(data, role)));
  const notes = missingSchemaNotes({
    Manpower: data.manpower, Kandidat: data.candidates,
    Onboarding: data.onboarding, Issue: data.issues,
  });
  const issueSchemaNote = data.issues?.detail_schema_ready === false ? data.issues.note : null;
  const perfSchemaNote = data.performances?.detail_schema_ready === false ? data.performances.note : null;

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>HR — Recruitment, Performance &amp; Issue</h1>
          <p>Antrean kerja HR: manpower request, kandidat, performance review, dan kasus karyawan.</p>
        </div>
        <button className="btn" onClick={load}><RefreshCw size={16} /> Muat ulang</button>
      </div>

      {err && <div className="notice danger">{err}</div>}

      <div className="cards">
        <div className="stat blue"><strong>{s.open}</strong><span>Perlu tindakan</span></div>
        <div className="stat amber"><strong>{s.blocked}</strong><span>Kurang data</span></div>
        <div className="stat red"><strong>{s.escalated}</strong><span>Eskalasi CEO</span></div>
        <div className="stat"><strong>{s.confidential}</strong><span>Kasus confidential</span></div>
      </div>

      <div className="notice info">
        Kasus <strong>confidential</strong> hanya dapat dibuka owner role HR (CHRO Manager) dan CEO —
        role HR Support melihatnya tersamarkan. Eskalasi ke CEO hanya untuk kasus RED dan selalu tercatat
        beserta Action Tracker. Status berubah melalui tindakan yang sah, bukan dropdown bebas.
      </div>

      {notes.length > 0 && (
        <div className="notice info">
          <strong>Struktur tabel belum lengkap.</strong>
          <ul style={{ margin: '6px 0 0 18px' }}>
            {notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
        </div>
      )}
      {perfSchemaNote && <div className="notice info">{perfSchemaNote}</div>}
      {issueSchemaNote && <div className="notice info">{issueSchemaNote}</div>}

      <div className="filter-bar">
        <div className="search-bar">
          <Search size={16} />
          <input placeholder="Cari ID, tahap, owner, next action, data yang kurang..." value={q}
                 onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="filter-pills">
          {KINDS.map((k) => (
            <button key={k.key} className={'pill ' + (kind === k.key ? 'active blue' : '')}
                    onClick={() => setKind(k.key)}>{k.label}</button>
          ))}
          <button className={'pill ' + (onlyBlocked ? 'active red' : '')}
                  onClick={() => setOnlyBlocked(!onlyBlocked)}>Kurang data</button>
        </div>
      </div>

      <section className="panel">
        <div className="panel-head"><h2>Antrean HR</h2><span>Read-only · {rows.length} baris</span></div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>{HR_QUEUE_COLUMNS.map(([key, label]) => <th key={key}>{label}</th>)}</tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={HR_QUEUE_COLUMNS.length} className="empty">Memuat antrean…</td></tr>}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={HR_QUEUE_COLUMNS.length} className="empty">Tidak ada baris yang cocok.</td></tr>
              )}
              {rows.map((r) => (
                <tr key={r.kind + '-' + r.task_id + '-' + r.ref}>
                  <td><strong>{r.task_id}</strong><div style={{ fontSize: 11, color: '#64748b' }}>{r.kind}</div></td>
                  <td>
                    <span className={'badge ' + stageTone(r.status)}>{r.stage || '-'}</span>
                    <div style={{ fontSize: 11, color: '#64748b' }}>
                      urut: {(STAGE_ORDER[r.kind] || []).indexOf(String(r.status).toUpperCase()) >= 0
                        ? STAGE_ORDER[r.kind].indexOf(String(r.status).toUpperCase()) + 1 : '-'}
                      /{(STAGE_ORDER[r.kind] || []).length}
                    </div>
                  </td>
                  <td>
                    <span className={'badge ' + stageTone(r.status)}>{r.status}</span>
                    {r.confidential && <div style={{ marginTop: 4 }}>
                      <span className="badge red" title="Hanya owner role HR + CEO">
                        <Lock size={11} /> confidential
                      </span>
                    </div>}
                    {r.escalated_to_ceo && <div style={{ marginTop: 4 }}>
                      <span className="badge red"><ShieldAlert size={11} /> escalated CEO</span>
                    </div>}
                  </td>
                  <td>
                    {(r.missing || []).length === 0
                      ? <span className="badge green">Lengkap</span>
                      : <span style={{ color: '#b45309' }}><AlertTriangle size={12} /> {formatMissing(r.missing)}</span>}
                  </td>
                  <td style={{ maxWidth: 260 }}>{r.next_action}</td>
                  <td>{r.owner}</td>
                  <td><span className={'badge ' + dueTone(r.due)}>{r.due || '-'}</span></td>
                  <td style={{ maxWidth: 200, fontSize: 12 }}>{r.source}</td>
                  <td style={{ fontSize: 12 }}>{formatUpdated(r.updated_at)}</td>
                  <td><span className="badge gray">{r.handoff}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><h2>Catatan kewenangan</h2><span>Blueprint HR-Y-003…006</span></div>
        <ul style={{ fontSize: 13, color: '#475569', margin: '4px 0 0 18px' }}>
          <li>Manpower request &amp; kandidat: HR mengelola proses, manager terkait menilai kebutuhan/kompetensi.</li>
          <li>Kandidat baru menjadi Employee setelah keputusan hire yang sah.</li>
          <li>Performance review enam parameter dengan evaluator <em>manager terkait</em>; HR memonitor, bukan menilai sendiri.</li>
          <li>Onboarding PASS mengaktifkan status karyawan dan membuat Payroll Handoff ke CFO — HR tidak mem-posting payroll.</li>
          <li>Tidak ada tombol hapus/ubah status bebas di halaman ini; perubahan status lewat tindakan yang tercatat.</li>
        </ul>
      </section>
    </div>
  );
}
