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
  /* Bukti yang jenisnya tidak diketahui tidak dihitung terpenuhi — sebutkan
     apa adanya supaya tidak terlihat seperti "sudah lengkap". */
  if(row.evidence_unclassified&&row.evidence_unclassified.length)
    out.push(`Bukti belum berjenis (tidak dihitung): ${row.evidence_unclassified.join(', ')}`);
  if(row.blocker) out.push(`${row.blocker} (owner ${row.blocker_owner||'—'})`);
  return [...new Set(out)];
}

/* Sumber data yang dipakai server. Kalau ada jalur heuristik yang aktif, UI
   mengatakannya — supaya angka di layar tidak menyamar sebagai data pasti. */
export function dataSourceNote(data){
  const src=(data&&data.data_source)||{};
  const active=src.heuristics_active||[];
  return {sources:src.sources||{},active,persisted:(data&&data.task_persistence)||null};
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

export function TaskCard({row,onAction,busy}){
  const blockers=blockersFor(row);
  const actions=allowedActions(row);
  const decided=row.buyer_decision&&row.buyer_decision.decided;
  /* Aksi yang benar-benar bisa DIJALANKAN: hanya kalau task sudah tersimpan
     (`task_db_id`) dan server tidak memblokirnya. `blocked_actions` dikirim
     backend beserta prasyarat yang kurang — UI tidak menebak. */
  const canRun=(row.task_db_id!=null&&typeof onAction==='function')?actions:[];
  const hasTask=row.task_db_id!=null;
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
          {row.evidence?`${row.evidence.uploaded}/${row.evidence.required}`:'—'}</span>
          {row.evidence_kind_source?<> <small>jenis bukti: {row.evidence_kind_source}</small></>:null}</p>
        {row.submitted_at&&<p><b>Submitted:</b> <small>{row.submitted_at}</small>
          {row.submitted_at_source?<> · <span className="badge gray">{row.submitted_at_source}</span></>:null}</p>}
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
        {e.sample_version?` · versi ${e.sample_version}`:''}
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
        {row.buyer_decision.reason?` — ${row.buyer_decision.reason}`:''}
        {row.buyer_decision.source?<> <small>(sumber: {row.buyer_decision.source})</small></>:null}</>}
      {!decided&&<> Menunggu <b>CMO_MANAGER</b> mencatat keputusan buyer.</>}
    </div>

    {canRun.length>0&&<div className="notice info">
      <b>Jalankan pekerjaan</b>{' '}
      {canRun.map(a=><button className="btn" key={a} disabled={busy}
        onClick={()=>onAction(row,a)}>{a.replace(/_/g,' ')}</button>)}
      {hasTask&&<small> Setiap aksi tercatat di audit dengan tahap lama → tahap baru.</small>}
    </div>}
  </section>;
}

export default function SampleTaskPage(){
  const [params,setParams]=useSearchParams();
  const [data,setData]=useState(null),[err,setErr]=useState(''),[busy,setBusy]=useState(false);
  const [msg,setMsg]=useState('');
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

  /* Aksi pekerjaan dikirim ke endpoint task. `WORK_REVISION` wajib alasan —
     server menolaknya (422) kalau kosong, jadi UI menanyakannya lebih dulu. */
  async function runAction(row,action){
    let body={action};
    if(action==='WORK_REVISION'){
      const reason=window.prompt('Alasan revisi (wajib):');
      if(!reason||!reason.trim()) return;
      body.reason=reason.trim();
    }
    setBusy(true);
    try{
      const res=await api('/sample/tasks/'+row.task_db_id+'/actions',{method:'POST',body:JSON.stringify(body)});
      setMsg(`${action} berhasil — tahap sekarang ${res.stage}.`);
      setErr(''); await load();
    }catch(e){setErr(e.message); setMsg('')}finally{setBusy(false)}
  }

  const tasks=useMemo(()=>data?data.tasks||[]:[],[data]);
  if(err&&!data) return <div className="page"><div className="notice danger">{err}</div></div>;
  if(!data) return <div className="page">Memuat tugas sample...</div>;

  const access=data.access||{};
  const src=dataSourceNote(data);
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

    {msg&&<div className="notice success">{msg}</div>}
    {err&&<div className="notice danger">{err}</div>}

    <div className="notice info">
      {data.sla_source}. Lifecycle: {STAGES.join(' → ')}.
      Task tidak pernah DONE tanpa sample version submitted dan seluruh required evidence.
    </div>

    {/* Revisi #34: versi dibaca dari kolom, bukan urutan id. Kalau ada jalur
        heuristik yang masih dipakai, katakan — jangan diam. */}
    <section className="panel">
      <div className="panel-head"><h2>Sumber data</h2>
        <span>{src.active.length?`${src.active.length} jalur fallback aktif`:'semua eksplisit'}</span></div>
      <p><b>Versi sample:</b> <code>{src.sources.sample_version}</code></p>
      <p><b>Jenis bukti:</b> <code>{src.sources.evidence_kind}</code></p>
      <p><b>Ikatan exception:</b> <code>{src.sources.exception_link}</code></p>
      <p><b>Penyimpanan task:</b> <code>{src.sources.task_store}</code>
        {src.persisted&&src.persisted.persisted!=null?<> · <span className="badge green">
          {src.persisted.persisted} task tersimpan</span></>:null}</p>
      {src.active.length>0&&<div className="notice amber">
        <b>Fallback yang masih dipakai:</b> {src.active.map(a=><span className="badge amber" key={a}>{a}</span>)}
        <small> Angka dari jalur ini bukan data tersimpan.</small>
      </div>}
    </section>

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
    {tasks.map(row=><TaskCard key={row.task_id+'+'+row.stage} row={row} busy={busy} onAction={runAction}/>)}

    <section className="panel">
      <div className="panel-head"><h2>Batas akses Sample PIC</h2><span>ditegakkan server-side</span></div>
      <p><b>Boleh:</b> {(access.can||[]).map(a=><span className="badge blue" key={a}>{a}</span>)}</p>
      <p><b>Tidak boleh:</b> {(access.cannot||[]).map(a=><span className="badge gray" key={a}>{a}</span>)}</p>
      <p><small>{access.note}</small></p>
    </section>
  </div>;
}
