import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import {
  Factory,
  ClipboardList,
  CheckSquare,
  AlertTriangle,
  RefreshCw,
  Cpu,
  ShieldCheck,
  Truck,
} from 'lucide-react';

/* COO TODAY — SITI (Revisi #37 / COO-S-001 & Revisi #46 / REF-COO-SITI).
   Action-first: antrean kerja perencanaan, SLA mesin, dan eksekusi produksi hari ini.
   Semua angka di halaman ini berasal dari API nyata (/coo/daily-execution dan
   /coo/handoffs) — bukan data contoh. Biaya/HPP finansial milik CFO dan tidak
   ditampilkan di sini; stok fisik milik Riadi.
*/

const STATUS_TONE = {
  NEW: 'blue', WAITING: 'gray', NOT_STARTED: 'gray', IN_PROCESS: 'amber',
  DONE: 'green', COMPLETED: 'green', CLOSED: 'green', HOLD: 'red',
  CANCELLED: 'gray', REJECT: 'red',
};
const statusTone = (s) => STATUS_TONE[s] || 'gray';

export default function COOHome() {
  const [de, setDe] = useState(null);
  const [handoffs, setHandoffs] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  async function loadData() {
    setLoading(true);
    try {
      const [exec, ho] = await Promise.all([
        api('/coo/daily-execution'),
        api('/coo/handoffs').catch(() => null),
      ]);
      setDe(exec);
      setHandoffs(ho);
      setErr('');
    } catch (e) {
      setErr(e.message || 'Gagal memuat COO Today');
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

  if (loading && !de) {
    return (
      <div className="page">
        <div className="empty"><RefreshCw className="spin" size={20} /> Memuat COO Today...</div>
      </div>
    );
  }

  const totals = de?.totals || {};
  const rows = de?.rows || [];
  const hoSum = handoffs?.summary || {};
  const activeBatches = rows.filter(
    (r) => r.overall_status && !['NEW', 'CLOSED', 'CANCELLED'].includes(r.overall_status),
  ).length;
  const unbalanced = totals.unbalanced_articles || 0;
  const reconIssues = totals.reconciliation_issues || 0;
  const pendingReceipt = hoSum.pending_receipt || 0;

  const num = (n) => Number(n || 0).toLocaleString('id-ID');

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>COO Today — Siti</h1>
          <p>Rencana, SLA, WIP, dan eksekusi produksi hari ini {de?.as_of ? `· per ${de.as_of}` : ''}</p>
        </div>
        <button onClick={loadData} className="btn sm">
          <RefreshCw size={14} style={{ marginRight: 6 }} /> Refresh
        </button>
      </div>

      {/* Metric Cards — dari data nyata */}
      <div className="cards" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <div className="stat blue">
          <div className="stat-icon"><Factory size={20} /></div>
          <strong>{activeBatches}</strong>
          <span>Artikel Sedang Berjalan</span>
        </div>
        <div className="stat green">
          <div className="stat-icon"><CheckSquare size={20} /></div>
          <strong>{num(totals.realised_today)}</strong>
          <span>Realisasi Hari Ini {totals.target_today ? `(target ${num(totals.target_today)})` : ''}</span>
        </div>
        <div className="stat red">
          <div className="stat-icon"><AlertTriangle size={20} /></div>
          <strong>{unbalanced}</strong>
          <span>Artikel Qty Tidak Seimbang</span>
        </div>
        <div className="stat purple">
          <div className="stat-icon"><Truck size={20} /></div>
          <strong>{pendingReceipt}</strong>
          <span>Handoff Menunggu Diterima</span>
        </div>
      </div>

      {reconIssues > 0 && (
        <div className="notice danger" role="alert" style={{ marginTop: 16 }}>
          <b>{reconIssues} masalah rekonsiliasi kuantitas</b> — Qty In ≠ Qty Selesai + Reject + WIP.
          Periksa baris bertanda “Rekonsiliasi” pada tabel di bawah.
        </div>
      )}

      {/* Production Plan & SLA — data nyata */}
      <section className="panel" style={{ marginTop: 20 }}>
        <div className="panel-head">
          <h2><Factory size={18} style={{ color: '#3b82f6', verticalAlign: '-3px', marginRight: 6 }} /> Production Plan & SLA</h2>
          <Link to="/coo/planning" className="btn sm">Buka Rencana</Link>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Order / Article</th>
                <th>Qty Order</th>
                <th>Rute Produksi</th>
                <th>Status</th>
                <th style={{ textAlign: 'right' }}>WIP</th>
                <th style={{ textAlign: 'right' }}>Selesai</th>
                <th style={{ textAlign: 'right' }}>Reject</th>
                <th style={{ textAlign: 'center' }}>Qty</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.order_id + '-' + r.article_id}>
                  <td>
                    <b>{r.order_id}</b><br />
                    <small style={{ color: '#64748b' }}>{r.article_code} · {r.garment_type} · {r.buyer}</small>
                  </td>
                  <td>{num(r.article_qty)} pcs</td>
                  <td><span className="badge gray">{r.production_route || '—'}</span></td>
                  <td><span className={'badge ' + statusTone(r.overall_status)}>{r.overall_status}</span></td>
                  <td style={{ textAlign: 'right' }}>{num(r.qty_wip)}</td>
                  <td style={{ textAlign: 'right' }}>{num(r.qty_done)}</td>
                  <td style={{ textAlign: 'right' }}>{num(r.qty_reject)}</td>
                  <td style={{ textAlign: 'center' }}>
                    {r.balanced
                      ? <span className="badge green">SEIMBANG</span>
                      : <span className="badge red">SELISIH</span>}
                  </td>
                </tr>
              ))}
              {!rows.length && (
                <tr><td colSpan={8} style={{ textAlign: 'center' }}>Belum ada artikel dalam produksi.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Mesin SLA & Aturan Tindakan */}
      <div className="grid2" style={{ marginTop: 20 }}>
        <section className="panel">
          <div className="panel-head">
            <h2><Cpu size={18} style={{ marginRight: 6 }} /> Logika Mesin SLA Produksi</h2>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '10px 0' }}>
            {[
              ['Ambil Data Nyata:', 'Qty proses, urutan route terdaftar, kapasitas efektif pcs/hari, kalender kerja aktif.'],
              ['Tentukan Mulai Paling Awal:', 'Max dari (Batch Release, Material Ready, Predecessor Handoff, Slot Kapasitas).'],
              ['Hitung Durasi Tiap Proses:', 'Pembulatan ke atas (qty proses ÷ kapasitas efektif harian).'],
              ['Bandingkan dengan Deadline Buyer:', 'Hitung buffer hari; klasifikasikan risiko (AMAN / PERHATIAN / TERLAMBAT).'],
              ['Kalkulasi Ulang Otomatis:', 'Trigger otomatis saat ada perubahan material shortage, kapasitas, actual output, atau rework.'],
            ].map(([t, d], i) => (
              <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                <span className="badge blue" style={{ width: 24, height: 24, padding: 0, textAlign: 'center', lineHeight: '24px' }}>{i + 1}</span>
                <div><b>{t}</b> {d}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2><ShieldCheck size={18} style={{ marginRight: 6 }} /> Aturan & Tindakan Terjaga</h2>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '10px 0' }}>
            <div style={{ padding: '10px', background: '#fef2f2', borderRadius: 6, borderLeft: '4px solid #ef4444' }}>
              <b>Material Shortage</b>
              <p style={{ margin: '4px 0 0', fontSize: 12, color: '#991b1b' }}>
                Otomatis menghasilkan Task kebutuhan ke Riadi (Purchasing/Warehouse). Siti dilarang mengubah status fisik barang.
              </p>
            </div>
            <div style={{ padding: '10px', background: '#fffbeb', borderRadius: 6, borderLeft: '4px solid #f59e0b' }}>
              <b>Capacity Conflict</b>
              <p style={{ margin: '4px 0 0', fontSize: 12, color: '#92400e' }}>
                Atur ulang urutan batch atau alokasi shift di Daily Execution untuk menghindari penumpukan bottleneck antrean.
              </p>
            </div>
            <div style={{ padding: '10px', background: '#f8fafc', borderRadius: 6, borderLeft: '4px solid #3b82f6' }}>
              <b>Handoff Selisih & Discrepancy</b>
              <p style={{ margin: '4px 0 0', fontSize: 12, color: '#1e40af' }}>
                Qty Selesai + Reject + Sisa wajib persis sama dengan Qty Masuk. Mismatch otomatis memicu Exception operasional.
              </p>
            </div>
            <div style={{ padding: '10px', background: '#f0fdf4', borderRadius: 6, borderLeft: '4px solid #10b981' }}>
              <b>Rework Selesai</b>
              <p style={{ margin: '4px 0 0', fontSize: 12, color: '#065f46' }}>
                Hasil perbaikan rework wajib diuji ulang oleh QC (maksimal 2 cycle) sebelum boleh di-handoff ke proses berikutnya.
              </p>
            </div>
          </div>
        </section>
      </div>

      <div style={{ marginTop: 20, padding: 12, background: '#f1f5f9', borderRadius: 6, fontSize: 12, color: '#475569' }}>
        <strong>Batas Kewenangan COO (Siti):</strong> Bertanggung jawab penuh atas penjadwalan produksi, Batch Release, eksekusi fisik, kuantitas WIP, QC internal, dan pengiriman fisik. Biaya di-masking read-only bagi Siti (dikelola CFO); pembelian dan stok gudang dikelola Riadi; janji tanggal buyer dikelola CMO.
      </div>

      <div style={{ marginTop: 10, fontSize: 12, color: '#94a3b8' }}>
        <ClipboardList size={12} style={{ verticalAlign: '-2px' }} /> {de?.invariant}
      </div>
    </div>
  );
}
