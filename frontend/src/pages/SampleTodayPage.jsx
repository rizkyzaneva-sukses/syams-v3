import React,{useEffect,useMemo,useState} from 'react';
import {Link} from 'react-router-dom';
import {api} from '../api';
import {RefreshCw,AlertTriangle,Clock,CheckCircle2,PlayCircle,Inbox} from 'lucide-react';

/* Revisi #31 (SMP-F-001) — LANDING SAMPLE TODAY (Sample PIC / Fahrul).
   Action-first: antrean kerja sample hari ini, bukan dashboard analisis.
   Lima bagian tetap sesuai blueprint: belum mulai, sedang dikerjakan,
   menunggu revisi, siap diserahkan, terlambat.

   BATAS AKSES (revisi #32): halaman ini TIDAK menawarkan APPROVE/REJECT.
   Keputusan buyer (BUYER_APPROVE/BUYER_REJECT) milik CMO_MANAGER dan hanya
   tampil sebagai informasi read-only. Tidak ada menu SPK, Production Queue,
   Purchasing, Finance, Delivery, atau Buyer Approval di sidebar Fahrul. */

export const SECTION_ICON={NOT_STARTED:Inbox,IN_PROGRESS:PlayCircle,WAITING_REVISION:AlertTriangle,READY_TO_HANDOFF:CheckCircle2,OVERDUE:Clock};

export function slaClass(state){
  if(state==='OVERDUE') return 'badge red';
  if(state==='DUE_TODAY') return 'badge amber';
  if(state==='DUE_SOON') return 'badge amber';
  if(state==='ON_TRACK') return 'badge green';
  return 'badge gray';
}

export function evidenceLabel(evidence){
  if(!evidence) return '—';
  const missing=(evidence.missing||[]).length;
  return missing?`${evidence.uploaded}/${evidence.required} · kurang ${missing}`:`${evidence.uploaded}/${evidence.required} lengkap`;
}

/* Kolom wajib setiap baris (revisi #31): Sample ID, Order ID, Article ID,
   version, prioritas, next action, SLA/due, evidence, blocker, owner, handoff. */
export function SampleRow({row}){
  const decided=row.buyer_decision&&row.buyer_decision.decided;
  return <tr>
    <td><b>{row.sample_id?`SMP-${row.sample_id}`:'—'}</b><br/><small>v{row.sample_version||1}</small></td>
    <td>{row.order_id?<Link to={'/orders/'+row.order_id}>{row.order_id}</Link>:'—'}</td>
    <td>{row.article_code||'—'}<br/><small>Article ID {row.article_id??'—'}</small></td>
    <td><span className={'badge '+(row.priority==='HIGH'?'red':'gray')}>{row.priority||'NORMAL'}</span></td>
    <td><span className="badge blue">{row.stage}</span></td>
    <td>{row.next_action}</td>
    <td><span className={slaClass(row.sla&&row.sla.state)}>{(row.sla&&row.sla.label)||'—'}</span>
      {row.sla&&row.sla.due?<><br/><small>Due {row.sla.due}</small></>:null}</td>
    <td><span className={'badge '+(row.evidence&&row.evidence.complete?'green':'amber')}>{evidenceLabel(row.evidence)}</span></td>
    <td>{row.blocker?<><span className="badge amber">{row.blocker}</span><br/><small>Owner: {row.blocker_owner}</small></>:'—'}</td>
    <td><span className="badge gray">{row.owner}</span></td>
    <td><small>{decided
      ? <span className="badge green">Buyer {row.buyer_decision.status} (CMO_MANAGER)</span>
      : row.handoff}</small></td>
  </tr>;
}

