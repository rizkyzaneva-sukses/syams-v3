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
  const [paymentsQueue, setPaymentsQueue] = useState([]);
  const [pendingPOs, setPendingPOs] = useState([]);
  const [shipments, setShipments] = useState([]);
  const [closings, setClosings] = useState([]);
  const [variance, setVariance] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  async function loadData() {
    setLoading(true);
    try {
      const [dash, ar, ap, pq, pos, shs, cls, v] = await Promise.all([
        api('/dashboard/CFO').catch(() => null),
        api('/cfo/ar-aging').catch(() => null),
        api('/cfo/ap-summary').catch(() => null),
        api('/cfo/payments-queue').catch(() => []),
        api('/cfo/purchase-orders').catch(() => []),
        api('/coo/shipments').catch(() => []),
        api('/coo/order-closing').catch(() => []),
        api('/cfo/actual-cost-variance').catch(() => null),
      ]);
      setData(dash);
      setArData(ar);
      setApData(ap);
      setPaymentsQueue(Array.isArray(pq) ? pq : []);
      setPendingPOs(Array.isArray(pos) ? pos.filter(p => p.status === 'PENDING') : []);
      setShipments(Array.isArray(shs) ? shs.filter(s => s.finance_gate === 'HOLD' || s.finance_gate === 'PENDING') : []);
      setClosings(Array.isArray(cls) ? cls.filter(c => c.financial_close_status === 'OPEN' && c.operational_close_status === 'CLOSED') : []);
      setVariance(v);
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

  if (loading && !data && !arData) {
    return (
      <div className="page">
        <div className="empty"><RefreshCw className="spin" size={20} /> Memuat Morning Finance...</div>
      </div>
    );
  }

  // Ringkasan metrik tindakan hari ini
  const paymentVerifCount = paymentsQueue.length || (arData?.summary?.invoices_with_unverified_payment?.length ?? 0);
  const invoiceDueCount = arData?.summary?.overdue_count ?? 0;
  const pricingReviewCount = variance?.totals?.over_count ?? 0;
  const payableDueCount = apData?.summary?.due_soon_count ?? (apData?.rows?.filter(r => r.outstanding > 0).length ?? 0);
  const closingCount = closings.length;

  // Daftar prioritas tindakan hari ini (action items) dari data riil
  const paymentItems = paymentsQueue.map(p => ({
    id: `PAY-${p.id}`,
    priority: 'P1',
    orderBuyer: `${p.order_id || p.invoice_no} / ${p.buyer || 'Buyer'}`,
    job: `Verifikasi pembayaran DP / Tagihan`,
    amount: rupiah(p.amount),
    evidence: p.evidence_ref || 'Bukti bayar diunggah',
    due: 'Hari ini',
    handoff: 'Update invoice -> update gate G1/G3',
    action: 'Verifikasi',
    actionLink: '/cfo/invoices',
  }));

  const poItems = pendingPOs.map(po => ({
    id: `PO-${po.id}`,
    priority: 'P1',
    orderBuyer: `${po.po_no} / ${po.supplier || po.item}`,
    job: `Persetujuan Anggaran PO (${po.item})`,
    amount: rupiah(po.amount),
    evidence: 'PR Riadi ready + review limit anggaran',
    due: 'Hari ini',
    handoff: 'Riadi proses PO & GR',
    action: 'Setujui PO',
    actionLink: '/cfo/purchase-orders',
  }));

  const shipmentItems = shipments.map(sh => ({
    id: `SH-${sh.id}`,
    priority: 'P2',
    orderBuyer: `${sh.shipment_no} / ${sh.buyer || 'Order #' + sh.order_fk}`,
    job: `Shipment Finance Gate (${sh.finance_gate})`,
    amount: `Total item: ${sh.line_total_qty || 0}`,
    evidence: sh.goods_ready ? 'Barang Siap Kirim (COO)' : 'Packing dalam proses',
    due: 'Hari ini',
    handoff: 'CEO exception bila ada tunggakan; COO eksekusi',
    action: 'Review Gate',
    actionLink: '/cfo/shipments',
  }));

  const closingItems = closings.map(cl => ({
    id: `CLS-${cl.order_fk}`,
    priority: 'P2',
    orderBuyer: `Order #${cl.order_fk}`,
    job: 'Financial Closing',
    amount: 'Rekonsiliasi invoice, cost & AP',
    evidence: 'Operasional selesai (COO Closed)',
    due: 'Besok',
    handoff: 'Tutup order final',
    action: 'Close Finance',
    actionLink: '/coo/closing',
  }));

  const priorityItems = [...paymentItems, ...poItems, ...shipmentItems, ...closingItems];

  // Collection & AR antrean riil
  const collectionRows = arData?.rows?.filter(r => Number(r.outstanding) > 0).slice(0, 5) || [];

  // Cash & Payable (AP) antrean riil
  const payableRows = apData?.rows?.slice(0, 5) || [];

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
              {!priorityItems.length&&<tr><td colSpan={8} className="empty" style={{textAlign:'center',padding:16}}>Semua tindakan harian keuangan telah selesai. Tidak ada antrean tertunda.</td></tr>}
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
                  <tr key={r.invoice_id || i}>
                    <td>
                      <b>{r.buyer}</b><br />
                      <small style={{ color: '#64748b' }}>{r.order_id || r.invoice_no}</small>
                    </td>
                    <td>{rupiah(r.outstanding)}</td>
                    <td><small>{r.due_date || '—'}</small></td>
                    <td><span className="badge amber">{r.next_action || 'Follow-up'}</span></td>
                  </tr>
                ))}
                {!collectionRows.length&&<tr><td colSpan={4} className="empty" style={{textAlign:'center',padding:12}}>Tidak ada piutang jatuh tempo</td></tr>}
              </tbody>
            </table>
          </div>
        </section>

        {/* Kolom 2: Cash & Payable */}
        <section className="panel">
          <div className="panel-head">
            <h2><Layers size={16} style={{ marginRight: 6 }} /> Cash & Payable (AP)</h2>
            <Link to="/cfo/receivables" className="btn sm">Lihat AP <ArrowRight size={12} /></Link>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Supplier / Partner</th>
                  <th>Nilai</th>
                  <th>Jatuh Tempo</th>
                  <th>Status AP</th>
                </tr>
              </thead>
              <tbody>
                {payableRows.map((r, i) => (
                  <tr key={r.po_id || i}>
                    <td>
                      <b>{r.supplier}</b><br />
                      <small style={{ color: '#64748b' }}>{r.item || r.po_no}</small>
                    </td>
                    <td>{rupiah(r.outstanding || r.amount)}</td>
                    <td><small>{r.due_date || '—'}</small></td>
                    <td>
                      <span className={'badge ' + (r.status === 'RECEIVED' ? 'green' : 'amber')}>
                        {r.approval_status || r.status || 'Pending'}
                      </span>
                    </td>
                  </tr>
                ))}
                {!payableRows.length&&<tr><td colSpan={4} className="empty" style={{textAlign:'center',padding:12}}>Tidak ada hutang jatuh tempo</td></tr>}
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
