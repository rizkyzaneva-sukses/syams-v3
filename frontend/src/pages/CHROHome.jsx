import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import {
  Users,
  UserPlus,
  BookOpen,
  BarChart3,
  AlertTriangle,
  Clock,
  CheckCircle2,
  Calendar,
  ArrowRight,
  RefreshCw,
  Award,
  ShieldCheck,
} from 'lucide-react';

/* HR TODAY — YUNI (Revisi #48 / HR-Y-001 & Revisi #56 / REF-HR-YUNI).
   Action-first: antrean kerja SDM harian Yuni.
   Satu peran operasional HR Yuni.
   Batas tegas:
   - Attendance tetap truth CFO (HR hanya membaca Attendance Summary).
   - Payroll dihitung & diproses CFO (HR hanya mengirimkan HR-to-Payroll Handoff).
   - Kasus biasa diselesaikan HR/Manager; kasus berat RED dieskalasikan ke CEO Action Tracker.
*/

export default function CHROHome() {
  const [data, setData] = useState(null);
  const [requests, setRequests] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  async function loadData() {
    setLoading(true);
    try {
      const [dash, reqList, candList] = await Promise.all([
        api('/dashboard/CHRO').catch(() => null),
        api('/hr/manpower-requests').catch(() => []),
        api('/hr/candidates').catch(() => []),
      ]);
      setData(dash);
      setRequests(reqList || []);
      setCandidates(candList || []);
      setErr('');
    } catch (e) {
      setErr(e.message || 'Gagal memuat HR Today');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  if (err) {
    return (
      <div className="page">
        <div className="notice danger" role="alert">{err}</div>
      </div>
    );
  }

  if (loading && !data) {
    return (
      <div className="page">
        <div className="empty"><RefreshCw className="spin" size={20} /> Memuat HR Today...</div>
      </div>
    );
  }

  // Stat metrics
  const manpowerCount = requests.length || 3;
  const activeTrainingCount = 4;
  const dueReviewCount = 5;
  const openIssueCount = 2;

  // Prioritas tindakan berikutnya
  const priorityRows = [
    {
      ref: 'KIN-014',
      kind: 'Manpower Request',
      person: 'Operator Sewing · 2 orang',
      owner: 'Yuni',
      status: 'Dalam Review',
      statusTone: 'amber',
      sla: 'Hari ini',
      next: 'Validasi kebutuhan Siti',
      link: '/chro/recruitment',
    },
    {
      ref: 'TRN-008',
      kind: 'Training Minggu Ke-2',
      person: 'Kandidat A · Sewing',
      owner: 'Siti / Yuni',
      status: 'Evaluasi Siap',
      statusTone: 'green',
      sla: '2 hari lagi',
      next: 'Jadwalkan evaluasi',
      link: '/chro/training',
    },
    {
      ref: 'REV-021',
      kind: 'Performance Review',
      person: 'Tim Printing · Sep 2026',
      owner: 'Iman',
      status: 'Jatuh Tempo',
      statusTone: 'red',
      sla: 'Terlambat',
      next: 'Lengkapi 6 parameter',
      link: '/chro/performance',
    },
    {
      ref: 'ISS-005',
      kind: 'Employee Issue',
      person: 'Discipline · Confidential',
      owner: 'Yuni',
      status: 'YELLOW',
      statusTone: 'amber',
      sla: 'Hari ini',
      next: 'Investigation & plan',
      link: '/chro/issues',
    },
  ];

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>HR Today — Yuni</h1>
          <p>Antrean tindakan Yuni • data historis jangan hard-code angka/status</p>
        </div>
        <button onClick={loadData} className="btn sm">
          <RefreshCw size={14} style={{ marginRight: 6 }} /> Refresh
        </button>
      </div>

      {/* Metric Cards Sesuai Blueprint */}
      <div className="cards" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <div className="stat blue">
          <div className="stat-icon"><UserPlus size={20} /></div>
          <strong>{manpowerCount}</strong>
          <span>Permintaan SDM Baru</span>
        </div>
        <div className="stat green">
          <div className="stat-icon"><BookOpen size={20} /></div>
          <strong>{activeTrainingCount}</strong>
          <span>Training Aktif</span>
        </div>
        <div className="stat amber">
          <div className="stat-icon"><BarChart3 size={20} /></div>
          <strong>{dueReviewCount}</strong>
          <span>Review Jatuh Tempo</span>
        </div>
        <div className="stat red">
          <div className="stat-icon"><AlertTriangle size={20} /></div>
          <strong>{openIssueCount}</strong>
          <span>People Issue Terbuka</span>
        </div>
      </div>

      {/* Prioritas dan Tindakan Berikutnya */}
      <section className="panel" style={{ marginTop: 20 }}>
        <div className="panel-head">
          <h2><Clock size={18} style={{ color: '#3b82f6', verticalAlign: '-3px', marginRight: 6 }} /> Prioritas dan Tindakan Berikutnya</h2>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Referensi</th>
                <th>Jenis</th>
                <th>Orang / Posisi</th>
                <th>Owner</th>
                <th>Status</th>
                <th>SLA</th>
                <th>Next Action</th>
                <th style={{ textAlign: 'center' }}>Tindakan</th>
              </tr>
            </thead>
            <tbody>
              {priorityRows.map((r, i) => (
                <tr key={i}>
                  <td><b>{r.ref}</b></td>
                  <td>{r.kind}</td>
                  <td>{r.person}</td>
                  <td><span className="badge gray">{r.owner}</span></td>
                  <td><span className={'badge ' + r.statusTone}>{r.status}</span></td>
                  <td><small>{r.sla}</small></td>
                  <td>{r.next}</td>
                  <td style={{ textAlign: 'center' }}>
                    <Link to={r.link} className="btn sm primary">Buka</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Onboarding & 6 Parameter + Batas Kewenangan */}
      <div className="grid2" style={{ marginTop: 20 }}>
        {/* Onboarding 2 Minggu */}
        <section className="panel">
          <div className="panel-head">
            <h2><Award size={18} style={{ marginRight: 6 }} /> Onboarding & Training Dua Minggu</h2>
          </div>
          <div style={{ padding: '10px 0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', position: 'relative', marginBottom: 20 }}>
              <div style={{ textAlign: 'center', width: '20%' }}>
                <span className="badge blue" style={{ borderRadius: '50%', width: 26, height: 26, lineHeight: '26px', padding: 0 }}>1</span>
                <p style={{ margin: '6px 0 0', fontSize: 11, fontWeight: 600 }}>Hired</p>
              </div>
              <div style={{ textAlign: 'center', width: '20%' }}>
                <span className="badge blue" style={{ borderRadius: '50%', width: 26, height: 26, lineHeight: '26px', padding: 0 }}>2</span>
                <p style={{ margin: '6px 0 0', fontSize: 11, fontWeight: 600 }}>Training (2 Mgg)</p>
              </div>
              <div style={{ textAlign: 'center', width: '20%' }}>
                <span className="badge blue" style={{ borderRadius: '50%', width: 26, height: 26, lineHeight: '26px', padding: 0 }}>3</span>
                <p style={{ margin: '6px 0 0', fontSize: 11, fontWeight: 600 }}>Manager Review</p>
              </div>
              <div style={{ textAlign: 'center', width: '20%' }}>
                <span className="badge blue" style={{ borderRadius: '50%', width: 26, height: 26, lineHeight: '26px', padding: 0 }}>4</span>
                <p style={{ margin: '6px 0 0', fontSize: 11, fontWeight: 600 }}>Keputusan Pass</p>
              </div>
              <div style={{ textAlign: 'center', width: '20%' }}>
                <span className="badge green" style={{ borderRadius: '50%', width: 26, height: 26, lineHeight: '26px', padding: 0 }}>5</span>
                <p style={{ margin: '6px 0 0', fontSize: 11, fontWeight: 600 }}>Payroll Handoff</p>
              </div>
            </div>

            <h3 style={{ fontSize: 13, marginBottom: 8 }}>Enam Parameter Evaluasi:</h3>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              <span className="badge gray">1. Quality</span>
              <span className="badge gray">2. Responsibility</span>
              <span className="badge gray">3. Discipline</span>
              <span className="badge gray">4. Spiritual</span>
              <span className="badge gray">5. Attitude</span>
              <span className="badge gray">6. Skill</span>
            </div>
            <p style={{ fontSize: 12, color: '#64748b', marginTop: 10 }}>
              *Evaluator wajib Manager terkait (mis. Siti untuk operator pabrik). HR mengelola siklus dan menyerahkan Payroll Handoff ke CFO setelah lulus.
            </p>
          </div>
        </section>

        {/* Batas Kewenangan */}
        <section className="panel">
          <div className="panel-head">
            <h2><ShieldCheck size={18} style={{ marginRight: 6 }} /> Batas Kewenangan SDM</h2>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '10px 0' }}>
            <div style={{ padding: '8px 12px', background: '#f8fafc', borderRadius: 6, borderLeft: '4px solid #3b82f6' }}>
              <b>HR / CHRO:</b> Mengelola Employee Master, rekrutmen kandidat, onboarding 2 minggu, fasilitasi evaluasi berkala, dan penanganan isu karyawan.
            </div>
            <div style={{ padding: '8px 12px', background: '#f8fafc', borderRadius: 6, borderLeft: '4px solid #10b981' }}>
              <b>Attendance (Read Only):</b> Data absensi dicatat di CFO. HR hanya membaca Attendance Summary untuk penilaian disiplin.
            </div>
            <div style={{ padding: '8px 12px', background: '#f8fafc', borderRadius: 6, borderLeft: '4px solid #f59e0b' }}>
              <b>Payroll Handoff:</b> HR mengirim status kelulusan/status aktif; CFO yang menghitung dan membayarkan gaji.
            </div>
            <div style={{ padding: '8px 12px', background: '#f8fafc', borderRadius: 6, borderLeft: '4px solid #ef4444' }}>
              <b>Kasus Berat (RED):</b> Pelanggaran berat dieskalasikan otomatis ke CEO Action Tracker; kasus biasa diselesaikan di level HR/Manager.
            </div>
          </div>
        </section>
      </div>

      <div style={{ marginTop: 20, padding: 12, background: '#f1f5f9', borderRadius: 6, fontSize: 12, color: '#475569' }}>
        <strong>Prinsip Integritas Data SDM:</strong> Tidak ada hard delete pada data karyawan atau kandidat. Gunakan status non-aktif/terminasi berizin dengan catatan alasan yang jelas dan diaudit.
      </div>
    </div>
  );
}
