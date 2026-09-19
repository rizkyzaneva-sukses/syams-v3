import React,{useEffect,useState} from 'react';
import {api} from '../api';
import {ClipboardList,Search,RefreshCw} from 'lucide-react';

/* Audit trail (revisi #77 CEO-I-008 + INT-ORDER-001 poin 10).
   Setiap perubahan status harus bisa ditelusuri: aktor, waktu, modul sumber,
   Order ID terkait, status lama -> baru, dan alasan bila dikoreksi. Kolom itu
   ada di API sejak migration 0017; halaman ini yang menampilkannya. */

const toneOf=action=>{
  const a=(action||'').toUpperCase();
  if(a.startsWith('DENIED')||a==='DELETE'||a==='REJECT') return 'red';
  if(a==='CREATE'||a.startsWith('CEO_')||a==='APPROVE') return 'green';
  if(a.startsWith('STATUS')||a==='UPDATE'||a.startsWith('OPERATOR')) return 'blue';
  return 'gray';
};

export default function AuditLogPage(){
  const [logs,setLogs]=useState([]),[err,setErr]=useState(''),[busy,setBusy]=useState(false);
  const [q,setQ]=useState(''),[onlyTransition,setOnlyTransition]=useState(false),[onlyDenied,setOnlyDenied]=useState(false);

  async function load(){
    setBusy(true);
    try{setLogs(await api('/audit-log?limit=500'));setErr('')}
    catch(e){setErr(e.message)}
    finally{setBusy(false)}
  }
  useEffect(()=>{load()},[]);

  const hasTransition=l=>Boolean(l.previous_status||l.new_status);
  const isDenied=l=>(l.action||'').toUpperCase().startsWith('DENIED');

  const shown=logs.filter(l=>{
    if(onlyTransition&&!hasTransition(l)) return false;
    if(onlyDenied&&!isDenied(l)) return false;
    if(!q) return true;
    const s=q.toLowerCase();
    return [l.entity,l.user,l.action,l.detail,l.source_module,l.order_id,l.previous_status,l.new_status,l.reason]
      .some(v=>(v||'').toLowerCase().includes(s));
  });

  const transitions=logs.filter(hasTransition).length;
  const denied=logs.filter(isDenied).length;

  return <div className="page">
    <div className="page-title">
      <div>
        <h1>Audit Log</h1>
        <p>{shown.length} dari {logs.length} aktivitas tercatat · {transitions} transisi status · {denied} tindakan ditolak</p>
      </div>
      <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
    </div>
    {err&&<div className="notice danger" role="alert">{err}</div>}

    <div className="filter-bar">
      <div className="search-bar" style={{flex:1}}>
        <Search size={16}/>
        <input aria-label="Cari audit log" placeholder="Cari entity, user, action, Order ID, modul, atau alasan..." value={q} onChange={e=>setQ(e.target.value)}/>
      </div>
      <button className={'btn'+(onlyTransition?' primary':'')} aria-pressed={onlyTransition} onClick={()=>setOnlyTransition(v=>!v)}>Hanya transisi ({transitions})</button>
      <button className={'btn'+(onlyDenied?' primary':'')} aria-pressed={onlyDenied} onClick={()=>setOnlyDenied(v=>!v)}>Hanya ditolak ({denied})</button>
    </div>

    <div className="table-scroll"><table><thead><tr>
      <th>Waktu</th><th>Actor</th><th>Action</th><th>Modul sumber</th><th>Entity</th><th>Order ID</th>
      <th>Transisi status</th><th>Alasan</th><th>Detail</th>
    </tr></thead>
    <tbody>{shown.map(l=><tr key={l.id}>
      <td style={{fontSize:'12px'}}>{l.created_at?new Date(l.created_at).toLocaleString('id-ID'):'—'}</td>
      <td><b>{l.user}</b></td>
      <td><span className={'badge '+toneOf(l.action)}>{l.action}</span></td>
      <td>{l.source_module?<span className="badge gray">{l.source_module}</span>:'—'}</td>
      <td>{l.entity}{l.entity_id!=null&&<small> #{l.entity_id}</small>}</td>
      <td>{l.order_id||'—'}</td>
      <td>{hasTransition(l)
        ? <span className="badge blue">{l.previous_status||'—'} → {l.new_status||'—'}</span>
        : <small style={{color:'#94a3b8'}}>bukan perubahan status</small>}</td>
      <td className="td-sm" style={{maxWidth:'220px'}}>{l.reason||'—'}</td>
      <td className="td-sm" style={{maxWidth:'250px'}}>{l.detail||'—'}</td>
    </tr>)}
    {shown.length===0&&<tr><td colSpan={9} className="empty">
      {logs.length?'Tidak ada log yang cocok dengan filter.':'Belum ada aktivitas tercatat.'}
    </td></tr>}</tbody></table></div>
  </div>;
}
