import React,{useEffect,useMemo,useState} from 'react';
import {api} from '../api';
import {AlertTriangle,ArrowRight,CheckCircle2,ClipboardList,Gauge,RotateCcw} from 'lucide-react';

// Revisi #53/#54/#57: papan eksekusi harian, WIP/handoff/kapasitas, dan
// pemakaian BOM fisik. Semua angka berasal dari transaksi (production
// movements, material consumptions, capacity snapshots) — tidak ada input
// bebas. Target vs realisasi, selisih handoff, dan selisih BOM selalu
// ditampilkan berdampingan supaya penyimpangan tidak tersembunyi di balik
// satu angka ringkasan.

function fmt(n){
  if(n===null||n===undefined) return '—';
  return typeof n==='number'?n.toLocaleString('id-ID'):n;
}

function fmtMoney(n){
  if(n===null||n===undefined) return '—';
  return n.toLocaleString('id-ID',{maximumFractionDigits:2});
}

const STATUS_TONE={DONE:'green',IN_PROCESS:'blue',WAITING:'gray',HOLD:'amber',NOT_STARTED:'gray'};
const USAGE_TONE={MATCH:'green',OVER_USAGE:'red',UNDER_USAGE:'amber'};
const HANDOFF_TONE={MATCHED:'green',PENDING_RECEIPT:'amber',OVER_RECEIPT:'red'};

