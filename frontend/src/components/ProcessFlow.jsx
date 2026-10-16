import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  FileText, DollarSign, Package, CheckSquare, Truck, Target, Factory,
  Layers, Lock, ChevronDown, ChevronUp, Database, ArrowRight, ShieldCheck,
  Factory as FactoryIcon, Scissors, Printer, Users,
} from 'lucide-react';

/* ============================================================================
   PROCESS FLOW — Alur Proses End-to-End BOS SYAMS (V0.3)
   ----------------------------------------------------------------------------
   Satu-satunya sumber urutan proses. Angka "Tahap 1..8" di sini SAMA dengan
   FLOW_STEPS di GuidePage.jsx (diagram ringkas). Isi teknis diambil langsung
   dari kode backend:
     - backend/app/flow_engine.py   → definisi step & gate per jenis order
     - backend/app/workflow.py      → syarat lolos tiap gate (validasi nyata)
     - backend/app/routers/*.py      → endpoint & status yang dipakai
   Jangan ubah teks gate tanpa menyelaraskan dengan workflow.py — teks di sini
   adalah cermin dari penolakan (HTTPException) yang benar-benar muncul.
============================================================================ */

const TONE = {
  blue: { bg: '#dbeafe', fg: '#1e40af', line: '#3b82f6' },
  amber: { bg: '#fef3c7', fg: '#92400e', line: '#f59e0b' },
  green: { bg: '#dcfce7', fg: '#166534', line: '#16a34a' },
};

