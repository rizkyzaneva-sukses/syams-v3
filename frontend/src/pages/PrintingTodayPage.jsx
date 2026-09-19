import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import {
  Target,
  FileText,
  AlertTriangle,
  Clock,
  CheckCircle2,
  Calendar,
  Layers,
  RefreshCw,
  Send,
  Upload,
  ArrowRight,
  Printer,
} from 'lucide-react';

/* PRINTING TODAY — IMAN (Revisi #28 / PRN-I-001 & Revisi #36 / REF-IMAN).
   Action-first: antrean kerja Printing/Bordir hari ini.
   Batas tegas (revisi #42):
   - Iman hanya menjalankan pekerjaan yang ditugaskan (Printing/Bordir).
   - Target harian fleksibel ditetapkan Iman; realisasi dihitung otomatis dari accepted output.
   - Qty Selesai + Qty Reject + Qty Sisa = Qty Masuk (keseimbangan fisik mutlak).
   - Partial handoff wajib verifikasi penerima (Sewing).
*/

export default function PrintingTodayPage() {
  const [targetVal, setTargetVal] = useState(640);
  const [selectedJob, setSelectedJob] = useState(null);
  const [qtyDone, setQtyDone] = useState(120);
  const [qtyReject, setQtyReject] = useState(5);
  const [defectCat, setDefectCat] = useState('BLUR');
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState('');

  // Antrean pekerjaan printing/bordir
  const jobs = [
    {
      priority: 'P1',
      priorityTone: 'red',
      jobId: 'PRN-2026-081',
      orderId: 'SO-BO001',
      article: 'BT-01',
      batch: 'B1',
      process: 'Printing Sablon Plastisol',
      qtyIn: 300,
      qtyDone: 120,
      qtyReject: 5,
      qtyRemaining: 175,
      sla: 'Hari ini (16:00)',
      slaTone: 'amber',
      status: 'IN_PROGRESS',
      spkVersion: 'SPK-2026-V1.0',
      artworkVersion: 'ART-BT-01-V2 (Approved)',
      machine: 'Mesin Otomatis #2',
      shift: 'Shift 1 (Pagi)',
    },
    {
      priority: 'P2',
      priorityTone: 'amber',
      jobId: 'PRN-2026-082',
      orderId: 'SO-BO012',
      article: 'SK-01',
      batch: 'B1',
      process: 'Bordir Komputer Logo',
      qtyIn: 500,
      qtyDone: 0,
      qtyReject: 0,
      qtyRemaining: 500,
      sla: 'Besok',
      slaTone: 'green',
      status: 'READY',
      spkVersion: 'SPK-2026-V1.1',
      artworkVersion: 'ART-SK-01-V1 (Approved)',
      machine: 'Bordir 12 Kepala',
      shift: 'Shift 1 (Pagi)',
    },
    {
      priority: 'P1',
      priorityTone: 'red',
      jobId: 'PRN-2026-079',
      orderId: 'SO-BO009',
      article: 'HD-02',
      batch: 'B2',
      process: 'Printing Discharge',
      qtyIn: 200,
      qtyDone: 80,
      qtyReject: 8,
      qtyRemaining: 112,
      sla: 'Terlambat 1 hari',
      slaTone: 'red',
      status: 'REWORK',
      spkVersion: 'SPK-2026-V2.0',
      artworkVersion: 'ART-HD-02-V1 (Approved)',
      machine: 'Meja Manual #1',
      shift: 'Shift 2 (Siang)',
    },
  ];

  const activeJob = selectedJob || jobs[0];

  function handleSubmitResult(e) {
    e.preventDefault();
    setFeedback('Hasil pekerjaan berhasil dilaporkan. Kuantitas seimbang.');
    setTimeout(() => setFeedback(''), 4000);
  }

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>Printing Today — Iman</h1>
          <p>Target harian, antrean sablon & bordir, job card, dan handoff ke proses berikutnya</p>
        </div>
      </div>

      {feedback && <div className="notice success">{feedback}</div>}

      {/* Top Metric Cards */}
      <div className="cards" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <div className="stat blue">
          <div className="stat-icon"><Target size={20} /></div>
          <strong>{targetVal} pcs</strong>
          <span>Target Harian</span>
        </div>
        <div className="stat green">
          <div className="stat-icon"><CheckCircle2 size={20} /></div>
          <strong>200 pcs</strong>
          <span>Realisasi Output Sah</span>
        </div>
        <div className="stat amber">
          <div className="stat-icon"><Layers size={20} /></div>
          <strong>{Math.round((200 / targetVal) * 100)}%</strong>
          <span>Pencapaian Target</span>
        </div>
        <div className="stat red">
          <div className="stat-icon"><AlertTriangle size={20} /></div>
          <strong>1</strong>
          <span>Job Terlambat</span>
        </div>
      </div>

      {/* Antrean Printing & Bordir */}
      <section className="panel" style={{ marginTop: 20 }}>
        <div className="panel-head">
          <h2><Printer size={18} style={{ marginRight: 6 }} /> Antrean Printing / Bordir Hari Ini</h2>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Prioritas</th>
                <th>Job ID</th>
                <th>Order / Article</th>
                <th>Proses</th>
                <th>Qty Masuk</th>
                <th>Qty Selesai</th>
                <th>Qty Reject</th>
                <th>Qty Sisa</th>
                <th>SLA</th>
                <th>Status</th>
                <th style={{ textAlign: 'center' }}>Pilih</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr
                  key={j.jobId}
                  style={{
                    background: activeJob.jobId === j.jobId ? '#f0fdf4' : undefined,
                    cursor: 'pointer',
                  }}
                  onClick={() => setSelectedJob(j)}
                >
                  <td><span className={'badge ' + j.priorityTone}>{j.priority}</span></td>
                  <td><b>{j.jobId}</b></td>
                  <td>
                    <b>{j.orderId}</b><br />
                    <small>{j.article} ({j.batch})</small>
                  </td>
                  <td>{j.process}</td>
                  <td><b>{j.qtyIn}</b></td>
                  <td><span className="badge green">{j.qtyDone}</span></td>
                  <td><span className="badge red">{j.qtyReject}</span></td>
                  <td>{j.qtyRemaining}</td>
                  <td><span className={'badge ' + j.slaTone}>{j.sla}</span></td>
                  <td><span className="badge gray">{j.status}</span></td>
                  <td style={{ textAlign: 'center' }}>
                    <button
                      type="button"
                      className={'btn sm ' + (activeJob.jobId === j.jobId ? 'primary' : '')}
                      onClick={() => setSelectedJob(j)}
                    >
                      Buka
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Grid: Job Card & Hasil Pekerjaan */}
      <div className="grid2" style={{ marginTop: 20 }}>
        {/* Job Card Terkunci */}
        <section className="panel">
          <div className="panel-head">
            <h2><FileText size={18} style={{ marginRight: 6 }} /> Job Card: {activeJob.jobId}</h2>
            <span className="badge blue">{activeJob.status}</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: 13 }}>
            <div>
              <small style={{ color: '#64748b' }}>Order ID & Article</small>
              <p style={{ margin: '2px 0 8px', fontWeight: 600 }}>{activeJob.orderId} / {activeJob.article}</p>
            </div>
            <div>
              <small style={{ color: '#64748b' }}>Batch ID</small>
              <p style={{ margin: '2px 0 8px', fontWeight: 600 }}>{activeJob.batch}</p>
            </div>
            <div>
              <small style={{ color: '#64748b' }}>SPK Versi Terkunci</small>
              <p style={{ margin: '2px 0 8px', fontWeight: 600 }}>{activeJob.spkVersion}</p>
            </div>
            <div>
              <small style={{ color: '#64748b' }}>Artwork / Mockup</small>
              <p style={{ margin: '2px 0 8px', fontWeight: 600, color: '#059669' }}>{activeJob.artworkVersion}</p>
            </div>
            <div>
              <small style={{ color: '#64748b' }}>Mesin / Vendor</small>
              <p style={{ margin: '2px 0 8px', fontWeight: 600 }}>{activeJob.machine}</p>
            </div>
            <div>
              <small style={{ color: '#64748b' }}>Shift / Regu</small>
              <p style={{ margin: '2px 0 8px', fontWeight: 600 }}>{activeJob.shift}</p>
            </div>
          </div>

          <div style={{ marginTop: 15, padding: 10, background: '#f8fafc', borderRadius: 6, fontSize: 12 }}>
            <b>Prasyarat Bukti:</b> Wajib unggah foto hasil sablon/bordir dan hasil uji cuci/tarik sebelum submit selesai.
          </div>
        </section>

        {/* Input Hasil & Handoff */}
        <section className="panel">
          <div className="panel-head">
            <h2><CheckCircle2 size={18} style={{ marginRight: 6 }} /> Lapor Hasil Pekerjaan</h2>
          </div>
          <form onSubmit={handleSubmitResult}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
              <div>
                <label style={{ fontSize: 12, fontWeight: 600 }}>Qty Selesai (Bagus)</label>
                <input
                  type="number"
                  value={qtyDone}
                  onChange={(e) => setQtyDone(Number(e.target.value))}
                  style={{ width: '100%', padding: '6px 10px', marginTop: 4 }}
                />
              </div>
              <div>
                <label style={{ fontSize: 12, fontWeight: 600 }}>Qty Reject</label>
                <input
                  type="number"
                  value={qtyReject}
                  onChange={(e) => setQtyReject(Number(e.target.value))}
                  style={{ width: '100%', padding: '6px 10px', marginTop: 4 }}
                />
              </div>
              <div>
                <label style={{ fontSize: 12, fontWeight: 600 }}>Kategori Defect</label>
                <select
                  value={defectCat}
                  onChange={(e) => setDefectCat(e.target.value)}
                  style={{ width: '100%', padding: '6px 10px', marginTop: 4 }}
                >
                  <option value="BLUR">Sablon Blur / Geser</option>
                  <option value="COLOR">Warna Tidak Sesuai</option>
                  <option value="STITCH">Bordir Loncat</option>
                  <option value="BURNT">Kain Hangus Press</option>
                </select>
              </div>
            </div>

            <div style={{ marginTop: 12, padding: 10, background: '#f0fdf4', borderRadius: 6, fontSize: 12 }}>
              <b>Rumus Saldo Terkunci:</b> Qty Masuk ({activeJob.qtyIn}) = Selesai ({qtyDone}) + Reject ({qtyReject}) + Sisa ({activeJob.qtyIn - qtyDone - qtyReject}).
            </div>

            <div style={{ display: 'flex', gap: 10, marginTop: 15 }}>
              <button type="button" className="btn" style={{ flex: 1 }}>
                <Upload size={14} style={{ marginRight: 6 }} /> Unggah Bukti
              </button>
              <button type="submit" className="btn primary" style={{ flex: 1 }}>
                <Send size={14} style={{ marginRight: 6 }} /> Submit & Handoff
              </button>
            </div>
          </form>
        </section>
      </div>

      <div style={{ marginTop: 20, padding: 12, background: '#f1f5f9', borderRadius: 6, fontSize: 12, color: '#475569' }}>
        <strong>Batas Kewenangan Printing PIC (Iman):</strong> Bertanggung jawab atas proses fisik sablon dan bordir, pelaporan output, pemilahan defect/reject, dan serah terima partial handoff ke proses Sewing. Iman tidak dapat mengubah SPK, persetujuan buyer, atau rate/harga biaya keuangan CFO.
      </div>
    </div>
  );
}
