import React,{useEffect,useMemo,useState} from 'react';
import {Link,useSearchParams} from 'react-router-dom';
import {api} from '../api';
import {RefreshCw,ShieldAlert,ListChecks,Lock} from 'lucide-react';

/* Revisi #35 (SMP-F-005) & #37 (SMP-F-007) — MY SAMPLE TASKS.
   Task berasal otomatis dari routing order/article yang eligible; SLA dari
   Master; lifecycle OPEN → START/IN_PROGRESS → UPDATE → INSPECTION →
   SUBMIT_RESULT → DONE. Task tidak DONE tanpa sample version submitted dan
   seluruh required evidence.

   BATAS AKSES: keputusan buyer (BUYER_APPROVE/BUYER_REJECT) TIDAK ditawarkan
   di sini — pemiliknya CMO_MANAGER. Exception milik owner lain hanya bisa
   dilihat/dieskalasi; resolve/override bukan milik Sample PIC. */

export const STAGES=['OPEN','IN_PROGRESS','UPDATE','INSPECTION','SUBMIT_RESULT','DONE'];

/* Aksi yang boleh ditawarkan ke Sample PIC. `BUYER_APPROVE`/`BUYER_REJECT`
   sengaja tidak ada; kalau backend tidak mengirimnya, UI tetap tidak
   mengarang aksi keputusan. */
export function allowedActions(row){
  const allowed=(row&&row.allowed_actions)||[];
  return allowed.filter(a=>!['BUYER_APPROVE','BUYER_REJECT','APPROVE','REJECT'].includes(a));
}

/* Satu-satunya sumber kebenaran "boleh DONE" adalah evidence + version dari
   backend, bukan tombol di UI. */
export function blockersFor(row){
  const out=[];
  if(!row) return out;
  if(!row.eligible) out.push(row.eligibility_reason||'Order/Article tidak eligible');
  if(row.evidence&&!row.evidence.complete) out.push(`Bukti kurang: ${(row.evidence.missing||[]).join(', ')}`);
  const reqs=row.requirements||{};
  for(const [key,v] of Object.entries(reqs)) if(v&&!v.ok) out.push(v.label);
  if(row.blocker) out.push(`${row.blocker} (owner ${row.blocker_owner||'—'})`);
  return [...new Set(out)];
}

export function LifecycleTrack({stage}){
  const active=stage==='WORK_REVISION'?'SUBMIT_RESULT':stage;
  const idx=STAGES.indexOf(active);
  return <div className="flow-list">
    {STAGES.map((s,i)=><div className="flow-row" key={s}>
      <b style={{background:i<idx?'#16a34a':i===idx?'#2563eb':'#cbd5e1'}}>{i+1}</b>
      <span style={{fontWeight:i===idx?'700':'400'}}>{s}{i===idx?' — posisi sekarang':''}</span>
    </div>)}
  </div>;
}

export function TaskCard({row}){
  const blockers=blockersFor(row);
  const actions=allowedActions(row);
  const decided=row.buyer_decision&&row.buyer_decision.decided;
  return <section className="panel">
    <div className="panel-head">
      <h2>{row.sample_id?`SMP-${row.sample_id}`:'SMP-BARU'} · {row.article_code||'—'} v{row.sample_version||1}</h2>
      <span>
        <span className="badge blue">{row.stage}</span>{' '}
        <span className="badge gray">{row.priority||'NORMAL'}</span>
      </span>
    </div>
    <div className="grid two">
      <div>
        <p><b>Order:</b> {row.order_id?<Link to={'/orders/'+row.order_id}>{row.order_id}</Link>:'—'}
          {' · '}<b>Article ID:</b> {row.article_id??'—'}{' · '}<b>Buyer:</b> {row.buyer||'—'}</p>
        <p><b>Status pekerjaan:</b> {row.sample_work_status} · <b>Owner:</b> {row.owner}</p>
        <p><b>Next action:</b> {row.next_action}</p>
        <p><b>SLA / due:</b> <span className={'badge '+((row.sla&&row.sla.state==='OVERDUE')?'red':'green')}>
          {(row.sla&&row.sla.label)||'—'}</span> {(row.sla&&row.sla.due)?`· ${row.sla.due}`:''}</p>
        <p><b>Evidence:</b> <span className={'badge '+(row.evidence&&row.evidence.complete?'green':'amber')}>
          {row.evidence?`${row.evidence.uploaded}/${row.evidence.required}`:'—'}</span></p>
        <p><b>Handoff berikutnya:</b> <small>{row.handoff}</small></p>
        <p><b>Updated:</b> <small>{row.updated_at?new Date(row.updated_at+'Z').toLocaleString('id-ID'):'—'}</small></p>
      </div>
      <div>
        <LifecycleTrack stage={row.stage}/>
      </div>
    </div>

    {row.exceptions&&row.exceptions.length>0&&<div className="notice danger">
      <ShieldAlert size={15}/> <b>Exception sample</b>
      <ul>{row.exceptions.map(e=><li key={e.exception_id}>
        [{e.severity}] {e.problem} — owner {e.owner}
        {e.next_action?` · next: ${e.next_action}`:''}
        {' · '}<span className="badge gray">{e.can_edit?'boleh update bukti/aksi':'lihat saja'}</span>
        {e.can_escalate&&<> <span className="badge amber">bisa dieskalasi</span></>}
        {!e.can_resolve&&<> <span className="badge gray">resolve bukan hak Sample PIC</span></>}
      </li>)}</ul>
    </div>}

    {blockers.length>0&&<div className="notice amber">
      <ListChecks size={15}/> <b>Prasyarat belum lengkap</b>
      <ul>{blockers.map((b,i)=><li key={i}>{b}</li>)}</ul>
      <small>Task tidak bisa DONE sebelum sample version submitted dan seluruh required evidence ada.</small>
    </div>}

    <div className="notice info">
      <Lock size={15}/> <b>Aksi yang tersedia untuk Sample PIC:</b>{' '}
      {actions.length?actions.map(a=><span className="badge blue" key={a}>{a}</span>):'—'}
      {' '}<b>Keputusan buyer APPROVED/REJECTED bukan aksi halaman ini.</b>
      {decided&&<> Sudah dicatat CMO_MANAGER: <span className="badge green">{row.buyer_decision.status}</span>
        {row.buyer_decision.reason?` — ${row.buyer_decision.reason}`:''}</>}
      {!decided&&<> Menunggu <b>CMO_MANAGER</b> mencatat keputusan buyer.</>}
    </div>
  </section>;
}