const PHASES = [
  {
    n: 1,
    title: 'PO Intake & Aktivasi Order',
    tone: 'blue',
    icon: FileText,
    who: 'Deby (CMO Support) → Cecep (CMO Manager)',
    what: 'Deby menginput PO buyer (data order, artikel, kuantitas, breakdown ukuran), mengunggah dokumen PDF asli, lalu submit. Cecep meninjau dan meng-“Accept” untuk mengaktifkan Order beserta nomor SO resmi.',
    pages: [
      { name: 'PO Inbox', path: '/cmo/po-inbox' },
      { name: 'Form PO Intake', path: '/cmo/po-inbox/new' },
      { name: 'Hari Ini (Deby)', path: '/cmo/today' },
    ],
    backend: [
      'POST /api/cmo/po-intake — simpan draft PO',
      'POST /api/cmo/po-intake/{id}/document — unggah PDF asli',
      'POST /api/cmo/po-intake/{id}/check — cek kelengkapan otomatis',
      'POST /api/cmo/po-intake/{id}/submit — kirim ke CMO Manager',
      'POST /api/cmo/po-intake/{id}/review — accept/reject (CMO Manager)',
    ],
    gate: [
      'Dokumen PDF PO asli WAJIB diunggah.',
      'Rute produksi per artikel terisi otomatis dengan rute standar “Cutting > Sewing > QC” (form PO tidak lagi memintanya).',
      'Order ID otomatis berformat SYM-YYMM-NNN (mis. SYM-2610-001), nomor naik per bulan.',
      'Rute produksi IMMUTABLE — tidak ada endpoint ubah artikel setelah order dibuat. Salah rute = buat order baru.',
      'Order langsung tidak bisa dibuat: POST /api/orders ditolak 403. Satu-satunya jalan adalah PO intake + acceptance.',
    ],
  },
  {
    n: 2,
    title: 'Quotation & Gerbang Harga (Margin)',
    tone: 'amber',
    icon: DollarSign,
    who: 'Cecep (CMO Manager) → Lutfi (CFO Manager)',
    what: 'Cecep menyusun harga jual per artikel (unit_price) sekaligus HPP (unit_hpp). Lutfi memeriksa kelayakan margin terhadap kebijakan bisnis, lalu meng-“Approve”.',
    pages: [
      { name: 'Quotation', path: '/cmo/quotations' },
      { name: 'Kebijakan Bisnis', path: '/ceo/business-policy' },
    ],
    backend: [
      'POST /api/cmo/quotations — buat draft',
      'PATCH /api/cmo/quotations/{id} — isi pricing & status APPROVED (CFO)',
      'POST /api/ceo/quotations/{id}/approve-limit — approval CEO bila melebihi limit CFO',
    ],
    gate: [
      'Pricing wajib lengkap: setiap artikel tepat sekali, unit_price > 0, unit_hpp ≥ 0. Amount/HPP/margin dihitung otomatis oleh sistem.',
      'Payment plan + alasan persetujuan CFO wajib diisi saat APPROVED.',
      'Margin ≥ batas minimum kebijakan bisnis (default ≥ 15%).',
      'Bila amount > limit CFO → butuh approval CEO dulu.',
      'Quotation APPROVED bersifat immutable; perubahan harus lewat revisi baru.',
    ],
  },
  {
    n: 3,
    title: 'Invoice, Pembayaran & Finance Gate (DP)',
    tone: 'amber',
    icon: DollarSign,
    who: 'Lutfi (CFO Manager)',
    what: 'Lutfi menerbitkan Invoice (DP/Pelunasan), mencatat pembayaran riil yang masuk ke rekening, melakukan rekonsiliasi dengan mutasi bank, lalu membuka Finance Gate agar order boleh lanjut ke SPK.',
    pages: [
      { name: 'CFO Home', path: '/cfo' },
      { name: 'Invoices', path: '/cfo/invoices' },
    ],
    backend: [
      'POST /api/cfo/invoices — terbitkan invoice (status UNPAID)',
      'POST /api/cfo/invoices/{id}/reconcile — tandai VERIFIED',
      'POST /api/cfo/payments — catat pembayaran masuk',
      'POST /api/cfo/payments/{id}/verify — verifikasi pembayaran',
    ],
    gate: [
      'Nominal terbayar (paid_amount) & status invoice TIDAK boleh diketik manual — dihitung sistem dari record pembayaran (anti-fraud).',
      'Invoice harus direkonsiliasi (VERIFIED) sebelum pembayaran baru diterima.',
      'Finance Gate (finance_gate_status) harus APPROVED + ada finance_verified_by_id + payment_evidence_ref.',
      'Syarat nominal sesuai termin: FULL (lunas), DP (≥ required_dp_amount), atau CREDIT (wajib credit_due_date).',
    ],
  },
  {
    n: 4,
    title: 'Sample & Development (bila diminta)',
    tone: 'blue',
    icon: Scissors,
    who: 'Fahrul (Sample PIC) → Cecep (CMO Manager) / Buyer',
    what: 'Fahrul membuat sample fisik & mengunggah bukti foto berversi (V1, V2, …). Keputusan buyer (APPROVED/REJECTED) dicatat CMO Manager sebagai penentu kunci. Tanpa approval sample, rilis SPK diblokir.',
    pages: [
      { name: 'Sample & PPM', path: '/cmo/samples' },
      { name: 'Sample Today', path: '/sample/today' },
      { name: 'My Sample Tasks', path: '/sample/tasks' },
      { name: 'Sample Lifecycle', path: '/sample/lifecycle' },
    ],
    backend: [
      'POST /api/cmo/samples — buat sample record',
      'POST /api/cmo/samples/{id}/evidence — unggah bukti foto',
      'POST /api/cmo/samples/{id}/customer-decision — catat keputusan buyer (CMO Manager)',
    ],
    gate: [
      'Sample untuk SETIAP artikel yang sample_required (atau order SAMPLE_ONLY) harus status APPROVED.',
      'Approval wajib punya customer_approved_by_id + alasan keputusan + bukti (evidence).',
      'Pemisahan tugas: pembuat sample (Fahrul) DILARANG meng-approve; keputusan buyer hanya dicatat CMO Manager.',
      'Sample yang sudah diputus (REJECTED/REVISION/APPROVED) terkunci — revisi harus versi baru.',
    ],
  },
  {
    n: 5,
    title: 'Release SPK',
    tone: 'green',
    icon: FactoryIcon,
    who: 'Deby (generate & print) → Cecep (release)',
    what: 'Deby meng-generate nomor SPK dan mencetak fisiknya (ber-snapshot terkunci). Cecep menekan “Release SPK” setelah 7 gate hijau. SPK dirilis SEBELUM bahan diproses, sama seperti sheet lama.',
    pages: [
      { name: 'Pusat SPK', path: '/cmo/spk' },
      { name: 'Release to COO', path: '/cmo/release-to-coo' },
    ],
    backend: [
      'POST /api/cmo/spk — buat SPK (DRAFT)',
      'POST /api/cmo/spk/{id}/generate — kunci snapshot (GENERATED)',
      'POST /api/cmo/spk/{id}/print — cetak (PRINTED)',
      'GET  /api/cmo/spk/{id}/release-readiness — cek 7 gate',
      'POST /api/cmo/spk/{id}/release — rilis (RELEASED)',
    ],
    gate: [
      '7 gate rilis SPK: dokumen tercetak, versi SPK terbaru, dokumen sesuai order, quotation APPROVED, Finance Gate APPROVED, sample lengkap, rute produksi lengkap.',
      'BOM, material, dan Rencana Produksi TIDAK dibutuhkan untuk merilis SPK — keduanya dikerjakan setelahnya.',
      'Alasan rilis wajib; versi > 1 wajib menyertakan alasan koreksi.',
      'Order SAMPLE_ONLY tidak masuk produksi.',
    ],
  },
  {
    n: 6,
    title: 'Bahan, Rencana Produksi & Eksekusi Fisik',
    tone: 'green',
    icon: Package,
    who: 'Siti (COO) → Riadi (Purchasing) → Lutfi (CFO) → Siti & Iman (pabrik)',
    what: 'Setelah SPK dirilis tahap BAHAN dimulai: Siti menyusun BOM dan Material Request, Riadi membeli bahan (Goods Receipt) setelah anggaran PO disetujui CFO, Siti meng-“Approve” Production Plan. Lalu pabrik mengeksekusi berurutan sesuai rute artikel. Seluruh tahap terpantau di Master Control.',
    pages: [
      { name: 'BOM & Cost', path: '/coo/bom-cost' },
      { name: 'Material Requests', path: '/coo/material-requests' },
      { name: 'Purchasing & Gudang', path: '/purchasing' },
      { name: 'Purchase Orders', path: '/cfo/purchase-orders' },
      { name: 'Production Plan', path: '/coo/planning' },
      { name: 'Production Queue', path: '/coo/production' },
      { name: 'Printing Hari Ini', path: '/printing/today' },
      { name: 'Master Control', path: '/master' },
    ],
    backend: [
      'POST /api/coo/bom — isi BOM per artikel',
      'POST /api/coo/material-requests — ajukan kebutuhan bahan',
      'PATCH /api/cfo/purchase-orders/{id} — set material_status READY + arrival_date',
      'POST /api/coo/production-plans — rencana produksi (APPROVED), butuh SPK RELEASED',
      'POST /api/coo/movements — pergerakan WIP per proses',
      'POST /api/control/orders/{id}/stages/{kode}/done — tandai tahap di Master Control',
    ],
    gate: [
      'Production Plan hanya bisa dibuat setelah SPK RELEASED, dan harus APPROVED + punya plan_date.',
      'BOM WAJIB ada untuk setiap artikel; Material Request ≥ Σ(qty_per_unit × qty artikel); setiap PO material_status READY.',
      'Proses produksi baru boleh dicatat setelah material READY dan Production Plan APPROVED.',
      'Eksekusi harus URUT rute (mis. Cutting → Printing → Sewing → QC). Tidak boleh lompat proses.',
      'Rumus kuantitas mutlak tiap handoff: Qty Masuk = Selesai + Reject + Sisa.',
      'Printing PIC hanya boleh update proses PRINTING/BORDIR/QC S/B.',
    ],
  },
  {
    n: 7,
    title: 'QC Final, Packing & Pengiriman',
    tone: 'green',
    icon: CheckSquare,
    who: 'Siti (COO) & Iman (Printing) → Lutfi (CFO)',
    what: 'Setelah seluruh kuantitas lulus QC Final (PASS tanpa reject), Siti mengemas (PACKED) dengan rekonsiliasi kuantitas baris artikel. Lutfi membuka Finance Gate Pengiriman, lalu barang diberangkatkan (SHIPPED).',
    pages: [
      { name: 'QC Records', path: '/coo/qc' },
      { name: 'Shipments Gate', path: '/cfo/shipments' },
    ],
    backend: [
      'POST /api/coo/qc-records — QC per artikel (PASS/FAIL/REWORK)',
      'PATCH /api/coo/shipments/{id} — packing_status PACKED',
      'POST /api/cfo/shipments/{id}/gate — Finance Gate pengiriman (CLEAR)',
      'PATCH /api/coo/shipments/{id} — status SHIPPED + shipped_date',
    ],
    gate: [
      'QC Final PASS: total_reject = 0 dan total_checked ≥ qty artikel.',
      'PACKED wajib disertai rekonsiliasi baris artikel (shipment lines) yang pas dengan kuantitas order.',
      'Finance Gate pengiriman harus CLEAR + ada finance_assessed_by_id.',
      'Bila masih ada outstanding, WAJIB ada approval CEO atas nominal outstanding tersebut.',
    ],
  },
  {
    n: 8,
    title: 'Serah Terima Fisik & 3-Way Closing',
    tone: 'blue',
    icon: Truck,
    who: 'Siti (COO) + Cecep (CMO) + Lutfi (CFO)',
    what: 'Siti mencatat serah terima fisik (DELIVERED). Cecep mencatat konfirmasi penerimaan buyer. Ketiganya lalu menutup order dari sisi masing-masing: Customer (CMO), Operational (COO), Financial (CFO). Order resmi CLOSED.',
    pages: [
      { name: 'Deliveries', path: '/coo/deliveries' },
      { name: 'Order Closing', path: '/coo/closing' },
    ],
    backend: [
      'PATCH /api/coo/shipments/{id} — status DELIVERED + delivery_date (COO)',
      'POST /api/coo/deliveries — DeliveryConfirmation CONFIRMED (CMO)',
      'POST /api/coo/closing — tiga status closing',
    ],
    gate: [
      'Serah terima fisik (DELIVERED + delivery_date) dicatat COO Manager; konfirmasi customer dicatat CMO Manager — keduanya terpisah dan wajib.',
      'Closing butuh TIGA peran berbeda (pemisahan tugas): customer_close_status (CMO), operational_close_status (COO), financial_close_status (CFO).',
      'Operational close: seluruh WIP selesai + semua shipment DELIVERED & PACKED + kuantitas artikel terekonkonsiliasi.',
      'Financial close: total invoice > 0, lunas (paid ≥ total), dan sudah direkonsiliasi.',
      'order_close_status bersifat TURUNAN — otomatis CLOSED bila ketiganya CLOSED; jangan dikirim manual.',
      'Order CLOSED bersifat immutable — semua data terkait terkunci.',
    ],
  },
];