export function SampleTable({rows}){
  if(!rows||!rows.length) return <p className="empty">Tidak ada baris di bagian ini.</p>;
  return <div className="table-scroll"><table>
    <thead><tr>
      <th>Sample ID</th><th>Order ID</th><th>Article ID</th><th>Prioritas</th>
      <th>Tahap</th><th>Next Action</th><th>SLA / Due</th><th>Evidence</th>
      <th>Blocker</th><th>Owner</th><th>Handoff</th>
    </tr></thead>
    <tbody>{rows.map(r=><SampleRow key={r.task_id+r.stage} row={r}/>)}</tbody>
  </table></div>;
}

export default function SampleTodayPage(){
  const [data,setData]=useState(null),[err,setErr]=useState(''),[busy,setBusy]=useState(false);
  async function load(){setBusy(true);try{setData(await api('/sample/today'));setErr('')}catch(e){setErr(e.message)}finally{setBusy(false)}}
  useEffect(()=>{load()},[]);

  const access=data&&data.access;
  const sections=useMemo(()=>data?data.sections||[]:[],[data]);

  if(err&&!data) return <div className="page"><div className="notice danger">{err}</div></div>;
  if(!data) return <div className="page">Memuat pekerjaan sample hari ini...</div>;

  const buckets=data.buckets||{};
  return <div className="page">
    <div className="page-title">
      <div>
        <h1>Sample Today</h1>
        <p>Antrean kerja sample Fahrul — apa yang dikerjakan, bukti yang kurang, dan siapa yang menunggu.</p>
      </div>
      <button className="btn" disabled={busy} onClick={load}><RefreshCw size={15}/> Muat ulang</button>
    </div>

    <div className="cards">
      <div className={'stat '+(buckets.not_started?'amber':'green')}><strong>{buckets.not_started||0}</strong><span>Belum mulai</span></div>
      <div className="stat blue"><strong>{buckets.in_progress||0}</strong><span>Sedang dikerjakan</span></div>
      <div className="stat amber"><strong>{buckets.waiting_revision||0}</strong><span>Menunggu revisi</span></div>
      <div className="stat gray"><strong>{buckets.ready_to_handoff||0}</strong><span>Siap diserahkan</span></div>
      <div className={'stat '+(data.overdue?'red':'green')}><strong>{data.overdue||0}</strong><span>Terlambat (SLA)</span></div>
    </div>

    {data.total_eligible===0&&<div className="notice success">Belum ada artikel yang butuh sample.</div>}

    <div className="notice info">
      Pekerjaan sample (start, update, inspeksi, unggah bukti, submit hasil) milik Sample PIC.
      Keputusan buyer <b>APPROVED / REJECTED</b> bukan milik halaman ini — itu kewenangan
      <b> CMO_MANAGER</b> dan hanya tampil sebagai informasi. SLA berasal dari Master dan
      tidak diubah bebas oleh Sample PIC.
    </div>

    {sections.map(sec=>{
      const Icon=SECTION_ICON[sec.key]||Inbox;
      return <section className="panel" key={sec.key}>
        <div className="panel-head">
          <h2><Icon size={16}/> {sec.label}</h2>
          <span>{(sec.rows||[]).length} artikel · owner {access?access.role:'SAMPLE_PIC'}</span>
        </div>
        <SampleTable rows={sec.rows}/>
      </section>;
    })}

    {(data.not_eligible||[]).length>0&&<section className="panel">
      <div className="panel-head">
        <h2>Tidak Eligible — tidak masuk antrean</h2>
        <span>{data.not_eligible.length} artikel ditolak server-side</span>
      </div>
      <div className="table-scroll"><table>
        <thead><tr><th>Order ID</th><th>Article ID</th><th>Alasan</th><th>Owner</th></tr></thead>
        <tbody>{data.not_eligible.map(r=><tr key={r.task_id}>
          <td>{r.order_id||'—'}</td>
          <td>{r.article_code||'—'}<br/><small>Article ID {r.article_id??'—'}</small></td>
          <td><span className="badge amber">{r.eligibility_reason}</span></td>
          <td><span className="badge gray">{r.blocker_owner||'—'}</span></td>
        </tr>)}</tbody>
      </table></div>
    </section>}
  </div>;
}
