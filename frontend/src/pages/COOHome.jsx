import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import {
  Factory,
  Package,
  Truck,
  ClipboardList,
  CheckSquare,
  AlertTriangle,
  Clock,
  CheckCircle2,
  Calendar,
  ArrowRight,
  RefreshCw,
  Cpu,
  ShieldCheck,
} from 'lucide-react';

/* COO TODAY — SITI (Revisi #37 / COO-S-001 & Revisi #46 / REF-COO-SITI).
   Action-first: antrean kerja perencanaan, SLA mesin, dan eksekusi produksi hari ini.
   Bukan dashboard umum, tanpa input biaya/HPP finansial (biaya milik CFO, stok fisik milik Riadi).
*/

export default function COOHome() {
  const [data, setData] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  async function loadData() {
    setLoading(true);
    try {
      const [dash, taskList] = await Promise.all([
        api('/dashboard/COO').catch(() => null),
        api('/coo/execution-tasks').catch(() => []),
      ]);
      setData(dash);
      setTasks(taskList || []);
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

  if (loading && !data) {
    return (
      <div className="page">
        <div className="empty"><RefreshCw className="spin" size={20} /> Memuat COO Today...</div>
      </div>
    );
  }

  // Stat metrics
  const unbudgetedSpk = 3;
  const readyToRelease = 2;
  const riskDelay = 1;
  const activeBatches = 2;

  // Production Plan & SLA items
  const planRows = [
    {
      orderId: 'SO-BC031247F1440FF',
      article: 'BT-01',
      qty: '200 pcs',
      route: 'Cut -> Sew -> QC',
      materialStatus: 'READY',
      materialTone: 'green',
      capacityStatus: 'Tersedia',
      capacityTone: 'green',
      internalEta: '26 Sep (8 hari kerja)',
      risk: 'AMAN',
      riskTone: 'green',
    },
    {
      orderId: 'SO-63444EF00CC31460A',
      article: 'SK-JKT-01',
      qty: '800 pcs',
      route: 'Belum lengkap',
      materialStatus: 'SHORTAGE',
      materialTone: 'red',
      capacityStatus: 'Menunggu',
      capacityTone: 'amber',
      internalEta: 'Belum dihitung',
      risk: 'TERTAHAN',
      riskTone: 'amber',
    },
    {
      orderId: 'SO-NA6C0D071018A2B4',
      article: 'BT-02',
      qty: '600 pcs',
      route: 'Cut -> Prn -> Sew -> QC',
      materialStatus: 'READY',
      materialTone: 'green',
      capacityStatus: 'Antrean padat',
      capacityTone: 'amber',
      internalEta: '2 Nov (24 hari kerja)',
      risk: 'TERLAMBAT',
      riskTone: 'red',
    },
  ];

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>COO Today — Siti</h1>
          <p>Rencana, SLA, WIP, dan eksekusi produksi hari ini</p>
        </div>
        <button onClick={loadData} className="btn sm">
          <RefreshCw size={14} style={{ marginRight: 6 }} /> Refresh
        </button>
      </div>

      {/* Metric Cards Sesuai Blueprint */}
      <div className="cards" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <div className="stat blue">
          <div className="stat-icon"><ClipboardList size={20} /></div>
          <strong>{unbudgetedSpk}</strong>
          <span>SPK Belum Direncanakan</span>
        </div>
        <div className="stat green">
          <div className="stat-icon"><CheckCircle2 size={20} /></div>
          <strong>{readyToRelease}</strong>
          <span>Batch Siap Release</span>
        </div>
        <div className="stat red">
          <div className="stat-icon"><AlertTriangle size={20} /></div>
          <strong>{riskDelay}</strong>
          <span>Berisiko Terlambat</span>
        </div>
        <div className="stat purple">
          <div className="stat-icon"><Factory size={20} /></div>
          <strong>{activeBatches}</strong>
          <span>Nomor Batch Aktif</span>
        </div>
      </div>

      {/* Production Plan & SLA */}
      <section className="panel" style={{ marginTop: 20 }}>
        <div className="panel-head">
          <h2><Factory size={18} style={{ color: '#3b82f6', verticalAlign: '-3px', marginRight: 6 }} /> Production Plan & SLA</h2>
          <Link to="/coo/planning" className="btn sm">Buka Rencana <ArrowRight size={13} /></Link>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Order / Article</th>
                <th>Qty</th>
                <th>Rute Produksi</th>
                <th>Status Material</th>
                <th>Kapasitas</th>
                <th>Internal ETA (SLA)</th>
                <th style={{ textAlign: 'center' }}>Risk</th>
              </tr>
            </thead>
            <tbody>
              {planRows.map((r, i) => (
                <tr key={i}>
                  <td>
                    <b>{r.orderId}</b><br />
                    <small style={{ color: '#64748b' }}>Article: {r.article}</small>
                  </td>
                  <td>{r.qty}</td>
                  <td><span className="badge gray">{r.route}</span></td>
                  <td><span className={'badge ' + r.materialTone}>{r.materialStatus}</span></td>
                  <td><span className={'badge ' + r.capacityTone}>{r.capacityStatus}</span></td>
                  <td>{r.internalEta}</td>
                  <td style={{ textAlign: 'center' }}>
                    <span className={'badge ' + r.riskTone}>{r.risk}</span>
                  </td>
                </tr>
              ))}
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
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
              <span className="badge blue" style={{ width: 24, height: 24, padding: 0, textAlign: 'center', lineHeight: '24px' }}>1</span>
              <div>
                <b>Ambil Data Nyata:</b> Qty proses, urutan route terdaftar, kapasitas efektif pcs/hari, kalender kerja aktif.
              </div>
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
              <span className="badge blue" style={{ width: 24, height: 24, padding: 0, textAlign: 'center', lineHeight: '24px' }}>2</span>
              <div>
                <b>Tentukan Mulai Paling Awal:</b> Max dari (Batch Release, Material Ready, Predecessor Handoff, Slot Kapasitas).
              </div>
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
              <span className="badge blue" style={{ width: 24, height: 24, padding: 0, textAlign: 'center', lineHeight: '24px' }}>3</span>
              <div>
                <b>Hitung Durasi Tiap Proses:</b> Pembulatan ke atas (qty proses &divide; kapasitas efektif harian).
              </div>
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
              <span className="badge blue" style={{ width: 24, height: 24, padding: 0, textAlign: 'center', lineHeight: '24px' }}>4</span>
              <div>
                <b>Bandingkan dengan Deadline Buyer:</b> Hitung buffer hari; klasifikasikan risiko (AMAN / PERHATIAN / TERLAMBAT).
              </div>
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
              <span className="badge blue" style={{ width: 24, height: 24, padding: 0, textAlign: 'center', lineHeight: '24px' }}>5</span>
              <div>
                <b>Kalkulasi Ulang Otomatis:</b> Trigger otomatis saat ada perubahan material shortage, kapasitas, actual output, atau rework.
              </div>
            </div>
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
    </div>
  );
}