const ORDER_TYPES = [
  {
    key: 'SAMPLE_ONLY',
    label: 'Sample Saja',
    steps: ['Order', 'Invoice', 'PPM', 'Sample', 'Sample Disetujui', 'Follow-up', 'Closed'],
    note: 'Tidak masuk produksi massal. Ditolak di tahap Production Plan.',
  },
  {
    key: 'SAMPLE_PRODUCTION',
    label: 'Sample → Produksi',
    steps: ['Order', 'Invoice', 'Sample', 'Sample Disetujui', 'SPK', 'Produksi', 'QC', 'Kirim', 'Diterima', 'Closed'],
    note: 'Order dengan sample wajib approve sebelum produksi massal.',
  },
  {
    key: 'REPEAT_PRODUCTION',
    label: 'Repeat / Produksi Ulang',
    steps: ['Order', 'Invoice', 'PPM', 'SPK', 'Produksi', 'QC', 'Kirim', 'Diterima', 'Closed'],
    note: 'Tanpa sample baru (mengulang desain yang sudah pernah disetujui).',
  },
];

function PhaseCard({ phase, open, onToggle }) {
  const t = TONE[phase.tone] || TONE.blue;
  const Icon = phase.icon;

  return (
    <div style={{
      border: `1px solid ${open ? t.line : '#e2e8f0'}`,
      borderRadius: 12,
      background: 'white',
      overflow: 'hidden',
      boxShadow: open ? `0 4px 14px ${t.line}22` : 'none',
      transition: 'all .15s ease',
    }}>
      <button
        type="button"
        onClick={onToggle}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 14,
          padding: '14px 18px', background: open ? '#f8fafc' : 'white',
          border: 'none', textAlign: 'left', cursor: 'pointer',
        }}
      >
        <span style={{
          width: 38, height: 38, borderRadius: 10, flexShrink: 0,
          background: t.bg, color: t.fg, display: 'grid', placeItems: 'center',
          fontWeight: 800, fontSize: 16,
        }}>
          <Icon size={20} />
        </span>
        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{ display: 'block', fontSize: 11, fontWeight: 700, color: t.fg, letterSpacing: '.04em', textTransform: 'uppercase' }}>
            Tahap {phase.n}
          </span>
          <span style={{ display: 'block', fontSize: 15.5, fontWeight: 800, color: '#0f172a' }}>{phase.title}</span>
          <span style={{ display: 'block', fontSize: 12.5, color: '#64748b', marginTop: 2 }}>{phase.who}</span>
        </span>
        {open ? <ChevronUp size={18} color="#64748b" /> : <ChevronDown size={18} color="#64748b" />}
      </button>

      {open && (
        <div style={{ padding: '4px 18px 18px', borderTop: '1px solid #eef2f6' }}>
          <p style={{ fontSize: 13.5, color: '#334155', lineHeight: 1.6, margin: '14px 0 16px' }}>
            {phase.what}
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            {/* Kolom sistem: endpoint */}
            <div style={{ background: '#f8fafc', border: '1px solid #eef2f6', borderRadius: 10, padding: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                <Database size={15} color="#2563eb" />
                <strong style={{ fontSize: 12.5, color: '#0f172a', textTransform: 'uppercase', letterSpacing: '.03em' }}>Proses di Sistem</strong>
              </div>
              <ul style={{ margin: 0, paddingLeft: 0, listStyle: 'none', fontSize: 12.5, color: '#334155', lineHeight: 1.5 }}>
                {phase.backend.map((b, i) => {
                  // Teks sumber berbentuk "POST /api/... — aksi manusia".
                  // Untuk Bos non-teknis, aksi (verb) ditampilkan DULU, endpoint
                  // jadi chip kecil di bawahnya supaya tidak mendominasi.
                  const parts = String(b).split(' — ');
                  const isApi = /^(GET|POST|PATCH|PUT|DELETE)\s/.test(parts[0]);
                  const action = isApi && parts[1] ? parts[1] : parts[0];
                  const api = isApi ? parts[0].replace(/\s+/g, ' ') : null;
                  return (
                    <li key={i} style={{ marginBottom: 7, display: 'flex', gap: 8 }}>
                      <span style={{ color: '#2563eb', fontWeight: 800, flexShrink: 0 }}>›</span>
                      <span>
                        <span style={{ fontWeight: 600, color: '#0f172a' }}>{action}</span>
                        {api && (
                          <>
                            <br />
                            <code style={{ fontSize: 11, color: '#3f4d60', background: '#e8eef5', border: '1px solid #dbe4ee', padding: '1px 6px', borderRadius: 4, display: 'inline-block', marginTop: 2 }}>{api}</code>
                          </>
                        )}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>

            {/* Kolom gate: syarat */}
            <div style={{ background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 10, padding: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                <Lock size={15} color="#b45309" />
                <strong style={{ fontSize: 12.5, color: '#92400e', textTransform: 'uppercase', letterSpacing: '.03em' }}>Syarat Lolos (Gate)</strong>
              </div>
              <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12.5, color: '#78350f', lineHeight: 1.65 }}>
                {phase.gate.map((g, i) => (
                  <li key={i} style={{ marginBottom: 5 }}>{g}</li>
                ))}
              </ul>
            </div>
          </div>

          {/* Halaman kerja */}
          <div style={{ marginTop: 14, display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: 12, color: '#64748b', fontWeight: 600 }}>Halaman kerja:</span>
            {phase.pages.map((p) => (
              <Link key={p.path} to={p.path} className="btn sm" style={{ padding: '4px 10px', fontSize: 12 }}>
                {p.name} <ArrowRight size={12} />
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function ProcessFlow() {
  // Sumber kebenaran tunggal untuk buka/tutup: besar kemungkinan React
  // menganggap state awal PhaseCard sebagai nilai tetap, sehingga tombol
  // "Buka Semua" tidak akan berpengaruh. Jadi state dipegang di sini.
  const [openSet, setOpenSet] = useState(() => new Set());
  const anyOpen = openSet.size > 0;
  const toggleOne = (n) => setOpenSet((prev) => {
    const next = new Set(prev);
    next.has(n) ? next.delete(n) : next.add(n);
    return next;
  });
  const toggleAll = () => setOpenSet(anyOpen ? new Set() : new Set(PHASES.map((p) => p.n)));

  return (
    <section className="panel" style={{ marginBottom: 32 }}>
      <div className="panel-head" style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 style={{ fontSize: 19, margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
            <Layers size={20} color="#2563eb" /> Alur Proses End-to-End (8 Tahap)
          </h2>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: '#64748b', maxWidth: 760 }}>
            Perjalanan satu order dari PO masuk sampai CLOSED. Setiap tahap punya pelaksana, halaman kerja, proses sistem,
            dan <strong>syarat lolos</strong> yang ditegakkan di backend (bukan hanya UI). Klik tahap untuk membuka detail.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" className="btn sm" onClick={toggleAll}>
            {anyOpen ? 'Tutup Semua' : 'Buka Semua'} <ChevronDown size={14} />
          </button>
        </div>
      </div>

      {/* Legenda peran */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, margin: '4px 0 18px' }}>
        {[
          ['Sales & Buyer', '#1e40af', '#dbeafe'],
          ['Keuangan', '#92400e', '#fef3c7'],
          ['Pabrik & Gudang', '#166534', '#dcfce7'],
        ].map(([label, fg, bg]) => (
          <span key={label} style={{ fontSize: 11.5, fontWeight: 700, color: fg, background: bg, padding: '3px 10px', borderRadius: 20 }}>
            {label}
          </span>
        ))}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {PHASES.map((phase) => (
          <PhaseCard
            key={phase.n}
            phase={phase}
            open={openSet.has(phase.n)}
            onToggle={() => toggleOne(phase.n)}
          />
        ))}
      </div>

      {/* Urutan wajib (teks rantai) */}
      <div style={{ marginTop: 18, padding: 16, background: '#f1f5f9', borderRadius: 12, border: '1px solid #e2e8f0' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <ShieldCheck size={17} color="#1e5ea5" />
          <strong style={{ fontSize: 14, color: '#0f172a' }}>Rantai urutan wajib (sistem menolak lompatan tahap)</strong>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, fontSize: 12.5, color: '#334155', lineHeight: 1.9 }}>
          {['Kebijakan Bisnis (CEO)', 'Order + Artikel', 'Quotation APPROVED', 'Invoice → Bayar → Rekonsiliasi', 'Finance Gate APPROVED', 'SPK RELEASED', 'Production Plan APPROVED', 'BAHAN: BOM → Material Request → PO READY', 'Proses per-rute → QC Final', 'PACKED → Gate Kirim → SHIPPED', 'DELIVERED + Konfirmasi Buyer', 'Closing 3 Arah'].map((s, i, arr) => (
            <React.Fragment key={s}>
              <span style={{ background: 'white', border: '1px solid #e2e8f0', borderRadius: 8, padding: '3px 10px', fontWeight: 600 }}>{s}</span>
              {i < arr.length - 1 && <ArrowRight size={13} color="#94a3b8" />}
            </React.Fragment>
          ))}
        </div>
        <p style={{ margin: '12px 0 0', fontSize: 12.5, color: '#64748b' }}>
          Cek posisi order kapan saja lewat endpoint <code style={{ background: '#eef2f7', padding: '1px 5px', borderRadius: 4 }}>GET /api/orders/&#123;order_id&#125;/flow</code> — laporan <em>current_step</em> beserta alasan setiap langkah berikutnya terblokir.
        </p>
      </div>

      {/* Tiga jenis order */}
      <div style={{ marginTop: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <Target size={17} color="#1e5ea5" />
          <strong style={{ fontSize: 14, color: '#0f172a' }}>Tiga jenis order & alur step-nya</strong>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 12 }}>
          {ORDER_TYPES.map((o) => (
            <div key={o.key} style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: 14, background: '#fafafa' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                <strong style={{ fontSize: 13.5, color: '#0f172a' }}>{o.label}</strong>
                <span className="badge blue" style={{ fontSize: 10 }}>{o.key}</span>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
                {o.steps.map((s, i) => (
                  <React.Fragment key={s + i}>
                    <span style={{ fontSize: 11, background: 'white', border: '1px solid #e2e8f0', borderRadius: 6, padding: '2px 7px', color: '#475569' }}>{s}</span>
                    {i < o.steps.length - 1 && <span style={{ color: '#cbd5e1', fontSize: 11 }}>›</span>}
                  </React.Fragment>
                ))}
              </div>
              <p style={{ margin: 0, fontSize: 12, color: '#64748b', lineHeight: 1.5 }}>{o.note}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
