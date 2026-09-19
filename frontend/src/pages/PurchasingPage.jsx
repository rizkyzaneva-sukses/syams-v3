import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import {
  Package,
  Truck,
  ShoppingCart,
  CheckSquare,
  Clock,
  AlertTriangle,
  RefreshCw,
  Send,
  ArrowRight,
  ShieldCheck,
  FileText,
  Boxes,
} from 'lucide-react';

/* MODUL PURCHASING & WAREHOUSE RIADI — INT-PUR-001 (Revisi #47 / ID 60).
   Workspace eksekusi terpadu milik Riadi:
   1. Intake Material Requirement dari Siti/COO
   2. Validasi stok on-hand / reserved / available & hitung Net Shortage
   3. Pembuatan Purchase Requisition (PR) & Handoff approval CFO
   4. Penerbitan Supplier PO & Tracking ETA
   5. Goods Receipt (GR) & Receiving Inspection (Stok Fisik)
   6. Inventory Ledger & Reserve per Order/Batch
   7. Handoff status "Material Ready" kembali ke COO
*/

const rupiah = (n) => 'Rp ' + Number(n || 0).toLocaleString('id-ID');

export default function PurchasingPage() {
  const [activeTab, setActiveTab] = useState('REQUIREMENTS');
  const [feedback, setFeedback] = useState('');

  // Mock / intake requirements dari COO
  const requirements = [
    {
      reqId: 'MR-2026-041',
      orderId: 'SO-BO001',
      article: 'BT-01',
      batch: 'B1',
      material: 'Kain Katun Combed 30s Hitam',
      uom: 'kg',
      grossNeed: 150,
      onHand: 30,
      reserved: 20,
      available: 10,
      netShortage: 140,
      requiredBy: '22 Sep 2026',
      status: 'PR_PENDING',
      supplier: 'PT Sumber Kain Utama',
    },
    {
      reqId: 'MR-2026-042',
      orderId: 'SO-BO001',
      article: 'BT-01',
      batch: 'B1',
      material: 'Rib Leher Katun Hitam',
      uom: 'kg',
      grossNeed: 12,
      onHand: 15,
      reserved: 0,
      available: 15,
      netShortage: 0,
      requiredBy: '22 Sep 2026',
      status: 'ALLOCATED_FROM_STOCK',
      supplier: '—',
    },
    {
      reqId: 'MR-2026-045',
      orderId: 'SO-BO012',
      article: 'SK-01',
      batch: 'B1',
      material: 'Kain Oxford Biru Langit',
      uom: 'yard',
      grossNeed: 600,
      onHand: 50,
      reserved: 50,
      available: 0,
      netShortage: 600,
      requiredBy: '25 Sep 2026',
      status: 'PO_ISSUED',
      supplier: 'CV Tekstil Nusantara',
    },
  ];

  // Supplier PO list
  const purchaseOrders = [
    {
      poNo: 'PO-2026-088',
      supplier: 'PT Sumber Kain Utama',
      material: 'Kain Katun Combed 30s Hitam',
      qty: '140 kg',
      amount: 14700000,
      status: 'APPROVED_BY_CFO',
      cfoApproval: 'Lutfi (VERIFIED)',
      etaSupplier: '21 Sep 2026',
      receiptStatus: 'WAITING_DELIVERY',
    },
    {
      poNo: 'PO-2026-085',
      supplier: 'CV Tekstil Nusantara',
      material: 'Kain Oxford Biru Langit',
      qty: '600 yard',
      amount: 21000000,
      status: 'GOODS_RECEIVED',
      cfoApproval: 'Lutfi (VERIFIED)',
      etaSupplier: '18 Sep 2026',
      receiptStatus: 'INSPECTED_PASS',
    },
  ];

  // Inventory Ledger snapshot
  const inventoryLedger = [
    { itemCode: 'RAW-KMB-30S-BLK', name: 'Kain Combed 30s Hitam', onHand: 170, reserved: 140, available: 30, uom: 'kg', loc: 'Gudang Kain A-1' },
    { itemCode: 'RAW-RIB-30S-BLK', name: 'Rib Katun Hitam', onHand: 27, reserved: 12, available: 15, uom: 'kg', loc: 'Gudang Kain A-3' },
    { itemCode: 'RAW-OXF-BLU', name: 'Kain Oxford Biru', onHand: 600, reserved: 600, available: 0, uom: 'yard', loc: 'Gudang Kain B-2' },
  ];

  function handleCreatePR(req) {
    setFeedback(`Purchase Requisition berhasil dibuat untuk ${req.material} (${req.netShortage} ${req.uom}). Terkirim ke CFO untuk budget approval.`);
    setTimeout(() => setFeedback(''), 5000);
  }

  function handleReceiveGR(po) {
    setFeedback(`Goods Receipt (GR) berhasil dicatat untuk ${po.poNo}. Stok masuk ke Inventory Ledger & status "Material Ready" dikirim ke COO.`);
    setTimeout(() => setFeedback(''), 5000);
  }

  return (
    <div className="page">
      <div className="page-title">
        <div>
          <h1>Purchasing & Warehouse — Riadi</h1>
          <p>Validasi kebutuhan material produksi, pengadaan (PR/PO), penerimaan barang (GR), dan alokasi stok fisik</p>
        </div>
      </div>

      {feedback && <div className="notice success">{feedback}</div>}

      {/* Tabs Menu */}
      <div className="tab-group" style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        <button
          type="button"
          className={'btn ' + (activeTab === 'REQUIREMENTS' ? 'primary' : '')}
          onClick={() => setActiveTab('REQUIREMENTS')}
        >
          <Package size={15} style={{ marginRight: 6 }} /> Kebutuhan Material COO
        </button>
        <button
          type="button"
          className={'btn ' + (activeTab === 'PURCHASE_ORDERS' ? 'primary' : '')}
          onClick={() => setActiveTab('PURCHASE_ORDERS')}
        >
          <ShoppingCart size={15} style={{ marginRight: 6 }} /> Supplier PO & Penerimaan (GR)
        </button>
        <button
          type="button"
          className={'btn ' + (activeTab === 'INVENTORY' ? 'primary' : '')}
          onClick={() => setActiveTab('INVENTORY')}
        >
          <Boxes size={15} style={{ marginRight: 6 }} /> Inventory Ledger & Alokasi
        </button>
      </div>

      {/* Tab 1: Kebutuhan Material COO */}
      {activeTab === 'REQUIREMENTS' && (
        <section className="panel">
          <div className="panel-head">
            <h2>Kebutuhan Material dari Production Plan (Siti / COO)</h2>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Req ID & Order</th>
                  <th>Nama Material</th>
                  <th>Gross Need</th>
                  <th>Stok On-Hand</th>
                  <th>Reserved</th>
                  <th>Available</th>
                  <th>Net Shortage</th>
                  <th>Required By</th>
                  <th>Status</th>
                  <th style={{ textAlign: 'center' }}>Tindakan</th>
                </tr>
              </thead>
              <tbody>
                {requirements.map((r) => (
                  <tr key={r.reqId}>
                    <td>
                      <b>{r.reqId}</b><br />
                      <small>{r.orderId} ({r.article})</small>
                    </td>
                    <td>{r.material}</td>
                    <td><b>{r.grossNeed} {r.uom}</b></td>
                    <td>{r.onHand}</td>
                    <td>{r.reserved}</td>
                    <td><span className={'badge ' + (r.available > 0 ? 'green' : 'gray')}>{r.available}</span></td>
                    <td>
                      <strong style={{ color: r.netShortage > 0 ? '#ef4444' : '#10b981' }}>
                        {r.netShortage} {r.uom}
                      </strong>
                    </td>
                    <td><small>{r.requiredBy}</small></td>
                    <td><span className="badge blue">{r.status}</span></td>
                    <td style={{ textAlign: 'center' }}>
                      {r.netShortage > 0 ? (
                        <button
                          type="button"
                          className="btn sm primary"
                          onClick={() => handleCreatePR(r)}
                        >
                          Buat PR
                        </button>
                      ) : (
                        <span className="badge green">Siap Alokasi</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Tab 2: Supplier PO & Goods Receipt (GR) */}
      {activeTab === 'PURCHASE_ORDERS' && (
        <section className="panel">
          <div className="panel-head">
            <h2>Daftar Supplier PO & Penerimaan Barang (GR)</h2>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Nomor PO</th>
                  <th>Supplier</th>
                  <th>Item & Qty</th>
                  <th>Total Biaya</th>
                  <th>Approval CFO</th>
                  <th>ETA Supplier</th>
                  <th>Status Barang</th>
                  <th style={{ textAlign: 'center' }}>Tindakan Fisik Riadi</th>
                </tr>
              </thead>
              <tbody>
                {purchaseOrders.map((po) => (
                  <tr key={po.poNo}>
                    <td><b>{po.poNo}</b></td>
                    <td>{po.supplier}</td>
                    <td>{po.material} ({po.qty})</td>
                    <td>{rupiah(po.amount)}</td>
                    <td><span className="badge green">{po.cfoApproval}</span></td>
                    <td><small>{po.etaSupplier}</small></td>
                    <td><span className="badge amber">{po.receiptStatus}</span></td>
                    <td style={{ textAlign: 'center' }}>
                      {po.receiptStatus === 'WAITING_DELIVERY' ? (
                        <button
                          type="button"
                          className="btn sm primary"
                          onClick={() => handleReceiveGR(po)}
                        >
                          Catat Terima (GR)
                        </button>
                      ) : (
                        <span className="badge green">Tersedia di Gudang</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Tab 3: Inventory Ledger */}
      {activeTab === 'INVENTORY' && (
        <section className="panel">
          <div className="panel-head">
            <h2>Inventory Ledger — Stok Bahan Baku Fisik</h2>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Kode Item</th>
                  <th>Deskripsi Bahan Baku</th>
                  <th>Total Fisik (On-Hand)</th>
                  <th>Dialokasikan (Reserved)</th>
                  <th>Bebas (Available)</th>
                  <th>Satuan</th>
                  <th>Lokasi Gudang</th>
                </tr>
              </thead>
              <tbody>
                {inventoryLedger.map((inv) => (
                  <tr key={inv.itemCode}>
                    <td><code>{inv.itemCode}</code></td>
                    <td><b>{inv.name}</b></td>
                    <td>{inv.onHand}</td>
                    <td><span className="badge amber">{inv.reserved}</span></td>
                    <td><span className="badge green">{inv.available}</span></td>
                    <td>{inv.uom}</td>
                    <td><small>{inv.loc}</small></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <div style={{ marginTop: 20, padding: 12, background: '#f1f5f9', borderRadius: 6, fontSize: 12, color: '#475569' }}>
        <strong>Batas Kewenangan Purchasing & Warehouse (Riadi):</strong> Riadi berwenang membuat Purchase Requisition, memproses Supplier PO setelah disetujui CFO, menerima barang fisik (Goods Receipt), melakukan receiving inspection, dan mengelola saldo stok di Inventory Ledger. Riadi tidak dapat melakukan approval anggaran (milik CFO) atau mengubah jadwal rute operasional (milik COO).
      </div>
    </div>
  );
}