export default function SampleTaskPage(){
  const [params,setParams]=useSearchParams();
  const [data,setData]=useState(null),[err,setErr]=useState(''),[busy,setBusy]=useState(false);
  const orderFilter=params.get('order_id')||'';
  const stageFilter=params.get('stage')||'';

  async function load(){
    setBusy(true);
    try{
      const q=new URLSearchParams();
      if(orderFilter) q.set('order_id',orderFilter);
      if(stageFilter) q.set('status',stageFilter);
      setData(await api('/sample/my-tasks'+(q.toString()?'?'+q.toString():'')));
      setErr('');
    }catch(e){setErr(e.message)}finally{setBusy(false)}
  }
  useEffect(()=>{load()},[orderFilter,stageFilter]);

  const tasks=useMemo(()=>data?data.tasks||[]:[],[data]);
  if(err&&!data) return <div className="page"><div className="notice danger">{err}</div></div>;
  if(!data) return <div className="page">Memuat tugas sample...</div>;

  const access=data.access||{};
  return <div className="page">
    <div className="page-title">
      <div>
        <h1>My Sample Tasks</h1>
        <p>Task sample otomatis dari routing order/article. SLA dari Master — bukan input bebas Sample PIC.</p>
      </div>
      <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
    </div>

    <div className="cards">
      <div className="stat blue"><strong>{data.my_sample_tasks||0}</strong><span>Task sample aktif</span></div>
      <div className="stat amber"><strong>{data.create_sample_tasks||0}</strong><span>Perlu CREATE SAMPLE</span></div>
      <div className="stat gray"><strong>{data.blocked||0}</strong><span>Terblokir</span></div>
      <div className={'stat '+(data.overdue?'red':'green')}><strong>{data.overdue||0}</strong><span>Lewat SLA</span></div>
    </div>

    <div className="notice info">
      {data.sla_source}. Lifecycle: {STAGES.join(' → ')}.
      Task tidak pernah DONE tanpa sample version submitted dan seluruh required evidence.
    </div>

    <section className="panel">
      <div className="panel-head"><h2>Filter</h2><span>{tasks.length} tugas ditampilkan</span></div>
      <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
        <input placeholder="Order ID" defaultValue={orderFilter}
          onKeyDown={e=>{if(e.key==='Enter') setParams(p=>{const n=new URLSearchParams(p);e.target.value?n.set('order_id',e.target.value):n.delete('order_id');return n})}}/>
        <select value={stageFilter} onChange={e=>setParams(p=>{const n=new URLSearchParams(p);e.target.value?n.set('stage',e.target.value):n.delete('stage');return n})}>
          <option value="">Semua tahap</option>
          {STAGES.map(s=><option key={s} value={s}>{s}</option>)}
        </select>
        <button className="btn" onClick={()=>setParams(new URLSearchParams())}>Reset</button>
      </div>
    </section>

    {tasks.length===0&&<div className="notice success">Tidak ada tugas sample yang cocok dengan filter.</div>}
    {tasks.map(row=><TaskCard key={row.task_id+r'+'+row.stage} row={row}/>)}

    <section className="panel">
      <div className="panel-head"><h2>Batas akses Sample PIC</h2><span>ditegakkan server-side</span></div>
      <p><b>Boleh:</b> {(access.can||[]).map(a=><span className="badge blue" key={a}>{a}</span>)}</p>
      <p><b>Tidak boleh:</b> {(access.cannot||[]).map(a=><span className="badge gray" key={a}>{a}</span>)}</p>
      <p><small>{access.note}</small></p>
    </section>
  </div>;
}
