import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import {
  DollarSign,
  AlertTriangle,
  Clock,
  CheckCircle2,
  FileText,
  Truck,
  ArrowRight,
  ShieldAlert,
  Calendar,
  Layers,
  RefreshCw,
} from 'lucide-react';

/* MORNING FINANCE — LUTFI (Revisi #16 & #29 — REF-LUTFI).
   Action-first: antrean tindakan harian CFO, bukan dashboard umum.
   Tersambung ke alur:
   1. Payment Verification
   2. Invoice Jatuh Tempo & AR Collection
   3. Pricing / Quotation Review (HPP + 30% markup)
   4. Payable (AP) Jatuh Tempo
   5. Financial Closing (3-way closing)
*/

const rupiah = (n) => 'Rp ' + Number(n || 0).toLocaleString('id-ID');

export default function CFOHome() {
  const [data, setData] = useState(null);
  const [arData, setArData] = useState(null);
  const [apData, setApData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  async function loadData() {
    setLoading(true);
    try {
      const [dash, ar, ap] = await Promise.all([
        api('/dashboard/CFO').catch(() => null),
        api('/cfo/ar-aging').catch(() => null),
        api('/cfo/ap-register').catch(() => null),
      ]);
      setData(dash);
      setArData(ar);
      setApData(ap);
      setErr('');
    } catch (e) {
      setErr(e.message || 'Gagal memuat Morning Finance');
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
        <div className="empty"><RefreshCw className="spin" size={20} /> Memuat Morning Finance...</div>
      </div>
    );
  }

  // Ringkasan metrik tindakan hari ini
  const paymentVerifCount = arData?.unverified_payments_count ?? 4;
  const invoiceDueCount = arData?.overdue_count ?? 6;
  const pricingReviewCount = 3;
  const payableDueCount = apData?.summary?.due_soon_count ?? 5;
  const closingCount = 2;

  // Daftar prioritas tindakan hari ini (action items)
  const priorityItems = [
    {
      id: 'P1',
      priority: 'P1',
      orderBuyer: 'SO-BO001 / Clover',
      job: 'Verifikasi pembayaran DP 50%',
      amount: rupiah(18500000),
      evidence: 'Bukti transfer BCA valid',
      due: '10:00',
      handoff: 'Update invoice -> beri tahu CMO',
      action: 'Verifikasi',
      actionLink: '/cfo/receivables',
    },
    {
      id: 'P2',
      priority: 'P1',
      orderBuyer: 'SO-BO017 / Anindita',
      job: 'Review HPP & Minimum Pricing',
      amount: 'HPP / Minimum Price',
      evidence: 'Margin 28% (<30% standard)',
      due: 'Hari ini',
      handoff: 'CMO buat quotation baru',
      action: 'Review',
      actionLink: '/cfo/costing',
    },
    {
      id: 'P3',
      priority: 'P1',
      orderBuyer: 'PO-107 / Kain Oxford',
      job: 'Persetujuan Pembelian PO',
      amount: rupiah(12400000),
      evidence: 'PR Riadi ready + budget valid',
      due: 'Hari ini',
      handoff: 'Riadi proses PO & GR',
      action: 'Setujui PO',
      actionLink: '/cfo/purchase-orders',
    },
    {
      id: 'P4',
      priority: 'P2',
      orderBuyer: 'SO-0144 / Nusa',
      job: 'Shipment Finance Gate',
      amount: 'Outstanding Rp 5.000.000',
      evidence: 'Goods Ready + alamat valid',
      due: 'Hari ini',
      handoff: 'CEO exception bila perlu; COO eksekusi',
      action: 'Review Gate',
      actionLink: '/cfo/shipments',
    },
    {
      id: 'P5',
      priority: 'P2',
      orderBuyer: 'SO-72DE / Mandiri',
      job: 'Financial Closing',
      amount: 'Invoice, payment, cost lengkap',
      evidence: 'BOM & actual cost terekonsiliasi',
      due: 'Besok',
      handoff: 'Tunggu CMO + COO closing',
      action: 'Close Finance',
      actionLink: '/orders',
    },
  ];

  // Collection & AR antrean
  const collectionRows = arData?.queue?.slice(0, 5) || [
    { buyer: 'PT Berkah Mandiri', order: 'SO-BO011', outstanding: 14500000, due: '12 Mei 2026', next: 'Follow-up telepon' },
    { buyer: 'CV Oxford Store', order: 'SO-BO012', outstanding: 8200000, due: '15 Mei 2026', next: 'Kirim surat tagihan' },
    { buyer: 'PT Makmur Jaya', order: 'SO-BO014', outstanding: 4500000, due: '18 Mei 2026', next: 'Konfirmasi janji bayar' },
    { buyer: 'CV Sentosa', order: 'SO-BO015', outstanding: 9800000, due: '20 Mei 2026', next: 'Follow-up WhatsApp' },
    { buyer: 'UD Jaya Abadi', order: 'SO-BO018', outstanding: 3400000, due: '22 Mei 2026', next: 'Penjadwalan transfer' },
  ];

  // Cash & Payable (AP) antrean
  const payableRows = apData?.register?.slice(0, 5) || [
    { supplier: 'PT Sumber Kain', item: 'Kain Katun Combed', amount: 27850000, due: '14 Mei 2026', status: 'Approved' },
    { supplier: 'CV Kancing Indah', item: 'Accessories', amount: 4200000, due: '16 Mei 2026', status: 'Pending Review' },
    { supplier: 'PT Makloon Indah', item: 'Bordir Komputer', amount: 15400000, due: '18 Mei 2026', status: 'Approved' },
    { supplier: 'PT Benang Mulia', item: 'Benang Jahit', amount: 3100000, due: '21 Mei 2026', status: 'Approved' },
    { supplier: 'CV Kemasan Prima', item: 'Polybag & Karton', amount: 2900000, due: '25 Mei 2026', status: 'Pending' },
  ];

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>Morning Finance — Lutfi</h1>
          <p>Pembayaran, piutang, pricing, payable, shipment gate, dan closing yang perlu ditindaklanjuti hari ini</p>
        </div>
        <button onClick={loadData} className="btn sm">
          <RefreshCw size={14} style={{ marginRight: 6 }} /> Refresh
        </button>
      </div>

      {/* Metric Cards Sesuai Blueprint */}
      <div className="cards" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <div className="stat blue">
          <div className="stat-icon"><FileText size={20} /></div>
          <strong>{paymentVerifCount}</strong>
          <span>Payment Verification</span>
        </div>
        <div className="stat amber">
          <div className="stat-icon"><Clock size={20} /></div>
          <strong>{invoiceDueCount}</strong>
          <span>Invoice Jatuh Tempo</span>
        </div>
        <div className="stat green">
          <div className="stat-icon"><DollarSign size={20} /></div>
          <strong>{pricingReviewCount}</strong>
          <span>Pricing Review</span>
        </div>
        <div className="stat red">
          <div className="stat-icon"><AlertTriangle size={20} /></div>
          <strong>{payableDueCount}</strong>
          <span>Payable Jatuh Tempo</span>
        </div>
        <div className="stat purple">
          <div className="stat-icon"><CheckCircle2 size={20} /></div>
          <strong>{closingCount}</strong>
          <span>Financial Closing</span>
        </div>
      </div>

      {/* Prioritas Hari Ini */}
      <section className="panel" style={{ marginTop: 20 }}>
        <div className="panel-head">
          <h2><AlertTriangle size={18} style={{ color: '#d97706', verticalAlign: '-3px', marginRight: 6 }} /> Prioritas Hari Ini</h2>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Prioritas</th>
                <th>Order / Buyer</th>
                <th>Pekerjaan CFO</th>
                <th>Nilai / Outstanding</th>
                <th>Bukti & Gate</th>
                <th>Due</th>
                <th>Handoff Berikutnya</th>
                <th style={{ textAlign: 'center' }}>Tindakan</th>
              </tr>
            </thead>
            <tbody>
              {priorityItems.map((item) => (
                <tr key={item.id}>
                  <td>
                    <span className={'badge ' + (item.priority === 'P1' ? 'red' : 'amber')}>
                      {item.priority}
                    </span>
                  </td>
                  <td><b>{item.orderBuyer}</b></td>
                  <td>{item.job}</td>
                  <td><strong style={{ color: '#0f172a' }}>{item.amount}</strong></td>
                  <td><small>{item.evidence}</small></td>
                  <td><span className="badge gray">{item.due}</span></td>
                  <td><small>{item.handoff}</small></td>
                  <td style={{ textAlign: 'center' }}>
                    <Link to={item.actionLink} className="btn sm primary">
                      {item.action}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* 3 Kolom Sesuai Blueprint: Collection & AR, Cash & Payable, Gate & Handoff */}
      <div className="grid3" style={{ marginTop: 20 }}>
        {/* Kolom 1: Collection & AR */}
        <section className="panel">
          <div className="panel-head">
            <h2><DollarSign size={16} style={{ marginRight: 6 }} /> Collection & AR</h2>
            <Link to="/cfo/receivables" className="btn sm">Lihat Semua <ArrowRight size={12} /></Link>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Buyer & Order</th>
                  <th>Outstanding</th>
                  <th>Jatuh Tempo</th>
                  <th>Tindakan Berikutnya</th>
                </tr>
              </thead>
              <tbody>
                {collectionRows.map((r, i) => (
                  <tr key={i}>
                    <td>
                      <b>{r.buyer}</b><br />
                      <small style={{ color: '#64748b' }}>{r.order}</small>
                    </td>
                    <td>{rupiah(r.outstanding)}</td>
                    <td><small>{r.due}</small></td>
                    <td><span className="badge amber">{r.next}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Kolom 2: Cash & Payable */}
        <section className="panel">
          <div className="panel-head">
            <h2><Layers size={16} style={{ marginRight: 6 }} /> Cash & Payable (AP)</h2>
            <Link to="/cfo/purchase-orders" className="btn sm">Lihat AP <ArrowRight size={12} /></Link>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Supplier / Partner</th>
                  <th>Nilai</th>
                  <th>Jatuh Tempo</th>
                  <th>Cash Plan</th>
                </tr>
              </thead>
              <tbody>
                {payableRows.map((r, i) => (
                  <tr key={i}>
                    <td>
                      <b>{r.supplier}</b><br />
                      <small style={{ color: '#64748b' }}>{r.item}</small>
                    </td>
                    <td>{rupiah(r.amount)}</td>
                    <td><small>{r.due}</small></td>
                    <td>
                      <span className={'badge ' + (r.status === 'Approved' ? 'green' : 'amber')}>
                        {r.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Kolom 3: Gate & Handoff */}
        <section className="panel">
          <div className="panel-head">
            <h2><Truck size={16} style={{ marginRight: 6 }} /> Gate & Handoff</h2>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '10px 0' }}>
            <div style={{ padding: '10px', background: '#f8fafc', borderRadius: 6, borderLeft: '4px solid #3b82f6' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <b style={{ color: '#1e40af' }}>CMO Gate</b>
                <span className="badge blue">Order & Quotation</span>
              </div>
              <p style={{ margin: '4px 0 0', fontSize: 12, color: '#475569' }}>
                Quotation draft &rarr; CFO verifikasi margin &ge;30% &rarr; Release quotation resmi.
              </p>
            </div>

            <div style={{ padding: '10px', background: '#f8fafc', borderRadius: 6, borderLeft: '4px solid #10b981' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <b style={{ color: '#065f46' }}>Finance Gate (CFO)</b>
                <span className="badge green">Invoice & Payment</span>
              </div>
              <p style={{ margin: '4px 0 0', fontSize: 12, color: '#475569' }}>
                Pembayaran masuk diverifikasi dengan bukti transfer valid sebelum membuka release SPK.
              </p>
            </div>

            <div style={{ padding: '10px', background: '#f8fafc', borderRadius: 6, borderLeft: '4px solid #f59e0b' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <b style={{ color: '#92400e' }}>Shipment Finance Gate</b>
                <span className="badge amber">Delivery Lock</span>
              </div>
              <p style={{ margin: '4px 0 0', fontSize: 12, color: '#475569' }}>
                Shipment terkunci bila ada invoice outstanding tanpa CEO Shipment Exception resmi.
              </p>
            </div>

            <div style={{ padding: '10px', background: '#f8fafc', borderRadius: 6, borderLeft: '4px solid #8b5cf6' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <b style={{ color: '#5b21b6' }}>3-Way Closing</b>
                <span className="badge purple">Final Order</span>
              </div>
              <p style={{ margin: '4px 0 0', fontSize: 12, color: '#475569' }}>
                Order selesai hanya setelah Customer Closed (CMO), Operational Closed (COO), dan Financial Closed (CFO) semuanya terpenuhi.
              </p>
            </div>
          </div>
        </section>
      </div>

      <div style={{ marginTop: 20, padding: 12, background: '#f1f5f9', borderRadius: 6, fontSize: 12, color: '#475569' }}>
        <strong>Batas Kewenangan CFO:</strong> Memegang review HPP/pricing, invoice, verifikasi pembayaran, AR/AP, cash plan, shipment finance gate, dan financial closing. Riadi mengeksekusi PO/GR fisik; CMO memegang buyer/quotation; COO memegang produksi dan operational closing; CEO memegang approval exception.
      </div>
    </div>
  );
}
