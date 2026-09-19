import React,{useCallback,useEffect,useMemo,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {useRole} from '../components/Access';
import {AlertTriangle,RefreshCw,Clock,ChevronRight,Activity} from 'lucide-react';

/* Revisi #13 / #14 poin 2 — MORNING PRIORITY (CMO Manager).
   ACTION-FIRST: ini antrean keputusan Cecep, bukan dashboard analitik.
   Urutan seksi mengikuti blueprint terkunci:
     prioritas artikel & kapasitas → PO/draft order menunggu review →
     quotation menunggu approval → sample decision → SPK siap Release to COO →
     exception → handoff berikutnya.
   Setiap baris WAJIB membuka Order terkait (order_link) atau dokumen sumbernya
   (source_link) kalau Order-nya belum ada — mis. PO intake yang masih DRAFT. */

const SEVERITY_BADGE={RED:'badge red',YELLOW:'badge amber',GREEN:'badge green',GRAY:'badge gray'};
const SLA_LABEL={
  OVERDUE:'Lewat SLA',DUE_TODAY:'Jatuh tempo hari ini',DUE_3_HARI:'≤ 3 hari',
  DUE_7_HARI:'≤ 7 hari',AMAN:'Aman',TANPA_DUE:'Tanpa due',
};
const SLA_BADGE={
  OVERDUE:'badge red',DUE_TODAY:'badge amber',DUE_3_HARI:'badge amber',
  DUE_7_HARI:'badge blue',AMAN:'badge green',TANPA_DUE:'badge gray',
};
/* Kapasitas dinaikkan terakhir kali: Stok harus aman sebelum cutting. */
const CAPACITY_TONE=(pct)=>pct==null?'gray':pct>=100?'red':pct>=85?'amber':'green';

function fmtDate(v){
  if(!v) return '—';
  const d=new Date(String(v).length<=10?v+'T00:00:00':v);
  if(Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleDateString('id-ID',{day:'2-digit',month:'short',year:'numeric'});
}
function fmtDateTime(v){
  if(!v) return '—';
  const d=new Date(String(v).endsWith('Z')?v:v+'Z');
  if(Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleString('id-ID',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});
}
function fmtNum(v){
  if(v==null||v==='') return '—';
  const n=Number(v);
  return Number.isNaN(n)?String(v):n.toLocaleString('id-ID');
}
function ownerTone(owner){
  const o=String(owner||'').toUpperCase();
  if(o.startsWith('CMO_MANAGER')) return 'badge blue';
  if(o.startsWith('CMO_SUPPORT')) return 'badge gray';
  if(o.startsWith('COO')) return 'badge amber';
  if(o.startsWith('CFO')) return 'badge green';
  return 'badge gray';
}
function sectionShell(row){
  if(row.order_id) return '/orders/'+row.order_id;
  return row.source_link||row.open_target||null;
}

/* Satu baris antrean. Selalu memberi jalan keluar: buka Order, atau buka
   dokumen sumber kalau Order belum ada (PO draft/exception tanpa order). */
function QueueRow({row,index}){
  const target=sectionShell(row);
  const label=row.order_id?('Order '+row.order_id):(row.open_target?'Buka '+labelForTarget(row):null);
  return <tr>
    <td><b>{row.task_id}</b></td>
    <td>{row.buyer||'—'}{row.customer_id?<small style={{display:'block',color:'#94a3b8'}}>buyer #{row.customer_id}</small>:null}</td>
    <td>{target
      ? <Link to={target} style={{fontWeight:600}}>{label}</Link>
      : <span style={{color:'#94a3b8'}}>Tanpa Order</span>}</td>
    <td>{row.article_code?<>{row.article_code}{row.article_qty?<small style={{display:'block',color:'#94a3b8'}}>{fmtNum(row.article_qty)} pcs</small>:null}</>:row.articles||'—'}</td>
    <td><span className="badge gray">{row.status||'—'}</span></td>
    <td className="td-sm" title={row.gate||''}>{row.gate||'—'}</td>
    <td className="td-sm" title={row.evidence||''}>{row.evidence||'—'}</td>
    <td className="td-sm">{row.next_action||'—'}</td>
    <td><span className={ownerTone(row.owner)}>{row.owner||'—'}</span></td>
    <td>{fmtDate(row.due)}
      {row.sla?<small style={{display:'block'}}><span className={SLA_BADGE[row.sla]||'badge gray'}>{SLA_LABEL[row.sla]||row.sla}{row.sla_days!=null&&row.sla_days<0?' ('+row.sla_days+'h)':''}</span></small>:null}
    </td>
    <td className="td-sm">{row.handoff||'—'}</td>
    <td><small>{fmtDateTime(row.updated_at)}</small></td>
  </tr>;
}

function labelForTarget(row){
  const path=row.open_target||row.source_link||'';
  if(path.startsWith('/cmo/po-inbox')) return 'PO Intake';
  if(path.startsWith('/cmo/quotations')) return 'Quotation';
  if(path.startsWith('/cmo/samples')) return 'Sample / PPM';
  if(path.startsWith('/cmo/spk')) return 'SPK';
  if(path.startsWith('/cmo/exception-center')) return 'Exception Center';
  if(path.startsWith('/cmo/buyer-crm')) return 'Buyer CRM';
  if(path.startsWith('/coo/production')) return 'Production (COO)';
  return 'dokumen sumber';
}

function QueueSection({queue,pageSize}){
  const [showAll,setShowAll]=useState(false);
  const rows=queue.rows||[];
  const visible=showAll?rows:rows.slice(0,pageSize);
  const explore=rows.filter(r=>r.severity==='RED').length;
  return <section className="panel" id={'queue-'+queue.key}>
    <div className="panel-head">
      <h2>{queue.label}{explore?<span className="badge red" style={{marginLeft:8}}>{explore} kritis</span>:null}</h2>
      <span style={{color:'#64748b',fontSize:13}}>
        <b style={{fontSize:18,color:'#10203d',marginRight:6}}>{rows.length}</b>baris · owner {queue.owner}
      </span>
    </div>
    <p style={{fontSize:12,color:'#64748b',margin:'2px 0 10px'}}>Handoff berikutnya: {queue.handoff}</p>
    {rows.length?<>
      <div className="table-scroll"><table>
        <thead><tr>
          <th>Task ID</th><th>Buyer</th><th>Order</th><th>Article</th>
          <th>Status</th><th>Evidence / Gate</th><th>Bukti</th><th>Next Action</th>
          <th>Owner</th><th>Due / SLA</th><th>Handoff berikutnya</th><th>Updated</th>
        </tr></thead>
        <tbody>{visible.map((row,i)=><QueueRow key={row.task_id} row={row} index={i}/>)}</tbody>
      </table></div>
      {rows.length>pageSize?<button className="btn sm" style={{marginTop:10}} onClick={()=>setShowAll(v=>!v)}>
        {showAll?'Tampilkan lebih sedikit':'Tampilkan semua ('+rows.length+')'}
      </button>:null}
    </>:<p className="empty">Tidak ada item menunggu di antrean ini.</p>}
  </section>;
}

function CapacitySection({capacity,bottleneck}){
  if(!capacity) return null;
  const procs=capacity.processes||[];
  return <section className="panel">
    <div className="panel-head">
      <h2><Activity size={16} style={{verticalAlign:-2,marginRight:6}}/>Kapasitas &amp; Bottleneck</h2>
      <span style={{fontSize:12,color:'#64748b'}}>snapshot {fmtDate(capacity.as_of)} · read-only (milik COO)</span>
    </div>
    <div style={{display:'flex',gap:18,flexWrap:'wrap',marginBottom:12}}>
      <div className="mini"><small>Kapasitas</small><b>{fmtNum(capacity.total_capacity)}</b></div>
      <div className="mini"><small>Beban terencana</small><b>{fmtNum(capacity.total_planned_load)}</b></div>
      <div className="mini"><small>WIP</small><b>{fmtNum(capacity.total_wip)}</b></div>
      <div className="mini"><small>Utilisasi</small><b>{capacity.utilization_percent==null?'—':capacity.utilization_percent+'%'}</b></div>
    </div>
    {procs.length?<div className="table-scroll"><table>
      <thead><tr><th>Proses</th><th>Kapasitas</th><th>Beban</th><th>WIP</th><th>Utilisasi</th><th>Status</th></tr></thead>
      <tbody>{procs.map(p=><tr key={p.process}>
        <td><b>{p.process}</b></td>
        <td>{fmtNum(p.capacity)}</td>
        <td>{fmtNum(p.planned_load)}</td>
        <td>{fmtNum(p.wip)}</td>
        <td>{p.utilization_percent==null?'—':p.utilization_percent+'%'}</td>
        <td><span className={'badge '+CAPACITY_TONE(p.utilization_percent)}>
          {p.bottleneck?'BOTTLENECK +'+fmtNum(p.overload_qty):p.utilization_percent>=85?'Mendekati penuh':'Aman'}
        </span></td>
      </tr>)}</tbody>
    </table></div>:<p className="empty">{capacity.note}</p>}
    <p style={{fontSize:12,color:'#64748b',marginTop:8}}>
      Bottleneck: {bottleneck&&bottleneck.detail?bottleneck.detail:capacity.note}
    </p>
  </section>;
}

export default function CMOPriorityV2Page(){
  const role=useRole();
  const [data,setData]=useState(null);
  const [err,setErr]=useState('');
  const [busy,setBusy]=useState(false);
  const [pageSize,setPageSize]=useState(8);

  const load=useCallback(async()=>{
    setBusy(true);
    try{setData(await api('/cmo/manager-priority'));setErr('')}
    catch(e){setErr(e.message||'Gagal memuat Morning Priority')}
    finally{setBusy(false)}
  },[]);
  useEffect(()=>{load()},[load]);

  const queues=data?.queues||[];
  const summary=data?.summary||{};
  const total=data?.total_actions||0;

  const ordered=useMemo(()=>queues,[queues]);

  if(err&&!data) return <div className="page"><div className="notice danger">{err}</div>
    <button className="btn" onClick={load}><RefreshCw size={15}/> Coba lagi</button></div>;
  if(!data) return <div className="page">Memuat Morning Priority…</div>;

  return <div className="page">
    <div className="page-title">
      <div>
        <h1>Morning Priority — CMO Manager</h1>
        <p>Antrean keputusan action-first Cecep. Setiap baris membuka Order terkait.</p>
      </div>
      <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/>{busy?'Memuat…':'Muat ulang'}</button>
    </div>

    <div className="cards">
      <div className={'stat '+(total?'amber':'green')}><strong>{total}</strong><span>Total baris antrean</span></div>
      <div className={'stat '+(summary.overdue?'red':'green')}><strong>{summary.overdue||0}</strong><span>Lewat SLA</span></div>
      <div className={'stat '+(summary.due_today?'amber':'blue')}><strong>{summary.due_today||0}</strong><span>Jatuh tempo hari ini</span></div>
      <div className="stat blue"><strong>{summary.must_decide_now||0}</strong><span>Keputusan Cecep ≤ 3 hari</span></div>
    </div>

    <div className="notice info">
      Hanya keputusan komersial yang menjadi kewenangan CMO Manager. Exception produksi,
      keuangan, dan operasional tetap milik COO, CFO, dan CEO — dan tidak ditampilkan di sini.
      {data.as_of?<> Snapshot {fmtDateTime(data.as_of)}.</>:null}
    </div>

    {err?<div className="notice danger">Muat ulang gagal: {err}</div>:null}

    {summary.overdue?<div className="notice danger">
      <AlertTriangle size={14} style={{verticalAlign:-2,marginRight:6}}/>
      {summary.overdue} baris sudah melewati SLA: {(summary.overdue_tasks||[]).join(', ')}
    </div>:null}

    {total===0?<div className="notice success">Tidak ada keputusan komersial yang menunggu hari ini.</div>:null}

    <CapacitySection capacity={data.capacity} bottleneck={data.bottleneck}/>

    {ordered.map(q=><QueueSection key={q.key} queue={q} pageSize={pageSize}/>)}

    <section className="panel">
      <div className="panel-head"><h2>Master Control — Prioritas Bisnis</h2><span className="badge gray">read-only</span></div>
      <p style={{fontSize:13,color:'#475569',margin:'0 0 8px'}}>{data.master_control?.note}</p>
      <p style={{fontSize:12,color:'#64748b',margin:0}}>
        Kewenangan CMO: {(data.authority?.held||[]).join(', ')}. Di luar kewenangan:{' '}
        {(data.authority?.not_held||[]).join('; ')}.
      </p>
    </section>
  </div>;
}
