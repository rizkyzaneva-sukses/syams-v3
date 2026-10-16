import React,{useCallback,useEffect,useState} from 'react';
import {Link,useOutletContext} from 'react-router-dom';
import {api} from '../api';
import {PRIORITY_FILTERS,boardQuery,invoiceTone} from '../control';
import OrderPanel,{Chip} from '../components/OrderPanel';

/* Control System — papan 15 tahap per order, sama dengan tab CONTROL SYSTEM di sheet lama.
   Cara pakai tim: klik baris order → tombol besar "Selesai" untuk tahap sekarang, atau
   "Ada masalah" bila terhambat. Status PROGRES/PERHATIAN/URGENT dihitung otomatis dari SLA. */

function Summary({s}){
  return <div className="cards cards-7">
    <div className="stat blue"><strong>{s.active_orders}</strong><span>Order aktif</span></div>
    <div className="stat blue"><strong>{s.active_qty}</strong><span>Active qty (pcs)</span></div>
    <div className="stat red"><strong>{s.urgent}</strong><span>Urgent</span></div>
    <div className="stat amber"><strong>{s.attention}</strong><span>Perhatian</span></div>
    <div className="stat gray"><strong>{s.progress}</strong><span>Progres</span></div>
    <div className="stat green"><strong>{s.done}</strong><span>Selesai</span></div>
    <div className="stat amber"><strong>{s.payment_outstanding}</strong><span>Belum lunas</span></div>
  </div>;
}

export default function ControlSystemPage(){
  const role=useOutletContext()?.me?.role;
  const [data,setData]=useState(null),[pics,setPics]=useState([]),[err,setErr]=useState('');
  const [pic,setPic]=useState('ALL'),[priority,setPriority]=useState('ALL'),[q,setQ]=useState('');
  const [open,setOpen]=useState(null);

  const load=useCallback(()=>api(boardQuery({pic,priority,q})).then(setData).catch(e=>setErr(e.message)),[pic,priority,q]);
  useEffect(()=>{const t=setTimeout(load,q?250:0);return()=>clearTimeout(t)},[load,q]);
  useEffect(()=>{api('/control/pics?active_only=true').then(setPics).catch(()=>{})},[]);

  const stages=data?.stages||[];
  return <div>
    {err&&<div className="notice danger" role="alert">{err}</div>}
    {data&&<Summary s={data.summary}/>}
    <div className="filter-bar">
      <input className="search-bar" placeholder="Cari order, buyer, atau article…" value={q} onChange={e=>setQ(e.target.value)} aria-label="Cari"/>
      <label className="inline-field">PIC <select value={pic} onChange={e=>setPic(e.target.value)}><option value="ALL">Semua</option>{pics.map(p=><option key={p.id} value={p.name}>{p.name}</option>)}</select></label>
      <div className="seg" role="group" aria-label="Filter prioritas">{PRIORITY_FILTERS.map(([key,label])=><button key={key} type="button" className={priority===key?'on':''} onClick={()=>setPriority(key)}>{label}</button>)}</div>
      <button className="btn" onClick={load}>Muat ulang</button>
    </div>
    <div className="legend"><span className="stage-chip st-green">SELESAI</span><span className="stage-chip st-plain">PROGRES</span><span className="stage-chip st-amber">PERHATIAN</span><span className="stage-chip st-red">URGENT</span><span className="stage-chip st-muted">-</span><small>"-" = tahap tidak dipakai. PERHATIAN/URGENT dihitung otomatis dari SLA tiap tahap.</small></div>
    <section className="panel flush"><div className="table-scroll control-scroll"><table className="control-table">
      <thead><tr><th>Prioritas</th><th>Order ID</th><th>Buyer</th><th>Article</th><th>Jenis</th><th>Qty</th><th>Extra</th><th>Deadline</th>{stages.map(s=><th key={s.code} className="stage-th">{s.label}</th>)}<th>Invoice</th><th>Bayar</th><th>Problem / block</th><th>Next action</th><th>PIC</th></tr></thead>
      <tbody>{(data?.rows||[]).map(r=><tr key={r.order_id} className={'control-row '+r.priority.toLowerCase()} onClick={()=>setOpen(r.order_id)} tabIndex={0} onKeyDown={e=>{if(e.key==='Enter')setOpen(r.order_id)}}>
        <td><span className={'badge '+(r.priority==='URGENT'?'red':r.priority==='PERHATIAN'?'amber':r.priority==='SELESAI'?'green':'gray')}>{r.priority}</span></td>
        <td><Link to={'/orders/'+r.order_id} onClick={e=>e.stopPropagation()}>{r.order_id}</Link></td>
        <td>{r.buyer}</td><td>{r.articles.join(', ')}</td><td>{r.garment_types.join(', ')||'-'}</td>
        <td>{r.total_qty}</td><td>{r.extra_size?r.extra_size+' ('+r.extra_total+')':'-'}</td><td>{r.deadline||'-'}</td>
        {r.stages.map(s=><td key={s.code} className="stage-td"><Chip stage={s}/></td>)}
        <td><span className={'badge '+invoiceTone(r.invoice_status)}>{r.invoice_status}</span></td>
        <td><span className={'badge '+(r.payment==='LUNAS'?'green':'amber')}>{r.payment}</span></td>
        <td className="wrap">{r.problem||'-'}</td><td className="wrap">{r.next_action||'-'}</td><td>{r.pic||'-'}</td>
      </tr>)}
      {data&&!data.rows.length&&<tr><td colSpan={stages.length+12} className="empty-cell">Belum ada order. Order muncul di sini setelah PO diterima Cecep.</td></tr>}
      </tbody></table></div></section>
    {open&&<OrderPanel orderId={open} role={role} pics={pics} onClose={()=>setOpen(null)} onChanged={load}/>}
  </div>;
}