export default function COOExecutionPage(){
  const [exec,setExec]=useState(null);
  const [handoff,setHandoff]=useState(null);
  const [bom,setBom]=useState(null);
  const [orders,setOrders]=useState([]);
  const [orderId,setOrderId]=useState('');
  const [err,setErr]=useState('');
  const [loading,setLoading]=useState(true);

  function load(id=orderId){
    setLoading(true);setErr('');
    const qs=id?`?order_fk=${id}`:'';
    Promise.all([api('/coo/daily-execution'+qs),api('/coo/handoff-capacity'+qs),api('/coo/bom-physical'+qs)])
      .then(([e,h,b])=>{setExec(e);setHandoff(h);setBom(b)})
      .catch(e=>setErr(e.message))
      .finally(()=>setLoading(false));
  }

  useEffect(()=>{api('/orders').then(setOrders).catch(e=>setErr(e.message))},[]);
  useEffect(()=>{load(orderId)},[orderId]);

  const unbalanced=useMemo(()=>exec?.rows?.filter(r=>!r.balanced)||[],[exec]);
  const issues=useMemo(()=>exec?.rows?.flatMap(r=>r.reconciliation.map(i=>({...i,order_id:r.order_id,article_code:r.article_code})))||[],[exec]);
  const followUps=handoff?.follow_ups||[];

  return <div className="page">
    <div className="page-title"><div>
      <h1><ClipboardList size={22}/> Eksekusi Harian Produksi</h1>
      <p>Target vs realisasi hari ini, WIP, handoff antar proses, kapasitas, dan pemakaian BOM fisik.</p>
    </div>
      <button className="btn" onClick={()=>load()}><RotateCcw size={14}/> Refresh</button>
    </div>

    {err&&<div className="notice danger">{err}</div>}

    <section className="panel">
      <label>Order
        <select value={orderId} onChange={e=>setOrderId(e.target.value)}>
          <option value="">Semua order</option>
          {orders.map(o=><option key={o.id} value={o.id}>{o.order_id} — {o.buyer}</option>)}
        </select>
      </label>
      {exec?.invariant&&<p className="muted">Aturan kuantitas: <code>{exec.invariant}</code></p>}
    </section>

    {loading?<div className="page">Memuat…</div>:<>

      {/* ── Revisi #53: Daily execution ── */}
      <div className="cards">
        <div className="stat blue"><strong>{fmt(exec?.totals?.target_today)}</strong><span>Target hari ini</span></div>
        <div className="stat green"><strong>{fmt(exec?.totals?.realised_today)}</strong><span>Realisasi hari ini</span></div>
        <div className={'stat '+(exec?.totals?.attainment_percent>=100?'green':'amber')}>
          <strong>{exec?.totals?.attainment_percent!=null?`${exec.totals.attainment_percent}%`:'—'}</strong><span>Pencapaian</span></div>
        <div className={'stat '+(exec?.totals?.qty_wip>0?'amber':'gray')}><strong>{fmt(exec?.totals?.qty_wip)}</strong><span>Total WIP</span></div>
        <div className={'stat '+(exec?.totals?.qty_reject>0?'red':'gray')}><strong>{fmt(exec?.totals?.qty_reject)}</strong><span>Reject</span></div>
      </div>

      {(unbalanced.length>0||issues.length>0)&&<div className="notice danger" style={{display:'flex',alignItems:'center',gap:'8px'}}>
        <AlertTriangle size={16}/> {unbalanced.length} artikel tidak seimbang, {issues.length} temuan rekonsiliasi kuantitas.
      </div>}

      <section className="panel">
        <h2>Target vs realisasi per order/artikel</h2>
        <div className="table-scroll"><table>
          <thead><tr><th>Order</th><th>Artikel</th><th>Rute</th><th>Target hari ini</th><th>Realisasi</th><th>Qty In</th><th>Done</th><th>Reject</th><th>WIP</th><th>Seimbang</th></tr></thead>
          <tbody>
            {exec?.rows?.map(r=><tr key={r.article_id}>
              <td>{r.order_id}</td>
              <td>{r.article_code} ({fmt(r.article_qty)} pcs)</td>
              <td className="muted">{r.production_route}</td>
              <td>{fmt(r.target_today)}</td>
              <td>{fmt(r.realised_today)}{r.attainment_percent!=null?` (${r.attainment_percent}%)`:''}</td>
              <td>{fmt(r.qty_in)}</td>
              <td>{fmt(r.qty_done)}</td>
              <td>{fmt(r.qty_reject)}</td>
              <td>{fmt(r.qty_wip)}</td>
              <td>{r.balanced?<CheckCircle2 size={14}/>:<AlertTriangle size={14} color="#c00"/>}</td>
            </tr>)}
            {!exec?.rows?.length&&<tr><td colSpan="10" className="empty">Belum ada artikel aktif.</td></tr>}
          </tbody>
        </table></div>
      </section>

      {issues.length>0&&<section className="panel">
        <h2>Temuan rekonsiliasi kuantitas</h2>
        <div className="table-scroll"><table>
          <thead><tr><th>Order</th><th>Artikel</th><th>Proses</th><th>Kode</th><th>Detail</th></tr></thead>
          <tbody>{issues.map((i,idx)=><tr key={idx}>
            <td>{i.order_id}</td><td>{i.article_code}</td><td>{i.process||'—'}</td><td>{i.code}</td><td>{i.detail}</td>
          </tr>)}</tbody>
        </table></div>
      </section>}

      {exec?.rows?.map(r=><section className="panel" key={'steps-'+r.article_id}>
        <h2>{r.order_id} · {r.article_code} — langkah proses</h2>
        <div className="table-scroll"><table>
          <thead><tr><th>#</th><th>Proses</th><th>Status</th><th>Qty In</th><th>Done</th><th>Reject</th><th>WIP</th><th>Jatuh tempo hari ini</th><th>PIC</th><th>ID Transaksi</th></tr></thead>
          <tbody>{r.steps.map(s=><tr key={s.process}>
            <td>{s.sequence}</td>
            <td>{s.process}</td>
            <td><span className={'pill '+(STATUS_TONE[s.status]||'gray')}>{s.status}</span></td>
            <td>{fmt(s.qty_in)}</td><td>{fmt(s.qty_done)}</td><td>{fmt(s.qty_reject)}</td>
            <td>{fmt(s.qty_wip)}</td>
            <td>{s.due_today?'Ya':'Tidak'}</td>
            <td>{s.pic_names.join(', ')||'—'}</td>
            <td className="muted">{s.movement_ids.join(', ')||'—'}</td>
          </tr>)}</tbody>
        </table></div>
        {r.steps.some(s=>s.reject_reasons.length>0)&&<p className="muted">Alasan reject: {r.steps.flatMap(s=>s.reject_reasons).join('; ')}</p>}
      </section>)}

      {/* ── Revisi #54: Handoff & capacity ── */}
      <section className="panel">
        <h2><ArrowRight size={16}/> Handoff antar proses</h2>
        <p className="muted">Qty dikirim tidak boleh ditimpa; selisih terhadap penerimaan ditampilkan apa adanya.</p>
        <div className="table-scroll"><table>
          <thead><tr><th>Order</th><th>Artikel</th><th>Dari</th><th>Ke</th><th>Qty Dikirim</th><th>Qty Diterima</th><th>Selisih</th><th>Sisa</th><th>Status</th><th>Pengirim</th><th>Penerima</th></tr></thead>
          <tbody>
            {handoff?.handoffs?.map((h,i)=><tr key={i}>
              <td>{h.order_id}</td><td>{h.article_code}</td>
              <td>{h.from_process}</td><td>{h.to_process}</td>
              <td>{fmt(h.qty_sent)}</td><td>{fmt(h.qty_received)}</td>
              <td className={h.discrepancy!==0?'strong':''}>{fmt(h.discrepancy)}</td>
              <td>{fmt(h.remaining_balance)}</td>
              <td><span className={'pill '+(HANDOFF_TONE[h.status]||'gray')}>{h.status}</span></td>
              <td>{h.sender_pics.join(', ')||'—'}</td>
              <td>{h.receiver_pics.join(', ')||'—'}</td>
            </tr>)}
            {!handoff?.handoffs?.length&&<tr><td colSpan="11" className="empty">Belum ada handoff.</td></tr>}
          </tbody>
        </table></div>
      </section>

      <section className="panel">
        <h2><Gauge size={16}/> Kapasitas terpakai vs tersedia</h2>
        <p className="muted">Beban terkomitmen dihitung dari WIP terbuka per proses, bukan angka ketikan.</p>
        <div className="table-scroll"><table>
          <thead><tr><th>Proses</th><th>Kapasitas/hari</th><th>Tersedia</th><th>Beban terkomitmen</th><th>Rencana load</th><th>Antrian</th><th>Utilisasi</th><th>Snapshot</th><th>Konflik</th></tr></thead>
          <tbody>
            {handoff?.capacity?.map(c=><tr key={c.process}>
              <td>{c.process}</td>
              <td>{fmt(c.capacity_per_day)}</td>
              <td>{fmt(c.available_capacity)}</td>
              <td>{fmt(c.committed_load)}</td>
              <td>{fmt(c.planned_load)}</td>
              <td>{fmt(c.queue)}</td>
              <td className={c.conflict?'strong':''}>{c.utilization_percent!=null?`${c.utilization_percent}%`:'—'}</td>
              <td className="muted">{c.snapshot_date||'tidak ada'} {c.is_stale?'(kedaluwarsa)':''}</td>
              <td>{c.conflict?<AlertTriangle size={14} color="#c00"/>:'—'}</td>
            </tr>)}
            {!handoff?.capacity?.length&&<tr><td colSpan="9" className="empty">Belum ada data kapasitas.</td></tr>}
          </tbody>
        </table></div>
        <p className="muted">Kapasitas/hari per proses (pcs) · <strong>{handoff?.summary?.bottleneck_process||'—'}</strong> adalah bottleneck saat ini.</p>
      </section>

      {followUps.length>0&&<div className="notice danger">
        <AlertTriangle size={16}/> Tindak lanjut otomatis: {followUps.map(f=>f.detail).join(' · ')}
      </div>}

      {/* ── Revisi #57: BOM fisik ── */}
      <section className="panel">
        <h2>Pemakaian BOM fisik vs rencana</h2>
        <p className="muted">Siti mencatat pemakaian fisik; kolom biaya bersifat referensi read-only dan tidak dapat diisi dari halaman ini.</p>
        <div className="table-scroll"><table>
          <thead><tr><th>Artikel</th><th>Material</th><th>Satuan</th><th>Qty/pcs</th><th>Rencana</th><th>Fisik</th><th>Selisih</th><th>%</th><th>Status</th><th>Biaya rencana</th><th>Biaya aktual</th></tr></thead>
          <tbody>
            {bom?.rows?.map(r=><tr key={r.bom_item_id}>
              <td>{r.article_code}</td><td>{r.material_name}</td><td>{r.unit}</td>
              <td>{fmt(r.qty_per_unit)}</td>
              <td>{fmt(r.planned_qty)}</td><td>{fmt(r.actual_qty)}</td>
              <td className={r.difference_qty!==0?'strong':''}>{fmt(r.difference_qty)}</td>
              <td>{r.variance_percent!=null?`${r.variance_percent}%`:'—'}</td>
              <td><span className={'pill '+(USAGE_TONE[r.status]||'gray')}>{r.status}</span></td>
              <td className="muted">{fmtMoney(r.planned_cost)}</td>
              <td className="muted">{fmtMoney(r.actual_cost)}</td>
            </tr>)}
            {!bom?.rows?.length&&<tr><td colSpan="11" className="empty">Belum ada item BOM.</td></tr>}
          </tbody>
        </table></div>
        {bom?.summary&&<p className="muted">
          Rencana {fmt(bom.summary.planned_qty)} · Fisik {fmt(bom.summary.actual_qty)} ·
          Selisih {fmt(bom.summary.difference_qty)} · {bom.summary.over_usage_items} item melebihi rencana.
        </p>}
      </section>

    </>}
  </div>
}
